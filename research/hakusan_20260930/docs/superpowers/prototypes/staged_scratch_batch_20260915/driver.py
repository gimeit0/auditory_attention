"""Local verification, explicit CPU scheduler actions and bounded collection."""
import argparse
import base64
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import common as c
import runtime

EVIDENCE = ROOT / 'docs/superpowers/evidence/staged-cpu-batch-20260915'
PRIOR = HERE.parent / 'staged_scratch_native_20260915/run_native.py'
PRIOR_SHA = '023d55693fbba6409936d13709a048d2da1113d92e40e9c8535d0e021353eacb'


def sources():
    c.require(c.sha(c.read(PRIOR)) == PRIOR_SHA, 'prior source provider changed')
    old = runtime.load(PRIOR, 'unchanged_native_source_provider')
    task, old_driver, files, _ = old.sources()
    files.update({c.PREFIX + n: c.read(HERE / n) for n in c.OWN})
    raw = c.wire(dict(scope='synthetic_staged_cpu_only', limits=c.LIMITS, remote_root=str(c.REMOTE),
                      files={n: c.sha(b) for n, b in files.items()}))
    c.release(raw, c.sha(raw))
    c.require(sum(map(len, files.values())) <= 16 * 1024**2, 'source budget exceeded')
    return raw, files, old_driver


def unpack(root, raw, files):
    for name in ('package', 'attempts', 'logs'):
        (root / name).mkdir(mode=0o700)
    for name, data in files.items():
        path = root / 'package' / c.member(name)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        c.write(path, data)
    c.write(root / 'RELEASE.json', raw)


def local():
    raw, files, _ = sources()
    folder = Path(tempfile.mkdtemp(prefix='local-', dir=EVIDENCE))
    unpack(folder, raw, files)
    nonce = uuid.uuid4().hex
    c.write(folder / 'LOCAL_REQUEST.json', c.wire(dict(release_sha256=c.sha(raw), nonce=nonce)))
    print('LOCAL_CPU_BATCH_EVIDENCE=' + str(folder), flush=True)
    # Exact packaged coordinator runs all three cold children; zero SSH or jobs.
    packaged = runtime.load(folder / 'package' / c.PREFIX / 'runtime.py', 'packaged_cpu_runtime')
    rc = packaged.run(folder, c.sha(raw), nonce, 'LOCAL_HARNESS')
    c.require(rc == 0, 'local CPU batch failed')
    result = runtime.review(folder, c.sha(raw), nonce, 'LOCAL_HARNESS', 'local')
    c.require(sources()[0] == raw, 'local source postcheck differs')
    c.write(folder / 'LOCAL_REVIEW.json', c.wire(result))
    print(json.dumps(result), flush=True)


def local_review(folder, raw):
    c.require(c.read(folder / 'RELEASE.json') == raw, 'matching local release required')
    request = json.loads(c.read(folder / 'LOCAL_REQUEST.json'))
    c.require(request['release_sha256'] == c.sha(raw), 'local request release differs')
    checked = runtime.review(folder, c.sha(raw), request['nonce'], 'LOCAL_HARNESS', 'local')
    c.require(json.loads(c.read(folder / 'LOCAL_REVIEW.json')) == checked, 'local review differs')
    return checked


def payload(spec, files):
    header = 'import base64,types,sys\nSPEC=' + repr(spec) + '\n'
    header += 'm=types.ModuleType("common");sys.modules["common"]=m\n'
    header += 'exec(compile(base64.b64decode(' + repr(base64.b64encode(files[c.PREFIX + 'common.py']).decode()) + '),"<cpu-common>","exec"),m.__dict__)\n'
    header += 'exec(compile(base64.b64decode(' + repr(base64.b64encode(files[c.PREFIX + 'remote.py']).decode()) + '),"<cpu-remote>","exec"))\n'
    return header.encode('ascii')


def operate(action, local_folder, test_folder=None, confirmation=None):
    raw, files, old_driver = sources()
    local_review(local_folder, raw)
    sys.path.insert(0, str(old_driver.CONTROL))
    import control
    control.master_check(control.SOCKET)
    nonce = uuid.uuid4().hex
    spec = dict(action=action, release_sha256=c.sha(raw), nonce=nonce)
    if action == 'deploy':
        spec.update(release=base64.b64encode(raw).decode(), files={n: base64.b64encode(b).decode() for n, b in files.items()})
    if action == 'submit':
        c.require(confirmation == c.CONFIRM and test_folder is not None, 'CPU confirmation/test receipt required')
        previous = json.loads(c.read(test_folder / 'RECEIPT.json'))
        c.require(previous['spec']['action'] == 'test-only' and previous['spec']['release_sha256'] == c.sha(raw)
                  and previous['transport']['returncode'] == 0 and previous['transport']['error'] is None
                  and previous['response']['ok'] and previous['response']['result']['status'] == 'CPU_SCHEDULER_TEST_PASS', 'test receipt differs')
        spec.update(confirm=confirmation, test_sha256=previous['response']['result']['test_sha256'])
        c.write(EVIDENCE / 'LOCAL_SUBMIT_INTENT.json', c.wire(spec))
    folder = Path(tempfile.mkdtemp(prefix=action + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-', dir=EVIDENCE))
    print('CPU_BATCH_ACTION_EVIDENCE=' + str(folder), flush=True)
    request = payload(spec, files)
    transport = control.transport(control.ssh_command(control.SOCKET), request, folder, timeout=150, log_cap=24 * 1024**2)
    output = c.read(folder / 'output.log', limit=24 * 1024**2)
    lines = [line[len('CPU_BATCH_RESPONSE='):] for line in output.decode().splitlines() if line.startswith('CPU_BATCH_RESPONSE=')]
    response = json.loads(lines[0]) if len(lines) == 1 else None
    receipt = dict(spec={k: v for k, v in spec.items() if k not in ('files', 'release')}, transport=transport,
                   request_sha256=c.sha(request), output_sha256=c.sha(output), response=response)
    c.write(folder / 'RECEIPT.json', c.wire(receipt))
    c.require(transport['returncode'] == 0 and transport['error'] is None and response and response['ok'],
              'CPU action failed/uncertain; preserve evidence, no automatic retry: ' + str(response))
    if action == 'collect':
        recovered = folder / 'recovered'
        recovered.mkdir(mode=0o700)
        for name, item in response['result']['files'].items():
            data = base64.b64decode(item['data'], validate=True)
            c.require(c.sha(data) == item['sha256'], 'collected artifact hash differs')
            path = recovered / c.member(name)
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            c.write(path, data)
        for name, data in files.items():
            path = recovered / 'package' / c.member(name)
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            c.write(path, data)
        c.write(recovered / 'ACCOUNTING.json', c.wire(response['result']['accounting']))
    result = response['result']
    printable = {k: v for k, v in result.items() if k not in ('files', 'terminal')}
    if result.get('terminal'):
        printable['terminal_status'] = result['terminal']['status']
        printable['terminal_error'] = result['terminal']['error']
    print(json.dumps(printable, sort_keys=True), flush=True)


def review_collected(folder, local_folder):
    raw, _, _ = sources()
    local_review(local_folder, raw)
    result = json.loads(c.read(folder / 'RECEIPT.json', limit=24 * 1024**2))
    output = c.read(folder / 'output.log', limit=24 * 1024**2)
    response_lines = [line[len('CPU_BATCH_RESPONSE='):] for line in output.decode().splitlines() if line.startswith('CPU_BATCH_RESPONSE=')]
    c.require(result['request_sha256'] == c.sha(c.read(folder / 'request.py'))
              and result['output_sha256'] == c.sha(output) and len(response_lines) == 1
              and json.loads(response_lines[0]) == result['response'], 'transport evidence changed')
    c.require(result['spec']['action'] == 'collect' and result['spec']['release_sha256'] == c.sha(raw)
              and result['transport']['returncode'] == 0 and result['response']['ok'], 'collection incomplete')
    root = folder / 'recovered'
    for name, item in result['response']['result']['files'].items():
        saved = c.read(root / c.member(name))
        c.require(saved == base64.b64decode(item['data'], validate=True) and c.sha(saved) == item['sha256'], 'saved collection changed')
    receipt = json.loads(c.read(root / 'SUBMISSION_RECEIPT.json'))
    intent = json.loads(c.read(EVIDENCE / 'LOCAL_SUBMIT_INTENT.json'))
    c.require(receipt['nonce'] == intent['nonce'] and receipt['release_sha256'] == intent['release_sha256'] == c.sha(raw), 'external submission binding differs')
    held = json.loads(c.read(root / 'HELD.json'))
    c.require(held['returncode'] == 0, 'held review absent')
    c.job_check(held['stdout'], receipt['job_id'], receipt['nonce'], c.REMOTE, held=True)
    accounting = json.loads(c.read(root / 'ACCOUNTING.json'))
    rows = [line.split('|') for line in accounting['stdout'].strip().splitlines()]
    c.require(accounting['returncode'] == 0 and len(rows) == 1 and rows[0][0:3] == [receipt['job_id'], 'COMPLETED', '0:0'], 'scheduler not successfully completed')
    c.tres(rows[0][4]); c.tres(rows[0][5])
    elapsed = rows[0][3].split(':')
    c.require(len(elapsed) == 3 and all(x.isdigit() for x in elapsed)
              and sum(int(x) * f for x, f in zip(elapsed, (3600, 60, 1))) <= 600, 'scheduler elapsed budget differs')
    checked = runtime.review(root, c.sha(raw), receipt['nonce'], 'NATIVE_BATCH', receipt['job_id'])
    c.write(folder / 'VERIFIED.json', c.wire(checked))
    print(json.dumps(checked), flush=True)


def main():
    os.umask(0o077)
    EVIDENCE.mkdir(mode=0o700, exist_ok=True)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('local', 'preflight', 'deploy', 'test-only', 'submit', 'status', 'collect', 'review'))
    p.add_argument('--local', type=Path)
    p.add_argument('--test', type=Path)
    p.add_argument('--confirmation')
    p.add_argument('--collection', type=Path)
    a = p.parse_args()
    if a.action == 'local':
        return local()
    c.require(a.local is not None and a.local.is_absolute(), 'local review folder required')
    if a.action == 'review':
        return review_collected(a.collection, a.local)
    return operate(a.action, a.local, a.test, a.confirmation)


if __name__ == '__main__':
    main()

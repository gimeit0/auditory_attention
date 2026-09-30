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

EVIDENCE = ROOT / 'docs/superpowers/evidence/g2-bridge-batch-20260916'
CONTROL = HERE.parent / 'targeted_gpu_control_20260914_v4'
CONTROL_PINS = {'control.py':'6316b50dec15365c4562953fda04411fc95ba68d5f2cfc8383b1dc9db8e78754',
                'remote_ops.py':'b4766450edae186912e586bd862e7d30697ef7b69e82c35f6ca6b8b63e18e06d'}


def sources():
    files = {c.PREFIX+n:c.read(HERE/n) for n in c.OWN}
    snapshot = ROOT / 'docs/superpowers/evidence/g2-paired-local-20260916T044126Z-o3f8g1xe'
    for name in c.CORE_FILES:
        files[name] = c.read(snapshot / 'package' / c.member(name))
    files['CORE_RELEASE.json'] = c.read(snapshot / 'RELEASE.json')
    files['process_runner.py'] = c.read(HERE.parent / 'targeted_gpu_job_20260915_v5/process_runner.py')
    for name, digest in c.EXTRA.items():
        c.require(c.sha(files[name]) == digest, 'fixed dependency changed: ' + name)
    for name, digest in {'TERMINAL.json': '7129014e988c5ceab3b36cb812771ffcc836473e34e098202fd7195e2dfb3f45',
                         'UNIT_TESTS.json': '5db4ab9a19e4355b283ec741a7f5433ef66b7a4d8f672dcc015d7a5b71a64096'}.items():
        c.require(c.sha(c.read(snapshot / name)) == digest, 'previous local core evidence changed')
    raw = c.wire(dict(scope='synthetic_native_guarded_two_pass_bridge_pair',limits=c.LIMITS,remote_root=str(c.REMOTE),
                      files={n:c.sha(b) for n,b in files.items()}))
    c.release(raw,c.sha(raw))
    return raw,files,None


def unpack(root, raw, files):
    for name in ('package', 'attempts', 'logs'):
        (root / name).mkdir(mode=0o700)
    for name, data in files.items():
        path = root / 'package' / c.member(name)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        c.write(path, data)
    c.write(root / 'BATCH_RELEASE.json', raw)
    c.write(root / 'RELEASE.json', files['CORE_RELEASE.json'])


def local():
    import subprocess
    raw,files,_ = sources()
    folder = Path(tempfile.mkdtemp(prefix='local-',dir=EVIDENCE))
    unpack(folder,raw,files)
    print('LOCAL_CPU_BATCH_EVIDENCE=' + str(folder),flush=True)
    env = dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1')
    logs = {}
    tests = [HERE/'test_batch.py']
    for path in tests:
        result = subprocess.run([sys.executable,'-I','-B',str(path)],env=env,capture_output=True,timeout=60)
        data = result.stdout+result.stderr
        c.write(folder/path.with_suffix('.log').name,data)
        print(data.decode(),flush=True)
        c.require(result.returncode == 0,'local protective tests failed')
        logs[path.name] = dict(sha256=c.sha(data),returncode=result.returncode)
    # Exercise the actual bundled path/layout with a local eager child. This
    # does not impersonate the native allocation or certify R/C compilation.
    spec = importlib.util.spec_from_file_location('batch_local_runner', folder / 'package/process_runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    part = folder / 'packaged-local'
    part.mkdir(mode=0o700)
    nonce = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='g2-bridge-package-local-') as temporary:
        env = runtime.child_environment(os.environ, Path(temporary).resolve(), 'D-observed')
        result = runner.run_process([sys.executable, '-I', '-B', str(folder / 'package' / c.CORE_PREFIX / 'child.py'),
            'local', 'D', 'observed', str(part / 'result.json'), c.CORE_SHA, nonce], env, part / 'child.log', seconds=60)
        c.write(part / 'process.json', c.wire(result))
    c.require(result['returncode'] == 0 and result['error'] is None, 'packaged local eager check failed')
    value = json.loads(c.read(part / 'result.json'))
    runtime.verify.protocol().child(value, profile='D', role='observed', native=False, release_sha=c.CORE_SHA, nonce=nonce)
    c.require(result['pid'] == value['pid'], 'packaged child PID differs')
    smoke = dict(nonce=nonce, files={n:c.sha(c.read(part / n)) for n in ('result.json', 'process.json', 'child.log')})
    c.require(sources()[0] == raw,'source changed during tests')
    c.write(folder/'LOCAL_REVIEW.json',c.wire(dict(release_sha256=c.sha(raw),tests=logs,
        packaged_eager=smoke, native_backend_validated=False,production_model_loaded=False,jobs_submitted=0)))
    local_review(folder, raw)
    print('BRIDGE_BATCH_LOCAL_REVIEW=PASS; no remote action or submission', flush=True)


def local_review(folder,raw):
    c.require(c.read(folder/'BATCH_RELEASE.json') == raw,'matching local release required')
    c.source_check(folder/'package',c.release(raw,c.sha(raw)))
    review = json.loads(c.read(folder/'LOCAL_REVIEW.json'))
    c.require(review['release_sha256'] == c.sha(raw)
              and set(review['tests']) == {'test_batch.py'},'test release/coverage differs')
    for name,item in review['tests'].items():
        data = c.read(folder/Path(name).with_suffix('.log'))
        c.require(item == dict(sha256=c.sha(data),returncode=0),'test evidence differs')
    smoke, part = review['packaged_eager'], folder / 'packaged-local'
    c.require(set(smoke['files']) == {'result.json', 'process.json', 'child.log'}, 'packaged check coverage differs')
    for name, digest in smoke['files'].items():
        c.require(c.sha(c.read(part / name)) == digest, 'packaged eager evidence changed')
    process, value = (json.loads(c.read(part / n)) for n in ('process.json', 'result.json'))
    runtime.verify.protocol().child(value, profile='D', role='observed', native=False,
                                    release_sha=c.CORE_SHA, nonce=smoke['nonce'])
    log = c.read(part / 'child.log')
    c.require(process['returncode'] == 0 and process['error'] is None and process['pid'] == value['pid']
              and process['elapsed_seconds'] <= 60.5
              and process['log'] == dict(name='child.log', sha256=c.sha(log), size=len(log)), 'packaged process evidence differs')
    return review


def payload(spec, files):
    header = 'import base64,types,sys\nSPEC=' + repr(spec) + '\n'
    header += 'm=types.ModuleType("common");sys.modules["common"]=m\n'
    header += 'exec(compile(base64.b64decode(' + repr(base64.b64encode(files[c.PREFIX + 'common.py']).decode()) + '),"<cpu-common>","exec"),m.__dict__)\n'
    header += 'exec(compile(base64.b64decode(' + repr(base64.b64encode(files[c.PREFIX + 'remote.py']).decode()) + '),"<cpu-remote>","exec"))\n'
    return header.encode('ascii')


def operate(action, local_folder, test_folder=None, confirmation=None):
    raw, files, old_driver = sources()
    local_review(local_folder, raw)
    for n,h in CONTROL_PINS.items():
        c.require(c.sha(c.read(CONTROL/n)) == h,'SSH transport source changed')
    sys.path.insert(0,str(CONTROL))
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
    transport = control.transport(control.ssh_command(control.SOCKET), request, folder, timeout=150, log_cap=64 * 1024**2)
    output = c.read(folder / 'output.log', limit=64 * 1024**2)
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
    result = json.loads(c.read(folder / 'RECEIPT.json', limit=64 * 1024**2))
    output = c.read(folder / 'output.log', limit=64 * 1024**2)
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
    c.require(accounting['returncode'] == 0 and len(rows) == 1 and rows[0][0] == receipt['job_id']
              and rows[0][1] in ('COMPLETED','FAILED'), 'scheduler not terminal/reviewable')
    c.tres(rows[0][4]); c.tres(rows[0][5])
    elapsed = rows[0][3].split(':')
    c.require(len(elapsed) == 3 and all(x.isdigit() for x in elapsed)
              and sum(int(x) * f for x, f in zip(elapsed, (3600, 60, 1))) <= 1320, 'scheduler elapsed budget differs')
    checked = runtime.review(root,c.sha(raw),receipt['nonce'],receipt['job_id'])
    expected = ['COMPLETED','0:0'] if checked['status'] == 'NATIVE_CPU_PAIR_VERIFIED' else ['FAILED','2:0']
    c.require(rows[0][1:3] == expected,'scheduler/runtime outcomes disagree')
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

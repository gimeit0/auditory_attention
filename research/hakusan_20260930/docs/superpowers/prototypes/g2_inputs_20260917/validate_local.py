"""Local bounded relation tests and hash-bound evidence. No network actions."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
REPORT = dict(tests=16, errors=0, failures=0, skipped=0, scope='LOCAL_RELATION_ONLY',
              actual_production_loader_executed=False, new_remote_freeze_created=False,
              production_model_loaded=False, jobs_submitted=0)


def wire(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def record(path):
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise RuntimeError('nonsymlink regular evidence/source required')
    raw = path.read_bytes()
    return dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def sources():
    fixed = ROOT / 'docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu'
    paths = [HERE / n for n in ('input_binding.py', 'test_input_binding.py', 'validate_local.py')]
    paths += [HERE.parent / 'g2_worker_20260916/cell_bridge.py', HERE.parent / 'g2_profiles_20260916/profiles.py',
              ROOT / 'docs/superpowers/evidence/v18-deployment-artifacts/input_freeze.json']
    paths += [fixed / p / n for p in 'RCDE' for n in ('diagnose_batch_invariance.py', 'numeric_trace.py')]
    return dict(sorted((str(p.relative_to(ROOT)), record(p)) for p in paths))


def write(path, raw):
    with path.open('xb') as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())


def parse(raw):
    found = [json.loads(line.split('=', 1)[1]) for line in raw.decode().splitlines()
             if line.startswith('G2_INPUT_TEST_REPORT=')]
    if found != [REPORT]:
        raise RuntimeError('test scope/coverage/result differs')
    return REPORT


def verify(folder):
    value = json.loads((folder / 'RECEIPT.json').read_bytes())
    if not (value['status'] == 'LOCAL_G2_INPUT_RELATION_PASS' and value['rc'] == 0
            and 0 <= value['elapsed_seconds'] < 30 and value['timeout_seconds'] == 30
            and value['before'] == value['after'] == sources()
            and value['remote_operations'] == value['jobs_submitted'] == 0):
        raise RuntimeError('receipt/source mismatch')
    for index, (name, expected) in enumerate(value['before'].items()):
        if record(folder / 'sources' / (str(index) + '-' + Path(name).name)) != expected:
            raise RuntimeError('source snapshot mismatch')
    if value['logs'] != {name: record(folder / name) for name in ('stdout.log', 'stderr.log')}:
        raise RuntimeError('test log mismatch')
    if parse((folder / 'stdout.log').read_bytes()) != value['report']:
        raise RuntimeError('test report mismatch')
    print('LOCAL_G2_INPUT_RELATION_RECHECK=PASS', flush=True)


def main():
    os.umask(0o077)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    folder = Path(tempfile.mkdtemp(prefix='g2-inputs-local-' + stamp,
                                 dir=ROOT / 'docs/superpowers/evidence'))
    print('LOCAL_EVIDENCE=' + str(folder), flush=True)
    before = sources()
    (folder / 'sources').mkdir(mode=0o700)
    for index, name in enumerate(before):
        write(folder / 'sources' / (str(index) + '-' + Path(name).name), (ROOT / name).read_bytes())
    started = time.monotonic()
    try:
        result = subprocess.run([sys.executable, '-I', '-B', str(HERE / 'test_input_binding.py')],
                                capture_output=True, timeout=30)
        rc, out, err = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as error:
        rc, out, err = 124, error.stdout or b'', error.stderr or b''
    elapsed, after = time.monotonic() - started, sources()
    write(folder / 'stdout.log', out)
    write(folder / 'stderr.log', err)
    try:
        report = parse(out)
    except (RuntimeError, ValueError):
        report = None
    passed = rc == 0 and elapsed < 30 and before == after and report == REPORT
    value = dict(status='LOCAL_G2_INPUT_RELATION_PASS' if passed else 'LOCAL_G2_INPUT_RELATION_FAILED',
                 rc=rc, elapsed_seconds=elapsed, timeout_seconds=30, before=before, after=after,
                 report=report, logs={name: record(folder / name) for name in ('stdout.log', 'stderr.log')},
                 jobs_submitted=0, remote_operations=0)
    write(folder / 'RECEIPT.json', wire(value))
    print(err.decode(), end='')
    print(out.decode(), end='')
    if passed:
        verify(folder)
    return 0 if passed else 2


if __name__ == '__main__':
    if len(sys.argv) == 1:
        raise SystemExit(main())
    if len(sys.argv) == 3 and sys.argv[1] == 'verify':
        verify(Path(sys.argv[2]).resolve())
    else:
        raise SystemExit('usage: validate_local.py [verify EVIDENCE_DIRECTORY]')

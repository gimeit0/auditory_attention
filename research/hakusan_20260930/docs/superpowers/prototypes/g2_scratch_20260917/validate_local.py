"""Record/recheck bounded local interface tests; never contacts the cluster."""
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


def wire(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def record(path):
    path = Path(path)
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise RuntimeError('regular nonsymlink source/artifact required')
    raw = path.read_bytes()
    return dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def sources():
    paths = [HERE / n for n in ('scratch_binding.py', 'test_scratch_binding.py', 'validate_local.py')]
    paths += [HERE.parent / 'g2_worker_20260916/cell_bridge.py',
              HERE.parent / 'g2_profiles_20260916/profiles.py']
    fixed = ROOT / 'docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu'
    paths += [fixed / p / n for p in 'RCDE' for n in ('diagnose_batch_invariance.py', 'numeric_trace.py')]
    return {str(p.relative_to(ROOT)): record(p) for p in paths}


def write(path, raw):
    with path.open('xb') as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())


def test_report(stdout):
    records = [json.loads(line.split('=', 1)[1]) for line in stdout.decode().splitlines()
               if line.startswith('G2_SCRATCH_TEST_REPORT=')]
    expected = dict(tests=15, errors=0, failures=0, skipped=0,
                    scope='LOCAL_FILESYSTEM_AND_INTERFACE_ONLY', linux_mount_test_stub=True,
                    production_model_loaded=False, gpu_validated=False, jobs_submitted=0)
    if records != [expected]:
        raise RuntimeError('local interface test report differs')
    return records[0]


def verify(directory):
    receipt = json.loads((directory / 'RECEIPT.json').read_bytes())
    if (receipt['status'] != 'LOCAL_G2_SCRATCH_INTERFACE_PASS' or receipt['rc'] != 0
            or not 0 <= receipt['elapsed_seconds'] < 45
            or receipt['sources_before'] != receipt['sources_after']
            or receipt['sources_after'] != sources()):
        raise RuntimeError('receipt/source mismatch')
    for index, (name, expected) in enumerate(receipt['sources_before'].items()):
        # Snapshots use sorted source-path order, independent of JSON key order.
        path = directory / 'sources' / (str(index) + '-' + Path(name).name)
        if record(path) != expected:
            raise RuntimeError('source snapshot mismatch')
    for name, expected in receipt['artifacts'].items():
        if name not in ('tests.stdout', 'tests.stderr') or record(directory / name) != expected:
            raise RuntimeError('test artifact mismatch')
    if set(receipt['artifacts']) != {'tests.stdout', 'tests.stderr'}:
        raise RuntimeError('missing test artifact')
    if test_report((directory / 'tests.stdout').read_bytes()) != receipt['report']:
        raise RuntimeError('test report mismatch')
    print('LOCAL_G2_SCRATCH_RECHECK=PASS', flush=True)


def run():
    os.umask(0o077)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    directory = Path(tempfile.mkdtemp(prefix='g2-scratch-local-' + stamp,
                                    dir=ROOT / 'docs/superpowers/evidence'))
    print('LOCAL_EVIDENCE=' + str(directory), flush=True)
    before = dict(sorted(sources().items()))
    (directory / 'sources').mkdir(mode=0o700)
    for index, name in enumerate(before):
        write(directory / 'sources' / (str(index) + '-' + Path(name).name), (ROOT / name).read_bytes())
    started = time.monotonic()
    try:
        completed = subprocess.run([sys.executable, '-I', '-B', str(HERE / 'test_scratch_binding.py')],
                                   capture_output=True, timeout=45,
                                   env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', CUDA_VISIBLE_DEVICES=''))
        rc, out, err = completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as error:
        rc, out, err = 124, error.stdout or b'', error.stderr or b''
    elapsed = time.monotonic() - started
    write(directory / 'tests.stdout', out)
    write(directory / 'tests.stderr', err)
    after = dict(sorted(sources().items()))
    try:
        report = test_report(out)
    except (ValueError, RuntimeError):
        report = None
    passed = rc == 0 and elapsed < 45 and before == after and report is not None
    value = dict(status='LOCAL_G2_SCRATCH_INTERFACE_PASS' if passed else 'LOCAL_G2_SCRATCH_INTERFACE_FAILED',
                 rc=rc, elapsed_seconds=elapsed, timeout_seconds=45, report=report,
                 sources_before=before, sources_after=after,
                 artifacts={n: record(directory / n) for n in ('tests.stdout', 'tests.stderr')},
                 production_ready=False, remote_operations=0, jobs_submitted=0)
    write(directory / 'RECEIPT.json', wire(value))
    print(err.decode(), end='')
    print(out.decode(), end='')
    if passed:
        verify(directory)
    return 0 if passed else 2


if __name__ == '__main__':
    if len(sys.argv) == 1:
        raise SystemExit(run())
    if len(sys.argv) == 3 and sys.argv[1] == 'verify':
        verify(Path(sys.argv[2]).resolve())
    else:
        raise SystemExit('usage: validate_local.py [verify EVIDENCE_DIRECTORY]')

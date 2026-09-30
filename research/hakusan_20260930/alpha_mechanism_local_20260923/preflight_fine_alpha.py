"""Authorized native source-only preflight; no upload, model load or scheduler writes."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tempfile

from publish_fine_alpha import PACKAGE, RELEASE_ROOT, REMOTE_PY, REMOTE_ROOT, SHA, SOCKET, SSH
from fine_alpha_entry import identity, verify_package

SNAPSHOT_SHA = '8febb19f3c183333adfc0f7543ba7a017a3c5d4d5ae2132ffa72e701da955dcb'
BOOTSTRAP = r'''
import hashlib, os, pathlib, pwd, subprocess, sys
root = pathlib.Path('/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v1/package')
digest, entry_sha, mode = sys.argv[1:]
if sys.platform != 'linux' or pwd.getpwuid(os.getuid()).pw_name != 's2510040':
    raise ValueError('NATIVE_ACCOUNT')
if not sys.flags.isolated or not sys.dont_write_bytecode: raise ValueError('ISOLATED_NO_BYTECODE')
if mode not in ('check', 'source-check'): raise ValueError('READ_ONLY_MODE_REQUIRED')
for p in (root, *root.parents):
    if p.is_symlink() or not p.is_dir(): raise ValueError('PACKAGE_ANCESTOR')
for name, expected in (('RELEASE.json', digest), ('fine_alpha_entry.py', entry_sha)):
    p = root/name
    if p.is_symlink() or not p.is_file(): raise ValueError('BOOTSTRAP_FILE')
    if hashlib.sha256(p.read_bytes()).hexdigest() != expected: raise ValueError('BOOTSTRAP_SHA')
env = os.environ.copy()
env.update(CUDA_VISIBLE_DEVICES='', PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
           PYTHONHASHSEED='0', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
try:
    completed = subprocess.run([sys.executable, '-I', '-B', str(root/'fine_alpha_entry.py'), mode, digest],
                               env=env, timeout=180)
except subprocess.TimeoutExpired:
    print('NATIVE_PREFLIGHT_TIMEOUT_NO_RETRY', file=sys.stderr, flush=True)
    sys.exit(124)
sys.exit(completed.returncode)
'''


def validate_record(raw, mode, *, expected_sha=SHA, counts=(219600, 194400)):
    if mode not in ('check', 'source-check'):
        raise ValueError('READ_ONLY_MODE_REQUIRED')
    row = json.loads(raw.decode().strip().splitlines()[-1])
    if type(row.get('jobs_submitted')) is not int or row['jobs_submitted'] != 0:
        raise ValueError('SOURCE_SCOPE_VIOLATION')
    if mode == 'check':
        if (row.get('status') != 'FINE_ALPHA_PACKAGE_CHECK_PASS' or row.get('release_sha256') != expected_sha
                or row.get('production_validated') is not False or row.get('predictions') != counts[0]
                or row.get('science_predictions') != counts[1]):
            raise ValueError('PACKAGE_CHECK_RECORD')
    else:
        if (row.get('status') != 'NATIVE_SOURCE_ONLY_IMPORT_PASS'
                or row.get('checkpoint_loaded') is not False or row.get('cuda_initialized') is not False):
            raise ValueError('SOURCE_SCOPE_VIOLATION')
        snapshot = row.get('snapshot', {})
        if (snapshot.get('manifest_sha256') != SNAPSHOT_SHA or snapshot.get('files') != 96
                or snapshot.get('required_import_policy') != 'hash_checked_source_only'):
            raise ValueError('SNAPSHOT_RECORD')
    return row


def main(*, package=PACKAGE, release_root=RELEASE_ROOT, remote_root=REMOTE_ROOT,
         digest=SHA, bootstrap=BOOTSTRAP, evidence_name=None, binding_path=None, publication=None, counts=(219600, 194400)):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-authorized-source-check', action='store_true', required=True)
    parser.parse_args()
    if evidence_name is None:
        evidence = Path(tempfile.mkdtemp(prefix='source-check-', dir=release_root))
    else:
        if Path(evidence_name).name != evidence_name: raise ValueError('EVIDENCE_NAME')
        evidence = release_root/evidence_name
        evidence.mkdir(mode=0o700, exist_ok=False)
    evidence.chmod(0o700)
    result = dict(started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  release_sha256=digest, remote_root=remote_root, evidence=str(evidence), steps=[],
                  authorized_scope='native_source_only_import_and_hash_checks',
                  jobs_submitted=0, gpu_authorized=False, checkpoint_loaded=None, cuda_initialized=None,
                  remote_source_check_attempted=False, automatic_retry=False, automatic_reconnect=False,
                  publication=publication, bootstrap_sha256=hashlib.sha256(bootstrap.encode()).hexdigest())

    def run(name, argv, seconds):
        try:
            p = subprocess.run(argv, capture_output=True, timeout=seconds)
        except subprocess.TimeoutExpired as exc:
            (evidence/(name+'.stdout')).write_bytes(exc.stdout or b'')
            (evidence/(name+'.stderr')).write_bytes(exc.stderr or b'')
            result['steps'].append(dict(name=name, status='TIMEOUT_INSPECT_NO_RETRY'))
            raise
        (evidence/(name+'.stdout')).write_bytes(p.stdout)
        (evidence/(name+'.stderr')).write_bytes(p.stderr)
        result['steps'].append(dict(name=name, returncode=p.returncode))
        print(p.stdout.decode(errors='replace'), end='', flush=True)
        if p.returncode:
            raise RuntimeError(name+' FAILED: '+p.stderr.decode(errors='replace'))
        return p.stdout

    try:
        manifest = verify_package(package, digest)
        result['driver'] = identity(Path(__file__))
        if binding_path is not None: result['version_binding_driver'] = identity(binding_path)
        if SOCKET.is_symlink() or not SOCKET.is_socket():
            raise ValueError('SSH_MASTER_ABSENT_USER_RECONNECT_REQUIRED')
        run('master', ['/usr/bin/ssh', '-S', str(SOCKET), '-O', 'check', 's2510040@hakusan1'], 10)
        for name, mode in (('pre-check', 'check'), ('source-check', 'source-check'), ('post-check', 'check')):
            if mode == 'source-check':
                result['remote_source_check_attempted'] = True
                (evidence/'SOURCE_CHECK_INTENT.json').write_text(json.dumps(result, indent=2)+'\n')
            command = shlex.join([REMOTE_PY, '-I', '-B', '-c', bootstrap, digest,
                                  manifest['files']['fine_alpha_entry.py']['sha256'], mode])
            row = validate_record(run(name, SSH+[command], 210), mode, expected_sha=digest, counts=counts)
            result['steps'][-1]['record'] = row
            if mode == 'source-check':
                result.update(checkpoint_loaded=False, cuda_initialized=False)
        verify_package(package, digest)
        result['status'] = 'FINE_ALPHA_NATIVE_SOURCE_CHECK_PASS_NO_GPU_JOB'
    except BaseException as exc:
        result.update(status='STOPPED_INSPECT_EVIDENCE_NO_RETRY', error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        result['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (evidence/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
        print('EVIDENCE='+str(evidence), flush=True)


if __name__ == '__main__':
    main()

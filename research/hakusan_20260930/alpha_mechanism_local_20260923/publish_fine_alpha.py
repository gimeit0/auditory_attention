"""User-authorized upload and read-only package check. No GPU authority/reconnect."""
import argparse
import datetime
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import tempfile
from fine_alpha_entry import identity, verify_package
from fine_alpha_upload_transport import validate_transport

HERE = Path(__file__).absolute().parent
RELEASE_ROOT = HERE/'release_fine_alpha_20260928_candidate_v1'
PACKAGE = RELEASE_ROOT/'package'
SHA = 'b0bd8b4269b5542b65bbf6d3982b7484838f983d0c5fe7a9538551ea9a076b8f'
SOCKET = HERE.parent/'.hakusan-control/master.sock'
REMOTE_PY = '/home/s2510040/miniconda3/envs/attn/bin/python'
REMOTE_ROOT = '/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v1'
SSH = ['/usr/bin/ssh', '-S', str(SOCKET), '-o', 'ControlMaster=no', '-o', 'BatchMode=yes',
       '-o', 'ProxyCommand=false', '-o', 'ConnectTimeout=12', 's2510040@hakusan1']

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-authorized-upload', required=True, action='store_true')
    parser.parse_args()
    evidence = Path(tempfile.mkdtemp(prefix='upload-', dir=RELEASE_ROOT)); steps = []
    result = dict(release_sha256=SHA, evidence=str(evidence), remote_root=REMOTE_ROOT, steps=steps,
                  authorized_scope='upload_new_directory_and_hash_verification_only',
                  jobs_submitted=0, gpu_authorized=False, checkpoint_loaded=False,
                  source_only_import_check_performed=False, remote_publish_attempted=False,
                  automatic_retry=False, automatic_reconnect=False)
    def run(name, argv, data=None, seconds=180):
        try:
            p = subprocess.run(argv, input=data, capture_output=True, timeout=seconds)
        except subprocess.TimeoutExpired as exc:
            (evidence/(name+'.stdout')).write_bytes(exc.stdout or b'')
            (evidence/(name+'.stderr')).write_bytes(exc.stderr or b'')
            steps.append(dict(name=name, status='TIMEOUT_INSPECT_BEFORE_ANY_NEXT_ACTION'))
            raise
        (evidence/(name+'.stdout')).write_bytes(p.stdout)
        (evidence/(name+'.stderr')).write_bytes(p.stderr)
        steps.append(dict(name=name, returncode=p.returncode))
        print(p.stdout.decode(errors='replace'), end='', flush=True)
        if p.returncode: raise RuntimeError(name+' FAILED: '+p.stderr.decode(errors='replace'))
        return p.stdout
    try:
        manifest = verify_package(PACKAGE, SHA)
        entry_sha = manifest['files']['fine_alpha_entry.py']['sha256']
        run('local-check', [sys.executable, '-I', '-B', str(PACKAGE/'fine_alpha_entry.py'), 'check', SHA], seconds=60)
        if SOCKET.is_symlink() or not SOCKET.is_socket():
            result['status'] = 'WAITING_FOR_USER_SSH_CONNECTION_NO_REMOTE_ACTION'
            raise ValueError('SSH_MASTER_ABSENT_USER_RECONNECT_REQUIRED')
        run('master', ['/usr/bin/ssh', '-S', str(SOCKET), '-O', 'check', 's2510040@hakusan1'], seconds=10)
        transport = io.BytesIO()
        with tarfile.open(fileobj=transport, mode='w:') as archive:
            for filename in sorted(set(manifest['files']) | {'RELEASE.json'}):
                raw = (PACKAGE/filename).read_bytes(); member = tarfile.TarInfo(filename)
                member.size = len(raw); member.mode = 0o600
                archive.addfile(member, io.BytesIO(raw))
        blob = transport.getvalue(); validate_transport(blob, SHA, entry_sha)
        verify_package(PACKAGE, SHA)
        receiver = HERE/'fine_alpha_upload_transport.py'
        result['receiver'] = identity(receiver)
        result['transport_bytes'] = len(blob)
        remote = shlex.join([REMOTE_PY, '-I', '-B', '-c', receiver.read_text(), SHA, entry_sha])
        result['remote_publish_attempted'] = True
        # Preserve intent before transmission. Any ambiguous response stops; never retry automatically.
        (evidence/'UPLOAD_INTENT.json').write_text(json.dumps(result, indent=2)+'\n')
        raw = run('publish', SSH+[remote], blob)
        row = json.loads(raw.decode().strip().splitlines()[-1])
        if (row.get('status') != 'FINE_ALPHA_FILES_PUBLISHED' or row.get('release_sha256') != SHA or
            row.get('files') != len(manifest['files'])+1 or row.get('jobs_submitted') != 0):
            raise ValueError('PUBLICATION_RECEIPT')
        raw = run('remote-package-check', SSH+[shlex.join([REMOTE_PY, '-I', '-B',
            REMOTE_ROOT+'/package/fine_alpha_entry.py', 'check', SHA])], seconds=120)
        row = json.loads(raw.decode().strip().splitlines()[-1])
        if row.get('status') != 'FINE_ALPHA_PACKAGE_CHECK_PASS' or row.get('release_sha256') != SHA or row.get('jobs_submitted') != 0:
            raise ValueError('REMOTE_PACKAGE_CHECK')
        verify_package(PACKAGE, SHA)
        result['status'] = 'FINE_ALPHA_UPLOADED_AND_HASH_VERIFIED_NO_JOB'
    except BaseException as exc:
        result.setdefault('status', 'STOPPED_INSPECT_EVIDENCE_NO_RETRY')
        result.update(error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        result['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (evidence/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
        print('EVIDENCE='+str(evidence), flush=True)

if __name__ == '__main__': main()

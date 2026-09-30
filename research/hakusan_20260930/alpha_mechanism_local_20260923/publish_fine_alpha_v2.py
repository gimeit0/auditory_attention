"""Fixed v2 upload once; package/hash verification only, no GPU authority."""
import argparse
import datetime
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile

from fine_alpha_entry import identity, verify_package
from fine_alpha_upload_transport import validate_transport
from publish_fine_alpha import SOCKET, SSH, REMOTE_PY

HERE = Path(__file__).absolute().parent
RELEASE_ROOT = HERE/'release_fine_alpha_20260928_candidate_v2'
PACKAGE = RELEASE_ROOT/'package'
SHA = 'a7a2f6307159af72a1906a153d07d8797c770de71037e24b382a873a9ed657e0'
SCOPE = 'FINE_ALPHA_001_20260928_V2'
REMOTE_ROOT = '/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v2'
V1_SHA = 'b0bd8b4269b5542b65bbf6d3982b7484838f983d0c5fe7a9538551ea9a076b8f'
REVIEWED_TREE = '/home/s2510040/selective_listening_repro/code/auditory_attention_seed20260928'
REVIEWED_LOG = REVIEWED_TREE+'/selftrain/hakusan/logs/audattn_numcheck_seed20260928_754073.log'
REVIEWED_JOBS = {'754073': {
    'JobName': 'audattn_numcheck_seed20260928',
    'Command': REVIEWED_TREE+'/selftrain/hakusan/run_numerics_preflight.sbatch',
    'WorkDir': REVIEWED_TREE, 'StdOut': REVIEWED_LOG, 'StdErr': REVIEWED_LOG,
    'command_sha256': 'a6a4a6413fb98759f214ed7c16f9d431cfb37bb55818527d79bca24fea040011',
}}


def make_transport(package=PACKAGE):
    manifest = verify_package(package, SHA)
    if manifest['scope'] != SCOPE: raise ValueError('V2_REQUIRED')
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:') as archive:
        for filename in sorted(set(manifest['files']) | {'RELEASE.json'}):
            raw = (package/filename).read_bytes()
            member = tarfile.TarInfo(filename); member.size = len(raw); member.mode = 0o600
            archive.addfile(member, io.BytesIO(raw))
    blob = stream.getvalue()
    validate_transport(blob, SHA, manifest['files']['fine_alpha_entry.py']['sha256'], expected_scope=SCOPE)
    verify_package(package, SHA)
    return manifest, blob


def receiver_bootstrap(source):
    # Execute the shared, tested receiver as a library. Its historical CLI keeps
    # V1 defaults; this wrapper binds V2 explicitly without changing the old root.
    return f'''
import hashlib, pathlib
namespace = {{'__name__': 'fine_alpha_v2_upload_receiver'}}
exec(compile({source!r}, '<bound-upload-receiver>', 'exec'), namespace)
legacy = pathlib.Path('/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v1/package/RELEASE.json')
def legacy_check():
    if legacy.is_symlink() or not legacy.is_file() or any(p.is_symlink() for p in legacy.parents):
        raise ValueError('V1_RELEASE_PATH')
    if hashlib.sha256(legacy.read_bytes()).hexdigest() != {V1_SHA!r}:
        raise ValueError('V1_RELEASE_SHA')
legacy_check()
namespace['main'](remote=pathlib.Path({REMOTE_ROOT!r}), expected_scope={SCOPE!r}, reviewed_jobs={REVIEWED_JOBS!r})
legacy_check()
'''


def validate_receipt(row, count):
    if (row.get('status') != 'FINE_ALPHA_FILES_PUBLISHED' or row.get('release_sha256') != SHA or
        row.get('root') != REMOTE_ROOT or row.get('files') != count or row.get('manifest_files') != count-1 or
        type(row.get('jobs_submitted')) is not int or row['jobs_submitted'] != 0 or
        type(row.get('checkpoints_loaded')) is not int or row['checkpoints_loaded'] != 0):
        raise ValueError('V2_PUBLICATION_RECEIPT')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-authorized-upload', action='store_true', required=True)
    parser.parse_args()
    manifest, blob = make_transport()
    previous = RELEASE_ROOT/'upload-v2-once'
    prior = json.loads((previous/'RESULT.json').read_text())
    queue = json.loads((previous/'publish.stdout').read_text())
    if (prior.get('status') != 'STOPPED_INSPECT_EVIDENCE_NO_RETRY' or prior.get('release_sha256') != SHA or
        prior.get('remote_root') != REMOTE_ROOT or 'QUEUE_FAILED_OR_RELATED_JOB' not in prior.get('error', '') or
        queue.get('stage') != 'read_only_queue' or queue.get('returncode') != 0 or
        queue.get('stdout') != '754073|audattn_numcheck_seed20260928|RUNNING\n' or
        [step.get('name') for step in prior.get('steps', [])] != ['local-check', 'master', 'publish']):
        raise ValueError('PREVIOUS_STOP_REVIEW_REQUIRED')
    evidence = RELEASE_ROOT/'upload-v2-reviewed-job-once'
    evidence.mkdir(mode=0o700, exist_ok=False)  # Any repeat, including an ambiguous one, needs manual inspection.
    result = dict(status='UPLOAD_NOT_FINISHED', release_sha256=SHA, remote_root=REMOTE_ROOT,
                  authorized_scope='upload_v2_new_directory_and_hash_package_verification_only',
                  user_instruction='开始上传吧；解释名称保护过宽后用户回复“好的”', evidence=str(evidence), steps=[], jobs_submitted=0,
                  gpu_authorized=False, checkpoint_loaded=False, source_only_import_check_performed=False,
                  automatic_retry=False, automatic_reconnect=False, remote_publish_attempted=False,
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  reviewed_jobs=REVIEWED_JOBS, previous_stopped_attempt=str(previous),
                  previous_result_identity=identity(previous/'RESULT.json'),
                  queue_policy='exact_reviewed_job_identity_and_disjoint_paths_upload_only')

    def run(name, argv, data=None, seconds=180):
        try:
            p = subprocess.run(argv, input=data, capture_output=True, timeout=seconds)
        except subprocess.TimeoutExpired as exc:
            (evidence/(name+'.stdout')).write_bytes(exc.stdout or b'')
            (evidence/(name+'.stderr')).write_bytes(exc.stderr or b'')
            result['steps'].append(dict(name=name, status='TIMEOUT_INSPECT_NO_RETRY')); raise
        (evidence/(name+'.stdout')).write_bytes(p.stdout)
        (evidence/(name+'.stderr')).write_bytes(p.stderr)
        result['steps'].append(dict(name=name, returncode=p.returncode))
        print(p.stdout.decode(errors='replace'), end='', flush=True)
        if p.returncode: raise RuntimeError(name+' FAILED: '+p.stderr.decode(errors='replace'))
        return p.stdout

    try:
        run('local-check', [sys.executable, '-I', '-B', str(PACKAGE/'fine_alpha_entry.py'), 'check', SHA], seconds=60)
        if SOCKET.is_symlink() or not SOCKET.is_socket(): raise ValueError('USER_RECONNECT_REQUIRED')
        run('master', ['/usr/bin/ssh', '-S', str(SOCKET), '-O', 'check', 's2510040@hakusan1'], seconds=10)
        receiver = HERE/'fine_alpha_upload_transport.py'; bootstrap = receiver_bootstrap(receiver.read_text())
        result.update(driver=identity(Path(__file__)), receiver=identity(receiver), transport_bytes=len(blob),
                      transport_sha256=hashlib.sha256(blob).hexdigest(),
                      bootstrap_sha256=hashlib.sha256(bootstrap.encode()).hexdigest(),
                      legacy_v1_release_sha256=V1_SHA)
        verify_package(PACKAGE, SHA)
        remote = shlex.join([REMOTE_PY, '-I', '-B', '-c', bootstrap, SHA,
                             manifest['files']['fine_alpha_entry.py']['sha256']])
        result['remote_publish_attempted'] = True
        with (evidence/'UPLOAD_INTENT.json').open('x') as stream: json.dump(result, stream, indent=2)
        raw = run('publish', SSH+[remote], blob)
        row = json.loads(raw.decode().strip().splitlines()[-1]); validate_receipt(row, len(manifest['files'])+1)
        result['publication'] = row; result['legacy_v1_release_unchanged'] = True
        raw = run('remote-package-check', SSH+[shlex.join([REMOTE_PY, '-I', '-B',
                   REMOTE_ROOT+'/package/fine_alpha_entry.py', 'check', SHA])], seconds=120)
        row = json.loads(raw.decode().strip().splitlines()[-1])
        if (row.get('status') != 'FINE_ALPHA_PACKAGE_CHECK_PASS' or row.get('release_sha256') != SHA or
            row.get('predictions') != 219600 or row.get('science_predictions') != 194400 or
            type(row.get('jobs_submitted')) is not int or row['jobs_submitted'] != 0 or
            row.get('production_validated') is not False): raise ValueError('V2_REMOTE_PACKAGE_CHECK')
        result['remote_check'] = row
        verify_package(PACKAGE, SHA)
        result['status'] = 'FINE_ALPHA_V2_UPLOADED_AND_HASH_VERIFIED_NO_JOB'
        print(json.dumps(result), flush=True)
    except BaseException as exc:
        result.update(status='STOPPED_INSPECT_EVIDENCE_NO_RETRY', error_type=type(exc).__name__, error=str(exc)); raise
    finally:
        result['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with (evidence/'RESULT.json').open('x') as stream: json.dump(result, stream, indent=2)
        print('UPLOAD_V2_EVIDENCE='+str(evidence), flush=True)


if __name__ == '__main__': main()

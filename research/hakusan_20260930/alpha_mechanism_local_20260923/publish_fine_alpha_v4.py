"""Fixed v4 upload once; package/hash verification only, no GPU authority."""
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
from publish_fine_alpha_v2 import V1_SHA, SHA as V2_SHA, REMOTE_ROOT as V2_ROOT
from publish_fine_alpha_v3 import SHA as V3_SHA, REMOTE_ROOT as V3_ROOT

HERE = Path(__file__).absolute().parent
RELEASE_ROOT = HERE/'release_fine_alpha_20260929_candidate_v4'
PACKAGE = RELEASE_ROOT/'package'
SHA = '0b067f57d612987d9c80a56e385658b1414095e46b5956b0bff43a7760668a2a'
SCOPE = 'FINE_ALPHA_002_20260929_V4'
REMOTE_ROOT = '/home/s2510040/audattn_fine_alpha/fine_alpha_20260929_v4'
V1_ROOT = '/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v1'
LEGACY = {V1_ROOT+'/package/RELEASE.json': V1_SHA, V2_ROOT+'/package/RELEASE.json': V2_SHA,
          V3_ROOT+'/package/RELEASE.json': V3_SHA}
# Live-reviewed on 2026-09-29 (read-only scontrol/spool): new-seed formal40 training; all writes under the
# seed tree, shared cv_train read through a symlink. The receiver re-checks these fields and the script SHA live.
SEED_TREE = '/home/s2510040/selective_listening_repro/code/auditory_attention_seed20260928'
REVIEWED_JOBS = {'757211': {
    'JobName': 'aud_formal40_newseed20260928_202_2ea4de47',
    'Command': SEED_TREE+'/selftrain/hakusan/run_training.sbatch', 'WorkDir': SEED_TREE,
    'StdOut': SEED_TREE+'/selftrain/hakusan/logs/aud_formal40_newseed20260928_202_2ea4de47_757211.log',
    'StdErr': SEED_TREE+'/selftrain/hakusan/logs/aud_formal40_newseed20260928_202_2ea4de47_757211.log',
    'command_sha256': '64a3fcbdc0b810dd96b0bf4735409f77a4ad41d60759b569ca1a09d705626220',
}}
EVIDENCE_NAME = 'upload-v4-once'


def make_transport(package=PACKAGE):
    manifest = verify_package(package, SHA)
    if manifest['scope'] != SCOPE: raise ValueError('V4_REQUIRED')
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
    # Shared, tested receiver executed as a library; its CLI defaults stay V1.
    return f'''
import hashlib, pathlib
namespace = {{'__name__': 'fine_alpha_v4_upload_receiver'}}
exec(compile({source!r}, '<bound-upload-receiver>', 'exec'), namespace)
legacy = {LEGACY!r}
def legacy_check():
    for name, expected in sorted(legacy.items()):
        path = pathlib.Path(name)
        if path.is_symlink() or not path.is_file() or any(p.is_symlink() for p in path.parents):
            raise ValueError('LEGACY_RELEASE_PATH')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('LEGACY_RELEASE_SHA')
legacy_check()
namespace['main'](remote=pathlib.Path({REMOTE_ROOT!r}), expected_scope={SCOPE!r}, reviewed_jobs={REVIEWED_JOBS!r})
legacy_check()
'''


def validate_receipt(row, count):
    if (row.get('status') != 'FINE_ALPHA_FILES_PUBLISHED' or row.get('release_sha256') != SHA or
        row.get('root') != REMOTE_ROOT or row.get('files') != count or row.get('manifest_files') != count-1 or
        type(row.get('jobs_submitted')) is not int or row['jobs_submitted'] != 0 or
        type(row.get('checkpoints_loaded')) is not int or row['checkpoints_loaded'] != 0):
        raise ValueError('V4_PUBLICATION_RECEIPT')


def validate_remote_check(row):
    if (row.get('status') != 'FINE_ALPHA_PACKAGE_CHECK_PASS' or row.get('release_sha256') != SHA or
        row.get('predictions') != 122400 or row.get('science_predictions') != 108000 or
        type(row.get('jobs_submitted')) is not int or row['jobs_submitted'] != 0 or
        row.get('production_validated') is not False): raise ValueError('V4_REMOTE_PACKAGE_CHECK')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-authorized-upload', action='store_true', required=True)
    parser.parse_args()
    manifest, blob = make_transport()
    evidence = RELEASE_ROOT/EVIDENCE_NAME
    evidence.mkdir(mode=0o700, exist_ok=False)  # Any repeat, including an ambiguous one, needs manual inspection.
    result = dict(status='UPLOAD_NOT_FINISHED', release_sha256=SHA, remote_root=REMOTE_ROOT,
                  authorized_scope='upload_v4_new_directory_and_hash_package_verification_only',
                  user_instruction='用户：“24 点加 4 个高 α 点 现在就开始准备 v4 包”；此前说明仅GPU使用需再确认',
                  evidence=str(evidence), steps=[], jobs_submitted=0,
                  gpu_authorized=False, checkpoint_loaded=False, source_only_import_check_performed=False,
                  automatic_retry=False, automatic_reconnect=False, remote_publish_attempted=False,
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  reviewed_jobs=REVIEWED_JOBS, legacy_releases=LEGACY,
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
                      bootstrap_sha256=hashlib.sha256(bootstrap.encode()).hexdigest())
        verify_package(PACKAGE, SHA)
        remote = shlex.join([REMOTE_PY, '-I', '-B', '-c', bootstrap, SHA,
                             manifest['files']['fine_alpha_entry.py']['sha256']])
        result['remote_publish_attempted'] = True
        with (evidence/'UPLOAD_INTENT.json').open('x') as stream: json.dump(result, stream, indent=2)
        raw = run('publish', SSH+[remote], blob)
        row = json.loads(raw.decode().strip().splitlines()[-1]); validate_receipt(row, len(manifest['files'])+1)
        result['publication'] = row; result['legacy_releases_unchanged'] = True
        raw = run('remote-package-check', SSH+[shlex.join([REMOTE_PY, '-I', '-B',
                   REMOTE_ROOT+'/package/fine_alpha_entry.py', 'check', SHA])], seconds=120)
        row = json.loads(raw.decode().strip().splitlines()[-1]); validate_remote_check(row)
        result['remote_check'] = row
        verify_package(PACKAGE, SHA)
        result['status'] = 'FINE_ALPHA_V4_UPLOADED_AND_HASH_VERIFIED_NO_JOB'
        print(json.dumps(result), flush=True)
    except BaseException as exc:
        result.update(status='STOPPED_INSPECT_EVIDENCE_NO_RETRY', error_type=type(exc).__name__, error=str(exc)); raise
    finally:
        result['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with (evidence/'RESULT.json').open('x') as stream: json.dump(result, stream, indent=2)
        print('UPLOAD_V4_EVIDENCE='+str(evidence), flush=True)


if __name__ == '__main__': main()

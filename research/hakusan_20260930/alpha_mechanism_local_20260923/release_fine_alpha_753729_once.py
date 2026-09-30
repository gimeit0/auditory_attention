"""Release only the verified A100 job 753729, exactly once; no resubmission."""
import argparse
import datetime
import hashlib
import inspect
import json
from pathlib import Path
import re
import shlex
import subprocess
from publish_fine_alpha import PACKAGE, RELEASE_ROOT, REMOTE_PY, REMOTE_ROOT, SHA, SOCKET, SSH
# Historical driver: its budget is the one frozen in its own package, not the current source tree.
BUDGET = json.loads((PACKAGE/'RELEASE.json').read_text())['budget']
from fine_alpha_entry import identity, verify_package
from correct_fine_alpha_753729_once import JOB, RECEIPT_SHA, held_fields

CORRECTION_SHA = '6ee3cd802bd0fbae159ba06a50958b7a21d21f9a66cd3401a5781ee515b3b1bc'
RUNNER_SHA = 'c7ac014fc70070923ebbc919dd8da83a63bf8acf0f04fb3178fea05bbf44b80c'
AUTHORIZATION = RELEASE_ROOT/'RELEASE_753729_AUTHORIZATION.json'
EVIDENCE = RELEASE_ROOT/'release-753729'


def validate_authorization(auth):
    if (auth.get('job_id') != JOB or auth.get('release_sha256') != SHA or auth.get('budget') != BUDGET
            or auth.get('release_authorized') is not True or auth.get('resubmission_authorized') is not False
            or auth.get('automatic_retry') is not False or auth.get('automatic_reconnect') is not False
            or auth.get('monitor_and_collect_authorized') is not True
            or type(auth.get('maximum_release_invocations')) is not int or auth['maximum_release_invocations'] != 1
            or auth.get('submission') != dict(size=569, sha256=RECEIPT_SHA)
            or auth.get('runner') != dict(size=952, sha256=RUNNER_SHA)
            or auth.get('correction') != dict(size=557, sha256=CORRECTION_SHA)):
        raise ValueError('RELEASE_AUTHORIZATION_SCOPE')


def released_fields(raw):
    fields = dict(re.findall(r'(\w+)=([^\s]+)', raw))
    expected = dict(JobId=JOB, JobName='audattn_fine_alpha', TimeLimit='06:00:00', Partition='GPU-1A',
                    Account='student', NumCPUs='8', NumTasks='1', MinMemoryNode='64G', Requeue='0', Restarts='0',
                    Command=REMOTE_ROOT+'/package/run_fine_alpha.sbatch', WorkDir=REMOTE_ROOT+'/state',
                    TresPerNode='gres/gpu:nvidia_a100:1')
    if any(fields.get(k) != v for k, v in expected.items()): raise ValueError('RELEASE_RESOURCE_DRIFT')
    if not fields.get('UserId', '').startswith('s2510040(') or fields.get('NumNodes') not in ('1', '1-1'):
        raise ValueError('RELEASE_OWNER_NODES')
    tres = dict(t.split('=', 1) for t in fields.get('ReqTRES', '').split(',') if '=' in t)
    if (tres.get('cpu') != '8' or tres.get('node') != '1' or tres.get('mem') not in ('64G', '65536M')
            or tres.get('gres/gpu:nvidia_a100') != '1' or tres.get('gres/gpu') not in (None, '1')
            or any(k.startswith('gres/') and k not in ('gres/gpu', 'gres/gpu:nvidia_a100') for k in tres)):
        raise ValueError('RELEASE_TYPED_GRES')
    if fields.get('JobState') not in ('PENDING', 'RUNNING') or fields.get('Reason') == 'JobHeldUser':
        raise ValueError('RELEASE_STATE_NEEDS_INSPECTION_NO_RETRY')
    if fields.get('JobState') == 'PENDING' and (not fields.get('Priority', '').isdigit() or int(fields['Priority']) <= 0):
        raise ValueError('RELEASE_PRIORITY')
    return fields


REMOTE = r'''
import hashlib, json, os, pathlib, pwd, re, subprocess, sys
JOB = '753729'
REMOTE_ROOT = '/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v1'
''' + inspect.getsource(held_fields) + r'''
def emit(stage, **kw): print(json.dumps(dict(stage=stage, **kw)), flush=True)
def identify(path):
    if path.is_symlink() or not path.is_file(): raise ValueError('PINNED_FILE')
    raw = path.read_bytes(); return dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
def write(path, row):
    with path.open('x') as f:
        json.dump(row, f, indent=2, sort_keys=True, allow_nan=False); f.flush(); os.fsync(f.fileno())
def command(stage, argv, timeout=30):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    emit(stage, argv=argv, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
    if p.returncode: raise ValueError(stage+'_NONZERO_INSPECT_NO_RETRY')
    return p.stdout
digest, entry_sha, auth_sha = sys.argv[1:]
root = pathlib.Path(REMOTE_ROOT); package = root/'package'; state = root/'state'
if sys.platform != 'linux' or pwd.getpwuid(os.getuid()).pw_name != 's2510040': raise ValueError('NATIVE_ACCOUNT')
if not sys.flags.isolated or not sys.dont_write_bytecode: raise ValueError('ISOLATED_REQUIRED')
for p in (package, state, root, *root.parents):
    if p.is_symlink() or not p.is_dir(): raise ValueError('DIRECTORY')
for p in (root, state):
    if p.stat().st_uid != os.getuid() or p.stat().st_mode & 0o077: raise ValueError('PRIVATE_DIRECTORY')
raw = sys.stdin.buffer.read(65537)
if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != auth_sha: raise ValueError('AUTHORIZATION_TRANSPORT')
auth = json.loads(raw)
if (auth.get('job_id') != JOB or auth.get('release_sha256') != digest or auth.get('release_authorized') is not True
    or auth.get('maximum_release_invocations') != 1 or auth.get('resubmission_authorized') is not False
    or auth.get('automatic_retry') is not False): raise ValueError('AUTHORIZATION_SCOPE')
if identify(package/'RELEASE.json')['sha256'] != digest or identify(package/'fine_alpha_entry.py')['sha256'] != entry_sha:
    raise ValueError('PACKAGE_EXTERNAL_HASH')
ns = dict(__name__='fine_release_bootstrap', __file__=str(package/'fine_alpha_entry.py'))
exec(compile((package/'fine_alpha_entry.py').read_bytes(), ns['__file__'], 'exec'), ns)
release = ns['verify_package'](package, digest)
receipt = json.loads((state/'SUBMISSION.json').read_text())
approval = json.loads((state/'APPROVAL.json').read_text())
ns['approval_gate'](approval, receipt, auth, digest, release['budget'], JOB,
                    identify(state/'APPROVAL.json'), identify(state/'SUBMISSION.json'), identify(package/'run_fine_alpha.sbatch'))
if auth['budget'] != release['budget']: raise ValueError('BUDGET')
for key, name in (('approval', 'APPROVAL.json'), ('intent', 'INTENT.json'), ('response', 'RESPONSE.json')):
    if receipt[key] != identify(state/name): raise ValueError('SUBMISSION_JOURNAL')
correction = state/'GRES_CORRECTION_753729_RESULT.json'
if identify(correction) != auth['correction']: raise ValueError('CORRECTION_SHA')
c = json.loads(correction.read_text())
if c['job_id'] != JOB or c['status'] != 'FINE_ALPHA_A100_CORRECTED_VERIFIED_STILL_HELD' or c['updates'] != 1:
    raise ValueError('CORRECTION_RECORD')
for name in ('RELEASE_AUTHORIZATION.json', 'RELEASE_753729_INTENT.json', 'RELEASE_753729_RESULT.json', 'attempt'):
    if os.path.lexists(state/name): raise ValueError('RELEASE_ALREADY_ATTEMPTED_INSPECT_NO_RETRY')
command('package-check', [sys.executable, '-I', '-B', str(package/'fine_alpha_entry.py'), 'check', digest], timeout=90)
before = command('before', ['/usr/bin/scontrol', 'show', 'job', '-o', JOB]); held_fields(before, 'nvidia_a100')
spool = command('spool', ['/usr/bin/scontrol', 'write', 'batch_script', JOB, '-'])
if spool.encode() != (package/'run_fine_alpha.sbatch').read_bytes(): raise ValueError('SPOOL_CHANGED')
preserved = {name: identify(state/name) for name in ('APPROVAL.json', 'INTENT.json', 'RESPONSE.json', 'SUBMISSION.json',
                                                   'STOPPED.json', 'GRES_CORRECTION_753729_RESULT.json')}
os.umask(0o077)
release_command = ['/usr/bin/scontrol', 'release', JOB]
write(state/'RELEASE_753729_INTENT.json', dict(job_id=JOB, release_sha256=digest, argv=release_command,
                                            authorization_sha256=auth_sha, before=before, automatic_retry=False))
with (state/'RELEASE_AUTHORIZATION.json').open('xb') as f:
    f.write(raw); f.flush(); os.fsync(f.fileno())
command('release_once', release_command)
result = dict(status='FINE_ALPHA_RELEASE_COMMAND_ACCEPTED', job_id=JOB, release_sha256=digest,
              release_invocations=1, authorization=identify(state/'RELEASE_AUTHORIZATION.json'),
              resubmission_attempted=False, automatic_retry=False)
write(state/'RELEASE_753729_RESULT.json', result); emit('release-result', result=result)
command('after', ['/usr/bin/scontrol', 'show', 'job', '-o', JOB])
command('queue', ['/usr/bin/squeue', '-h', '-j', JOB, '-o', '%i|%T|%r|%b|%N'])
ns['verify_package'](package, digest)
if any(identify(state/name) != expected for name, expected in preserved.items()): raise ValueError('JOURNAL_CHANGED')
emit('post-check', status='FINE_ALPHA_RELEASE_POSTCHECK_PASS', package_unchanged=True, original_journals_unchanged=True)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-authorized-release-once', required=True, action='store_true')
    parser.parse_args()
    manifest = verify_package(PACKAGE, SHA)
    raw = AUTHORIZATION.read_bytes(); validate_authorization(json.loads(raw))
    if SOCKET.is_symlink() or not SOCKET.is_socket(): raise ValueError('MASTER_ABSENT_USER_RECONNECT_REQUIRED')
    EVIDENCE.mkdir(mode=0o700, exist_ok=False)
    result = dict(status='RELEASE_NOT_ATTEMPTED', job_id=JOB, release_sha256=SHA, resubmission_attempted=False,
                  automatic_retry=False, started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    try:
        master = subprocess.run(['/usr/bin/ssh', '-S', str(SOCKET), '-O', 'check', 's2510040@hakusan1'], capture_output=True, timeout=10)
        (EVIDENCE/'master.log').write_bytes(master.stdout+master.stderr)
        if master.returncode: raise ValueError('MASTER_UNAVAILABLE_NO_RECONNECT')
        (EVIDENCE/'LOCAL_INTENT.json').write_text(json.dumps(dict(authorization=identity(AUTHORIZATION),
            driver=identity(Path(__file__)), scope='RELEASE_753729_ONCE_THEN_READ_ONLY_MONITOR_AND_COLLECT'), indent=2)+'\n')
        cmd = shlex.join([REMOTE_PY, '-I', '-B', '-c', REMOTE, SHA,
                          manifest['files']['fine_alpha_entry.py']['sha256'], hashlib.sha256(raw).hexdigest()])
        result['status'] = 'RELEASE_UNKNOWN_INSPECT_NO_RETRY'
        with (EVIDENCE/'remote.jsonl').open('xb') as out, (EVIDENCE/'remote.stderr').open('xb') as err:
            p = subprocess.run(SSH+[cmd], input=raw, stdout=out, stderr=err, timeout=240)
        result['transport_returncode'] = p.returncode
        rows = [json.loads(line) for line in (EVIDENCE/'remote.jsonl').read_text().splitlines() if line.strip()]
        stages = {row['stage']: row for row in rows}
        accepted = stages.get('release-result', {}).get('result', {})
        if accepted.get('status') == 'FINE_ALPHA_RELEASE_COMMAND_ACCEPTED': result.update(accepted)
        if p.returncode: raise ValueError('REMOTE_NONZERO_INSPECT_NO_RETRY')
        if len(rows) != len(stages) or accepted.get('job_id') != JOB or accepted.get('release_invocations') != 1:
            raise ValueError('RELEASE_RECORD')
        held_fields(stages['before']['stdout'], 'nvidia_a100')
        if stages['release_once']['argv'] != ['/usr/bin/scontrol', 'release', JOB]: raise ValueError('RELEASE_ARGV')
        fields = released_fields(stages['after']['stdout'])
        if stages['post-check']['status'] != 'FINE_ALPHA_RELEASE_POSTCHECK_PASS': raise ValueError('POST_CHECK')
        verify_package(PACKAGE, SHA)
        result.update(status='FINE_ALPHA_RELEASED_READBACK_VERIFIED', fields=fields)
        print(json.dumps(result), flush=True)
    except BaseException as exc:
        result.update(error_type=type(exc).__name__, error=str(exc)); raise
    finally:
        result['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (EVIDENCE/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
        print('EVIDENCE='+str(EVIDENCE), flush=True)


if __name__ == '__main__':
    main()

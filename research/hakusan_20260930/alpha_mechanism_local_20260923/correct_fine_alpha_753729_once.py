"""Job 753729 only: one explicitly authorized GRES correction, still held."""
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
from fine_alpha_entry import identity, verify_package

JOB = '753729'
RECEIPT_SHA = '97579946e89d4efaf2f98909c9e2c7641105c7ade5c1a290328d0e55f10cffa7'
AUTHORIZATION = RELEASE_ROOT/'GRES_CORRECTION_753729_AUTHORIZATION.json'
EVIDENCE = RELEASE_ROOT/'gres-correction-753729'


def validate_authorization(auth):
    if (auth.get('job_id') != JOB or auth.get('release_sha256') != SHA
            or auth.get('submission_sha256') != RECEIPT_SHA
            or type(auth.get('maximum_update_invocations')) is not int or auth['maximum_update_invocations'] != 1
            or auth.get('requested_gres') != 'gpu:nvidia_a100:1'
            or auth.get('preserve_other_resources') is not True or auth.get('must_remain_held') is not True
            or auth.get('release_authorized') is not False or auth.get('resubmission_authorized') is not False
            or auth.get('automatic_retry') is not False):
        raise ValueError('CORRECTION_AUTHORIZATION_SCOPE')


def held_fields(raw, gpu_type):
    if gpu_type not in ('h100-20c', 'nvidia_a100'): raise ValueError('GPU_TYPE')
    fields = dict(re.findall(r'(\w+)=([^\s]+)', raw))
    expected = dict(JobId=JOB, JobName='audattn_fine_alpha', JobState='PENDING', Reason='JobHeldUser',
                    Priority='0', RunTime='00:00:00', TimeLimit='06:00:00', Partition='GPU-1A', Account='student',
                    NumCPUs='8', NumTasks='1', MinMemoryNode='64G', Requeue='0', Restarts='0',
                    Command=REMOTE_ROOT+'/package/run_fine_alpha.sbatch', WorkDir=REMOTE_ROOT+'/state')
    if any(fields.get(k) != v for k, v in expected.items()): raise ValueError('HELD_BUDGET_IDENTITY')
    if not fields.get('UserId', '').startswith('s2510040(') or fields.get('NumNodes') not in ('1', '1-1'):
        raise ValueError('OWNER_OR_NODES')
    tres = dict(item.split('=', 1) for item in fields.get('ReqTRES', '').split(',') if '=' in item)
    typed = 'gres/gpu:'+gpu_type
    if (tres.get('cpu') != '8' or tres.get('node') != '1' or tres.get('mem') not in ('64G', '65536M')
            or tres.get(typed) != '1' or tres.get('gres/gpu') not in (None, '1')
            or any(k.startswith('gres/') and k not in ('gres/gpu', typed) for k in tres)):
        raise ValueError('EXACT_GRES_AND_BUDGET_REQUIRED')
    per_node = 'gres/gpu:1' if gpu_type == 'h100-20c' else 'gres/gpu:nvidia_a100:1'
    if fields.get('TresPerNode') != per_node: raise ValueError('TRES_PER_NODE')
    return fields


REMOTE = r'''
import hashlib, json, os, pathlib, pwd, re, subprocess, sys
JOB = '753729'
REMOTE_ROOT = '/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v1'
SHA = 'b0bd8b4269b5542b65bbf6d3982b7484838f983d0c5fe7a9538551ea9a076b8f'
RECEIPT_SHA = '97579946e89d4efaf2f98909c9e2c7641105c7ade5c1a290328d0e55f10cffa7'
''' + inspect.getsource(validate_authorization) + '\n' + inspect.getsource(held_fields) + r'''
def emit(stage, **kw): print(json.dumps(dict(stage=stage, **kw)), flush=True)
def identify(path):
    if path.is_symlink() or not path.is_file(): raise ValueError('PINNED_FILE')
    raw = path.read_bytes()
    return dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
def write(path, record):
    with path.open('x') as f:
        json.dump(record, f, sort_keys=True, indent=2, allow_nan=False); f.flush(); os.fsync(f.fileno())
def command(stage, argv):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    emit(stage, argv=argv, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
    if p.returncode: raise ValueError(stage+'_FAILED_NO_RETRY')
    return p.stdout
root = pathlib.Path(REMOTE_ROOT); package = root/'package'; state = root/'state'
entry_sha, auth_sha = sys.argv[1:]
if sys.platform != 'linux' or pwd.getpwuid(os.getuid()).pw_name != 's2510040': raise ValueError('NATIVE_ACCOUNT')
if not sys.flags.isolated or not sys.dont_write_bytecode: raise ValueError('ISOLATED_REQUIRED')
for p in (package, state, root, *root.parents):
    if p.is_symlink() or not p.is_dir(): raise ValueError('DIRECTORY')
for p in (root, state):
    if p.stat().st_uid != os.getuid() or p.stat().st_mode & 0o077: raise ValueError('PRIVATE_DIRECTORY')
raw = sys.stdin.buffer.read(65537)
if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != auth_sha: raise ValueError('AUTHORIZATION_TRANSPORT')
auth = json.loads(raw); validate_authorization(auth)
if identify(package/'RELEASE.json')['sha256'] != SHA or identify(package/'fine_alpha_entry.py')['sha256'] != entry_sha:
    raise ValueError('EXTERNAL_PACKAGE_HASH')
namespace = dict(__name__='fine_correction_bootstrap', __file__=str(package/'fine_alpha_entry.py'))
exec(compile((package/'fine_alpha_entry.py').read_bytes(), namespace['__file__'], 'exec'), namespace)
release = namespace['verify_package'](package, SHA)
receipt_id = identify(state/'SUBMISSION.json')
if receipt_id['sha256'] != RECEIPT_SHA: raise ValueError('SUBMISSION_SHA')
receipt = json.loads((state/'SUBMISSION.json').read_text())
if receipt['job_id'] != JOB or receipt['release_sha256'] != SHA or receipt['status'] != 'SUBMITTED_HELD_NOT_RELEASED':
    raise ValueError('SUBMISSION_BINDING')
for key, name in (('approval', 'APPROVAL.json'), ('intent', 'INTENT.json'), ('response', 'RESPONSE.json')):
    if identify(state/name) != receipt[key]: raise ValueError('SUBMISSION_JOURNAL')
approval = json.loads((state/'APPROVAL.json').read_text())
if (approval['budget'] != release['budget'] or approval['release_sha256'] != SHA or approval['authorized'] is not True
    or approval['single_held_submission_authorized'] is not True or approval['release_authorized'] is not False):
    raise ValueError('HELD_APPROVAL')
if os.path.lexists(state/'RELEASE_AUTHORIZATION.json'): raise ValueError('RELEASE_ALREADY_AUTHORIZED')
intent_path = state/'GRES_CORRECTION_753729_INTENT.json'
result_path = state/'GRES_CORRECTION_753729_RESULT.json'
if os.path.lexists(intent_path) or os.path.lexists(result_path): raise ValueError('CORRECTION_ALREADY_ATTEMPTED_NO_RETRY')
preserved = {name: identify(state/name) for name in ('APPROVAL.json', 'INTENT.json', 'RESPONSE.json', 'SUBMISSION.json', 'STOPPED.json')}
before = command('before', ['/usr/bin/scontrol', 'show', 'job', '-o', JOB]); held_fields(before, 'h100-20c')
spool_before = command('spool-before', ['/usr/bin/scontrol', 'write', 'batch_script', JOB, '-'])
if spool_before.encode() != (package/'run_fine_alpha.sbatch').read_bytes(): raise ValueError('SPOOL_BEFORE_CHANGED')
update = ['/usr/bin/scontrol', 'update', 'JobId='+JOB, 'Gres=gpu:nvidia_a100:1']
os.umask(0o077)
write(intent_path, dict(job_id=JOB, release_sha256=SHA, authorization=auth, submission=receipt_id,
                       argv=update, before=before, authorized_once=True, release_authorized=False))
emit('intent', identity=identify(intent_path))
command('update_once', update)  # The only scheduler mutation; no retry on error or timeout.
after = command('after', ['/usr/bin/scontrol', 'show', 'job', '-o', JOB]); held_fields(after, 'nvidia_a100')
spool_after = command('spool-after', ['/usr/bin/scontrol', 'write', 'batch_script', JOB, '-'])
if spool_after != spool_before: raise ValueError('SPOOL_AFTER_CHANGED')
command('queue', ['/usr/bin/squeue', '-h', '-j', JOB, '-o', '%i|%T|%r|%b'])
namespace['verify_package'](package, SHA)
if any(identify(state/name) != value for name, value in preserved.items()): raise ValueError('JOURNAL_CHANGED')
result = dict(status='FINE_ALPHA_A100_CORRECTED_VERIFIED_STILL_HELD', job_id=JOB, release_sha256=SHA,
              updates=1, release_attempted=False, resubmission_attempted=False, automatic_retry=False,
              submission=receipt_id, spool_sha256=hashlib.sha256(spool_after.encode()).hexdigest(),
              original_journals_unchanged=True, package_unchanged=True)
write(result_path, result); emit('result', result=result)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-authorized-correction-once', required=True, action='store_true')
    parser.parse_args()
    release = verify_package(PACKAGE, SHA)
    raw = AUTHORIZATION.read_bytes(); auth = json.loads(raw); validate_authorization(auth)
    if SOCKET.is_symlink() or not SOCKET.is_socket(): raise ValueError('MASTER_ABSENT_USER_RECONNECT_REQUIRED')
    EVIDENCE.mkdir(mode=0o700, exist_ok=False)
    result = dict(status='CORRECTION_NOT_ATTEMPTED', job_id=JOB, release_sha256=SHA,
                  release_attempted=False, resubmission_attempted=False, automatic_retry=False,
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    try:
        master = subprocess.run(['/usr/bin/ssh', '-S', str(SOCKET), '-O', 'check', 's2510040@hakusan1'], capture_output=True, timeout=10)
        (EVIDENCE/'master.log').write_bytes(master.stdout+master.stderr)
        if master.returncode: raise ValueError('MASTER_UNAVAILABLE_NO_RECONNECT')
        (EVIDENCE/'LOCAL_INTENT.json').write_text(json.dumps(dict(authorization=auth,
            authorization_identity=identity(AUTHORIZATION), driver=identity(Path(__file__))), indent=2)+'\n')
        cmd = shlex.join([REMOTE_PY, '-I', '-B', '-c', REMOTE,
                          release['files']['fine_alpha_entry.py']['sha256'], hashlib.sha256(raw).hexdigest()])
        result['status'] = 'CORRECTION_UNKNOWN_INSPECT_NO_RETRY'
        with (EVIDENCE/'remote.jsonl').open('xb') as out, (EVIDENCE/'remote.stderr').open('xb') as err:
            p = subprocess.run(SSH+[cmd], input=raw, stdout=out, stderr=err, timeout=240)
        result['transport_returncode'] = p.returncode
        if p.returncode: raise ValueError('REMOTE_NONZERO_INSPECT_NO_RETRY')
        rows = [json.loads(line) for line in (EVIDENCE/'remote.jsonl').read_text().splitlines() if line.strip()]
        stages = {row['stage']: row for row in rows}
        if len(stages) != len(rows): raise ValueError('DUPLICATE_STAGE')
        held_fields(stages['before']['stdout'], 'h100-20c')
        fields = held_fields(stages['after']['stdout'], 'nvidia_a100')
        if stages['update_once']['argv'] != ['/usr/bin/scontrol', 'update', 'JobId='+JOB, 'Gres=gpu:nvidia_a100:1']:
            raise ValueError('UPDATE_SCOPE')
        for name in ('before', 'spool-before', 'update_once', 'after', 'spool-after', 'queue'):
            if stages[name]['returncode'] != 0: raise ValueError('COMMAND_FAILED')
        for name in ('spool-before', 'spool-after'):
            if stages[name]['stdout'].encode() != (PACKAGE/'run_fine_alpha.sbatch').read_bytes(): raise ValueError('SPOOL_CHANGED')
        final = stages['result']['result']
        if (final.get('status') != 'FINE_ALPHA_A100_CORRECTED_VERIFIED_STILL_HELD' or final.get('job_id') != JOB
                or final.get('release_sha256') != SHA or final.get('updates') != 1 or final.get('release_attempted') is not False
                or final.get('resubmission_attempted') is not False or final.get('original_journals_unchanged') is not True
                or final.get('submission', {}).get('sha256') != RECEIPT_SHA
                or final.get('spool_sha256') != release['files']['run_fine_alpha.sbatch']['sha256']):
            raise ValueError('FINAL_RECORD')
        verify_package(PACKAGE, SHA)
        result.update(final, fields=fields)
        print(json.dumps(result), flush=True)
    except BaseException as exc:
        result.update(error_type=type(exc).__name__, error=str(exc)); raise
    finally:
        result['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (EVIDENCE/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
        print('EVIDENCE='+str(EVIDENCE), flush=True)


if __name__ == '__main__':
    main()

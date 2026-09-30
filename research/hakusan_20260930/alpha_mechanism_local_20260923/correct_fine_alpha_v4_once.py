"""V4 held job only: one GRES correction h100-20c -> nvidia_a100, still held; no release/resubmission."""
import argparse
import datetime
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from publish_fine_alpha import REMOTE_PY, SOCKET, SSH
from publish_fine_alpha_v4 import PACKAGE, RELEASE_ROOT, REMOTE_ROOT, SHA
from submit_fine_alpha_v4 import completed_result, submission_evidence
from fine_alpha_entry import identity, verify_package

REFUSED = 'CORRECTION_NOT_ATTEMPTED_REMOTE_REFUSED'


def _attempts():
    found = sorted(RELEASE_ROOT.glob('gres-correction-v4-*'), key=lambda p: int(p.name.rsplit('-', 1)[1]))
    if [int(p.name.rsplit('-', 1)[1]) for p in found] != list(range(1, len(found)+1)): raise ValueError('ATTEMPT_SEQUENCE')
    return found


def _clean_no_update(directory):
    row = json.loads((directory/'RESULT.json').read_text())
    never_sent = (row.get('status') == 'CORRECTION_NOT_ATTEMPTED' and 'transport_returncode' not in row
                  and not os.path.lexists(directory/'remote.jsonl') and not os.path.lexists(directory/'remote.stderr'))
    return never_sent or (row.get('status') == REFUSED and row.get('update_reached') is False)


def attempt_paths():
    previous = _attempts()
    for directory in previous:
        if not _clean_no_update(directory): raise ValueError('PRIOR_CORRECTION_ATTEMPT_INSPECT_NO_RETRY: '+directory.name)
    n = len(previous)+1
    return RELEASE_ROOT/f'GRES_CORRECTION_AUTHORIZATION_{n}.json', RELEASE_ROOT/f'gres-correction-v4-{n}'


def correction_evidence():
    """The attempt that completed the correction; every earlier attempt must be a clean no-update stop."""
    found = _attempts()
    if not found: raise ValueError('NO_CORRECTION_ATTEMPT')
    *earlier, last = found
    for directory in earlier:
        if not _clean_no_update(directory): raise ValueError('PRIOR_CORRECTION_ATTEMPT_INSPECT: '+directory.name)
    return last


def submission_binding():
    """Job id and receipt identity only from the verified local held-submission evidence."""
    evidence = submission_evidence()
    result = completed_result(json.loads((evidence/'RESULT.json').read_text()))
    if (result.get('status') != 'FINE_ALPHA_SUBMITTED_HELD_RESOURCE_MISMATCH' or result.get('release_sha256') != SHA
            or result.get('resource_error') != 'SCHEDULER_TYPED_GRES'
            or result.get('jobs_submitted') != 1 or result.get('held') is not True):
        raise ValueError('HELD_MISMATCH_SUBMISSION_REQUIRED')
    job = result['job_id']
    if not re.fullmatch(r'[1-9][0-9]*', job): raise ValueError('JOB_ID')
    # Only the observed h100-20c rewrite is correctable here; check its exact shape before any file is created.
    rows = [json.loads(line) for line in (evidence/'remote.jsonl').read_text().splitlines() if line.strip()]
    observed = [row for row in rows if row.get('stage') == 'scontrol']
    if len(observed) != 1 or observed[0].get('returncode') != 0: raise ValueError('HELD_READBACK')
    held_fields(observed[0]['stdout'], 'h100-20c', job, REMOTE_ROOT)
    return job, result['submission_identity']


def validate_authorization(auth, job, receipt):
    if (auth.get('job_id') != job or auth.get('release_sha256') != SHA
            or auth.get('submission') != receipt
            or type(auth.get('maximum_update_invocations')) is not int or auth['maximum_update_invocations'] != 1
            or auth.get('requested_gres') != 'gpu:nvidia_a100:1'
            or auth.get('preserve_other_resources') is not True or auth.get('must_remain_held') is not True
            or auth.get('release_authorized') is not False or auth.get('resubmission_authorized') is not False
            or auth.get('automatic_retry') is not False):
        raise ValueError('CORRECTION_AUTHORIZATION_SCOPE')


def held_fields(raw, gpu_type, job, remote_root):
    if gpu_type not in ('h100-20c', 'nvidia_a100'): raise ValueError('GPU_TYPE')
    fields = dict(re.findall(r'(\w+)=([^\s]+)', raw))
    expected = dict(JobId=job, JobName='audattn_fine_alpha', JobState='PENDING', Reason='JobHeldUser',
                    Priority='0', RunTime='00:00:00', TimeLimit='04:00:00', Partition='GPU-1A', Account='student',
                    NumCPUs='8', NumTasks='1', MinMemoryNode='64G', Requeue='0', Restarts='0',
                    Command=remote_root+'/package/run_fine_alpha.sbatch', WorkDir=remote_root+'/state')
    if any(fields.get(k) != v for k, v in expected.items()): raise ValueError('HELD_BUDGET_IDENTITY')
    if not re.fullmatch(r's2510040\([0-9]+\)', fields.get('UserId', '')) or fields.get('NumNodes') not in ('1', '1-1'):
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
REMOTE_ROOT = '/home/s2510040/audattn_fine_alpha/fine_alpha_20260929_v4'
SHA = '0b067f57d612987d9c80a56e385658b1414095e46b5956b0bff43a7760668a2a'
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
def read(stage, argv):
    # Read-only scheduler queries only: bounded retry for transient slurmctld failures, one row per stage.
    import time
    failed = []
    for attempt in range(3):
        if attempt: time.sleep(10)
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=30)
            row = dict(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
        except subprocess.TimeoutExpired:
            row = dict(returncode=124, stdout='', stderr='READ_ONLY_QUERY_TIMEOUT')
        if row['returncode'] == 0: break
        failed.append(dict(returncode=row['returncode'], stderr=row['stderr']))
    emit(stage, argv=argv, failed_attempts=failed, **row)
    if row['returncode']: raise ValueError(stage+'_FAILED_AFTER_READ_RETRIES')
    return row['stdout']
root = pathlib.Path(REMOTE_ROOT); package = root/'package'; state = root/'state'
# Everything before the intent file is a pure check: any stop emits exactly one marker and writes nothing.
try:
    JOB, entry_sha, auth_sha, receipt_sha = sys.argv[1:]
    if not re.fullmatch(r'[1-9][0-9]*', JOB): raise ValueError('JOB_ID')
    if sys.platform != 'linux' or pwd.getpwuid(os.getuid()).pw_name != 's2510040': raise ValueError('NATIVE_ACCOUNT')
    if not sys.flags.isolated or not sys.dont_write_bytecode: raise ValueError('ISOLATED_REQUIRED')
    for p in (package, state, root, *root.parents):
        if p.is_symlink() or not p.is_dir(): raise ValueError('DIRECTORY')
    for p in (root, state):
        if p.stat().st_uid != os.getuid() or p.stat().st_mode & 0o077: raise ValueError('PRIVATE_DIRECTORY')
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != auth_sha: raise ValueError('AUTHORIZATION_TRANSPORT')
    receipt_id = identify(state/'SUBMISSION.json')
    if receipt_id['sha256'] != receipt_sha: raise ValueError('SUBMISSION_SHA')
    auth = json.loads(raw); validate_authorization(auth, JOB, receipt_id)
    if identify(package/'RELEASE.json')['sha256'] != SHA or identify(package/'fine_alpha_entry.py')['sha256'] != entry_sha:
        raise ValueError('EXTERNAL_PACKAGE_HASH')
    namespace = dict(__name__='fine_correction_v4_bootstrap', __file__=str(package/'fine_alpha_entry.py'))
    exec(compile((package/'fine_alpha_entry.py').read_bytes(), namespace['__file__'], 'exec'), namespace)
    release = namespace['verify_package'](package, SHA)
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
    intent_path = state/'GRES_CORRECTION_INTENT.json'
    result_path = state/'GRES_CORRECTION_RESULT.json'
    if os.path.lexists(intent_path) or os.path.lexists(result_path): raise ValueError('CORRECTION_ALREADY_ATTEMPTED_NO_RETRY')
    def maybe(path): return identify(path) if os.path.lexists(path) else None
    PRESERVED = ('APPROVAL.json', 'QUEUE_INITIAL.json', 'TEST_ONLY.json', 'QUEUE_FINAL.json', 'INTENT.json', 'RESPONSE.json',
                 'SUBMISSION.json', 'HELD_RESOURCES.json', 'SPOOL.json', 'STOPPED.json')
    preserved = {name: maybe(state/name) for name in PRESERVED}
    before = read('before', ['/usr/bin/scontrol', 'show', 'job', '-o', JOB]); held_fields(before, 'h100-20c', JOB, REMOTE_ROOT)
    spool_before = read('spool-before', ['/usr/bin/scontrol', 'write', 'batch_script', JOB, '-'])
    if spool_before.encode() != (package/'run_fine_alpha.sbatch').read_bytes(): raise ValueError('SPOOL_BEFORE_CHANGED')
except BaseException as exc:
    emit('refused-before-intent', kind='already_attempted' if ('ALREADY_ATTEMPTED' in str(exc) or 'ALREADY_AUTHORIZED' in str(exc)) else 'refused',
         error_type=type(exc).__name__, error=str(exc))
    raise
update = ['/usr/bin/scontrol', 'update', 'JobId='+JOB, 'Gres=gpu:nvidia_a100:1']
os.umask(0o077)
write(intent_path, dict(job_id=JOB, release_sha256=SHA, authorization=auth, submission=receipt_id,
                       argv=update, before=before, authorized_once=True, release_authorized=False))
emit('intent', identity=identify(intent_path))
command('update_once', update)  # The only scheduler mutation; no retry on error or timeout.
after = read('after', ['/usr/bin/scontrol', 'show', 'job', '-o', JOB]); held_fields(after, 'nvidia_a100', JOB, REMOTE_ROOT)
spool_after = read('spool-after', ['/usr/bin/scontrol', 'write', 'batch_script', JOB, '-'])
if spool_after != spool_before: raise ValueError('SPOOL_AFTER_CHANGED')
try:  # evidence only; never stops a verified correction
    q = subprocess.run(['/usr/bin/squeue', '-h', '-j', JOB, '-o', '%i|%T|%r|%b'], capture_output=True, text=True, timeout=30)
    emit('queue', returncode=q.returncode, stdout=q.stdout, stderr=q.stderr, evidence_only=True)
except subprocess.TimeoutExpired:
    emit('queue', returncode=124, stdout='', stderr='READ_ONLY_QUERY_TIMEOUT', evidence_only=True)
namespace['verify_package'](package, SHA)
if any(maybe(state/name) != value for name, value in preserved.items()): raise ValueError('JOURNAL_CHANGED')
result = dict(status='FINE_ALPHA_A100_CORRECTED_VERIFIED_STILL_HELD', job_id=JOB, release_sha256=SHA,
              updates=1, release_attempted=False, resubmission_attempted=False, automatic_retry=False,
              submission=receipt_id, spool_sha256=hashlib.sha256(spool_after.encode()).hexdigest(),
              original_journals_unchanged=True, package_unchanged=True)
write(result_path, result); emit('result', result=result, identity=identify(result_path))
'''


def authorization_for(job, receipt):
    return dict(schema_version=1, job_id=job, release_sha256=SHA, submission=receipt,
                maximum_update_invocations=1, requested_gres='gpu:nvidia_a100:1',
                preserve_other_resources=True, must_remain_held=True, release_authorized=False,
                resubmission_authorized=False, automatic_retry=False,
                authorization_basis=dict(date='2026-09-28', user_response='不需要我批准 我希望你直接推进到第4步',
                                         question_scope='48号文第4步：提交后如站点typed GRES改写，保持held，同作业唯一一次修正为A100；'
                                                        '用户明确授权直接推进至放行，无需逐步再批。'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-authorized-correction-once', required=True, action='store_true')
    parser.parse_args()
    release = verify_package(PACKAGE, SHA)
    job, receipt = submission_binding()
    auth = authorization_for(job, receipt); validate_authorization(auth, job, receipt)
    if SOCKET.is_symlink() or not SOCKET.is_socket(): raise ValueError('MASTER_ABSENT_USER_RECONNECT_REQUIRED')
    master = subprocess.run(['/usr/bin/ssh', '-S', str(SOCKET), '-O', 'check', 's2510040@hakusan1'], capture_output=True, timeout=10)
    if master.returncode:
        print((master.stdout+master.stderr).decode(errors='replace'), flush=True)
        raise ValueError('MASTER_UNAVAILABLE_USER_RECONNECT_REQUIRED_NOTHING_SENT')
    AUTHORIZATION, EVIDENCE = attempt_paths()
    with AUTHORIZATION.open('x') as stream: stream.write(json.dumps(auth, indent=2, ensure_ascii=False)+'\n')
    raw = AUTHORIZATION.read_bytes()
    EVIDENCE.mkdir(mode=0o700, exist_ok=False)
    result = dict(status='CORRECTION_NOT_ATTEMPTED', job_id=job, release_sha256=SHA, update_reached=None,
                  release_attempted=False, resubmission_attempted=False, automatic_retry=False,
                  authorization_file=AUTHORIZATION.name,
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    try:
        (EVIDENCE/'master.log').write_bytes(master.stdout+master.stderr)
        (EVIDENCE/'LOCAL_INTENT.json').write_text(json.dumps(dict(authorization=auth,
            authorization_identity=identity(AUTHORIZATION), driver=identity(Path(__file__))), indent=2, ensure_ascii=False)+'\n')
        cmd = shlex.join([REMOTE_PY, '-I', '-B', '-c', REMOTE, job, release['files']['fine_alpha_entry.py']['sha256'],
                          hashlib.sha256(raw).hexdigest(), receipt['sha256']])
        result['status'] = 'CORRECTION_UNKNOWN_INSPECT_NO_RETRY'
        with (EVIDENCE/'remote.jsonl').open('xb') as out, (EVIDENCE/'remote.stderr').open('xb') as err:
            p = subprocess.run(SSH+[cmd], input=raw, stdout=out, stderr=err, timeout=720)
        result['transport_returncode'] = p.returncode
        rows = [json.loads(line) for line in (EVIDENCE/'remote.jsonl').read_text().splitlines() if line.strip()]
        stages = {row['stage']: row for row in rows}
        reached = 'intent' in stages or 'update_once' in stages
        refusals = [row for row in rows if row['stage'] == 'refused-before-intent']
        if (not reached and len(refusals) == 1 and rows[-1] is refusals[0] and p.returncode != 0
                and refusals[0].get('kind') == 'refused'):
            result.update(status=REFUSED, update_reached=False, remote_refusal=refusals[0])
            raise ValueError('CORRECTION_REFUSED_BEFORE_INTENT: '+refusals[0].get('error', ''))
        result['update_reached'] = True if reached else None
        if p.returncode: raise ValueError('REMOTE_NONZERO_INSPECT_NO_RETRY')
        if len(stages) != len(rows): raise ValueError('DUPLICATE_STAGE')
        held_fields(stages['before']['stdout'], 'h100-20c', job, REMOTE_ROOT)
        fields = held_fields(stages['after']['stdout'], 'nvidia_a100', job, REMOTE_ROOT)
        if stages['update_once']['argv'] != ['/usr/bin/scontrol', 'update', 'JobId='+job, 'Gres=gpu:nvidia_a100:1']:
            raise ValueError('UPDATE_SCOPE')
        if 'queue' not in stages: raise ValueError('QUEUE_EVIDENCE_ROW')
        for name in ('before', 'spool-before', 'update_once', 'after', 'spool-after'):
            if stages[name]['returncode'] != 0: raise ValueError('COMMAND_FAILED')
        for name in ('spool-before', 'spool-after'):
            if stages[name]['stdout'].encode() != (PACKAGE/'run_fine_alpha.sbatch').read_bytes(): raise ValueError('SPOOL_CHANGED')
        final = stages['result']['result']
        if (final.get('status') != 'FINE_ALPHA_A100_CORRECTED_VERIFIED_STILL_HELD' or final.get('job_id') != job
                or final.get('release_sha256') != SHA or final.get('updates') != 1 or final.get('release_attempted') is not False
                or final.get('resubmission_attempted') is not False or final.get('original_journals_unchanged') is not True
                or final.get('submission') != receipt
                or final.get('spool_sha256') != release['files']['run_fine_alpha.sbatch']['sha256']):
            raise ValueError('FINAL_RECORD')
        verify_package(PACKAGE, SHA)
        result.update(final, fields=fields, result_identity=stages['result']['identity'])
        print(json.dumps(result), flush=True)
    except BaseException as exc:
        result.update(error_type=type(exc).__name__, error=str(exc)); raise
    finally:
        result['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (EVIDENCE/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
        print('EVIDENCE='+str(EVIDENCE), flush=True)


if __name__ == '__main__':
    main()

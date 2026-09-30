"""V4 held job only: re-check resources and concurrency, then release exactly once; no resubmission."""
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
# Historical driver: its budget is the one frozen in its own package, not the current source tree.
BUDGET = json.loads((PACKAGE/'RELEASE.json').read_text())['budget']
from fine_alpha_entry import identity, verify_package
from submit_fine_alpha_v4 import completed_result, submission_evidence
from correct_fine_alpha_v4_once import correction_evidence, held_fields
import review_fine_alpha_v4_queue as queue_review

# Attempt-scoped names: a remote refusal before `scontrol release` leaves a later attempt possible,
# but any attempt that reached (or may have reached) the release command blocks every rerun.
REFUSED = 'RELEASE_NOT_ATTEMPTED_REMOTE_REFUSED'


def attempt_paths():
    previous = sorted(RELEASE_ROOT.glob('release-v4-*'), key=lambda p: int(p.name.rsplit('-', 1)[1]))
    for directory in previous:
        row = json.loads((directory/'RESULT.json').read_text())
        never_sent = (row.get('status') == 'RELEASE_NOT_ATTEMPTED' and 'transport_returncode' not in row
                      and not os.path.lexists(directory/'remote.jsonl') and not os.path.lexists(directory/'remote.stderr'))
        refused = row.get('status') == REFUSED and row.get('release_command_reached') is False
        if not (never_sent or refused):
            raise ValueError('PRIOR_RELEASE_ATTEMPT_INSPECT_NO_RETRY: '+directory.name)
    n = len(previous)+1
    if [int(p.name.rsplit('-', 1)[1]) for p in previous] != list(range(1, n)): raise ValueError('ATTEMPT_SEQUENCE')
    return RELEASE_ROOT/f'RELEASE_AUTHORIZATION_{n}.json', RELEASE_ROOT/f'release-v4-{n}'


def held_binding():
    """Job, receipt and (if needed) correction identities only from verified local evidence."""
    submitted = completed_result(json.loads((submission_evidence()/'RESULT.json').read_text()))
    if submitted.get('release_sha256') != SHA or submitted.get('held') is not True or submitted.get('jobs_submitted') != 1:
        raise ValueError('HELD_SUBMISSION_REQUIRED')
    job = submitted['job_id']
    if not re.fullmatch(r'[1-9][0-9]*', job): raise ValueError('JOB_ID')
    after = submitted['finished_utc']
    if submitted.get('status') == 'FINE_ALPHA_HELD_RESOURCES_VERIFIED_NOT_RELEASED':
        correction = None
    elif submitted.get('status') == 'FINE_ALPHA_SUBMITTED_HELD_RESOURCE_MISMATCH':
        corrected = json.loads((correction_evidence()/'RESULT.json').read_text())
        if ('error' in corrected or 'error_type' in corrected or corrected.get('transport_returncode') != 0
                or corrected.get('status') != 'FINE_ALPHA_A100_CORRECTED_VERIFIED_STILL_HELD' or corrected.get('job_id') != job
                or corrected.get('release_sha256') != SHA or corrected.get('updates') != 1
                or corrected.get('submission') != submitted['submission_identity']):
            raise ValueError('CORRECTION_REQUIRED')
        # Identity of the remote state/GRES_CORRECTION_RESULT.json bytes, as read back on the cluster.
        correction = corrected.get('result_identity')
        if (type(correction) is not dict or set(correction) != {'size', 'sha256'}
                or not re.fullmatch(r'[0-9a-f]{64}', str(correction['sha256']))):
            raise ValueError('CORRECTION_IDENTITY')
        after = corrected['finished_utc']
    else:
        raise ValueError('HELD_SUBMISSION_STATUS')
    return job, submitted['submission_identity'], correction, after


def fresh_review(job, after):
    """Newest release-time read-only capture for this held job; it must postdate the submission/correction
    and every earlier release attempt, and it must itself have passed (a newer refusal is never skipped)."""
    floor = after
    for directory in RELEASE_ROOT.glob('release-v4-*'):
        floor = max(floor, json.loads((directory/'RESULT.json').read_text())['finished_utc'])
    rows = []
    for directory in RELEASE_ROOT.glob('queue-review-*'):
        if not (directory/'RESULT.json').is_file(): raise ValueError('QUEUE_REVIEW_WITHOUT_RESULT: '+directory.name)
        row = json.loads((directory/'RESULT.json').read_text())
        if row.get('own_held_job') == job and row.get('started_utc', '') > floor: rows.append((row['started_utc'], directory, row))
    if not rows: raise ValueError('RELEASE_TIME_QUEUE_REVIEW_REQUIRED')
    _, directory, row = max(rows, key=lambda item: item[0])
    if row.get('status') != 'FINE_ALPHA_V4_CONCURRENCY_REVIEW_CAPTURED' or row.get('release_sha256') != SHA:
        raise ValueError('RELEASE_TIME_QUEUE_REVIEW_STATUS')
    rebuilt, _ = queue_review.build_review(row['capture'], job)
    if rebuilt != row['review'] or json.loads((directory/'CONCURRENCY_REVIEW.json').read_text()) != rebuilt:
        raise ValueError('RELEASE_TIME_QUEUE_REVIEW_MISMATCH')
    return rebuilt, dict(path=str(directory.relative_to(RELEASE_ROOT)), **identity(directory/'RESULT.json'))


def validate_authorization(auth, job, receipt, runner, correction):
    if (auth.get('job_id') != job or auth.get('release_sha256') != SHA or auth.get('budget') != BUDGET
            or auth.get('release_authorized') is not True or auth.get('resubmission_authorized') is not False
            or auth.get('automatic_retry') is not False or auth.get('automatic_reconnect') is not False
            or auth.get('monitor_and_collect_authorized') is not True
            or type(auth.get('maximum_release_invocations')) is not int or auth['maximum_release_invocations'] != 1
            or auth.get('submission') != receipt or auth.get('runner') != runner
            or auth.get('correction') != correction or auth.get('scheduler_quota_verified') is not False):
        raise ValueError('RELEASE_AUTHORIZATION_SCOPE')
    queue_review.load_queue_module().validate_review(auth.get('concurrency_review'))


def released_fields(raw, job, remote_root):
    fields = dict(re.findall(r'(\w+)=([^\s]+)', raw))
    expected = dict(JobId=job, JobName='audattn_fine_alpha', TimeLimit='04:00:00', Partition='GPU-1A',
                    Account='student', NumCPUs='8', NumTasks='1', MinMemoryNode='64G', Requeue='0', Restarts='0',
                    Command=remote_root+'/package/run_fine_alpha.sbatch', WorkDir=remote_root+'/state',
                    TresPerNode='gres/gpu:nvidia_a100:1')
    if any(fields.get(k) != v for k, v in expected.items()): raise ValueError('RELEASE_RESOURCE_DRIFT')
    if not re.fullmatch(r's2510040\([0-9]+\)', fields.get('UserId', '')) or fields.get('NumNodes') not in ('1', '1-1'):
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


def own_row_filter(scheduler, job, own):
    """Remove exactly this held job's own queue row; everything else goes to the frozen reviewer."""
    mine = job+'|audattn_fine_alpha|PENDING'
    def execute(argv):
        row = scheduler(argv)
        if argv[:2] == ['/usr/bin/squeue', '-h'] and row['returncode'] == 0:
            lines = row['stdout'].splitlines()
            own.extend(line for line in lines if line == mine)
            row = dict(row, stdout=''.join(line+'\n' for line in lines if line != mine))
        return row
    return execute


REMOTE = r'''
import hashlib, json, os, pathlib, pwd, re, subprocess, sys
REMOTE_ROOT = '/home/s2510040/audattn_fine_alpha/fine_alpha_20260929_v4'
''' + inspect.getsource(held_fields) + '\n' + inspect.getsource(own_row_filter) + r'''
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
JOB, digest, entry_sha, auth_sha = sys.argv[1:]
if not re.fullmatch(r'[1-9][0-9]*', JOB): raise ValueError('JOB_ID')
root = pathlib.Path(REMOTE_ROOT); package = root/'package'; state = root/'state'
# Everything up to the first state write is a pure check: any stop here emits exactly one
# 'refused-before-write' marker and writes nothing, so a later attempt stays possible.
queue = []; own = []
try:
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
    ns = dict(__name__='fine_release_v4_bootstrap', __file__=str(package/'fine_alpha_entry.py'))
    exec(compile((package/'fine_alpha_entry.py').read_bytes(), ns['__file__'], 'exec'), ns)
    release = ns['verify_package'](package, digest)
    receipt = json.loads((state/'SUBMISSION.json').read_text())
    approval = json.loads((state/'APPROVAL.json').read_text())
    ns['approval_gate'](approval, receipt, auth, digest, release['budget'], JOB,
                        identify(state/'APPROVAL.json'), identify(state/'SUBMISSION.json'), identify(package/'run_fine_alpha.sbatch'))
    if auth['budget'] != release['budget']: raise ValueError('BUDGET')
    for key, name in (('approval', 'APPROVAL.json'), ('intent', 'INTENT.json'), ('response', 'RESPONSE.json')):
        if receipt[key] != identify(state/name): raise ValueError('SUBMISSION_JOURNAL')
    correction = state/'GRES_CORRECTION_RESULT.json'
    if auth['correction'] is None:
        if os.path.lexists(correction): raise ValueError('UNBOUND_CORRECTION_RECORD')
    else:
        if identify(correction) != auth['correction']: raise ValueError('CORRECTION_SHA')
        c = json.loads(correction.read_text())
        if c['job_id'] != JOB or c['status'] != 'FINE_ALPHA_A100_CORRECTED_VERIFIED_STILL_HELD' or c['updates'] != 1:
            raise ValueError('CORRECTION_RECORD')
    for name in ('RELEASE_AUTHORIZATION.json', 'RELEASE_INTENT.json', 'RELEASE_RESULT.json', 'QUEUE_RELEASE.json', 'attempt'):
        if os.path.lexists(state/name): raise ValueError('RELEASE_ALREADY_ATTEMPTED_INSPECT_NO_RETRY')
    command('package-check', [sys.executable, '-I', '-B', str(package/'fine_alpha_entry.py'), 'check', digest], timeout=90)
    before = command('before', ['/usr/bin/scontrol', 'show', 'job', '-o', JOB]); held_fields(before, 'nvidia_a100', JOB, REMOTE_ROOT)
    spool = command('spool', ['/usr/bin/scontrol', 'write', 'batch_script', JOB, '-'])
    if spool.encode() != (package/'run_fine_alpha.sbatch').read_bytes(): raise ValueError('SPOOL_CHANGED')
    # Concurrency re-check with the frozen reviewer and the release authorization's fresh review.
    # Only this held job's exact queue row is removed.
    sys.path.insert(0, str(package))
    from e2_submit_once import command as scheduler
    from fine_alpha_submission_queue import inspect_queue
    execute = own_row_filter(scheduler, JOB, own)
    verified = inspect_queue(execute, root, auth['concurrency_review'],
                             record=lambda name, row: queue.append(dict(stage=name, record=row)))
    if own != [JOB+'|audattn_fine_alpha|PENDING']: raise ValueError('OWN_HELD_ROW')
except BaseException as exc:
    emit('refused-before-write', kind='already_attempted' if 'RELEASE_ALREADY_ATTEMPTED' in str(exc) else 'refused',
         events=queue, own_rows_removed=own, error_type=type(exc).__name__, error=str(exc))
    raise
os.umask(0o077)
write(state/'QUEUE_RELEASE.json', dict(events=queue, own_rows_removed=own))
emit('queue-release', identity=identify(state/'QUEUE_RELEASE.json'), verified=verified)
preserved = {name: identify(state/name) for name in ('APPROVAL.json', 'INTENT.json', 'RESPONSE.json', 'SUBMISSION.json',
                                                   'QUEUE_INITIAL.json', 'QUEUE_FINAL.json', 'QUEUE_RELEASE.json')}
if auth['correction'] is not None: preserved['GRES_CORRECTION_RESULT.json'] = identify(correction)
release_command = ['/usr/bin/scontrol', 'release', JOB]
write(state/'RELEASE_INTENT.json', dict(job_id=JOB, release_sha256=digest, argv=release_command,
                                      authorization_sha256=auth_sha, before=before, automatic_retry=False,
                                      queue_release=identify(state/'QUEUE_RELEASE.json')))
with (state/'RELEASE_AUTHORIZATION.json').open('xb') as f:
    f.write(raw); f.flush(); os.fsync(f.fileno())
try:
    released = subprocess.run(release_command, capture_output=True, text=True, timeout=60)
    rc, out, err = released.returncode, released.stdout, released.stderr
except subprocess.TimeoutExpired as exc:
    rc, out, err = 124, str(exc.stdout or ''), str(exc.stderr or '')
# Record first, then report: the durable result must not depend on stdout still being connected.
result = dict(status='FINE_ALPHA_RELEASE_COMMAND_ACCEPTED' if rc == 0 else 'FINE_ALPHA_RELEASE_COMMAND_FAILED_INSPECT',
              job_id=JOB, release_sha256=digest, release_invocations=1, returncode=rc, stdout=out, stderr=err,
              authorization=identify(state/'RELEASE_AUTHORIZATION.json'), resubmission_attempted=False, automatic_retry=False)
write(state/'RELEASE_RESULT.json', result)
emit('release_once', argv=release_command, returncode=rc, stdout=out, stderr=err)
emit('release-result', result=result)
if rc: raise ValueError('RELEASE_NONZERO_INSPECT_NO_RETRY')
command('after', ['/usr/bin/scontrol', 'show', 'job', '-o', JOB])
command('queue', ['/usr/bin/squeue', '-h', '-j', JOB, '-o', '%i|%T|%r|%b|%N'])
ns['verify_package'](package, digest)
if any(identify(state/name) != expected for name, expected in preserved.items()): raise ValueError('JOURNAL_CHANGED')
emit('post-check', status='FINE_ALPHA_RELEASE_POSTCHECK_PASS', package_unchanged=True, original_journals_unchanged=True)
'''


def authorization_for(job, receipt, runner, correction, review, capture):
    return dict(schema_version=1, job_id=job, release_sha256=SHA, release_authorized=True,
                maximum_release_invocations=1, resubmission_authorized=False, automatic_retry=False,
                automatic_reconnect=False, monitor_and_collect_authorized=True, submission=receipt,
                runner=runner, correction=correction, budget=BUDGET, scheduler_quota_verified=False,
                concurrency_review=review, concurrency_review_capture=capture,
                authorization_basis=dict(date='2026-09-28', user_response='不需要我批准 我希望你直接推进到第4步',
                                         question_scope='48号文第4步：held资源与并发状态（放行前新抓取的只读审阅）重新核查通过后正式放行一次；'
                                                        '异常时停止，不自动重投、不扩预算。'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-authorized-release-once', required=True, action='store_true')
    parser.parse_args()
    manifest = verify_package(PACKAGE, SHA)
    job, receipt, correction, after = held_binding()
    review, capture = fresh_review(job, after)
    runner = manifest['files']['run_fine_alpha.sbatch']
    auth = authorization_for(job, receipt, runner, correction, review, capture)
    validate_authorization(auth, job, receipt, runner, correction)
    if SOCKET.is_symlink() or not SOCKET.is_socket(): raise ValueError('MASTER_ABSENT_USER_RECONNECT_REQUIRED')
    authorization, evidence = attempt_paths()
    with authorization.open('x') as stream: stream.write(json.dumps(auth, indent=2, ensure_ascii=False)+'\n')
    raw = authorization.read_bytes()
    evidence.mkdir(mode=0o700, exist_ok=False)
    result = dict(status='RELEASE_NOT_ATTEMPTED', job_id=job, release_sha256=SHA, resubmission_attempted=False,
                  automatic_retry=False, release_command_reached=None, authorization=str(authorization.name),
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    try:
        master = subprocess.run(['/usr/bin/ssh', '-S', str(SOCKET), '-O', 'check', 's2510040@hakusan1'], capture_output=True, timeout=10)
        (evidence/'master.log').write_bytes(master.stdout+master.stderr)
        if master.returncode: raise ValueError('MASTER_UNAVAILABLE_NO_RECONNECT')
        (evidence/'LOCAL_INTENT.json').write_text(json.dumps(dict(authorization=identity(authorization),
            driver=identity(Path(__file__)), scope='RELEASE_V4_HELD_JOB_ONCE_AFTER_QUEUE_RECHECK'), indent=2)+'\n')
        cmd = shlex.join([REMOTE_PY, '-I', '-B', '-c', REMOTE, job, SHA,
                          manifest['files']['fine_alpha_entry.py']['sha256'], hashlib.sha256(raw).hexdigest()])
        result['status'] = 'RELEASE_UNKNOWN_INSPECT_NO_RETRY'
        with (evidence/'remote.jsonl').open('xb') as out, (evidence/'remote.stderr').open('xb') as err:
            p = subprocess.run(SSH+[cmd], input=raw, stdout=out, stderr=err, timeout=600)
        result['transport_returncode'] = p.returncode
        rows = [json.loads(line) for line in (evidence/'remote.jsonl').read_text().splitlines() if line.strip()]
        stages = {row['stage']: row for row in rows}
        reached = any(name in stages for name in ('queue-release', 'release_once', 'release-result'))
        refusals = [row for row in rows if row['stage'] == 'refused-before-write']
        if (not reached and len(refusals) == 1 and rows[-1] is refusals[0] and p.returncode != 0
                and refusals[0].get('kind') == 'refused'):
            result.update(status=REFUSED, release_command_reached=False, remote_refusal=refusals[0])
            raise ValueError('RELEASE_REFUSED_BEFORE_ANY_WRITE: '+refusals[0].get('error', ''))
        result['release_command_reached'] = True if reached else None
        accepted = stages.get('release-result', {}).get('result', {})
        if accepted.get('status') == 'FINE_ALPHA_RELEASE_COMMAND_ACCEPTED': result.update(accepted)
        if p.returncode: raise ValueError('REMOTE_NONZERO_INSPECT_NO_RETRY')
        if len(rows) != len(stages) or accepted.get('job_id') != job or accepted.get('release_invocations') != 1:
            raise ValueError('RELEASE_RECORD')
        held_fields(stages['before']['stdout'], 'nvidia_a100', job, REMOTE_ROOT)
        verified = stages['queue-release']['verified']
        if verified.get('status') != 'CONCURRENT_JOBS_REVIEWED_DISJOINT': raise ValueError('RELEASE_QUEUE_REVIEW')
        if stages['release_once']['argv'] != ['/usr/bin/scontrol', 'release', job]: raise ValueError('RELEASE_ARGV')
        fields = released_fields(stages['after']['stdout'], job, REMOTE_ROOT)
        if stages['post-check']['status'] != 'FINE_ALPHA_RELEASE_POSTCHECK_PASS': raise ValueError('POST_CHECK')
        verify_package(PACKAGE, SHA)
        result.update(status='FINE_ALPHA_RELEASED_READBACK_VERIFIED', fields=fields, queue_release=verified)
        print(json.dumps(result), flush=True)
    except BaseException as exc:
        result.update(error_type=type(exc).__name__, error=str(exc)); raise
    finally:
        result['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (evidence/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
        print('EVIDENCE='+str(evidence), flush=True)


if __name__ == '__main__':
    main()

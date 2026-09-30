"""V3 only: one authorized held submission via the frozen submitter; read-only evidence after."""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

from publish_fine_alpha import REMOTE_PY, SOCKET, SSH
from publish_fine_alpha_v3 import PACKAGE, RELEASE_ROOT, REMOTE_ROOT, SHA, SCOPE
# Historical driver: its budget is the one frozen in its own package, not the current source tree.
BUDGET = json.loads((PACKAGE/'RELEASE.json').read_text())['budget']
from fine_alpha_entry import identity, verify_package
from e2_submit_once import check_job_resources

SOURCE_CHECK = RELEASE_ROOT/'source-check-v3-once/RESULT.json'
HELD = ('FINE_ALPHA_HELD_RESOURCES_VERIFIED_NOT_RELEASED', 'FINE_ALPHA_SUBMITTED_HELD_RESOURCE_MISMATCH')
# Frozen-helper stops caused only by a failed read-only query after the job exists.
HELPER_READ_ERRORS = ('SCHEDULER_QUERY_FAILED', 'FINE_SPOOL_MISMATCH')
JOURNALS = ('APPROVAL.json', 'QUEUE_INITIAL.json', 'TEST_ONLY.json', 'QUEUE_FINAL.json', 'INTENT.json',
            'RESPONSE.json', 'SUBMISSION.json', 'HELD_RESOURCES.json', 'SPOOL.json', 'STOPPED.json')

REMOTE = r'''
import hashlib, json, os, pathlib, pwd, subprocess, sys
root = pathlib.Path('/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v3')
package = root/'package'
JOURNALS = %r
digest, entry_sha, submit_sha, queue_sha, approval_sha = sys.argv[1:]
def emit(stage, **kw): print(json.dumps(dict(stage=stage, **kw)), flush=True)
def identify(raw): return dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
# Pure checks before the first write: a stop here emits exactly one marker and writes nothing.
try:
    if sys.platform != 'linux' or pwd.getpwuid(os.getuid()).pw_name != 's2510040': raise ValueError('NATIVE_ACCOUNT')
    if not sys.flags.isolated or not sys.dont_write_bytecode: raise ValueError('ISOLATED_REQUIRED')
    for p in (package, *package.parents):
        if p.is_symlink() or not p.is_dir(): raise ValueError('REMOTE_PATH')
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077: raise ValueError('ROOT_PERMISSIONS')
    for name, expected in (('RELEASE.json', digest), ('fine_alpha_entry.py', entry_sha),
                           ('fine_alpha_submit_once.py', submit_sha), ('fine_alpha_submission_queue.py', queue_sha)):
        p = package/name
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError('EXTERNAL_HASH:'+name)
    # Validate the whole frozen package before creating any remote authorization.
    namespace = dict(__name__='fine_held_v3_bootstrap', __file__=str(package/'fine_alpha_entry.py'))
    exec(compile((package/'fine_alpha_entry.py').read_bytes(), namespace['__file__'], 'exec'), namespace)
    release = namespace['verify_package'](package, digest)
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536 or identify(raw)['sha256'] != approval_sha: raise ValueError('APPROVAL_TRANSPORT')
    approval = json.loads(raw)
    if (approval.get('release_sha256') != digest or approval.get('budget') != release['budget']
        or approval.get('authorized') is not True or approval.get('single_held_submission_authorized') is not True
        or approval.get('release_authorized') is not False or approval.get('gres_correction_authorized') is not False
        or approval.get('automatic_retry') is not False or approval.get('automatic_reconnect') is not False
        or type(approval.get('concurrency_review')) is not dict):
        raise ValueError('APPROVAL_SCOPE')
    if os.path.lexists(root/'state') or os.path.lexists(root/'APPROVAL.json'):
        raise ValueError('EXISTING_AUTHORIZATION_OR_ATTEMPT_INSPECT_NO_RETRY')
except BaseException as exc:
    emit('refused-before-write', kind='existing' if 'EXISTING_AUTHORIZATION_OR_ATTEMPT' in str(exc) else 'refused',
         error_type=type(exc).__name__, error=str(exc))
    raise
os.umask(0o077)
with (root/'APPROVAL.json').open('xb') as f:
    f.write(raw); f.flush(); os.fsync(f.fileno())
emit('approval', **identify((root/'APPROVAL.json').read_bytes()))
argv = [sys.executable, '-I', '-B', str(package/'fine_alpha_submit_once.py'),
        '--release-sha256', digest, '--confirm-action', 'SUBMIT_FINE_ALPHA_HELD_ONCE_6_GPU_HOURS']
# Exactly one invocation. The pinned helper owns both queue reviews, test-only, hold and refusal of repeats.
try:
    submitted = subprocess.run(argv, capture_output=True, timeout=900)
    rc, out, err = submitted.returncode, submitted.stdout, submitted.stderr
except subprocess.TimeoutExpired as exc:
    rc, out, err = 124, exc.stdout or b'', exc.stderr or b''
emit('submit', returncode=rc, stdout=out.decode(errors='replace'), stderr=err.decode(errors='replace'))
state = root/'state'
if not os.path.lexists(state):
    # state.mkdir precedes every sbatch call in the frozen helper, so no state means no test-only/--hold ran.
    # Retire (never overwrite) this approval so a later, freshly reviewed attempt can be delivered.
    n = 1
    while os.path.lexists(root/('APPROVAL.no-state-%%s-%%d.json' %% (approval_sha[:16], n))): n += 1
    retired = root/('APPROVAL.no-state-%%s-%%d.json' %% (approval_sha[:16], n))
    os.link(root/'APPROVAL.json', retired); os.unlink(root/'APPROVAL.json')
    fd = os.open(root, os.O_RDONLY); os.fsync(fd); os.close(fd)
    if os.path.lexists(state): raise ValueError('STATE_APPEARED_INSPECT_NO_RETRY')
    emit('approval-retired', name=retired.name, **identify(retired.read_bytes()))
    emit('no-state', note='submitter stopped before creating state; queue evidence is in submit.stdout')
    raise SystemExit(rc or 2)
if state.is_symlink() or not state.is_dir(): raise ValueError('STATE_PATH_INSPECT_NO_RETRY')
records = {}
for name in JOURNALS:
    p = state/name
    if not os.path.lexists(p): continue
    if p.is_symlink() or not p.is_file() or p.stat().st_size > 1048576: raise ValueError('JOURNAL_FILE')
    raw = p.read_bytes(); record = json.loads(raw); records[name] = record
    emit('journal', file=name, raw=raw.decode(), **identify(raw))
receipt = records.get('SUBMISSION.json')
if receipt is None: raise SystemExit(rc or 2)
job = receipt.get('job_id', '')
if (not isinstance(job, str) or not job.isdigit() or receipt.get('release_sha256') != digest
    or receipt.get('status') != 'SUBMITTED_HELD_NOT_RELEASED'): raise ValueError('RECEIPT')
emit('receipt', receipt=receipt)
import time
def read_only(command, retry):
    # Read-only queries only; the transient-failure retry never touches the scheduler state.
    attempts = []
    for attempt in range(3 if retry else 1):
        if attempt: time.sleep(10)
        try:
            q = subprocess.run(command, capture_output=True, timeout=30)
            row = dict(returncode=q.returncode, stdout=q.stdout.decode(errors='replace'), stderr=q.stderr.decode(errors='replace'))
            raw_out = q.stdout
        except subprocess.TimeoutExpired:
            row = dict(returncode=124, stdout='', stderr='READ_ONLY_QUERY_TIMEOUT'); raw_out = b''
        if row['returncode'] == 0: break
        attempts.append(dict(returncode=row['returncode'], stderr=row['stderr']))
    return row, raw_out, attempts
for name, command in (
    ('scontrol', ['/usr/bin/scontrol', 'show', 'job', '-o', job]),
    ('squeue', ['/usr/bin/squeue', '-h', '-j', job, '-o', '%%i|%%T|%%r|%%P|%%b']),
    ('sacct', ['/usr/bin/sacct', '-j', job, '-X', '-P', '--format=JobIDRaw,State,ExitCode,Elapsed,ReqTRES,Timelimit']),
    ('spool', ['/usr/bin/scontrol', 'write', 'batch_script', job, '-'])):
    row, raw_out, attempts = read_only(command, name in ('scontrol', 'spool'))
    if name == 'spool': row.update(sha256=hashlib.sha256(raw_out).hexdigest(), matches_runner=raw_out == (package/'run_fine_alpha.sbatch').read_bytes())
    emit(name, failed_attempts=attempts, **row)
namespace['verify_package'](package, digest)
emit('post-check', status='FINE_ALPHA_PACKAGE_BYTES_PASS', release_sha256=digest)
raise SystemExit(rc)
''' % (JOURNALS,)


def package_argv():
    spec = importlib.util.spec_from_file_location('fine_alpha_submit_once_v3', PACKAGE/'fine_alpha_submit_once.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.argv


def _attempts():
    found = sorted(RELEASE_ROOT.glob('held-submission-v3-*'), key=lambda p: int(p.name.rsplit('-', 1)[1]))
    if [int(p.name.rsplit('-', 1)[1]) for p in found] != list(range(1, len(found)+1)): raise ValueError('ATTEMPT_SEQUENCE')
    return found


def _clean_no_job(directory):
    """True only when an attempt provably created no job and left the remote root reusable."""
    row = json.loads((directory/'RESULT.json').read_text())
    if (row.get('status') == 'SUBMISSION_NOT_ATTEMPTED' and 'transport_returncode' not in row
            and not os.path.lexists(directory/'remote.jsonl') and not os.path.lexists(directory/'remote.stderr')):
        return True
    if row.get('status') == 'SUBMISSION_NOT_ATTEMPTED_REMOTE_REFUSED' and row.get('jobs_submitted') == 0:
        rows = [json.loads(line) for line in (directory/'remote.jsonl').read_text().splitlines() if line.strip()]
        return len(rows) == 1 and rows[0]['stage'] == 'refused-before-write' and rows[0].get('kind') == 'refused'
    if row.get('status') != 'STOPPED_BEFORE_STATE_NO_JOB' or row.get('jobs_submitted') != 0: return False
    rows = [json.loads(line) for line in (directory/'remote.jsonl').read_text().splitlines() if line.strip()]
    stages = [r['stage'] for r in rows]
    sent = json.loads((directory/'LOCAL_INTENT.json').read_text())['authorization']
    retired = next((r for r in rows if r['stage'] == 'approval-retired'), {})
    return (stages == ['approval', 'submit', 'approval-retired', 'no-state']
            and {k: retired.get(k) for k in ('size', 'sha256')} == sent)


def attempt_paths():
    previous = _attempts()
    for directory in previous:
        if not _clean_no_job(directory): raise ValueError('PRIOR_SUBMISSION_ATTEMPT_INSPECT_NO_RETRY: '+directory.name)
    n = len(previous)+1
    return RELEASE_ROOT/f'GPU_HELD_AUTHORIZATION_{n}.json', RELEASE_ROOT/f'held-submission-v3-{n}'


def submission_evidence():
    """The single attempt that reached a completed held receipt; every earlier attempt must be a clean no-job stop."""
    found = _attempts()
    if not found: raise ValueError('NO_SUBMISSION_ATTEMPT')
    *earlier, last = found
    for directory in earlier:
        if not _clean_no_job(directory): raise ValueError('PRIOR_SUBMISSION_ATTEMPT_INSPECT: '+directory.name)
    return last


def no_job_stop(rows, authorization, raw_approval):
    """State exists but journals prove the helper stopped before INTENT (no --hold); evidence classification only."""
    journals = {}; stages = {}
    for row in rows:
        if row['stage'] == 'journal':
            raw = row['raw'].encode()
            if row['file'] in journals or row['size'] != len(raw) or row['sha256'] != hashlib.sha256(raw).hexdigest():
                raise ValueError('JOURNAL_IDENTITY')
            journals[row['file']] = json.loads(raw)
        else:
            if row['stage'] in stages: raise ValueError('DUPLICATE_STAGE')
            stages[row['stage']] = row
    stopped = journals.get('STOPPED.json')
    if (stopped is None or stopped.get('submission_may_have_happened') is not False or 'receipt' in stages
            or {'INTENT.json', 'RESPONSE.json', 'SUBMISSION.json', 'HELD_RESOURCES.json', 'SPOOL.json'} & set(journals)
            or journals.get('APPROVAL.json') != authorization
            or stages.get('approval', {}).get('sha256') != hashlib.sha256(raw_approval).hexdigest()
            or not stages.get('submit', {}).get('returncode')):
        return None
    return stopped


def completed_result(result):
    """A downstream step may bind only to a submission RESULT that ended without any error."""
    if ('error' in result or 'error_type' in result or 'unverified_review' in result
            or result.get('transport_returncode') != result.get('submitter_returncode')):
        raise ValueError('SUBMISSION_ENDED_WITH_ERROR')
    return result


def validate_approval(row):
    if (row.get('release_sha256') != SHA or row.get('budget') != BUDGET or row.get('authorized') is not True
            or row.get('single_held_submission_authorized') is not True or row.get('release_authorized') is not False
            or row.get('gres_correction_authorized') is not False or row.get('automatic_retry') is not False
            or row.get('automatic_reconnect') is not False or row.get('scheduler_quota_verified') is not False):
        raise ValueError('AUTHORIZATION_SCOPE')
    spec = importlib.util.spec_from_file_location('fine_alpha_submission_queue_v3', PACKAGE/'fine_alpha_submission_queue.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.validate_review(row.get('concurrency_review'))


def queue_verified(record, review):
    if type(record) is not list or not record or record[-1].get('stage') != 'verified':
        raise ValueError('QUEUE_REVIEW_INCOMPLETE')
    verified = record[-1]['record']
    if (verified.get('status') != 'CONCURRENT_JOBS_REVIEWED_DISJOINT' or verified.get('scheduler_quota_verified') is not False
            or {row['job_id'] for row in verified.get('jobs', [])} - set(review['jobs'])):
        raise ValueError('QUEUE_REVIEW_RESULT')
    return verified


def review(rows, authorization):
    journals = {}; stages = {}
    for row in rows:
        if row['stage'] == 'journal':
            name = row['file']; raw = row['raw'].encode()
            if name in journals or row['size'] != len(raw) or row['sha256'] != hashlib.sha256(raw).hexdigest():
                raise ValueError('JOURNAL_IDENTITY')
            journals[name] = (json.loads(raw), dict(size=len(raw), sha256=row['sha256']))
        else:
            if row['stage'] in stages: raise ValueError('DUPLICATE_STAGE')
            stages[row['stage']] = row
    receipt = stages.get('receipt', {}).get('receipt')
    if not receipt: raise ValueError('MISSING_RECEIPT_INSPECT_NO_RETRY')
    job = receipt.get('job_id', '')
    if (not isinstance(job, str) or not job.isdigit() or receipt.get('release_sha256') != SHA
            or receipt.get('status') != 'SUBMITTED_HELD_NOT_RELEASED' or receipt.get('automatic_retry') is not False
            or receipt.get('automatic_release') is not False): raise ValueError('RECEIPT_BINDING')
    if journals['SUBMISSION.json'][0] != receipt or journals['APPROVAL.json'][0] != authorization:
        raise ValueError('JOURNAL_RECEIPT')
    for key, name in (('approval', 'APPROVAL.json'), ('intent', 'INTENT.json'), ('response', 'RESPONSE.json')):
        if receipt[key] != journals[name][1]: raise ValueError('RECEIPT_JOURNAL_SHA')
    response = journals['RESPONSE.json'][0]
    if response.get('returncode') != 0 or not re.fullmatch(re.escape(job)+r'(?:;[\w.-]+)?\s*', response.get('stdout', '')):
        raise ValueError('SBATCH_RESPONSE_BINDING')
    intent = journals['INTENT.json'][0]
    if (intent.get('argv') != package_argv()(Path(REMOTE_ROOT)/'package', Path(REMOTE_ROOT)/'state', SHA)
            or intent.get('release_sha256') != SHA or intent.get('automatic_retry') is not False
            or intent.get('queue_review') != journals['QUEUE_FINAL.json'][1]):
        raise ValueError('SUBMIT_INTENT')
    queue = dict(initial=queue_verified(journals['QUEUE_INITIAL.json'][0], authorization['concurrency_review']),
                 final=queue_verified(journals['QUEUE_FINAL.json'][0], authorization['concurrency_review']))
    if journals['TEST_ONLY.json'][0].get('returncode') != 0: raise ValueError('TEST_ONLY')
    observed = stages['scontrol']
    if observed.get('returncode') != 0: raise ValueError('JOB_QUERY_FAILED')
    fields = dict(re.findall(r'(\w+)=([^\s]+)', observed['stdout']))
    if (fields.get('JobId') != job or fields.get('JobState') != 'PENDING' or fields.get('Reason') != 'JobHeldUser'
            or fields.get('Priority') != '0' or fields.get('RunTime') != '00:00:00'
            or fields.get('JobName') != 'audattn_fine_alpha' or fields.get('Command') != REMOTE_ROOT+'/package/run_fine_alpha.sbatch'
            or fields.get('WorkDir') != REMOTE_ROOT+'/state'):
        raise ValueError('JOB_NOT_CONFIRMED_HELD')
    spool = stages['spool']; raw = spool.get('stdout', '').encode()
    if spool.get('returncode') or raw != (PACKAGE/'run_fine_alpha.sbatch').read_bytes():
        raise ValueError('SPOOL_MISMATCH')
    if spool.get('sha256') != hashlib.sha256(raw).hexdigest(): raise ValueError('SPOOL_SHA')
    if (stages['post-check'].get('status') != 'FINE_ALPHA_PACKAGE_BYTES_PASS'
            or stages['post-check'].get('release_sha256') != SHA): raise ValueError('POST_CHECK')
    report = dict(job_id=job, jobs_submitted=1, held=True, fields=fields, spool_matches_runner=True,
                  submitter_returncode=stages['submit']['returncode'], queue_review=queue,
                  submission_identity=journals['SUBMISSION.json'][1])
    stopped = journals.get('STOPPED.json', (None,))[0]
    helper_read_failed = bool(stopped) and stopped.get('submission_may_have_happened') is True and (
        stopped.get('error') in HELPER_READ_ERRORS or stopped.get('error_type') == 'TimeoutExpired')
    report['helper_read_failed'] = helper_read_failed
    try:
        check_job_resources(observed, job, BUDGET, held=True)
    except ValueError as exc:
        # The frozen helper either stopped on this same resource difference, or its own read-only query
        # failed; in both cases the driver's own read-back above is what gets classified.
        if not stopped or stopped.get('submission_may_have_happened') is not True or not (
                stopped.get('error') == str(exc) or helper_read_failed):
            raise ValueError('RESOURCE_STOP_NOT_JOURNALED')
        report.update(status='FINE_ALPHA_SUBMITTED_HELD_RESOURCE_MISMATCH', resource_error=str(exc))
        return report
    if (stages['submit']['returncode'] != 0 or 'STOPPED.json' in journals) and not helper_read_failed:
        raise ValueError('HELPER_STOPPED_INSPECT_NO_RETRY')
    report['status'] = 'FINE_ALPHA_HELD_RESOURCES_VERIFIED_NOT_RELEASED'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-authorized-held-once', required=True, action='store_true')
    parser.parse_args()
    release = verify_package(PACKAGE, SHA)
    if release['scope'] != SCOPE or release['budget'] != BUDGET: raise ValueError('V3_RELEASE')
    previous = json.loads(SOURCE_CHECK.read_text())
    if (previous.get('status') != 'FINE_ALPHA_NATIVE_SOURCE_CHECK_PASS_NO_GPU_JOB'
            or previous.get('release_sha256') != SHA or previous.get('remote_root') != REMOTE_ROOT):
        raise ValueError('NATIVE_PREFLIGHT_REQUIRED')
    AUTHORIZATION, EVIDENCE = attempt_paths()
    raw_approval = AUTHORIZATION.read_bytes(); approval = json.loads(raw_approval); validate_approval(approval)
    if SOCKET.is_symlink() or not SOCKET.is_socket(): raise ValueError('MASTER_ABSENT_USER_RECONNECT_REQUIRED')
    # Local-only mux check before any evidence exists: a stale socket must not consume an attempt.
    master = subprocess.run(['/usr/bin/ssh', '-S', str(SOCKET), '-O', 'check', 's2510040@hakusan1'], capture_output=True, timeout=10)
    if master.returncode:
        print((master.stdout+master.stderr).decode(errors='replace'), flush=True)
        raise ValueError('MASTER_UNAVAILABLE_USER_RECONNECT_REQUIRED_NOTHING_SENT')
    EVIDENCE.mkdir(mode=0o700, exist_ok=False)  # A second invocation cannot send another request.
    result = dict(status='SUBMISSION_NOT_ATTEMPTED', release_sha256=SHA, jobs_submitted=None,
                  budget=BUDGET, gpu_authorized=True, release_attempted=False, gres_edit_attempted=False,
                  retry_attempted=False, automatic_reconnect=False, remote_submitter_attempted=False,
                  authorization_file=AUTHORIZATION.name,
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    try:
        (EVIDENCE/'master.log').write_bytes(master.stdout+master.stderr)
        intent = dict(release_sha256=SHA, authorization=identity(AUTHORIZATION), source_check=identity(SOURCE_CHECK),
                      driver=identity(Path(__file__)), scope='ONE_HELD_INVOCATION_NO_RETRY_NO_RELEASE',
                      recorded_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        (EVIDENCE/'LOCAL_INTENT.json').write_text(json.dumps(intent, indent=2)+'\n')
        files = release['files']
        command = shlex.join([REMOTE_PY, '-I', '-B', '-c', REMOTE, SHA, files['fine_alpha_entry.py']['sha256'],
                              files['fine_alpha_submit_once.py']['sha256'], files['fine_alpha_submission_queue.py']['sha256'],
                              hashlib.sha256(raw_approval).hexdigest()])
        result.update(status='SUBMISSION_UNKNOWN_INSPECT_NO_RETRY', remote_submitter_attempted=True)
        with (EVIDENCE/'remote.jsonl').open('xb') as out, (EVIDENCE/'remote.stderr').open('xb') as err:
            p = subprocess.run(SSH+[command], input=raw_approval, stdout=out, stderr=err, timeout=1140)
        result['transport_returncode'] = p.returncode
        rows = [json.loads(line) for line in (EVIDENCE/'remote.jsonl').read_text().splitlines() if line.strip()]
        if (len(rows) == 1 and rows[0].get('stage') == 'refused-before-write' and rows[0].get('kind') == 'refused'
                and p.returncode != 0):
            result.update(status='SUBMISSION_NOT_ATTEMPTED_REMOTE_REFUSED', jobs_submitted=0, remote_refusal=rows[0])
            raise ValueError('SUBMISSION_REFUSED_BEFORE_ANY_WRITE: '+rows[0].get('error', ''))
        if any(row.get('stage') == 'no-state' for row in rows):
            result.update(status='STOPPED_BEFORE_STATE_NO_JOB', jobs_submitted=0)
            raise ValueError('SUBMITTER_STOPPED_BEFORE_STATE_INSPECT')
        stopped = no_job_stop(rows, approval, raw_approval)
        if stopped is not None:
            result.update(status='STOPPED_AFTER_STATE_BEFORE_INTENT_NO_JOB', jobs_submitted=0, helper_stop=stopped)
            raise ValueError('SUBMITTER_STOPPED_BEFORE_INTENT_INSPECT')
        report = review(rows, approval)
        # Merge the reviewed status only after every post-review check passes; otherwise keep it
        # visible for inspection under a separate key so no downstream step can bind to it.
        result['unverified_review'] = report
        if p.returncode != report['submitter_returncode']: raise ValueError('TRANSPORT_RETURN_CODE')
        verify_package(PACKAGE, SHA)
        del result['unverified_review']; result.update(report)
        print(json.dumps(result), flush=True)
    except BaseException as exc:
        if result['status'] in ('FINE_ALPHA_HELD_RESOURCES_VERIFIED_NOT_RELEASED', 'FINE_ALPHA_SUBMITTED_HELD_RESOURCE_MISMATCH'):
            result['status'] = 'SUBMITTED_POSTCHECK_FAILED_INSPECT_NO_RETRY'
        result.update(error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        result['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (EVIDENCE/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
        print('EVIDENCE='+str(EVIDENCE), flush=True)
    if result['status'] != 'FINE_ALPHA_HELD_RESOURCES_VERIFIED_NOT_RELEASED':
        raise SystemExit(2)


if __name__ == '__main__':
    main()

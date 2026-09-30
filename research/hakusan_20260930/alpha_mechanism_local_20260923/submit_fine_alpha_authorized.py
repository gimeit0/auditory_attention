"""One authorized held submission; preserve failures and collect read-only evidence."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

from publish_fine_alpha import PACKAGE, RELEASE_ROOT, REMOTE_PY, REMOTE_ROOT, SHA, SOCKET, SSH
# Historical driver: its budget is the one frozen in its own package, not the current source tree.
BUDGET = json.loads((PACKAGE/'RELEASE.json').read_text())['budget']
from fine_alpha_entry import identity, verify_package
from e2_submit_once import check_job_resources

AUTHORIZATION = RELEASE_ROOT/'GPU_HELD_AUTHORIZATION.json'
SOURCE_CHECK = RELEASE_ROOT/'source-check-mmwdh22h/RESULT.json'
EVIDENCE = RELEASE_ROOT/'held-submission-20260928'

REMOTE = r'''
import hashlib, json, os, pathlib, pwd, subprocess, sys
root = pathlib.Path('/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v1')
package = root/'package'
digest, entry_sha, submit_sha, approval_sha = sys.argv[1:]
def emit(stage, **kw): print(json.dumps(dict(stage=stage, **kw)), flush=True)
def identify(raw): return dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
if sys.platform != 'linux' or pwd.getpwuid(os.getuid()).pw_name != 's2510040': raise ValueError('NATIVE_ACCOUNT')
if not sys.flags.isolated or not sys.dont_write_bytecode: raise ValueError('ISOLATED_REQUIRED')
for p in (package, *package.parents):
    if p.is_symlink() or not p.is_dir(): raise ValueError('REMOTE_PATH')
if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077: raise ValueError('ROOT_PERMISSIONS')
for name, expected in (('RELEASE.json', digest), ('fine_alpha_entry.py', entry_sha), ('fine_alpha_submit_once.py', submit_sha)):
    p = package/name
    if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
        raise ValueError('EXTERNAL_HASH:'+name)
# Validate the whole frozen package before creating any remote authorization.
namespace = dict(__name__='fine_held_readonly_bootstrap', __file__=str(package/'fine_alpha_entry.py'))
exec(compile((package/'fine_alpha_entry.py').read_bytes(), namespace['__file__'], 'exec'), namespace)
release = namespace['verify_package'](package, digest)
raw = sys.stdin.buffer.read(65537)
if len(raw) > 65536 or identify(raw)['sha256'] != approval_sha: raise ValueError('APPROVAL_TRANSPORT')
approval = json.loads(raw)
if (approval.get('release_sha256') != digest or approval.get('budget') != release['budget']
    or approval.get('authorized') is not True or approval.get('single_held_submission_authorized') is not True
    or approval.get('release_authorized') is not False or approval.get('gres_correction_authorized') is not False
    or approval.get('automatic_retry') is not False or approval.get('automatic_reconnect') is not False):
    raise ValueError('APPROVAL_SCOPE')
if os.path.lexists(root/'state') or os.path.lexists(root/'APPROVAL.json'):
    raise ValueError('EXISTING_AUTHORIZATION_OR_ATTEMPT_INSPECT_NO_RETRY')
os.umask(0o077)
with (root/'APPROVAL.json').open('xb') as f:
    f.write(raw); f.flush(); os.fsync(f.fileno())
emit('approval', **identify((root/'APPROVAL.json').read_bytes()))
argv = [sys.executable, '-I', '-B', str(package/'fine_alpha_submit_once.py'),
        '--release-sha256', digest, '--confirm-action', 'SUBMIT_FINE_ALPHA_HELD_ONCE_6_GPU_HOURS']
# Exactly one invocation. The pinned helper owns queue/test-only/hold/refusal of repeats.
try:
    submitted = subprocess.run(argv, capture_output=True, timeout=360)
    rc, out, err = submitted.returncode, submitted.stdout, submitted.stderr
except subprocess.TimeoutExpired as exc:
    rc, out, err = 124, exc.stdout or b'', exc.stderr or b''
emit('submit', returncode=rc, stdout=out.decode(errors='replace'), stderr=err.decode(errors='replace'))
# Preserve and inspect the receipt even when resource validation deliberately stopped the helper.
state = root/'state'
if state.is_symlink() or not state.is_dir(): raise ValueError('NO_STATE_INSPECT_NO_RETRY')
records = {}
for name in ('APPROVAL.json', 'QUEUE.json', 'TEST_ONLY.json', 'INTENT.json', 'RESPONSE.json',
             'SUBMISSION.json', 'HELD_RESOURCES.json', 'SPOOL.json', 'STOPPED.json'):
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
for name, command in (
    ('scontrol', ['/usr/bin/scontrol', 'show', 'job', '-o', job]),
    ('squeue', ['/usr/bin/squeue', '-h', '-j', job, '-o', '%i|%T|%r|%P|%b']),
    ('sacct', ['/usr/bin/sacct', '-j', job, '-X', '-P', '--format=JobIDRaw,State,ExitCode,Elapsed,ReqTRES,Timelimit']),
    ('spool', ['/usr/bin/scontrol', 'write', 'batch_script', job, '-'])):
    try:
        q = subprocess.run(command, capture_output=True, timeout=30)
        row = dict(returncode=q.returncode, stdout=q.stdout.decode(errors='replace'), stderr=q.stderr.decode(errors='replace'))
        if name == 'spool': row.update(sha256=hashlib.sha256(q.stdout).hexdigest(), matches_runner=q.stdout == (package/'run_fine_alpha.sbatch').read_bytes())
        emit(name, **row)
    except subprocess.TimeoutExpired:
        emit(name, returncode=124, stdout='', stderr='READ_ONLY_QUERY_TIMEOUT_NO_RETRY')
namespace['verify_package'](package, digest)
emit('post-check', status='FINE_ALPHA_PACKAGE_BYTES_PASS', release_sha256=digest)
raise SystemExit(rc)
'''


def package_argv():
    """argv of the frozen v1 package itself (self-contained, --time=06:00:00), never the current source tree."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('fine_alpha_submit_once_v1', PACKAGE/'fine_alpha_submit_once.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.argv


def validate_approval(row):
    if (row.get('release_sha256') != SHA or row.get('budget') != BUDGET or row.get('authorized') is not True
            or row.get('single_held_submission_authorized') is not True or row.get('release_authorized') is not False
            or row.get('gres_correction_authorized') is not False or row.get('automatic_retry') is not False
            or row.get('automatic_reconnect') is not False):
        raise ValueError('AUTHORIZATION_SCOPE')


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
            or intent.get('release_sha256') != SHA or intent.get('automatic_retry') is not False):
        raise ValueError('SUBMIT_ARGV')
    observed = stages['scontrol']
    if observed.get('returncode') != 0: raise ValueError('JOB_QUERY_FAILED')
    fields = dict(re.findall(r'(\w+)=([^\s]+)', observed['stdout']))
    if (fields.get('JobId') != job or fields.get('JobState') != 'PENDING' or fields.get('Reason') != 'JobHeldUser'
            or fields.get('Priority') != '0' or fields.get('RunTime') != '00:00:00'):
        raise ValueError('JOB_NOT_CONFIRMED_HELD')
    spool = stages['spool']; raw = spool.get('stdout', '').encode()
    if spool.get('returncode') or raw != (PACKAGE/'run_fine_alpha.sbatch').read_bytes():
        raise ValueError('SPOOL_MISMATCH')
    if spool.get('sha256') != hashlib.sha256(raw).hexdigest(): raise ValueError('SPOOL_SHA')
    if (stages['post-check'].get('status') != 'FINE_ALPHA_PACKAGE_BYTES_PASS'
            or stages['post-check'].get('release_sha256') != SHA): raise ValueError('POST_CHECK')
    report = dict(job_id=job, jobs_submitted=1, held=True, fields=fields, spool_matches_runner=True,
                  submitter_returncode=stages['submit']['returncode'])
    try:
        check_job_resources(observed, job, BUDGET, held=True)
    except ValueError as exc:
        report.update(status='FINE_ALPHA_SUBMITTED_HELD_RESOURCE_MISMATCH', resource_error=str(exc))
        return report
    if stages['submit']['returncode'] != 0 or 'STOPPED.json' in journals:
        raise ValueError('HELPER_STOPPED_INSPECT_NO_RETRY')
    report['status'] = 'FINE_ALPHA_HELD_RESOURCES_VERIFIED_NOT_RELEASED'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-authorized-held-once', required=True, action='store_true')
    parser.parse_args()
    release = verify_package(PACKAGE, SHA)
    raw_approval = AUTHORIZATION.read_bytes(); approval = json.loads(raw_approval); validate_approval(approval)
    previous = json.loads(SOURCE_CHECK.read_text())
    if (previous.get('status') != 'FINE_ALPHA_NATIVE_SOURCE_CHECK_PASS_NO_GPU_JOB'
            or previous.get('release_sha256') != SHA): raise ValueError('NATIVE_PREFLIGHT_REQUIRED')
    if SOCKET.is_symlink() or not SOCKET.is_socket(): raise ValueError('MASTER_ABSENT_USER_RECONNECT_REQUIRED')
    EVIDENCE.mkdir(mode=0o700, exist_ok=False)  # A second invocation cannot send another request.
    result = dict(status='SUBMISSION_NOT_ATTEMPTED', release_sha256=SHA, jobs_submitted=None,
                  budget=BUDGET, gpu_authorized=True, release_attempted=False, gres_edit_attempted=False,
                  retry_attempted=False, automatic_reconnect=False, remote_submitter_attempted=False,
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    try:
        master = subprocess.run(['/usr/bin/ssh', '-S', str(SOCKET), '-O', 'check', 's2510040@hakusan1'], capture_output=True, timeout=10)
        (EVIDENCE/'master.log').write_bytes(master.stdout+master.stderr)
        if master.returncode: raise ValueError('MASTER_UNAVAILABLE_NO_RECONNECT')
        intent = dict(release_sha256=SHA, authorization=identity(AUTHORIZATION), source_check=identity(SOURCE_CHECK),
                      driver=identity(Path(__file__)), scope='ONE_HELD_INVOCATION_NO_RETRY_NO_RELEASE',
                      recorded_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        (EVIDENCE/'LOCAL_INTENT.json').write_text(json.dumps(intent, indent=2)+'\n')
        command = shlex.join([REMOTE_PY, '-I', '-B', '-c', REMOTE, SHA,
                             release['files']['fine_alpha_entry.py']['sha256'],
                             release['files']['fine_alpha_submit_once.py']['sha256'], hashlib.sha256(raw_approval).hexdigest()])
        result.update(status='SUBMISSION_UNKNOWN_INSPECT_NO_RETRY', remote_submitter_attempted=True)
        with (EVIDENCE/'remote.jsonl').open('xb') as out, (EVIDENCE/'remote.stderr').open('xb') as err:
            p = subprocess.run(SSH+[command], input=raw_approval, stdout=out, stderr=err, timeout=540)
        result['transport_returncode'] = p.returncode
        rows = [json.loads(line) for line in (EVIDENCE/'remote.jsonl').read_text().splitlines() if line.strip()]
        result.update(review(rows, approval))
        if p.returncode != result['submitter_returncode']: raise ValueError('TRANSPORT_RETURN_CODE')
        verify_package(PACKAGE, SHA)
        print(json.dumps(result), flush=True)
    except BaseException as exc:
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

"""Read-only status/evidence snapshot of the released v3 job; no reconnect or scheduler writes."""
import argparse
import datetime
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
from publish_fine_alpha import REMOTE_PY, SOCKET, SSH
from publish_fine_alpha_v3 import RELEASE_ROOT, REMOTE_ROOT, SHA
from submit_fine_alpha_v3 import completed_result, submission_evidence

TERMINAL = {'COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'OUT_OF_MEMORY', 'NODE_FAIL', 'PREEMPTED', 'BOOT_FAIL',
            'DEADLINE', 'REVOKED'}
EXPECTED_RECORDS = {'A': 126, 'B': 120, 'C': 120}  # passes x conditions x 3 domains; progress display only


def released_job():
    """Job id and receipt identity only from the verified submission and a verified release attempt."""
    submitted = completed_result(json.loads((submission_evidence()/'RESULT.json').read_text()))
    job = submitted['job_id']
    released = [json.loads((d/'RESULT.json').read_text()) for d in sorted(RELEASE_ROOT.glob('release-v3-*'))]
    if not any(r.get('status') == 'FINE_ALPHA_RELEASED_READBACK_VERIFIED' and r.get('job_id') == job for r in released):
        raise ValueError('RELEASED_JOB_REQUIRED')
    if not re.fullmatch(r'[1-9][0-9]*', job) or submitted.get('release_sha256') != SHA: raise ValueError('JOB_BINDING')
    return job, submitted['submission_identity']['sha256']


REMOTE = r'''
import datetime, hashlib, json, pathlib, subprocess, sys
root = pathlib.Path(%r)
state = root/'state'; job, receipt_sha = sys.argv[1:]
for p in (state, root, *root.parents):
    if p.is_symlink() or not p.is_dir(): raise ValueError('DIRECTORY')
receipt_path = state/'SUBMISSION.json'
if receipt_path.is_symlink() or not receipt_path.is_file(): raise ValueError('RECEIPT_FILE')
if hashlib.sha256(receipt_path.read_bytes()).hexdigest() != receipt_sha: raise ValueError('RECEIPT_SHA')
receipt = json.loads(receipt_path.read_bytes())
if receipt['job_id'] != job: raise ValueError('JOB')
commands = {}
for name, argv in (
    ('squeue', ['/usr/bin/squeue', '-h', '-u', 's2510040', '-o', '%%i|%%T|%%r|%%M|%%b|%%N']),
    ('sacct', ['/usr/bin/sacct', '-j', job, '-X', '-P', '--format=JobIDRaw,State,ExitCode,Elapsed,Start,End,NodeList,ReqTRES,Timelimit'])):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        commands[name] = dict(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
    except subprocess.TimeoutExpired:
        commands[name] = dict(returncode=124, stdout='', stderr='READ_ONLY_QUERY_TIMEOUT')
attempt = state/'attempt'
if attempt.is_symlink(): raise ValueError('ATTEMPT_SYMLINK')
markers = {}; blocks = {}; tails = {}
for name in ('RUN.json', 'VERIFY_REQUEST.json', 'COMPLETE.json', 'FAILED.json', 'VERIFY/VERIFIED.json'):
    p = attempt/name
    if any(part.is_symlink() for part in (p, p.parent)): raise ValueError('MARKER_SYMLINK')
    if p.exists():
        if not p.is_file() or p.stat().st_size > 1048576: raise ValueError('MARKER_SIZE')
        markers[name] = json.loads(p.read_bytes())
for block in ('A', 'B', 'C'):
    d = attempt/block; output = d/'output'
    if d.is_symlink() or output.is_symlink(): raise ValueError('BLOCK_SYMLINK')
    info = dict(started=d.exists(), completed_records_observed=0, output_files=0)
    if output.is_dir():
        paths = list(output.iterdir())
        if len(paths) > 400 or any(p.is_symlink() for p in paths): raise ValueError('OUTPUT_INVENTORY')
        info['completed_records_observed'] = sum(p.is_file() and p.suffix == '.npz' for p in paths)
        info['output_files'] = len(paths)
    for name in ('LAUNCH.json', 'PROCESS.json', 'output/FAILED.json', 'output/ENVIRONMENT_PRECHECK.json'):
        p = d/name
        if p.is_symlink(): raise ValueError('BLOCK_MARKER_SYMLINK')
        if p.exists():
            if not p.is_file() or p.stat().st_size > 1048576: raise ValueError('BLOCK_MARKER_SIZE')
            info[name] = json.loads(p.read_bytes())
    info['worker_record_present'] = (output/'WORKER.json').is_file()
    blocks[block] = info
sizes = {}
for name in ('slurm-%%s.log' %% job, 'attempt/A/stderr.log', 'attempt/B/stderr.log', 'attempt/C/stderr.log', 'attempt/VERIFY/stderr.log'):
    p = state/name
    if p.is_symlink() or any(parent.is_symlink() for parent in p.parents): raise ValueError('LOG_SYMLINK')
    if p.is_file():
        sizes[name] = p.stat().st_size
        with p.open('rb') as f:
            f.seek(max(0, p.stat().st_size-16384)); tails[name] = f.read(16384).decode(errors='replace')
print(json.dumps(dict(status='FINE_ALPHA_READ_ONLY_SNAPSHOT', job_id=job, release_sha256=receipt['release_sha256'],
                     observed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), commands=commands,
                     markers=markers, blocks=blocks, log_tails=tails, log_sizes=sizes, jobs_submitted=0,
                     automatic_reconnect=False)))
''' % (REMOTE_ROOT,)


def classify(snapshot, job):
    if snapshot.get('job_id') != job or snapshot.get('release_sha256') != SHA: raise ValueError('SNAPSHOT_BINDING')
    commands = snapshot['commands']
    active = [line.split('|') for line in commands['squeue']['stdout'].splitlines() if line.split('|')[0] == job]
    accounting = [line.split('|') for line in commands['sacct']['stdout'].splitlines() if line.split('|')[0] == job]
    if len(active) > 1 or len(accounting) > 1: raise ValueError('DUPLICATE_JOB_RECORD')
    queue_ok = commands['squeue']['returncode'] == 0; sacct_ok = commands['sacct']['returncode'] == 0
    sacct_phase = accounting[0][1].split()[0].rstrip('+') if sacct_ok and accounting else None
    if queue_ok and active: phase = active[0][1]
    elif sacct_phase in TERMINAL: phase = sacct_phase        # left the queue, or squeue failed: trust terminal accounting only
    elif queue_ok and not active and sacct_phase: phase = sacct_phase
    else: raise ValueError('SCHEDULER_QUERY_INCONCLUSIVE')
    markers = snapshot['markers']
    complete = markers.get('COMPLETE.json')
    if complete and (complete.get('job_id') != job or complete.get('release_sha256') != SHA
                     or complete.get('status') != 'FINE_ALPHA_ARTIFACTS_VERIFIED'): raise ValueError('COMPLETE_BINDING')
    block_failures = {b: info['output/FAILED.json'] for b, info in snapshot['blocks'].items() if 'output/FAILED.json' in info}
    records = {b: snapshot['blocks'][b]['completed_records_observed'] for b in ('A', 'B', 'C')}
    return dict(job_id=job, scheduler_state=phase, terminal=phase in TERMINAL,
                exit_code=accounting[0][2] if accounting else None,
                elapsed=accounting[0][3] if accounting else None,
                node=accounting[0][6] if accounting and len(accounting[0]) > 6 else None,
                reason=active[0][2] if active else None,
                query_warnings=[n for n, ok in (('squeue', queue_ok), ('sacct', sacct_ok)) if not ok],
                complete_marker=bool(complete), failure_marker='FAILED.json' in markers,
                failure=markers.get('FAILED.json'), block_failures=block_failures,
                observed_records=records, expected_records=EXPECTED_RECORDS,
                progress=round(sum(records.values())/sum(EXPECTED_RECORDS.values()), 4),
                worker_records={b: snapshot['blocks'][b]['worker_record_present'] for b in ('A', 'B', 'C')},
                log_sizes=snapshot.get('log_sizes', {}))


def elapsed_seconds(text):
    if not text: return None
    days, _, clock = text.rpartition('-')
    parts = [int(x) for x in clock.split(':')]
    while len(parts) < 3: parts.insert(0, 0)
    return (int(days) if days else 0)*86400 + parts[0]*3600 + parts[1]*60 + parts[2]


def query(job=None, receipt_sha=None):
    if job is None: job, receipt_sha = released_job()
    if SOCKET.is_symlink() or not SOCKET.is_socket(): raise ConnectionError('MASTER_ABSENT_USER_RECONNECT_REQUIRED')
    evidence = Path(tempfile.mkdtemp(prefix=f'status-{job}-', dir=RELEASE_ROOT))
    result = dict(status='QUERY_NOT_FINISHED', job_id=job, evidence=str(evidence), automatic_reconnect=False)
    try:
        cmd = shlex.join([REMOTE_PY, '-I', '-B', '-c', REMOTE, job, receipt_sha])
        with (evidence/'remote.json').open('xb') as out, (evidence/'remote.stderr').open('xb') as err:
            p = subprocess.run(SSH+[cmd], stdout=out, stderr=err, timeout=100)
        if p.returncode == 255: raise ConnectionError('SSH_TRANSPORT_255')
        if p.returncode: raise ValueError('QUERY_RC='+str(p.returncode))
        snapshot = json.loads((evidence/'remote.json').read_bytes())
        result.update(classify(snapshot, job), status='FINE_ALPHA_STATUS_OBSERVED', observed_utc=snapshot['observed_utc'])
        print(json.dumps(result), flush=True)
        return result
    except BaseException as exc:
        result.update(status='QUERY_FAILED_NO_RECONNECT', error_type=type(exc).__name__, error=str(exc)); raise
    finally:
        (evidence/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
        print('EVIDENCE='+str(evidence), flush=True)


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    query()

"""Read-only status/evidence snapshot of job 753729; no reconnect or scheduler writes."""
import argparse
import datetime
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
from publish_fine_alpha import RELEASE_ROOT, REMOTE_PY, SOCKET, SSH, SHA

JOB = '753729'
TERMINAL = {'COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'OUT_OF_MEMORY', 'NODE_FAIL', 'PREEMPTED', 'BOOT_FAIL', 'DEADLINE', 'REVOKED'}
REMOTE = r'''
import datetime, hashlib, json, pathlib, subprocess
root = pathlib.Path('/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v1')
state = root/'state'; job = '753729'
for p in (state, root, *root.parents):
    if p.is_symlink() or not p.is_dir(): raise ValueError('DIRECTORY')
receipt_path = state/'SUBMISSION.json'
if receipt_path.is_symlink() or not receipt_path.is_file(): raise ValueError('RECEIPT_FILE')
if hashlib.sha256(receipt_path.read_bytes()).hexdigest() != '97579946e89d4efaf2f98909c9e2c7641105c7ade5c1a290328d0e55f10cffa7':
    raise ValueError('RECEIPT_SHA')
receipt = json.loads(receipt_path.read_bytes())
if receipt['job_id'] != job: raise ValueError('JOB')
commands = {}
for name, argv in (
    ('squeue', ['/usr/bin/squeue', '-h', '-u', 's2510040', '-o', '%i|%T|%r|%M|%b|%N']),
    ('sacct', ['/usr/bin/sacct', '-j', job, '-X', '-P', '--format=JobIDRaw,State,ExitCode,Elapsed,Start,End,NodeList,ReqTRES,Timelimit'])):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    commands[name] = dict(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
    if p.returncode and name == 'sacct': raise ValueError('QUERY_FAILED:'+name)
attempt = state/'attempt'
if attempt.is_symlink(): raise ValueError('ATTEMPT_SYMLINK')
markers = {}; blocks = {}; tails = {}
for name in ('RUN.json', 'COMPLETE.json', 'FAILED.json', 'VERIFY/VERIFIED.json'):
    p = attempt/name
    if any(part.is_symlink() for part in (p, p.parent)): raise ValueError('MARKER_SYMLINK')
    if p.exists():
        if not p.is_file() or p.stat().st_size > 1048576: raise ValueError('MARKER_SIZE')
        markers[name] = json.loads(p.read_bytes())
for block in ('A', 'B', 'C'):
    d = attempt/block; output = d/'output'
    if d.is_symlink() or output.is_symlink(): raise ValueError('BLOCK_SYMLINK')
    info = dict(started=d.exists(), completed_records_observed=0)
    if output.is_dir():
        paths = list(output.iterdir())
        if len(paths) > 300 or any(p.is_symlink() for p in paths): raise ValueError('OUTPUT_INVENTORY')
        info['completed_records_observed'] = sum(p.is_file() and p.suffix == '.npz' for p in paths)
    for name in ('LAUNCH.json', 'PROCESS.json', 'output/FAILED.json'):
        p = d/name
        if p.is_symlink(): raise ValueError('BLOCK_MARKER_SYMLINK')
        if p.exists():
            if not p.is_file() or p.stat().st_size > 1048576: raise ValueError('BLOCK_MARKER_SIZE')
            info[name] = json.loads(p.read_bytes())
    info['worker_record_present'] = (output/'WORKER.json').is_file()
    blocks[block] = info
for name in ('slurm-753729.log', 'attempt/A/stderr.log', 'attempt/B/stderr.log', 'attempt/C/stderr.log', 'attempt/VERIFY/stderr.log'):
    p = state/name
    if p.is_symlink() or any(parent.is_symlink() for parent in p.parents): raise ValueError('LOG_SYMLINK')
    if p.is_file():
        with p.open('rb') as f:
            f.seek(max(0, p.stat().st_size-16384)); tails[name] = f.read(16384).decode(errors='replace')
print(json.dumps(dict(status='FINE_ALPHA_READ_ONLY_SNAPSHOT', job_id=job, release_sha256=receipt['release_sha256'],
                     observed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), commands=commands,
                     markers=markers, blocks=blocks, log_tails=tails, jobs_submitted=0, automatic_reconnect=False)))
'''


def classify(snapshot):
    if snapshot.get('job_id') != JOB or snapshot.get('release_sha256') != SHA: raise ValueError('SNAPSHOT_BINDING')
    commands = snapshot['commands']
    if commands['sacct']['returncode'] != 0: raise ValueError('QUERY_FAILED:sacct')
    active = [line.split('|') for line in commands['squeue']['stdout'].splitlines() if line.split('|')[0] == JOB]
    accounting = [line.split('|') for line in commands['sacct']['stdout'].splitlines() if line.split('|')[0] == JOB]
    if len(active) > 1 or len(accounting) > 1: raise ValueError('DUPLICATE_JOB_RECORD')
    queue_error = commands['squeue']['returncode'] != 0
    # A queue error is not job failure. Accept only an exact, terminal accounting
    # record as fallback, and retain the original error in the evidence/warning.
    if queue_error and (active or not accounting or accounting[0][1].split()[0].rstrip('+') not in TERMINAL):
        raise ValueError('QUERY_FAILED:squeue_without_terminal_accounting')
    phase = active[0][1] if active else accounting[0][1].split()[0].rstrip('+') if accounting else 'UNKNOWN'
    markers = snapshot['markers']
    complete = markers.get('COMPLETE.json')
    if complete and (complete.get('job_id') != JOB or complete.get('release_sha256') != SHA
                     or complete.get('status') != 'FINE_ALPHA_ARTIFACTS_VERIFIED'): raise ValueError('COMPLETE_BINDING')
    return dict(job_id=JOB, scheduler_state=phase, terminal=phase in TERMINAL,
                exit_code=accounting[0][2] if accounting else None,
                elapsed=accounting[0][3] if accounting else None,
                reason=active[0][2] if active else None,
                queue_query_returncode=commands['squeue']['returncode'],
                query_warning='SQUEUE_FAILED_TERMINAL_SACCT_FALLBACK' if queue_error else None,
                complete_marker=bool(complete), failure_marker='FAILED.json' in markers,
                observed_records={b: snapshot['blocks'][b]['completed_records_observed'] for b in ('A', 'B', 'C')})


def query():
    if SOCKET.is_symlink() or not SOCKET.is_socket(): raise ValueError('MASTER_ABSENT_USER_RECONNECT_REQUIRED')
    evidence = Path(tempfile.mkdtemp(prefix='status-753729-', dir=RELEASE_ROOT))
    result = dict(status='QUERY_NOT_FINISHED', job_id=JOB, evidence=str(evidence), automatic_reconnect=False)
    try:
        cmd = shlex.join([REMOTE_PY, '-I', '-B', '-c', REMOTE])
        with (evidence/'remote.json').open('xb') as out, (evidence/'remote.stderr').open('xb') as err:
            p = subprocess.run(SSH+[cmd], stdout=out, stderr=err, timeout=100)
        if p.returncode: raise ValueError('QUERY_RC='+str(p.returncode))
        snapshot = json.loads((evidence/'remote.json').read_bytes())
        result.update(classify(snapshot), status='FINE_ALPHA_STATUS_OBSERVED', observed_utc=snapshot['observed_utc'])
        print(json.dumps(result), flush=True)
        return result
    except BaseException as exc:
        result.update(status='QUERY_FAILED_STOP_NO_RECONNECT', error_type=type(exc).__name__, error=str(exc)); raise
    finally:
        (evidence/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
        print('EVIDENCE='+str(evidence), flush=True)


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    query()

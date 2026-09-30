"""Terminal v3 job: read-only state collection and frozen offline verification; no remote writes.

Collection is read-only, so a transport failure may be retried into a NEW evidence directory;
earlier directories are kept. Nothing here submits, releases, cancels or edits a job.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import sys
import tarfile
import tempfile
from publish_fine_alpha import REMOTE_PY, SOCKET, SSH
from publish_fine_alpha_v3 import PACKAGE, RELEASE_ROOT, REMOTE_ROOT, SHA
from fine_alpha_entry import verify_package
from status_fine_alpha_v3 import TERMINAL, released_job

MAX_BYTES = 3*1024**3
MAX_FILES = 1500
REMOTE = r'''
import hashlib, io, json, pathlib, stat, subprocess, sys, tarfile
root = pathlib.Path(%r)/'state'
job, receipt_sha = sys.argv[1:]; maximum = %d; max_files = %d
TERMINAL = %r
for p in (root, *root.parents):
    if p.is_symlink() or not p.is_dir(): raise ValueError('COLLECTION_DIRECTORY')
receipt = root/'SUBMISSION.json'
if receipt.is_symlink() or hashlib.sha256(receipt.read_bytes()).hexdigest() != receipt_sha: raise ValueError('RECEIPT_SHA')
if json.loads(receipt.read_text())['job_id'] != job: raise ValueError('RECEIPT_JOB')
q = subprocess.run(['/usr/bin/sacct', '-j', job, '-X', '-P', '--format=JobIDRaw,State,ExitCode,Elapsed,Start,End,NodeList,ReqTRES,Timelimit'],
                   capture_output=True, text=True, timeout=60, check=True)
rows = [line.split('|') for line in q.stdout.splitlines() if line.split('|')[0] == job]
if len(rows) != 1: raise ValueError('ACCOUNTING_RECORD')
phase = rows[0][1].split()[0].rstrip('+')
if phase not in TERMINAL: raise ValueError('JOB_NOT_TERMINAL')
paths = sorted(root.rglob('*'))
if len(paths) > max_files+200 or any(p.is_symlink() or not (p.is_dir() or stat.S_ISREG(p.stat().st_mode)) for p in paths):
    raise ValueError('COLLECTION_INVENTORY')
files = [p for p in paths if p.is_file()]
if len(files) > max_files or sum(p.stat().st_size for p in files) > maximum: raise ValueError('COLLECTION_BUDGET')
inventory = {}
for p in files:
    raw = p.read_bytes(); inventory[str(p.relative_to(root))] = dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
manifest = dict(job_id=job, release_sha256=json.loads(receipt.read_text())['release_sha256'],
                scheduler_state=phase, exit_code=rows[0][2], sacct=q.stdout, files=inventory)
meta = json.dumps(manifest, indent=2, sort_keys=True).encode()
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
    member = tarfile.TarInfo('COLLECTION_MANIFEST.json'); member.size = len(meta); archive.addfile(member, io.BytesIO(meta))
    for p in files:
        raw = p.read_bytes(); relative = str(p.relative_to(root))
        if dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()) != inventory[relative]: raise ValueError('SOURCE_CHANGED')
        member = tarfile.TarInfo('state/'+relative); member.size = len(raw); archive.addfile(member, io.BytesIO(raw))
if sorted(root.rglob('*')) != paths: raise ValueError('INVENTORY_CHANGED')
for p in files:
    raw = p.read_bytes()
    if dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()) != inventory[str(p.relative_to(root))]:
        raise ValueError('SOURCE_POSTCHECK_CHANGED')
''' % (REMOTE_ROOT, MAX_BYTES, MAX_FILES, sorted(TERMINAL))


def extract_verified(archive_path, destination, job):
    if archive_path.stat().st_size > MAX_BYTES+8*1024**2: raise ValueError('TRANSPORT_SIZE')
    with tarfile.open(archive_path, 'r:') as archive:
        members = archive.getmembers(); names = [m.name for m in members]
        if len(names) != len(set(names)) or len(names) > MAX_FILES+1: raise ValueError('TRANSPORT_INVENTORY')
        for m in members:
            p = PurePosixPath(m.name)
            if (not m.isfile() or m.issparse() or p.is_absolute() or '..' in p.parts or str(p) != m.name
                    or m.size < 0 or m.size > MAX_BYTES): raise ValueError('UNSAFE_MEMBER')
        manifest = json.load(archive.extractfile('COLLECTION_MANIFEST.json'))
        if manifest.get('job_id') != job or manifest.get('release_sha256') != SHA: raise ValueError('MANIFEST_BINDING')
        if set(names) != {'COLLECTION_MANIFEST.json'} | {'state/'+n for n in manifest['files']}:
            raise ValueError('MANIFEST_INVENTORY')
        if sum(m.size for m in members) > MAX_BYTES+1024**2: raise ValueError('PAYLOAD_SIZE')
        for m in members:
            raw = archive.extractfile(m).read()
            if m.name != 'COLLECTION_MANIFEST.json':
                expected = manifest['files'][m.name[6:]]
                if dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()) != expected: raise ValueError('TRANSFER_SHA')
            dest = destination/m.name; dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open('xb') as f: f.write(raw)
            if hashlib.sha256(dest.read_bytes()).hexdigest() != hashlib.sha256(raw).hexdigest(): raise ValueError('DISK_SHA')
    return manifest


def offline_verify(out, job):
    with (out/'offline-check.json').open('xb') as stdout, (out/'offline-check.stderr').open('xb') as stderr:
        p = subprocess.run([sys.executable, '-I', '-B', str(PACKAGE/'fine_alpha_entry.py'), 'offline-check',
                            SHA, str(out/'state/attempt'), job], stdout=stdout, stderr=stderr, timeout=1800)
    if p.returncode: raise ValueError('OFFLINE_CHECK_RC='+str(p.returncode))
    verified = json.loads((out/'offline-check.json').read_bytes())
    complete = json.loads((out/'state/attempt/COMPLETE.json').read_bytes())
    if (verified.get('status') != 'FINE_ALPHA_ARTIFACTS_VERIFIED' or verified.get('job_id') != job
            or verified.get('release_sha256') != SHA or verified.get('predictions') != 219600
            or any(complete.get(k) != v for k, v in verified.items())): raise ValueError('OFFLINE_RESULT')
    return verified


def collect(job=None, receipt_sha=None):
    if job is None: job, receipt_sha = released_job()
    verify_package(PACKAGE, SHA)
    if SOCKET.is_symlink() or not SOCKET.is_socket(): raise ConnectionError('MASTER_ABSENT_USER_RECONNECT_REQUIRED')
    out = Path(tempfile.mkdtemp(prefix=f'collected-{job}-', dir=RELEASE_ROOT))
    result = dict(status='COLLECTION_NOT_FINISHED', job_id=job, release_sha256=SHA, evidence=str(out),
                  jobs_submitted=0, scheduler_writes=0, automatic_reconnect=False, scientific_report_complete=False)
    print('COLLECTION_DIRECTORY='+str(out), flush=True)
    try:
        cmd = shlex.join([REMOTE_PY, '-I', '-B', '-c', REMOTE, job, receipt_sha])
        with (out/'transport.tar').open('xb') as stream, (out/'transport.stderr').open('xb') as err:
            p = subprocess.run(SSH+[cmd], stdout=stream, stderr=err, timeout=3600)
        if p.returncode == 255: raise ConnectionError('SSH_TRANSPORT_255')
        if p.returncode: raise ValueError('COLLECTION_RC='+str(p.returncode))
        manifest = extract_verified(out/'transport.tar', out, job)
        (out/'transport.tar').unlink()  # verified per file on disk; keep the extracted copy only
        result.update(files=len(manifest['files']), scheduler_state=manifest['scheduler_state'],
                      exit_code=manifest['exit_code'], sacct=manifest['sacct'])
        if manifest['scheduler_state'] == 'COMPLETED' and manifest['exit_code'] == '0:0':
            result.update(status='FINE_ALPHA_COLLECTED_OFFLINE_VERIFIED_ANALYSIS_PENDING', verification=offline_verify(out, job))
        else:
            result.update(status='FINE_ALPHA_TERMINAL_FAILURE_COLLECTED_NO_RETRY', numeric_results_interpretable=False)
        verify_package(PACKAGE, SHA)
        print(json.dumps(result), flush=True)
        return result
    except BaseException as exc:
        result.update(status='COLLECTION_OR_VERIFICATION_FAILED', error_type=type(exc).__name__, error=str(exc)); raise
    finally:
        (out/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    collect()

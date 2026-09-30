"""Stdlib-only bounded upload receiver; no model execution or job submission."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import subprocess
import sys
import tarfile

REMOTE = Path('/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v1')
MAX_TRANSPORT = 64 * 1024**2
MAX_MEMBER = 16 * 1024**2

def sha(raw): return hashlib.sha256(raw).hexdigest()

def validate_transport(blob, release_sha, entry_sha, *, expected_scope='FINE_ALPHA_001_20260928_V1'):
    if len(blob) > MAX_TRANSPORT: raise ValueError('TRANSPORT_SIZE')
    items = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:') as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if (not member.isfile() or path.is_absolute() or '..' in path.parts or
                str(path) != member.name or not path.parts or member.name in items):
                raise ValueError('TRANSPORT_MEMBER')
            if member.size < 0 or member.size > MAX_MEMBER: raise ValueError('MEMBER_SIZE')
            data = archive.extractfile(member).read()
            if len(data) != member.size: raise ValueError('MEMBER_READ_SIZE')
            items[member.name] = data
    if sha(items.get('RELEASE.json', b'')) != release_sha: raise ValueError('RELEASE_SHA')
    if sha(items.get('fine_alpha_entry.py', b'')) != entry_sha: raise ValueError('ENTRY_SHA')
    release = json.loads(items['RELEASE.json'])
    if release.get('scope') != expected_scope: raise ValueError('RELEASE_SCOPE')
    if set(items) != set(release['files']) | {'RELEASE.json'}: raise ValueError('TRANSPORT_INVENTORY')
    for name, record in release['files'].items():
        if dict(size=len(items[name]), sha256=sha(items[name])) != record: raise ValueError('FILE_HASH: '+name)
    for name in items:
        if any(str(p) in items for p in PurePosixPath(name).parents): raise ValueError('FILE_DIRECTORY_COLLISION')
    return items

def publish(blob, root, release_sha, entry_sha, *, expected_scope='FINE_ALPHA_001_20260928_V1'):
    # Used with the fixed REMOTE path by main; temp paths only in local tests.
    root = Path(root); base = root.parent
    items = validate_transport(blob, release_sha, entry_sha, expected_scope=expected_scope)  # Validate before writes.
    for parent in (base.parent, *base.parent.parents):
        if parent.is_symlink() or not parent.is_dir(): raise ValueError('ANCESTOR_DIRECTORY')
    if os.path.lexists(root): raise ValueError('TARGET_EXISTS_NO_OVERWRITE')
    if os.path.lexists(base) and (base.is_symlink() or not base.is_dir() or
                                 base.stat().st_uid != os.getuid() or base.stat().st_mode & 0o022):
        raise ValueError('BASE_DIRECTORY')
    os.umask(0o077)
    if not base.exists(): base.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    stage = root/'.upload-staging'; stage.mkdir(mode=0o700)
    directories = {p for n in items for p in PurePosixPath(n).parents if str(p) != '.'}
    for directory in sorted(directories, key=lambda p: (len(p.parts), str(p))):
        (stage/str(directory)).mkdir(mode=0o700)
    for name, raw in items.items():
        with (stage/name).open('xb') as output:
            output.write(raw); output.flush(); os.fsync(output.fileno())
    for name, raw in items.items():
        path = stage/name
        if path.is_symlink() or path.read_bytes() != raw: raise ValueError('REMOTE_DISK_VERIFY')
    if os.path.lexists(root/'package'): raise ValueError('PACKAGE_EXISTS_NO_OVERWRITE')
    stage.rename(root/'package')
    return dict(status='FINE_ALPHA_FILES_PUBLISHED', root=str(root), release_sha256=release_sha,
                files=len(items), manifest_files=len(items)-1, jobs_submitted=0, checkpoints_loaded=0)

def validate_reviewed_job(text, job_id, queue_name, remote, expected):
    """Validate one explicitly reviewed job; a name match alone grants nothing."""
    fields = {}
    for key in ('JobId', 'JobName', 'UserId', 'Command', 'WorkDir', 'StdOut', 'StdErr'):
        values = re.findall(r'(?:^|\s)' + key + r'=(\S+)', text)
        if len(values) != 1: raise ValueError('JOB_METADATA_FIELD: ' + key)
        fields[key] = values[0]
    if fields['JobId'] != job_id or fields['JobName'] != queue_name:
        raise ValueError('JOB_IDENTITY')
    if not re.fullmatch(r's2510040\([0-9]+\)', fields['UserId']): raise ValueError('JOB_OWNER')
    for key in ('JobName', 'Command', 'WorkDir', 'StdOut', 'StdErr'):
        if fields[key] != expected[key]: raise ValueError('REVIEWED_JOB_CHANGED: ' + key)
    target = PurePosixPath(remote)
    for key in ('Command', 'WorkDir', 'StdOut', 'StdErr'):
        path = PurePosixPath(fields[key])
        if not path.is_absolute() or '..' in path.parts: raise ValueError('JOB_PATH')
        if path == target or path in target.parents or target in path.parents:
            raise ValueError('UPLOAD_JOB_PATH_CONFLICT: ' + key)
    return fields


def check_upload_queue(remote, q, reviewed_jobs=None):
    if q.returncode: raise ValueError('QUEUE_FAILED_OR_RELATED_JOB')
    if reviewed_jobs is None:
        # Preserve historical V1 behavior. Only V2 explicitly supplies reviewed identities.
        if any('audattn' in line for line in q.stdout.splitlines()):
            raise ValueError('QUEUE_FAILED_OR_RELATED_JOB')
        return
    seen = set()
    for line in q.stdout.splitlines():
        parts = line.split('|')
        if len(parts) != 3 or not parts[0].isdigit() or not parts[2]:
            raise ValueError('QUEUE_FORMAT')
        job_id, name, _ = parts
        if job_id in seen or job_id not in reviewed_jobs:
            raise ValueError('UNREVIEWED_QUEUED_JOB: ' + job_id)
        seen.add(job_id)
        p = subprocess.run(['/usr/bin/scontrol', 'show', 'job', '-o', job_id],
                           capture_output=True, text=True, timeout=30)
        if p.returncode: raise ValueError('JOB_METADATA_QUERY_FAILED')
        expected = reviewed_jobs[job_id]
        fields = validate_reviewed_job(p.stdout, job_id, name, remote, expected)
        command = Path(fields['Command'])
        if (not command.is_file() or command.is_symlink() or
            any(parent.is_symlink() for parent in command.parents)):
            raise ValueError('REVIEWED_COMMAND_PATH')
        if sha(command.read_bytes()) != expected['command_sha256']:
            raise ValueError('REVIEWED_COMMAND_SHA')
        print(json.dumps(dict(stage='reviewed_independent_job', fields=fields,
                              command_sha256=expected['command_sha256'],
                              scope='upload_only_not_gpu_concurrency_approval')), flush=True)


def main(*, remote=REMOTE, expected_scope='FINE_ALPHA_001_20260928_V1', reviewed_jobs=None):
    if len(sys.argv) != 3 or sys.platform != 'linux' or pwd.getpwuid(os.getuid()).pw_name != 's2510040':
        raise ValueError('REMOTE_ACCOUNT_OR_ARGS')
    if not sys.flags.isolated or not sys.dont_write_bytecode: raise ValueError('ISOLATED_REQUIRED')
    if os.path.lexists(remote): raise ValueError('TARGET_EXISTS_NO_OVERWRITE')
    q = subprocess.run(['/usr/bin/squeue', '-h', '-u', 's2510040', '-o', '%i|%j|%T'],
                       capture_output=True, text=True, timeout=30)
    print(json.dumps(dict(stage='read_only_queue', returncode=q.returncode, stdout=q.stdout, stderr=q.stderr)), flush=True)
    check_upload_queue(remote, q, reviewed_jobs)
    result = publish(sys.stdin.buffer.read(MAX_TRANSPORT+1), remote, sys.argv[1], sys.argv[2], expected_scope=expected_scope)
    print(json.dumps(result), flush=True)

if __name__ == '__main__': main()

"""Reviewed independent jobs, not name-based exclusion or a scheduler quota claim."""
import hashlib
import re
from pathlib import Path, PurePosixPath

POLICY = 'EXPLICIT_INDEPENDENT_JOB_REVIEW_V1'
FIELDS = ('JobName', 'UserId', 'Command', 'WorkDir', 'StdOut', 'StdErr')
PATH_FIELDS = ('Command', 'WorkDir', 'StdOut', 'StdErr')


def digest(raw): return hashlib.sha256(raw).hexdigest()


def validate_review(review):
    if (type(review) is not dict or set(review) != {'policy', 'jobs'} or
        review['policy'] != POLICY or type(review['jobs']) is not dict or len(review['jobs']) > 64):
        raise ValueError('CONCURRENCY_REVIEW_REQUIRED')
    for job, row in review['jobs'].items():
        if type(job) is not str or not re.fullmatch(r'[1-9][0-9]*', job): raise ValueError('REVIEW_JOB_ID')
        if (type(row) is not dict or set(row) != {'fields', 'command_sha256', 'spool_sha256',
                                                'independent_outputs', 'shared_inputs_read_only'} or
            row['independent_outputs'] is not True or row['shared_inputs_read_only'] is not True):
            raise ValueError('REVIEW_SCOPE')
        fields = row['fields']
        if (type(fields) is not dict or set(fields) != set(FIELDS) or
            any(type(v) is not str or not v or re.search(r'\s', v) for v in fields.values()) or
            not re.fullmatch(r's2510040\([0-9]+\)', fields['UserId'])):
            raise ValueError('REVIEW_FIELDS')
        for key in PATH_FIELDS:
            path = PurePosixPath(fields[key])
            if not path.is_absolute() or '..' in path.parts or str(path) != fields[key]:
                raise ValueError('REVIEW_PATH')
        for key in ('command_sha256', 'spool_sha256'):
            if type(row[key]) is not str or not re.fullmatch(r'[0-9a-f]{64}', row[key]):
                raise ValueError('REVIEW_SHA')
    return review


def response_text(row):
    if (type(row) is not dict or type(row.get('returncode')) is not int or row['returncode'] != 0 or
        type(row.get('stdout')) is not str or type(row.get('stderr')) is not str or
        len(row['stdout'].encode()) > 2 * 1024**2):
        raise ValueError('QUEUE_OR_JOB_QUERY_FAILED')
    return row['stdout']


def metadata_fields(text):
    fields = {}
    for key in ('JobId', *FIELDS):
        values = re.findall(r'(?:^|\s)' + key + r'=(\S+)', text)
        if len(values) != 1: raise ValueError('QUEUE_JOB_METADATA: ' + key)
        fields[key] = values[0]
    return fields


def validate_paths(fields, root):
    target = PurePosixPath(root)
    if not target.is_absolute(): raise ValueError('SUBMISSION_ROOT')
    if (fields['JobName'].startswith('audattn_fine_alpha') or
        PurePosixPath(fields['Command']).name == 'run_fine_alpha.sbatch'):
        raise ValueError('DUPLICATE_FINE_ALPHA_JOB')
    for key in PATH_FIELDS:
        path = PurePosixPath(fields[key])
        if not path.is_absolute() or '..' in path.parts or str(path) != fields[key]:
            raise ValueError('QUEUE_JOB_PATH')
        if path == target or path in target.parents or target in path.parents:
            raise ValueError('QUEUE_JOB_PATH_CONFLICT: ' + key)
        actual = Path(path)
        if any(p.is_symlink() for p in (actual, *actual.parents)):
            raise ValueError('QUEUE_JOB_PATH_SYMLINK: ' + key)


def reviewed_command_sha(path):
    path = Path(path)
    if (path.is_symlink() or not path.is_file() or any(p.is_symlink() for p in path.parents) or
        path.stat().st_size > 2 * 1024**2):
        raise ValueError('REVIEWED_COMMAND_FILE')
    return digest(path.read_bytes())


def inspect_queue(execute, root, review, *, record=lambda name, row: None,
                  command_sha=reviewed_command_sha):
    """Read-only live evidence; approved reviews may include jobs already finished.

    Unknown jobs fail closed. No hard-coded two-job quota, no cancellation,
    requeue, GRES change, or release. Any exceptions are handled by the caller.
    """
    validate_review(review)
    queue = execute(['/usr/bin/squeue', '-h', '-u', 's2510040', '-o', '%i|%j|%T'])
    record('queue', queue)
    rows = response_text(queue).splitlines()
    if len(rows) > 64: raise ValueError('QUEUE_REVIEW_BOUND')
    jobs = {}; verified = []
    for row in rows:
        parts = row.split('|')
        if (len(parts) != 3 or not re.fullmatch(r'[1-9][0-9]*', parts[0]) or
            not re.fullmatch(r'\S+', parts[1]) or not re.fullmatch(r'[A-Z_]+', parts[2]) or
            parts[0] in jobs): raise ValueError('QUEUE_FORMAT')
        job, name, state = parts; jobs[job] = (name, state)
        if name.startswith('audattn_fine_alpha'): raise ValueError('DUPLICATE_FINE_ALPHA_JOB')
        if job not in review['jobs']: raise ValueError('UNREVIEWED_CONCURRENT_JOB: ' + job)
    for job, (name, state) in sorted(jobs.items()):
        expected = review['jobs'][job]
        queried = execute(['/usr/bin/scontrol', 'show', 'job', '-o', job])
        record('job-'+job, queried); fields = metadata_fields(response_text(queried))
        if (fields.pop('JobId') != job or fields['JobName'] != name or fields != expected['fields']):
            raise ValueError('CONCURRENT_JOB_IDENTITY_CHANGED')
        validate_paths(fields, root)
        actual_sha = command_sha(Path(fields['Command']))
        record('command-'+job, dict(path=fields['Command'], sha256=actual_sha))
        if actual_sha != expected['command_sha256']: raise ValueError('CONCURRENT_COMMAND_CHANGED')
        spool = execute(['/usr/bin/scontrol', 'write', 'batch_script', job, '-'])
        # The final '-' requests stdout, not a remote output file. Keep hashes,
        # not arbitrary script contents, in the public/pre-state event stream.
        raw = spool.get('stdout') if type(spool) is dict else None
        record('spool-'+job, dict(returncode=spool.get('returncode') if type(spool) is dict else None,
                                 stderr=spool.get('stderr') if type(spool) is dict else None,
                                 size=len(raw.encode()) if type(raw) is str else None,
                                 sha256=digest(raw.encode()) if type(raw) is str else None))
        text = response_text(spool); spool_sha = digest(text.encode())
        if spool_sha != expected['spool_sha256']: raise ValueError('CONCURRENT_SPOOL_CHANGED')
        verified.append(dict(job_id=job, queue_state=state, fields=fields,
                             command_sha256=actual_sha, spool_sha256=spool_sha))
    result = dict(status='CONCURRENT_JOBS_REVIEWED_DISJOINT', policy=POLICY, jobs=verified,
                  scheduler_quota_verified=False, jobs_submitted=0)
    record('verified', result)
    return result

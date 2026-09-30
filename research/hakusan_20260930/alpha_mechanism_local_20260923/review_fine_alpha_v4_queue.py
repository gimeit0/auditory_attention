"""Read-only live queue capture for the V4 concurrency review; no submission or scheduler writes.

A job becomes part of the review only when it is listed in ASSESSED with the exact
command/spool SHA that was read and judged, and its output paths are disjoint from
every fine-alpha input/output root. Anything else stops: an unknown job needs a new
human-readable assessment, never a name- or quota-based pass.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import tempfile

from fine_alpha_entry import identity, verify_package
from publish_fine_alpha import SOCKET, SSH, REMOTE_PY
from publish_fine_alpha_v4 import PACKAGE, RELEASE_ROOT, REMOTE_ROOT, SHA

POLICY = 'EXPLICIT_INDEPENDENT_JOB_REVIEW_V1'
# Everything the V4 runner reads or writes on the cluster (from the frozen package's own paths).
FINE_ALPHA_ROOTS = (REMOTE_ROOT, '/home/s2510040/selective_listening_repro/code/auditory_attention',
                    '/home/s2510040/audattn_e2', '/home/s2510040/audattn_external_eval')
SEED_ROOT = '/home/s2510040/selective_listening_repro/code/auditory_attention_seed20260928'
ASSESSED = {'757211': dict(
    command_sha256='64a3fcbdc0b810dd96b0bf4735409f77a4ad41d60759b569ca1a09d705626220',
    spool_sha256='64a3fcbdc0b810dd96b0bf4735409f77a4ad41d60759b569ca1a09d705626220',
    basis=('Spool read 2026-09-29: new-seed formal40 training (run_training.sbatch). PROJECT_ROOT and all writes '
           '(selftrain/experiments/runs/$RUN_ID snapshot/state/full checkpoints/evaluation, Slurm log) are under '+SEED_ROOT+'. '
           'SHARED INPUT: '+SEED_ROOT+'/cv_train and /cv_clips are symlinks to the original '
           '/home/s2510040/selective_listening_repro/code/auditory_attention/{cv_train,cv_clips}; CV_CLIPS is read for '
           'training only. It also reads the shared attn conda env. It never writes the original auditory_attention '
           'tree, audattn_e2, audattn_external_eval or audattn_fine_alpha. Fine-alpha pins each E1 clip sha256/size '
           'before and after inference.'),
    output_root=SEED_ROOT)}

REMOTE = r'''
import hashlib, json, os, pathlib, pwd, subprocess, sys
if sys.platform != 'linux' or pwd.getpwuid(os.getuid()).pw_name != 's2510040': raise ValueError('NATIVE_ACCOUNT')
if not sys.flags.isolated or not sys.dont_write_bytecode: raise ValueError('ISOLATED_REQUIRED')
def run(argv):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    return dict(argv=argv, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
out = dict(queue=run(['/usr/bin/squeue', '-h', '-u', 's2510040', '-o', '%i|%j|%T']), jobs={})
if out['queue']['returncode'] == 0:
    for line in out['queue']['stdout'].splitlines()[:64]:
        job = line.split('|')[0]
        if not job.isdigit(): continue
        row = dict(scontrol=run(['/usr/bin/scontrol', 'show', 'job', '-o', job]),
                   spool=run(['/usr/bin/scontrol', 'write', 'batch_script', job, '-']))
        row['spool']['sha256'] = hashlib.sha256(row['spool']['stdout'].encode()).hexdigest()
        command = None
        for token in row['scontrol']['stdout'].split():
            if token.startswith('Command='): command = token[len('Command='):]
        if command:
            path = pathlib.Path(command)
            ok = path.is_file() and not path.is_symlink() and not any(p.is_symlink() for p in path.parents)
            row['command'] = dict(path=command, regular_file_no_symlink=ok,
                                  sha256=hashlib.sha256(path.read_bytes()).hexdigest() if ok else None)
        workdir = None
        for token in row['scontrol']['stdout'].split():
            if token.startswith('WorkDir='): workdir = token[len('WorkDir='):]
        if workdir:
            row['workdir_links'] = {name: (os.readlink(p) if os.path.islink(p) else None)
                                    for name in ('cv_train', 'cv_clips') for p in [os.path.join(workdir, name)]}
        out['jobs'][job] = row
print(json.dumps(out))
'''


def load_queue_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location('fine_alpha_submission_queue_v4', PACKAGE/'fine_alpha_submission_queue.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def disjoint(path, root):
    path, root = PurePosixPath(path), PurePosixPath(root)
    return not (path == root or path in root.parents or root in path.parents)


def build_review(capture, own_job=None):
    """Turn one live capture into the exact concurrency_review the frozen submitter checks.

    own_job: only for the release-time capture; exactly this held fine-alpha row is skipped."""
    q = load_queue_module()
    text = q.response_text(capture['queue'])
    jobs = {}; notes = {}; own = []
    for line in text.splitlines():
        if own_job is not None and line == str(own_job)+'|audattn_fine_alpha|PENDING':
            own.append(line); continue
        parts = line.split('|')
        if len(parts) != 3 or not parts[0].isdigit(): raise ValueError('QUEUE_FORMAT')
        job, name, state = parts
        if name.startswith('audattn_fine_alpha'): raise ValueError('DUPLICATE_FINE_ALPHA_JOB')
        if job not in ASSESSED: raise ValueError('UNASSESSED_CONCURRENT_JOB_NEEDS_NEW_REVIEW: '+job)
        row = capture['jobs'][job]; expected = ASSESSED[job]
        fields = q.metadata_fields(q.response_text(row['scontrol']))
        if fields.pop('JobId') != job or fields['JobName'] != name: raise ValueError('JOB_IDENTITY')
        spool = q.response_text(row['spool'])
        spool_sha = hashlib.sha256(spool.encode()).hexdigest()
        command = row.get('command') or {}
        if (command.get('path') != fields['Command'] or command.get('regular_file_no_symlink') is not True or
            command.get('sha256') != expected['command_sha256'] or spool_sha != expected['spool_sha256']):
            raise ValueError('ASSESSED_SCRIPT_CHANGED: '+job)
        for key in ('WorkDir', 'StdOut', 'StdErr'):
            if not PurePosixPath(fields[key]).is_relative_to(expected['output_root']):
                raise ValueError('OUTPUT_OUTSIDE_ASSESSED_ROOT: '+key)
        for key in ('Command', 'WorkDir', 'StdOut', 'StdErr'):
            for root in FINE_ALPHA_ROOTS:
                if not disjoint(fields[key], root): raise ValueError('FINE_ALPHA_PATH_OVERLAP: '+key)
        jobs[job] = dict(fields=fields, command_sha256=command['sha256'], spool_sha256=spool_sha,
                         independent_outputs=True, shared_inputs_read_only=True)
        notes[job] = dict(queue_state=state, basis=expected['basis'], output_root=expected['output_root'])
        links = row.get('workdir_links')
        if links is not None: notes[job]['workdir_links'] = links
    if own_job is not None and len(own) != 1: raise ValueError('OWN_HELD_ROW')
    review = q.validate_review(dict(policy=POLICY, jobs=jobs))
    return review, notes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-read-only-queue-review', action='store_true', required=True)
    parser.add_argument('--own-held-job', default=None, help='release-time capture: skip exactly this held fine-alpha row')
    args = parser.parse_args()
    if args.own_held_job is not None and not args.own_held_job.isdigit(): raise ValueError('OWN_JOB')
    verify_package(PACKAGE, SHA)
    if SOCKET.is_symlink() or not SOCKET.is_socket(): raise ValueError('USER_RECONNECT_REQUIRED')
    evidence = Path(tempfile.mkdtemp(prefix='queue-review-', dir=RELEASE_ROOT))
    result = dict(status='QUEUE_REVIEW_NOT_FINISHED', release_sha256=SHA, jobs_submitted=0, scheduler_writes=0,
                  own_held_job=args.own_held_job,
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  driver=identity(Path(__file__)))
    try:
        p = subprocess.run(SSH+[shlex.join([REMOTE_PY, '-I', '-B', '-c', REMOTE])], capture_output=True, timeout=120)
        (evidence/'remote.json').write_bytes(p.stdout); (evidence/'remote.stderr').write_bytes(p.stderr)
        if p.returncode: raise ValueError('REMOTE_QUERY_FAILED')
        capture = json.loads(p.stdout)
        review, notes = build_review(capture, args.own_held_job)
        (evidence/'CONCURRENCY_REVIEW.json').write_text(json.dumps(review, indent=2, sort_keys=True)+'\n')
        result.update(status='FINE_ALPHA_V4_CONCURRENCY_REVIEW_CAPTURED', review=review, notes=notes,
                      own_held_job=args.own_held_job, capture=capture,
                      review_identity=identity(evidence/'CONCURRENCY_REVIEW.json'), scheduler_quota_verified=False)
        print(json.dumps(result), flush=True)
    except BaseException as exc:
        result.update(status='STOPPED_INSPECT_NO_RETRY', error_type=type(exc).__name__, error=str(exc)); raise
    finally:
        result['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (evidence/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
        print('QUEUE_REVIEW_EVIDENCE='+str(evidence), flush=True)


if __name__ == '__main__': main()

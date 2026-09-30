"""Remote held-only fine scan submitter. Explicit approval; no repair/release/retry."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import sys

def bootstrap(package, digest):
    entry = package/'fine_alpha_entry.py'
    if entry.is_symlink() or not entry.is_file(): raise ValueError('ENTRY_FILE')
    spec = importlib.util.spec_from_file_location('fine_submit_bootstrap', entry)
    module = importlib.util.module_from_spec(spec)
    exec(compile(entry.read_bytes(), str(entry), 'exec'), module.__dict__)
    release = module.verify_package(package, digest)
    return module, release

def time_limit(budget):
    hours, minutes = divmod(budget['wall_minutes'], 60)
    return f'{hours:02d}:{minutes:02d}:00'

def confirm_action(budget):
    if budget['wall_minutes'] % 60: raise ValueError('WHOLE_GPU_HOURS_REQUIRED')
    return f"SUBMIT_FINE_ALPHA_HELD_ONCE_{budget['wall_minutes']//60}_GPU_HOURS"

def argv(package, state, digest, *, test=False, budget=None):
    # Budget from this package's own RELEASE.json (never a later source tree's contract). A local reviewer that
    # rebuilds the argv for the REMOTE package path passes the frozen budget explicitly instead.
    if budget is None: budget = json.loads((Path(package)/'RELEASE.json').read_text())['budget']
    return ['/usr/bin/sbatch', '--test-only' if test else '--hold', '--parsable', '--export=NONE', '--no-requeue',
        '--partition=GPU-1A', '--account=student', '--nodes=1', '--ntasks=1', '--cpus-per-task=8',
        '--threads-per-core=1', '--mem=65536M', '--time='+time_limit(budget), '--gres=gpu:nvidia_a100:1',
        '--job-name=audattn_fine_alpha', '--chdir='+str(state), '--input=/dev/null',
        '--output='+str(state/'slurm-%j.log'), '--error='+str(state/'slurm-%j.log'),
        str(package/'run_fine_alpha.sbatch'), str(package), digest, str(state)]

def submit(package, digest, *, execute=None):
    package = Path(package); entry, release = bootstrap(package, digest)
    from fine_alpha_contract import BUDGET, SCOPE
    from e2_submit_once import command, check_job_resources
    from e2_process import write
    from fine_alpha_submission_queue import inspect_queue, validate_review
    execute = command if execute is None else execute
    if release['budget'] != BUDGET: raise ValueError('FINE_BUDGET')
    if release.get('scope') != SCOPE: raise ValueError('FINE_SUBMISSION_SCOPE')
    root = package.parent; approval = root/'APPROVAL.json'; approval_id = entry.identity(approval)
    a = json.loads(approval.read_text())
    if (a.get('release_sha256') != digest or a.get('budget') != BUDGET or a.get('authorized') is not True or
        a.get('single_held_submission_authorized') is not True or a.get('release_authorized') is not False):
        raise ValueError('FINE_EXPLICIT_APPROVAL_REQUIRED')
    review = validate_review(a.get('concurrency_review'))
    state = root/'state'
    if os.path.lexists(state): raise FileExistsError('EXISTING_ATTEMPT_NO_RETRY')
    initial = []
    def before_state(name, row):
        event = dict(stage=name, record=row); initial.append(event)
        print(json.dumps(dict(submission_preflight=event)), flush=True)
    # A busy/unknown queue must not create the single-use submission state.
    # Preserve pre-state evidence on stdout, captured by the invoking driver.
    inspect_queue(execute, root, review, record=before_state)
    if entry.identity(approval) != approval_id: raise ValueError('APPROVAL_CHANGED_DURING_PREFLIGHT')
    state.mkdir(mode=0o700, exist_ok=False)  # Refuses all repeats, even uncertain ones.
    write(state/'APPROVAL.json', a)
    try:
        write(state/'QUEUE_INITIAL.json', initial)
        tested = execute(argv(package, state, digest, test=True)); write(state/'TEST_ONLY.json', tested)
        if tested['returncode']: raise ValueError('FINE_TEST_ONLY_FAILED')
        final = []
        try:
            inspect_queue(execute, root, review, record=lambda name, row: final.append(dict(stage=name, record=row)))
        finally:
            write(state/'QUEUE_FINAL.json', final)
        if entry.identity(approval) != approval_id: raise ValueError('APPROVAL_CHANGED_BEFORE_SUBMIT')
        entry.verify_package(package, digest)
        planned = argv(package, state, digest)
        write(state/'INTENT.json', dict(argv=planned, release_sha256=digest, automatic_retry=False,
                                      queue_review=entry.identity(state/'QUEUE_FINAL.json')))
        response = execute(planned); write(state/'RESPONSE.json', response)
        if response['returncode'] or not re.fullmatch(r'[0-9]+(?:;[\w.-]+)?\s*', response['stdout']):
            raise ValueError('FINE_SUBMISSION_UNKNOWN_NO_RETRY')
        job = response['stdout'].strip().split(';')[0]
        receipt = dict(status='SUBMITTED_HELD_NOT_RELEASED', job_id=job, release_sha256=digest,
            approval=entry.identity(state/'APPROVAL.json'), intent=entry.identity(state/'INTENT.json'),
            response=entry.identity(state/'RESPONSE.json'), automatic_retry=False, automatic_release=False)
        write(state/'SUBMISSION.json', receipt)
        observed = execute(['/usr/bin/scontrol', 'show', 'job', '-o', job]); write(state/'HELD_RESOURCES.json', observed)
        check_job_resources(observed, job, BUDGET, held=True)
        spool = execute(['/usr/bin/scontrol', 'write', 'batch_script', job, '-']); write(state/'SPOOL.json', spool)
        if spool['returncode'] or spool['stdout'] != (package/'run_fine_alpha.sbatch').read_text():
            raise ValueError('FINE_SPOOL_MISMATCH')
        entry.verify_package(package, digest)
        return receipt
    except BaseException as exc:
        write(state/'STOPPED.json', dict(error_type=type(exc).__name__, error=str(exc),
              submission_may_have_happened=(state/'INTENT.json').exists(), automatic_retry=False))
        raise

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release-sha256', required=True)
    p.add_argument('--confirm-action', required=True)
    a = p.parse_args(); package = Path(__file__).absolute().parent
    if sys.platform != 'linux' or pwd.getpwuid(os.getuid()).pw_name != 's2510040': raise ValueError('NATIVE_ACCOUNT')
    if not sys.flags.isolated or not sys.dont_write_bytecode: raise ValueError('ISOLATED_REQUIRED')
    bootstrap(package, a.release_sha256)  # Verify before sibling imports.
    sys.path.insert(0, str(package))
    from fine_alpha_contract import REMOTE, BUDGET
    if a.confirm_action != confirm_action(BUDGET): raise ValueError('CONFIRM_ACTION_BUDGET')
    root = Path(REMOTE)
    if package != root/'package' or any(p.is_symlink() for p in (root, *root.parents)): raise ValueError('REMOTE_PATH')
    print(json.dumps(submit(package, a.release_sha256)))
    print('HELD ONLY. Separate release approval required; no retry or automatic GRES repair.')

if __name__ == '__main__': main()

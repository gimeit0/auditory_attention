"""Isolated, SHA-bound fine-alpha package bootstrap. Never submits jobs."""
import hashlib
import json
import os
from pathlib import Path
import sys

def identity(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file(): raise ValueError('PACKAGE_FILE')
    raw = path.read_bytes()
    return dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())

def verify_package(root, digest):
    root = Path(root)
    if root.is_symlink() or not root.is_dir(): raise ValueError('PACKAGE_ROOT')
    if identity(root/'RELEASE.json')['sha256'] != digest: raise ValueError('RELEASE_SHA')
    release = json.loads((root/'RELEASE.json').read_text())
    # Prior versions remain readable for fixed historical collectors. Execution below
    # still requires exact equality with this package's versioned contract.
    if release.get('scope') not in ('FINE_ALPHA_001_20260928_V1', 'FINE_ALPHA_001_20260928_V2', 'FINE_ALPHA_001_20260928_V3') or release.get('predictions') != 219600:
        raise ValueError('RELEASE_CONTRACT')
    if any(p.is_symlink() for p in root.rglob('*')): raise ValueError('PACKAGE_SYMLINK')
    for name, expected in release['files'].items():
        p = Path(name)
        if p.is_absolute() or '..' in p.parts or str(p) != name: raise ValueError('PACKAGE_PATH')
        if identity(root/p) != expected: raise ValueError('PACKAGE_BYTES: '+name)
    if {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()} != set(release['files']) | {'RELEASE.json'}:
        raise ValueError('PACKAGE_INVENTORY')
    return release

def approval_gate(approval, receipt, authorization, digest, budget, job_id, approval_identity, receipt_identity, runner_identity):
    if (approval.get('release_sha256') != digest or approval.get('budget') != budget or
        approval.get('authorized') is not True or approval.get('single_held_submission_authorized') is not True or
        approval.get('release_authorized') is not False): raise ValueError('FINE_GPU_APPROVAL_REQUIRED')
    if (receipt.get('status') != 'SUBMITTED_HELD_NOT_RELEASED' or receipt.get('job_id') != job_id or
        receipt.get('release_sha256') != digest or receipt.get('approval') != approval_identity):
        raise ValueError('FINE_SUBMISSION_BINDING')
    if (authorization.get('job_id') != job_id or authorization.get('release_sha256') != digest or
        authorization.get('release_authorized') is not True or authorization.get('submission') != receipt_identity or
        authorization.get('runner') != runner_identity): raise ValueError('FINE_RELEASE_AUTHORIZATION_REQUIRED')

def allocated_gate(package, digest):
    import pwd
    from fine_alpha_contract import REMOTE, BUDGET
    root = Path(REMOTE)
    if sys.platform != 'linux' or pwd.getpwuid(os.getuid()).pw_name != 's2510040': raise ValueError('NATIVE_ACCOUNT')
    if package != root/'package' or any(p.is_symlink() for p in (root, *root.parents)): raise ValueError('REMOTE_PATH')
    job = os.environ.get('SLURM_JOB_ID', '')
    if not job.isdigit(): raise ValueError('SLURM_REQUIRED')
    state = root/'state'
    if state.is_symlink() or not state.is_dir(): raise ValueError('STATE_DIRECTORY')
    a, r, rel = (state/name for name in ('APPROVAL.json', 'SUBMISSION.json', 'RELEASE_AUTHORIZATION.json'))
    aid, rid = identity(a), identity(r); identity(rel)
    approval_gate(json.loads(a.read_text()), json.loads(r.read_text()), json.loads(rel.read_text()),
                  digest, BUDGET, job, aid, rid, identity(package/'run_fine_alpha.sbatch'))
    from e2_submit_once import check_job_resources, command
    check_job_resources(command(['/usr/bin/scontrol', 'show', 'job', '-o', job]), job, BUDGET, held=False)
    return job

def worker_command(package, digest, block):
    return ['/home/s2510040/miniconda3/envs/attn/bin/python', '-I', '-B', '-u',
            str(package/'fine_alpha_entry.py'), 'worker', digest, block]

def main():
    if not sys.flags.isolated or not sys.dont_write_bytecode: raise ValueError('ISOLATED_NO_BYTECODE')
    mode, digest, *args = sys.argv[1:]
    package = Path(__file__).absolute().parent
    release = verify_package(package, digest)
    sys.path.insert(0, str(package))
    from fine_alpha_contract import REMOTE, BUDGET, BLOCKS, contract
    from e1_inputs import build_contract
    from e2_history_bridge import read_reference
    layout = build_contract(package)
    if release['contract'] != contract(layout) or release['budget'] != BUDGET: raise ValueError('FINE_CONTRACT')
    if mode == 'check':
        if args: raise ValueError('ARGS')
        read_reference(package/'reference')
        print(json.dumps(dict(status='FINE_ALPHA_PACKAGE_CHECK_PASS', release_sha256=digest,
                              science_predictions=194400, predictions=219600, jobs_submitted=0,
                              production_validated=False))); return
    if mode == 'source-check':
        if args: raise ValueError('ARGS')
        from e1_audited_session import native_source_preflight
        result = native_source_preflight(); verify_package(package, digest)
        print(json.dumps(result)); return
    from fine_alpha_archive import verify
    command = lambda b: worker_command(package if mode != 'offline-check' else Path(REMOTE)/'package', digest, b)
    if mode == 'offline-check':
        if len(args) != 2 or not args[1].isdigit(): raise ValueError('ARGS')
        result, _ = verify(Path(args[0]), layout, digest, args[1], command, read_reference(package/'reference'))
        verify_package(package, digest); print(json.dumps(result)); return
    job = allocated_gate(package, digest)
    root = Path(REMOTE)/'state/attempt'
    if mode == 'worker':
        if len(args) != 1 or args[0] not in BLOCKS: raise ValueError('ARGS')
        from fine_alpha_archive import run_worker
        run_worker(root/args[0]/'output', args[0], digest, package/'reference')
        verify_package(package, digest)
    elif mode == 'run':
        if args: raise ValueError('ARGS')
        from fine_alpha_pipeline import coordinate
        print(json.dumps(coordinate(root, command, digest, job,
            lambda: verify_package(package, digest),
            ['/home/s2510040/miniconda3/envs/attn/bin/python', '-I', '-B', '-u', str(package/'fine_alpha_entry.py'), 'verify', digest])))
    elif mode == 'verify':
        if args: raise ValueError('ARGS')
        from e1_artifacts import write_json
        result, _ = verify(root, layout, digest, job, command, read_reference(package/'reference'))
        verify_package(package, digest); write_json(root/'VERIFY/VERIFIED.json', result)
    else: raise ValueError('MODE')

if __name__ == '__main__': main()

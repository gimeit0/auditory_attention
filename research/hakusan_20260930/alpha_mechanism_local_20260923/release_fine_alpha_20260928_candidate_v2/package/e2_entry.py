"""Hash-verified portable E2 bootstrap. No submission/release operation."""
import hashlib
import json
import os
from pathlib import Path
import sys

SCOPE='E2_TRAJECTORY_20260928_V1'
REMOTE=Path('/home/s2510040/audattn_e2/e2_20260928_v1')
BUDGET=dict(gpus=1,gpu_type='a100',cpus=8,host_memory_gib=64,wall_minutes=240,
            coordinator_deadline_seconds=13500,worker_deadline_seconds=9000)

def profile_spec(profile):
    if profile=='formal': return dict(scope=SCOPE,remote=str(Path('/home/s2510040/audattn_e2/e2_20260928_v1')),
        budget=dict(gpus=1,gpu_type='a100',cpus=8,host_memory_gib=64,wall_minutes=240,
                    coordinator_deadline_seconds=13500,worker_deadline_seconds=9000),predictions=91134)
    if profile=='pilot': return dict(scope='E2_NATIVE_PILOT_20260928_V1',
        remote='/home/s2510040/audattn_e2/e2_pilot_20260928_v1',
        budget=dict(gpus=1,gpu_type='a100',cpus=8,host_memory_gib=64,wall_minutes=60,
                    coordinator_deadline_seconds=3300,worker_deadline_seconds=600),predictions=2709)
    raise ValueError('PROFILE')

def identity(path):
    if path.is_symlink() or not path.is_file(): raise ValueError('PACKAGE_FILE')
    raw=path.read_bytes(); return dict(size=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def verify_package(root,digest):
    root=Path(root)
    if root.is_symlink() or not root.is_dir(): raise ValueError('PACKAGE_ROOT')
    if identity(root/'RELEASE.json')['sha256']!=digest: raise ValueError('RELEASE_SHA')
    release=json.loads((root/'RELEASE.json').read_text())
    spec=profile_spec(release['profile'])
    if release['scope']!=spec['scope'] or release['budget']!=spec['budget'] or release['predictions']!=spec['predictions']:
        raise ValueError('RELEASE_CONTRACT')
    if any(p.is_symlink() for p in root.rglob('*')): raise ValueError('PACKAGE_SYMLINK')
    for name,wanted in release['files'].items():
        p=Path(name)
        if p.is_absolute() or '..' in p.parts or str(p)!=name: raise ValueError('PACKAGE_PATH')
        if identity(root/p)!=wanted: raise ValueError('PACKAGE_BYTES: '+name)
    actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
    if actual!=set(release['files'])|{'RELEASE.json'}: raise ValueError('PACKAGE_INVENTORY')
    return release

def worker_command(rounds,mode,unused_output=None):
    return ['/home/s2510040/miniconda3/envs/attn/bin/python','-I','-B','-u',
            str(REMOTE/'package/e2_entry.py'),'worker',ACTIVE_DIGEST,str(rounds),mode]

def allocated_gate(package,digest):
    import pwd
    if sys.platform!='linux' or pwd.getpwuid(os.getuid()).pw_name!='s2510040': raise ValueError('NATIVE_ACCOUNT')
    if package!=REMOTE/'package': raise ValueError('REMOTE_PACKAGE_PATH')
    for p in (REMOTE,*REMOTE.parents):
        if p.is_symlink(): raise ValueError('REMOTE_SYMLINK')
    job=os.environ.get('SLURM_JOB_ID','')
    if not job.isdigit(): raise ValueError('SLURM_REQUIRED')
    state=REMOTE/'state'
    approval=state/'APPROVAL.json'; receipt=state/'SUBMISSION.json'
    identity(approval); identity(receipt)
    a=json.loads(approval.read_text()); r=json.loads(receipt.read_text())
    if a.get('release_sha256')!=digest or a.get('budget')!=BUDGET or a.get('authorized') is not True:
        raise ValueError('GPU_APPROVAL_REQUIRED')
    if r.get('job_id')!=job or r.get('release_sha256')!=digest or r.get('approval')!=identity(approval):
        raise ValueError('SUBMISSION_BINDING')
    if r.get('status')!='SUBMITTED_HELD_NOT_RELEASED': raise ValueError('SUBMISSION_STATUS')
    release=state/'RELEASE_AUTHORIZATION.json'
    identity(release); authorized=json.loads(release.read_text())
    if authorized.get('job_id')!=job or authorized.get('release_sha256')!=digest or authorized.get('release_authorized') is not True:
        raise ValueError('RELEASE_AUTHORIZATION_REQUIRED')
    if authorized.get('submission')!=identity(receipt) or authorized.get('runner')!=identity(package/'run_e2.sbatch'):
        raise ValueError('RELEASE_AUTHORIZATION_BINDING')
    from e2_submit_once import check_job_resources,command
    check_job_resources(command(['/usr/bin/scontrol','show','job','-o',job]),job,BUDGET,held=False)
    return job

ACTIVE_DIGEST=None
def main():
    global ACTIVE_DIGEST,REMOTE,BUDGET
    if not sys.flags.isolated or not sys.dont_write_bytecode: raise ValueError('ISOLATED_NO_BYTECODE')
    mode,digest,*rest=sys.argv[1:]
    package=Path(__file__).absolute().parent
    release=verify_package(package,digest); ACTIVE_DIGEST=digest
    spec=profile_spec(release['profile']); REMOTE=Path(spec['remote']); BUDGET=spec['budget']
    pilot=release['profile']=='pilot'
    sys.path.insert(0,str(package))
    from e1_inputs import build_contract
    from e2_matrix import expected_records
    from e2_pipeline import WORKERS,PILOT_WORKERS
    workers=PILOT_WORKERS if pilot else WORKERS
    from e2_endpoint import probe_spec
    c=build_contract(package)
    if sum(len(ids) for _,r,m in workers for ids in expected_records(c,r,m).values())+9*2*sum(len(ids) for *_,ids in probe_spec(c))!=release['predictions']:
        raise ValueError('MATRIX_COUNT')
    reference=package/'reference'
    if mode=='check':
        if rest: raise ValueError('ARGS')
        from e2_history_bridge import read_reference
        read_reference(reference)
        print(json.dumps(dict(status='E2_PACKAGE_CHECK_PASS',release_sha256=digest,predictions=release['predictions'],profile=release['profile'],
                              jobs_submitted=0,production_ready=False))); return
    if mode=='source-check':
        if rest: raise ValueError('ARGS')
        from e2_audited_session import native_source_preflight
        result=native_source_preflight(); verify_package(package,digest)
        print(json.dumps(result)); return
    from e2_verify_pipeline import verify_pipeline
    if mode=='offline-check':
        if len(rest)!=2 or not rest[1].isdigit(): raise ValueError('ARGS')
        result=verify_pipeline(Path(rest[0]),c,worker_command,job_id=rest[1],reference_root=reference,pilot=pilot)
        verify_package(package,digest); print(json.dumps(result)); return
    job=allocated_gate(package,digest)
    from e2_pipeline import WORKERS,coordinate
    from e2_process import write
    attempt=REMOTE/'state/attempt'
    if mode=='run':
        if rest: raise ValueError('ARGS')
        result=coordinate(attempt,worker_command,
            lambda root: ['/home/s2510040/miniconda3/envs/attn/bin/python','-I','-B','-u',str(package/'e2_entry.py'),'verify',digest],
            seconds=BUDGET['coordinator_deadline_seconds'],pilot=pilot,
            final_check=lambda:verify_package(package,digest),worker_seconds=BUDGET['worker_deadline_seconds'])
        print(json.dumps(result))
    elif mode=='worker':
        if len(rest)!=2: raise ValueError('ARGS')
        rounds=int(rest[0]); stage_mode=rest[1]
        matches=[label for label,r,m in workers if (r,m)==(rounds,stage_mode)]
        if len(matches)!=1: raise ValueError('WORKER_MODE')
        from e2_stage_worker import run_stage
        run_stage(attempt/matches[0]/'output',rounds,seconds=BUDGET['worker_deadline_seconds'],
                  reference_root=reference,mode=stage_mode)
        verify_package(package,digest)
    elif mode=='verify':
        if rest: raise ValueError('ARGS')
        result=verify_pipeline(attempt,c,worker_command,job_id=job,reference_root=reference,pilot=pilot)
        verify_package(package,digest); write(attempt/'VERIFY/VERIFIED.json',result)
    else: raise ValueError('MODE')

if __name__=='__main__': main()

"""Stdlib bootstrap for the E1 candidate. Never submits or releases jobs."""
import hashlib
import json
import os
from pathlib import Path
import sys

SCOPE='E1_FORMAL40_NATIVE_20260926_V1'
REMOTE_ROOT=Path('/home/s2510040/audattn_e1/e1_20260926_v1')
BUDGET=dict(wall_minutes=180,gpus=1,cpus=8,host_memory_gib=64,
            coordinator_deadline_seconds=9900,worker_deadline_seconds=9000)

def require(ok,message):
    if not ok: raise ValueError(message)

def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def identity(path):
    require(path.is_file() and not path.is_symlink(),'REGULAR_FILE_REQUIRED')
    raw=path.read_bytes()
    return dict(size=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def verify_package(package,digest):
    package=Path(package)
    require(package.is_dir() and not package.is_symlink(),'PACKAGE_DIRECTORY')
    require(identity(package/'RELEASE.json')['sha256']==digest,'RELEASE_SHA')
    release=json.loads((package/'RELEASE.json').read_bytes())
    require(release['scope']==SCOPE and release['schema_version']==1,'RELEASE_SCOPE')
    require(release['budget']==BUDGET and release['predictions']==38400,'RELEASE_BUDGET')
    require(release['submission']=='held_once_manual_review_required','RELEASE_SUBMISSION')
    require(not any(p.is_symlink() for p in package.rglob('*')),'PACKAGE_SYMLINK')
    for name,row in release['files'].items():
        relative=Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts and str(relative)==name,'PACKAGE_PATH')
        require(identity(package/relative)==row,'PACKAGE_FILE: '+name)
    actual={str(p.relative_to(package)) for p in package.rglob('*') if p.is_file()}
    require(actual==set(release['files'])|{'RELEASE.json'},'PACKAGE_INVENTORY')
    return release

def load_contract(package,release):
    from e1_inputs import build_contract
    from e1_execution import execution_spec
    c=json.loads((package/'E1_CONTRACT.json').read_bytes())
    require(hashlib.sha256(canonical(c)).hexdigest()==release['contract_sha256'],'CONTRACT_SHA')
    require(canonical(c)==canonical(build_contract(package)),'CONTRACT_INPUT_BINDING')
    require(canonical(release['execution'])==canonical(execution_spec(c)),'EXECUTION_SPEC')
    return c

def check_receipt(state,digest,job_id):
    require(state.is_dir() and not state.is_symlink(),'STATE_DIRECTORY')
    for name in ('SUBMISSION.json','INTENT.json','SUBMISSION_RESPONSE.json'):
        identity(state/name)
    r=json.loads((state/'SUBMISSION.json').read_bytes())
    require(r['job_id']==job_id and r['release_sha256']==digest and
            r['status']=='SUBMITTED_HELD_NOT_RELEASED','JOB_RECEIPT')
    require(r['intent']==identity(state/'INTENT.json') and
            r['response']==identity(state/'SUBMISSION_RESPONSE.json'),'RECEIPT_CHAIN')
    intent=json.loads((state/'INTENT.json').read_bytes())
    response=json.loads((state/'SUBMISSION_RESPONSE.json').read_bytes())
    require(intent['release_sha256']==digest and intent['budget_gpu_hours']==3 and
            '--hold' in intent['argv'] and '--no-requeue' in intent['argv'],'INTENT_BINDING')
    require(response['returncode']==0 and response['stdout'].strip().split(';')[0]==job_id,'RESPONSE_JOB')
    return r

def allocated_gate(package,digest):
    import pwd
    require(sys.platform=='linux' and pwd.getpwuid(os.getuid()).pw_name=='s2510040','NATIVE_ACCOUNT')
    require(package==REMOTE_ROOT/'package','DEPLOYMENT_PATH')
    require(not any(p.is_symlink() for p in [REMOTE_ROOT,*REMOTE_ROOT.parents]),'DEPLOYMENT_SYMLINK')
    job=os.environ.get('SLURM_JOB_ID','')
    require(job.isdigit(),'ALLOCATED_ONLY')
    check_receipt(REMOTE_ROOT/'state',digest,job)
    return job

def main():
    require(sys.flags.isolated and sys.dont_write_bytecode,'ISOLATED_NO_BYTECODE_REQUIRED')
    args=sys.argv[1:]
    require(len(args)>=2,'ENTRY_ARGUMENTS')
    mode,digest,*rest=args
    require(mode in ('check','source-check','run','worker','verify','offline-check'),'ENTRY_MODE')
    package=Path(__file__).absolute().parent
    release=verify_package(package,digest)
    sys.path.insert(0,str(package))
    c=load_contract(package,release)
    if mode=='check':
        require(not rest,'ENTRY_ARGUMENTS')
        print(json.dumps(dict(status='E1_PACKAGE_BYTES_AND_INPUTS_PASS',release_sha256=digest,
                              contract_sha256=release['contract_sha256'],jobs_submitted=0)))
        return
    if mode=='source-check':
        require(not rest,'ENTRY_ARGUMENTS')
        from e1_audited_session import native_source_preflight
        result=native_source_preflight()
        verify_package(package,digest)
        print(json.dumps(result)); return
    if mode=='offline-check':
        require(len(rest)==2 and rest[1].isdigit(),'ENTRY_ARGUMENTS')
        from production_e1 import verify_completed
        result=verify_completed(Path(rest[0]),c,package,release,digest,rest[1])
        verify_package(package,digest)
        print(json.dumps(result)); return
    job=allocated_gate(package,digest)
    attempt=REMOTE_ROOT/'state/attempt'
    from production_e1 import coordinator,worker,verifier
    if mode=='run':
        require(not rest,'ENTRY_ARGUMENTS')
        coordinator(package,attempt,c,release,digest,job)
    elif mode=='worker':
        require(len(rest)==1 and rest[0] in ('A','B'),'ENTRY_ARGUMENTS')
        worker(package,attempt/rest[0],c,rest[0],release,digest)
    else:
        require(mode=='verify' and not rest,'ENTRY_ARGUMENTS')
        verifier(package,attempt,c,release,digest,job)

if __name__=='__main__': main()

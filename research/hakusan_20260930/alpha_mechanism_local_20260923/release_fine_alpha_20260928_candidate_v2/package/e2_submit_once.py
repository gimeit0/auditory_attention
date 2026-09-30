"""Remote held-only pilot submitter; explicit approval, no retry or release."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys

# Explicit isolated bootstrap; externally verified release binds this sibling.
entry=Path(__file__).absolute().with_name('e2_entry.py')
if entry.is_symlink() or not entry.is_file(): raise ValueError('BOOTSTRAP_FILE')
spec=importlib.util.spec_from_file_location('e2_submit_bootstrap',entry)
bootstrap=importlib.util.module_from_spec(spec)
exec(compile(entry.read_bytes(),str(entry),'exec'),bootstrap.__dict__)
identity=bootstrap.identity

def write(path,value):
    with path.open('x') as f:
        json.dump(value,f,sort_keys=True,indent=2,allow_nan=False); f.flush(); os.fsync(f.fileno())

def command(argv):
    p=subprocess.run(argv,capture_output=True,text=True,timeout=60)
    return dict(returncode=p.returncode,stdout=p.stdout,stderr=p.stderr)

def check_job_resources(response,job,budget,*,held):
    if response['returncode']!=0: raise ValueError('SCHEDULER_QUERY_FAILED')
    fields=dict(re.findall(r'(\w+)=([^\s]+)',response['stdout']))
    hours,minutes=divmod(budget['wall_minutes'],60)
    wanted={'JobId':str(job),'Partition':'GPU-1A','Account':'student',
            'NumCPUs':str(budget['cpus']),'NumTasks':'1','TimeLimit':f'{hours:02d}:{minutes:02d}:00',
            'JobState':'PENDING' if held else 'RUNNING','Requeue':'0','Restarts':'0'}
    if any(fields.get(k)!=v for k,v in wanted.items()): raise ValueError('SCHEDULER_RESOURCE_FIELDS')
    if fields.get('NumNodes') not in ('1','1-1'): raise ValueError('SCHEDULER_NODE_RANGE')
    if not fields.get('UserId','').startswith('s2510040('): raise ValueError('SCHEDULER_OWNER')
    if held and (fields.get('Reason')!='JobHeldUser' or fields.get('Priority')!='0'):
        raise ValueError('JOB_NOT_HELD')
    tres=dict(x.split('=',1) for x in fields.get('ReqTRES','').split(',') if '=' in x)
    if tres.get('cpu')!='8' or tres.get('node')!='1' or tres.get('mem') not in ('64G','65536M'):
        raise ValueError('SCHEDULER_TRES')
    if tres.get('gres/gpu') not in (None,'1') or tres.get('gres/gpu:nvidia_a100')!='1':
        raise ValueError('SCHEDULER_TYPED_GRES')
    if any(k.startswith('gres/') and k not in ('gres/gpu','gres/gpu:nvidia_a100') for k in tres):
        raise ValueError('SCHEDULER_EXTRA_GRES')
    if fields.get('TresPerNode')!='gres/gpu:nvidia_a100:1': raise ValueError('SCHEDULER_NODE_GRES')
    return dict(status='E2_SCHEDULER_RESOURCES_PASS',job_id=str(job),held=held,fields=fields)

def submit_argv(package,state,digest,test=False):
    return ['/usr/bin/sbatch','--test-only' if test else '--hold','--parsable','--export=NONE','--no-requeue',
        '--partition=GPU-1A','--account=student','--nodes=1','--ntasks=1','--cpus-per-task=8',
        '--threads-per-core=1','--mem=65536M','--time=01:00:00','--gres=gpu:nvidia_a100:1',
        '--job-name=audattn_e2_pilot','--chdir='+str(state),'--input=/dev/null',
        '--output='+str(state/'slurm-%j.log'),'--error='+str(state/'slurm-%j.log'),
        str(package/'run_e2.sbatch'),str(package),digest,str(state)]

def submit(package,digest,*,execute=command):
    package=Path(package); release=bootstrap.verify_package(package,digest)
    if release['profile']!='pilot': raise ValueError('ONLY_PILOT_AUTHORIZABLE')
    root=package.parent; approval=root/'APPROVAL.json'; identity(approval)
    a=json.loads(approval.read_text())
    if (a.get('release_sha256')!=digest or a.get('budget')!=release['budget'] or
        a.get('authorized') is not True or a.get('single_held_submission_authorized') is not True or
        a.get('release_authorized') is not False): raise ValueError('EXPLICIT_PILOT_APPROVAL_REQUIRED')
    state=root/'state'
    state.mkdir(mode=0o700,exist_ok=False) # Any previous attempt blocks automatic resubmission.
    write(state/'APPROVAL.json',a)
    try:
        queue=execute(['/usr/bin/squeue','-h','-u','s2510040','-o','%i|%j|%T'])
        write(state/'QUEUE.json',queue)
        if queue['returncode'] or any('audattn' in line for line in queue['stdout'].splitlines()):
            raise ValueError('QUEUE_FAILED_OR_RELATED_JOB')
        test=execute(submit_argv(package,state,digest,True)); write(state/'TEST_ONLY.json',test)
        if test['returncode']: raise ValueError('TEST_ONLY_FAILED')
        argv=submit_argv(package,state,digest)
        write(state/'INTENT.json',dict(argv=argv,release_sha256=digest,automatic_retry=False))
        response=execute(argv); write(state/'RESPONSE.json',response)
        if response['returncode'] or not re.fullmatch(r'[0-9]+(?:;[\w.-]+)?\s*',response['stdout']):
            raise ValueError('SUBMISSION_UNKNOWN_NO_RETRY')
        job=response['stdout'].strip().split(';')[0]
        receipt=dict(status='SUBMITTED_HELD_NOT_RELEASED',job_id=job,release_sha256=digest,
            approval=identity(state/'APPROVAL.json'),intent=identity(state/'INTENT.json'),
            response=identity(state/'RESPONSE.json'),automatic_retry=False,automatic_release=False)
        write(state/'SUBMISSION.json',receipt) # Preserve job id before any scheduler inspection.
        observed=execute(['/usr/bin/scontrol','show','job','-o',job]); write(state/'HELD_RESOURCES.json',observed)
        check_job_resources(observed,job,release['budget'],held=True)
        spool=execute(['/usr/bin/scontrol','write','batch_script',job,'-']); write(state/'SPOOL.json',spool)
        if spool['returncode'] or spool['stdout']!=(package/'run_e2.sbatch').read_text():
            raise ValueError('SPOOL_MISMATCH')
        bootstrap.verify_package(package,digest)
        return receipt
    except BaseException as exc:
        write(state/'STOPPED.json',dict(error=str(exc),error_type=type(exc).__name__,
            submission_may_have_happened=(state/'INTENT.json').exists(),automatic_retry=False))
        raise

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release-sha256',required=True)
    p.add_argument('--confirm-action',required=True,choices=['SUBMIT_E2_PILOT_HELD_ONCE_1_GPU_HOUR'])
    a=p.parse_args(); package=Path(__file__).absolute().parent
    if sys.platform!='linux' or pwd.getpwuid(os.getuid()).pw_name!='s2510040': raise ValueError('NATIVE_ACCOUNT')
    if not sys.flags.isolated or not sys.dont_write_bytecode: raise ValueError('ISOLATED_REQUIRED')
    root=Path(bootstrap.profile_spec('pilot')['remote'])
    if package!=root/'package' or any(x.is_symlink() for x in (root,*root.parents)):
        raise ValueError('REMOTE_PATH')
    print(json.dumps(submit(package,a.release_sha256)))
    print('HELD ONLY. Separate release approval required. No retry or automatic GRES repair.')

if __name__=='__main__': main()

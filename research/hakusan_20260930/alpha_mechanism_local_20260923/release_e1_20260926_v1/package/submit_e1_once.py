"""Explicit single held submission. No SSH, retries, GRES edits or release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
from e1_entry import REMOTE_ROOT,verify_package,identity

def create(path,value):
    with path.open('xb') as f:
        f.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode()); f.flush(); os.fsync(f.fileno())

def command(argv):
    r=subprocess.run(argv,capture_output=True,text=True,timeout=60,check=False)
    return dict(returncode=r.returncode,stdout=r.stdout,stderr=r.stderr)

def argv(package,state,digest,test=False):
    return ['/usr/bin/sbatch','--test-only' if test else '--hold','--parsable','--export=NONE','--no-requeue',
            '--partition=GPU-1A','--account=student','--nodes=1','--ntasks=1','--cpus-per-task=8',
            '--threads-per-core=1','--mem=65536M','--time=03:00:00','--gres=gpu:nvidia_a100:1',
            '--job-name=audattn_alpha_e1','--chdir='+str(state),'--input=/dev/null',
            '--output='+str(state/'slurm-%j.log'),'--error='+str(state/'slurm-%j.log'),
            str(package/'run_e1.sbatch'),str(package),digest,str(state)]

def submit(package,state,digest,execute=command):
    verify_package(package,digest)
    if state.exists() or state.is_symlink(): raise ValueError('STATE_EXISTS_NO_RETRY')
    state.mkdir(mode=0o700)
    try:
        q=execute(['/usr/bin/squeue','-h','-u','s2510040','-o','%i|%j|%T'])
        create(state/'QUEUE.json',q)
        if q['returncode'] or any('audattn' in line for line in q['stdout'].splitlines()):
            raise ValueError('QUEUE_CHECK_FAILED_OR_RELATED_JOB')
        test=execute(argv(package,state,digest,True)); create(state/'TEST_ONLY.json',test)
        if test['returncode']: raise ValueError('SBATCH_TEST_ONLY_FAILED')
        request=argv(package,state,digest)
        create(state/'INTENT.json',dict(argv=request,release_sha256=digest,budget_gpu_hours=3,status='INTENT'))
        # Never retry even if transport fails after scheduler accepted the job.
        response=execute(request)
        create(state/'SUBMISSION_RESPONSE.json',response)
        if response['returncode'] or not re.fullmatch(r'[0-9]+(?:;[A-Za-z0-9_.-]+)?\s*',response['stdout']):
            raise ValueError('SUBMISSION_UNKNOWN_INSPECT_NO_RETRY')
        receipt=dict(job_id=response['stdout'].strip().split(';')[0],release_sha256=digest,
                     status='SUBMITTED_HELD_NOT_RELEASED',intent=identity(state/'INTENT.json'),
                     response=identity(state/'SUBMISSION_RESPONSE.json'),automatic_retry=False,automatic_release=False)
        create(state/'SUBMISSION.json',receipt)
        return receipt
    except BaseException as e:
        create(state/'STOPPED.json',dict(error_type=type(e).__name__,error=str(e),
               submission_may_have_happened=(state/'INTENT.json').exists(),automatic_retry=False))
        raise

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release-sha256',required=True)
    p.add_argument('--confirm-action',required=True,choices=['SUBMIT_E1_HELD_ONCE_3_GPU_HOURS'])
    a=p.parse_args()
    if sys.platform!='linux' or pwd.getpwuid(os.getuid()).pw_name!='s2510040': raise ValueError('NATIVE_ACCOUNT')
    package=Path(__file__).absolute().parent
    if package!=REMOTE_ROOT/'package': raise ValueError('DEPLOYMENT_PATH')
    if any(p.is_symlink() for p in [REMOTE_ROOT,*REMOTE_ROOT.parents]): raise ValueError('DEPLOYMENT_SYMLINK')
    print(json.dumps(submit(package,REMOTE_ROOT/'state',a.release_sha256)))
    print('STOP: held only; resources, GRES and spool hash require review before separate release approval.')

if __name__=='__main__': main()

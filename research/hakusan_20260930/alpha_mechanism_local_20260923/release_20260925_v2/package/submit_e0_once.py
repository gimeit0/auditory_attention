"""Single held submission only. No SSH, retries, GRES edits or release command."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys

ROOT=Path('/home/s2510040/audattn_e0/e0_20260925_v2')

def create(path,data):
    with path.open('xb') as f:
        f.write((json.dumps(data,sort_keys=True,indent=2)+'\n').encode())
        f.flush(); os.fsync(f.fileno())

def command(argv):
    result=subprocess.run(argv,capture_output=True,text=True,timeout=60,check=False)
    return dict(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr)

def argv(package,state,digest,test=False):
    return ['/usr/bin/sbatch','--test-only' if test else '--hold','--parsable','--export=NONE','--no-requeue',
            '--partition=GPU-1A','--account=student','--nodes=1','--ntasks=1','--cpus-per-task=8',
            '--threads-per-core=1','--mem=65536M','--time=00:30:00','--gres=gpu:nvidia_a100:1',
            '--job-name=audattn_alpha_e0','--chdir='+str(state),'--input=/dev/null',
            '--output='+str(state/'slurm-%j.log'),'--error='+str(state/'slurm-%j.log'),
            str(package/'run_e0.sbatch'),str(package),digest,str(state)]

def submit(package,state,digest,execute=command):
    if state.exists() or state.is_symlink(): raise ValueError('STATE_EXISTS_NO_RETRY')
    state.mkdir(mode=0o700)
    # Exclusive directory means even ambiguous/time-out submission cannot be retried.
    queue=execute(['/usr/bin/squeue','-h','-u','s2510040','-o','%i|%j|%T'])
    create(state/'QUEUE.json',queue)
    if queue['returncode'] or any('audattn' in line for line in queue['stdout'].splitlines()):
        raise ValueError('QUEUE_CHECK_FAILED_OR_RELATED_JOB')
    trial=execute(argv(package,state,digest,True))
    create(state/'TEST_ONLY.json',trial)
    if trial['returncode']: raise ValueError('SBATCH_TEST_ONLY_FAILED')
    request=argv(package,state,digest)
    create(state/'INTENT.json',dict(argv=request,release_sha256=digest,budget_gpu_hours=.5,status='INTENT'))
    try:
        response=execute(request)
    except BaseException as error:
        create(state/'SUBMISSION_UNKNOWN.json',dict(error=repr(error),next='inspect scheduler; never resubmit'))
        raise
    create(state/'SUBMISSION_RESPONSE.json',response)
    if response['returncode'] or not re.fullmatch(r'[0-9]+(?:;[A-Za-z0-9_.-]+)?\s*',response['stdout']):
        raise ValueError('SUBMISSION_UNKNOWN_INSPECT_NO_RETRY')
    receipt=dict(job_id=response['stdout'].strip().split(';')[0],release_sha256=digest,
                 status='SUBMITTED_HELD_NOT_RELEASED',automatic_retry=False,automatic_release=False)
    create(state/'SUBMISSION.json',receipt)
    return receipt

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--release-sha256',required=True)
    parser.add_argument('--confirm-action',required=True,choices=['SUBMIT_E0_HELD_ONCE'])
    args=parser.parse_args()
    if sys.platform!='linux' or pwd.getpwuid(os.getuid()).pw_name!='s2510040': raise ValueError('NATIVE_ACCOUNT_REQUIRED')
    package=Path(__file__).resolve().parent
    if package!=ROOT/'package': raise ValueError('DEPLOYMENT_PATH')
    for path in (ROOT,*ROOT.parents):
        if path.is_symlink(): raise ValueError('SYMLINK_ROOT')
    spec=importlib.util.spec_from_file_location('bootstrap',package/'e0_entry.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.verify_package(package,args.release_sha256)
    receipt=submit(package,ROOT/'state',args.release_sha256)
    print(json.dumps(receipt))
    print('STOP: held job only. Review scontrol resources/GRES and receipt before separately authorized release.')

if __name__=='__main__': main()

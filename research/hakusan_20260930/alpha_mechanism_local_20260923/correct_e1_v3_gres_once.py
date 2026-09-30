"""Job 750474 only. One separately authorized GRES edit; never release/retry."""
import datetime
import json
from pathlib import Path
import shlex
import subprocess
from publish_e1_v3 import SSH,SOCKET,REMOTE_PY
from check_e1_v3_handoff import HERE,RELEASE_SHA

REMOTE=r'''
import hashlib,json,os,pathlib,subprocess,sys
job='750474'
root=pathlib.Path('/home/s2510040/audattn_e1/e1_20260927_v3')
state=root/'state'
receipt=json.loads((state/'SUBMISSION.json').read_text())
if receipt['job_id']!=job or receipt['release_sha256']!=sys.argv[1]:raise ValueError('RECEIPT_BINDING')
def command(name,argv):
    p=subprocess.run(argv,capture_output=True,text=True,timeout=30)
    print(json.dumps(dict(stage=name,argv=argv,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr)),flush=True)
    if p.returncode:raise ValueError(name+'_NONZERO_NO_RETRY')
    return p.stdout
def fields(raw):return dict(t.split('=',1) for t in raw.split() if '=' in t)
def held(f):
    expected={'JobId':job,'JobName':'audattn_alpha_e1','JobState':'PENDING','Reason':'JobHeldUser','Priority':'0',
              'TimeLimit':'03:00:00','NumCPUs':'8','MinMemoryNode':'64G','Requeue':'0','RunTime':'00:00:00',
              'Command':str(root/'package/run_e1.sbatch'),'WorkDir':str(state)}
    if any(f.get(k)!=v for k,v in expected.items()):raise ValueError('HELD_RESOURCE_PRECONDITION')
before=command('before',['/usr/bin/scontrol','show','job','-dd',job]);f=fields(before);held(f)
if 'gres/gpu:h100-20c=1' not in f.get('ReqTRES','').split(','):raise ValueError('UNEXPECTED_GRES_NO_UPDATE')
intent=state/'GRES_CORRECTION_750474_INTENT.json'
argv=['/usr/bin/scontrol','update','JobId='+job,'Gres=gpu:nvidia_a100:1']
os.umask(0o077)
with intent.open('x') as out:
    json.dump(dict(job_id=job,release_sha256=sys.argv[1],argv=argv,before=before,authorized_once=True),out)
    out.flush();os.fsync(out.fileno())
command('update_once',argv)
after=command('after',['/usr/bin/scontrol','show','job','-dd',job]);f=fields(after);held(f)
tres=f.get('ReqTRES','').split(',')
if 'gres/gpu:nvidia_a100=1' not in tres or any('h100' in t for t in tres):raise ValueError('A100_NOT_CONFIRMED_NO_RETRY')
if f.get('TresPerNode')!='gres/gpu:nvidia_a100:1':raise ValueError('TRES_PER_NODE')
spool=command('spool',['/usr/bin/scontrol','write','batch_script',job,'-'])
if spool.encode()!=(root/'package/run_e1.sbatch').read_bytes():raise ValueError('SPOOL_CHANGED')
command('queue',['/usr/bin/squeue','-h','-j',job,'-o','%i|%T|%r|%b'])
result=dict(status='A100_CORRECTED_VERIFIED_STILL_HELD',job_id=job,release_sha256=sys.argv[1],
            spool_sha256=hashlib.sha256(spool.encode()).hexdigest(),release_attempted=False,updates=1)
with (state/'GRES_CORRECTION_750474_RESULT.json').open('x') as out:json.dump(result,out)
print(json.dumps(result),flush=True)
'''

def main():
    if not SOCKET.is_socket() or SOCKET.is_symlink():raise ValueError('MASTER_REQUIRED_NO_RECONNECT')
    auth=json.loads((HERE.parent/'docs/superpowers/evidence/e1-contract-signoff-20260927/GRES_CORRECTION_750474.json').read_text())
    if auth['job_id']!='750474' or auth['maximum_update_invocations']!=1 or auth['release_authorized']:
        raise ValueError('AUTHORIZATION')
    evidence=HERE/'release_e1_20260927_v3/gres-correction-750474'
    evidence.mkdir(mode=0o700,exist_ok=False)
    (evidence/'LOCAL_INTENT.json').write_text(json.dumps(auth,indent=2)+'\n')
    result=dict(status='UNKNOWN_INSPECT_NO_RETRY',job_id='750474',release_attempted=False)
    try:
        cmd=shlex.join([REMOTE_PY,'-I','-B','-c',REMOTE,RELEASE_SHA])
        with (evidence/'remote.jsonl').open('xb') as out,(evidence/'remote.stderr').open('xb') as err:
            p=subprocess.run(SSH+[cmd],stdout=out,stderr=err,timeout=180)
        print((evidence/'remote.jsonl').read_text(),end='')
        if p.returncode:raise ValueError('REMOTE_NONZERO_INSPECT_NO_RETRY')
        result=json.loads((evidence/'remote.jsonl').read_text().splitlines()[-1])
        if result.get('status')!='A100_CORRECTED_VERIFIED_STILL_HELD':raise ValueError('RESULT_STATUS')
    except BaseException as e:
        result.update(error_type=type(e).__name__,error=str(e));raise
    finally:
        result['recorded_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        (evidence/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
        print('EVIDENCE='+str(evidence),flush=True)

if __name__=='__main__':main()

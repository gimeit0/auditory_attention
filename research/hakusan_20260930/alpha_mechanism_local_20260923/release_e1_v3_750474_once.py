"""Release only the verified held job 750474 once; no retry or resource edits."""
import datetime
import json
import shlex
import subprocess
from publish_e1_v3 import SSH,SOCKET,REMOTE_PY
from check_e1_v3_handoff import HERE,RELEASE_SHA,ENTRY_SHA

REMOTE=r'''
import hashlib,json,os,pathlib,subprocess,sys
root=pathlib.Path('/home/s2510040/audattn_e1/e1_20260927_v3');state=root/'state';job='750474'
def command(name,argv):
    p=subprocess.run(argv,capture_output=True,text=True,timeout=60)
    print(json.dumps(dict(stage=name,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr)),flush=True)
    if p.returncode:raise ValueError(name+'_FAILED_NO_RETRY')
    return p.stdout
for name,digest in [('RELEASE.json',sys.argv[1]),('e1_entry.py',sys.argv[2])]:
    p=root/'package'/name
    if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('PACKAGE_HASH')
command('package_check',[sys.executable,'-I','-B',str(root/'package/e1_entry.py'),'check',sys.argv[1]])
r=json.loads((state/'SUBMISSION.json').read_text())
if r['job_id']!=job or r['release_sha256']!=sys.argv[1]:raise ValueError('RECEIPT')
correction=json.loads((state/'GRES_CORRECTION_750474_RESULT.json').read_text())
if correction['status']!='A100_CORRECTED_VERIFIED_STILL_HELD' or correction['job_id']!=job:raise ValueError('CORRECTION')
before=command('before',['/usr/bin/scontrol','show','job','-dd',job])
f=dict(t.split('=',1) for t in before.split() if '=' in t)
expected={'JobId':job,'JobName':'audattn_alpha_e1','JobState':'PENDING','Reason':'JobHeldUser','Priority':'0',
          'NumCPUs':'8','MinMemoryNode':'64G','TimeLimit':'03:00:00','Requeue':'0','RunTime':'00:00:00',
          'TresPerNode':'gres/gpu:nvidia_a100:1','Command':str(root/'package/run_e1.sbatch'),'WorkDir':str(state)}
if any(f.get(k)!=v for k,v in expected.items()):raise ValueError('HELD_RESOURCE_CHANGED')
if set(f.get('ReqTRES','').split(','))!={'cpu=8','mem=64G','node=1','billing=8','gres/gpu:nvidia_a100=1'}:raise ValueError('REQ_TRES')
spool=command('spool',['/usr/bin/scontrol','write','batch_script',job,'-'])
if hashlib.sha256(spool.encode()).hexdigest()!='5f7fa068f203555c6f6ac42764ef70869b7b2488e341b4b25191d5a5adb32341':raise ValueError('SPOOL_SHA')
os.umask(0o077)
with (state/'RELEASE_750474_INTENT.json').open('x') as out:
    json.dump(dict(job_id=job,release_sha256=sys.argv[1],command=['scontrol','release',job],before=before),out)
    out.flush();os.fsync(out.fileno())
command('release_once',['/usr/bin/scontrol','release',job])
result=dict(status='RELEASE_COMMAND_ACCEPTED',job_id=job,release_sha256=sys.argv[1],release_invocations=1)
with (state/'RELEASE_750474_RESULT.json').open('x') as out:json.dump(result,out)
print(json.dumps(result),flush=True)
command('after',['/usr/bin/scontrol','show','job','-dd',job])
command('queue',['/usr/bin/squeue','-h','-j',job,'-o','%i|%T|%r|%b|%N'])
'''

def main():
    if not SOCKET.is_socket() or SOCKET.is_symlink():raise ValueError('MASTER_REQUIRED_NO_RECONNECT')
    auth=json.loads((HERE.parent/'docs/superpowers/evidence/e1-contract-signoff-20260927/RELEASE_750474.json').read_text())
    if auth['job_id']!='750474' or auth['release_authorized'] is not True:raise ValueError('AUTHORIZATION')
    evidence=HERE/'release_e1_20260927_v3/release-750474';evidence.mkdir(mode=0o700,exist_ok=False)
    (evidence/'LOCAL_INTENT.json').write_text(json.dumps(auth,indent=2)+'\n')
    result=dict(status='UNKNOWN_INSPECT_NO_RETRY',job_id='750474',retry_attempted=False)
    try:
        cmd=shlex.join([REMOTE_PY,'-I','-B','-c',REMOTE,RELEASE_SHA,ENTRY_SHA])
        with (evidence/'remote.jsonl').open('xb') as out,(evidence/'remote.stderr').open('xb') as err:
            p=subprocess.run(SSH+[cmd],stdout=out,stderr=err,timeout=240)
        raw=(evidence/'remote.jsonl').read_text();print(raw,end='')
        rows=[json.loads(l) for l in raw.splitlines() if l.strip()]
        if any(r.get('status')=='RELEASE_COMMAND_ACCEPTED' for r in rows):result['status']='RELEASE_COMMAND_ACCEPTED'
        if p.returncode:raise ValueError('REMOTE_NONZERO_INSPECT_NO_RETRY')
        result['readback_collected']=True
    except BaseException as e:
        result.update(error_type=type(e).__name__,error=str(e));raise
    finally:
        result['recorded_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        (evidence/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
        print('EVIDENCE='+str(evidence),flush=True)

if __name__=='__main__':main()

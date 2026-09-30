"""One authorized held invocation plus read-only receipt/resources/spool collection."""
import datetime
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
from check_e1_v3_handoff import check,HERE,RELEASE_SHA,ENTRY_SHA
from publish_e1_v3 import SSH,SOCKET,REMOTE_PY

SUBMIT_SHA='f16f1d2c6a922c60a4daad253df071cf643e4d099e305751c9e37ef2f58b796a'
REMOTE=r'''
import hashlib,json,pathlib,subprocess,sys
root=pathlib.Path('/home/s2510040/audattn_e1/e1_20260927_v3')
package=root/'package'
for name,sha in [('RELEASE.json',sys.argv[1]),('e1_entry.py',sys.argv[2]),('submit_e1_once.py',sys.argv[3])]:
    p=package/name
    if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:
        raise ValueError('EXTERNAL_HASH:'+name)
# Exactly one invocation; the pinned helper owns preflight, no-retry state, test-only and held submission.
p=subprocess.run([sys.executable,'-I','-B',str(package/'submit_e1_once.py'),
    '--release-sha256',sys.argv[1],'--confirm-action','SUBMIT_E1_HELD_ONCE_3_GPU_HOURS'],capture_output=True,text=True,timeout=210)
print(json.dumps(dict(stage='submit',returncode=p.returncode,stdout=p.stdout,stderr=p.stderr)),flush=True)
if p.returncode: raise SystemExit(p.returncode)
r=json.loads((root/'state/SUBMISSION.json').read_text())
job=r['job_id']
if not job.isdigit() or r['release_sha256']!=sys.argv[1]:raise ValueError('RECEIPT')
print(json.dumps(dict(stage='receipt',receipt=r)),flush=True)
for name in ('INTENT.json','SUBMISSION_RESPONSE.json','SUBMISSION.json','QUEUE.json','TEST_ONLY.json'):
    raw=(root/'state'/name).read_bytes()
    print(json.dumps(dict(stage='journal',file=name,sha256=hashlib.sha256(raw).hexdigest(),size=len(raw),record=json.loads(raw))),flush=True)
commands=[('scontrol',['/usr/bin/scontrol','show','job','-dd',job]),
          ('squeue',['/usr/bin/squeue','-h','-j',job,'-o','%i|%T|%r|%P|%b']),
          ('sacct',['/usr/bin/sacct','-j',job,'-X','-P','--format=JobIDRaw,State,ExitCode,Elapsed,ReqTRES,Timelimit']),
          ('spool',['/usr/bin/scontrol','write','batch_script',job,'-'])]
for name,argv in commands:
    q=subprocess.run(argv,capture_output=True,timeout=30)
    rec=dict(stage=name,returncode=q.returncode,stdout=q.stdout.decode(errors='replace'),stderr=q.stderr.decode(errors='replace'))
    if name=='spool':
        rec.update(sha256=hashlib.sha256(q.stdout).hexdigest(),matches_runner=q.stdout==(package/'run_e1.sbatch').read_bytes())
    print(json.dumps(rec),flush=True)
'''

def main():
    check()
    a=json.loads((HERE.parent/'docs/superpowers/evidence/e1-contract-signoff-20260927/GPU_HELD_AUTHORIZATION.json').read_text())
    if a['release_sha256']!=RELEASE_SHA or a['single_held_submission_authorized'] is not True or a['release_authorized']:
        raise ValueError('AUTHORIZATION_SCOPE')
    if not SOCKET.is_socket() or SOCKET.is_symlink():raise ValueError('MASTER_ABSENT')
    root=HERE/'release_e1_20260927_v3'
    evidence=root/'held-submission-20260927'
    evidence.mkdir(mode=0o700,exist_ok=False)
    with (evidence/'LOCAL_INTENT.json').open('x') as f:
        json.dump(dict(release_sha256=RELEASE_SHA,scope='ONE_HELD_INVOCATION_NO_RETRY_NO_RELEASE',
                       recorded_utc=datetime.datetime.now(datetime.timezone.utc).isoformat()),f,indent=2)
    result=dict(status='SUBMISSION_UNKNOWN_INSPECT_NO_RETRY',release_sha256=RELEASE_SHA,
                release_attempted=False,gres_edit_attempted=False,retry_attempted=False)
    try:
        master=subprocess.run(['/usr/bin/ssh','-S',str(SOCKET),'-O','check','s2510040@hakusan1'],capture_output=True,timeout=10)
        (evidence/'master.log').write_bytes(master.stdout+master.stderr)
        if master.returncode:raise ValueError('MASTER_UNAVAILABLE_NO_RECONNECT')
        cmd=shlex.join([REMOTE_PY,'-I','-B','-c',REMOTE,RELEASE_SHA,ENTRY_SHA,SUBMIT_SHA])
        with (evidence/'remote.jsonl').open('xb') as out,(evidence/'remote.stderr').open('xb') as err:
            p=subprocess.run(SSH+[cmd],stdout=out,stderr=err,timeout=360)
        result['transport_returncode']=p.returncode
        rows=[json.loads(l) for l in (evidence/'remote.jsonl').read_text().splitlines() if l.strip()]
        receipts=[r['receipt'] for r in rows if r['stage']=='receipt']
        if receipts:
            result.update(job_id=receipts[0]['job_id'],status='HELD_SUBMISSION_RECEIPT_RECORDED_MANUAL_REVIEW_REQUIRED')
        if p.returncode:raise ValueError('REMOTE_NONZERO_INSPECT_NO_RETRY')
        if not receipts:raise ValueError('MISSING_RECEIPT_INSPECT_NO_RETRY')
        for row in rows:
            if row['stage'] in ('receipt','scontrol','squeue','sacct','spool'):print(json.dumps(row),flush=True)
    except BaseException as e:
        result.update(error_type=type(e).__name__,error=str(e));raise
    finally:
        (evidence/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
        print('EVIDENCE='+str(evidence),flush=True)

if __name__=='__main__':main()

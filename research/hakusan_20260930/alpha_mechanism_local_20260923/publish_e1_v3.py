"""Authorized publication only; reuse SSH master, no authentication/retry/GPU submission."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile
import datetime
import sys
from check_e1_v3_handoff import check,RELEASE_SHA,ENTRY_SHA,HERE

SOCKET=HERE.parent/'.hakusan-control/master.sock'
SSH=['/usr/bin/ssh','-S',str(SOCKET),'-o','ControlMaster=no','-o','BatchMode=yes',
     '-o','ProxyCommand=false','s2510040@hakusan1']
REMOTE_PY='/home/s2510040/miniconda3/envs/attn/bin/python'
REMOTE_ROOT='/home/s2510040/audattn_e1/e1_20260927_v3'

PUBLISH=r'''
import hashlib,io,json,os,pathlib,pwd,stat,subprocess,sys,tarfile
root=pathlib.Path('/home/s2510040/audattn_e1/e1_20260927_v3')
base=root.parent
if pwd.getpwuid(os.getuid()).pw_name!='s2510040': raise ValueError('REMOTE_ACCOUNT')
for p in (base.parent,*base.parent.parents):
    if p.is_symlink() or not p.is_dir(): raise ValueError('ANCESTOR_DIRECTORY')
if os.path.lexists(root): raise ValueError('TARGET_EXISTS_NO_OVERWRITE')
if os.path.lexists(base) and (base.is_symlink() or not base.is_dir() or base.stat().st_uid!=os.getuid()):
    raise ValueError('BASE_DIRECTORY')
q=subprocess.run(['/usr/bin/squeue','-h','-u','s2510040','-o','%i|%j|%T'],capture_output=True,text=True,timeout=30)
print('QUEUE='+q.stdout,flush=True)
if q.returncode or any('audattn' in s for s in q.stdout.splitlines()): raise ValueError('QUEUE_NOT_CLEAR')
# Validate complete transport before writing any remote file.
blob=sys.stdin.buffer.read(32*1024*1024+1)
if len(blob)>32*1024*1024: raise ValueError('TRANSPORT_SIZE')
items={}
with tarfile.open(fileobj=io.BytesIO(blob),mode='r:') as t:
    for member in t.getmembers():
        if not member.isfile() or pathlib.PurePosixPath(member.name).name!=member.name or member.name in items:
            raise ValueError('TRANSPORT_MEMBER')
        if member.size>16*1024*1024: raise ValueError('MEMBER_SIZE')
        items[member.name]=t.extractfile(member).read()
sha=lambda b:hashlib.sha256(b).hexdigest()
if sha(items['RELEASE.json'])!=sys.argv[1] or sha(items['e1_entry.py'])!=sys.argv[2]: raise ValueError('EXTERNAL_HASH')
r=json.loads(items['RELEASE.json'])
if set(items)!=set(r['files'])|{'RELEASE.json'}: raise ValueError('INVENTORY')
for name,row in r['files'].items():
    if {'size':len(items[name]),'sha256':sha(items[name])}!=row: raise ValueError('FILE_HASH:'+name)
os.umask(0o077)
if not base.exists(): base.mkdir(mode=0o700)
root.mkdir(mode=0o700)
stage=root/'.upload-staging';stage.mkdir(mode=0o700)
for name,data in items.items():
    with (stage/name).open('xb') as f:f.write(data)
for name,data in items.items():
    if (stage/name).read_bytes()!=data: raise ValueError('DISK_VERIFY')
os.rename(stage,root/'package')
print(json.dumps(dict(status='E1_V3_FILES_PUBLISHED',root=str(root),files=len(items),release_sha256=sys.argv[1],jobs_submitted=0)),flush=True)
'''

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execute-authorized-publication',action='store_true',required=True)
    ap.parse_args()
    report=check()
    signoff=json.loads((HERE.parent/'docs/superpowers/evidence/e1-contract-signoff-20260927/SIGNOFF.json').read_text())
    if signoff['release_sha256']!=RELEASE_SHA or signoff['remote_publication_authorized'] is not True:
        raise ValueError('PUBLICATION_NOT_AUTHORIZED')
    if SOCKET.is_symlink() or not SOCKET.is_socket(): raise ValueError('SSH_MASTER_ABSENT_USER_RECONNECT_REQUIRED')
    evidence=Path(tempfile.mkdtemp(prefix='publish-',dir=HERE/'release_e1_20260927_v3'))
    steps=[]
    def run(name,argv,data=None,seconds=180):
        try:
            p=subprocess.run(argv,input=data,capture_output=True,timeout=seconds)
        except subprocess.TimeoutExpired as e:
            (evidence/(name+'.stdout')).write_bytes(e.stdout or b'')
            (evidence/(name+'.stderr')).write_bytes(e.stderr or b'')
            steps.append(dict(name=name,status='TIMEOUT_REMOTE_STATE_MUST_BE_INSPECTED_NO_RETRY'))
            raise
        (evidence/(name+'.stdout')).write_bytes(p.stdout)
        (evidence/(name+'.stderr')).write_bytes(p.stderr)
        steps.append(dict(name=name,returncode=p.returncode))
        print(p.stdout.decode(errors='replace'),end='',flush=True)
        if p.returncode: raise ValueError(name+' FAILED: '+p.stderr.decode(errors='replace'))
        return p.stdout
    result=dict(release_sha256=RELEASE_SHA,evidence=str(evidence),steps=steps,jobs_submitted=0,
                checkpoint_loaded=False,automatic_retry=False,automatic_reconnect=False)
    try:
        run('master', ['/usr/bin/ssh','-S',str(SOCKET),'-O','check','s2510040@hakusan1'],seconds=10)
        (evidence/'LOCAL_CHECK.json').write_text(json.dumps(report,indent=2)+'\n')
        buf=io.BytesIO();package=HERE/'release_e1_20260927_v3/package_ready'
        with tarfile.open(fileobj=buf,mode='w:') as t:
            for p in sorted(package.iterdir()):
                if p.is_symlink() or not p.is_file(): raise ValueError('LOCAL_FILE')
                data=p.read_bytes();m=tarfile.TarInfo(p.name);m.size=len(data);m.mode=0o600
                t.addfile(m,io.BytesIO(data))
        cmd=shlex.join([REMOTE_PY,'-I','-B','-c',PUBLISH,RELEASE_SHA,ENTRY_SHA])
        run('publish',SSH+[cmd],buf.getvalue())
        entry=REMOTE_ROOT+'/package/e1_entry.py'
        for mode in ('check','source-check','check'):
            name=mode if mode!='check' or not any(s['name']=='check' for s in steps) else 'post-check'
            raw=run(name,SSH+[shlex.join([REMOTE_PY,'-I','-B',entry,mode,RELEASE_SHA])],seconds=240)
            # source imports may print diagnostic lines; require the final structured record.
            row=json.loads(raw.decode().strip().splitlines()[-1])
            expected='NATIVE_SOURCE_ONLY_IMPORT_PASS' if mode=='source-check' else 'E1_PACKAGE_BYTES_AND_INPUTS_PASS'
            if row['status']!=expected: raise ValueError('REMOTE_STATUS')
            if mode=='source-check' and (row['checkpoint_loaded'] or row['cuda_initialized'] or row['jobs_submitted']):
                raise ValueError('SOURCE_SCOPE_VIOLATION')
        result['status']='E1_V3_PUBLISHED_AND_NATIVE_SOURCE_CHECK_PASS_NO_GPU_JOB'
    except BaseException as e:
        result.update(status='STOPPED_INSPECT_EVIDENCE_NO_RETRY',error_type=type(e).__name__,error=str(e))
        raise
    finally:
        result['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        (evidence/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
        print('EVIDENCE='+str(evidence),flush=True)

if __name__=='__main__':main()

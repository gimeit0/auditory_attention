"""Read-only one-shot SSH audio audit. Local evidence only; no retry/submission."""
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
from select_e1 import HERE,BANK,BANK_SHA,ROLES,checked,require
from check_e1_clean_audio import CANDIDATE_SHA,ANCHOR_SHA,anchor_check

LOCAL=Path('/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en/clips')
REMOTE='/home/s2510040/selective_listening_repro/code/auditory_attention/cv_train/clips'
SOCKET='/Users/gigi/发表/超算/.hakusan-control/master.sock'
REMOTE_CODE=r'''
import hashlib,json,os,stat,sys,time
from pathlib import Path
root=Path('/home/s2510040/selective_listening_repro/code/auditory_attention/cv_train/clips')
request=json.load(sys.stdin)
assert 0<len(request['files'])<=15000
begin=time.monotonic(); results=[]
for row in request['files']:
    assert time.monotonic()-begin<240
    name=row['name']; assert Path(name).name==name and name not in ('','.','..')
    p=root/name
    try:
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as f:
            a=os.fstat(f.fileno()); assert stat.S_ISREG(a.st_mode) and 0<a.st_size<=10485760
            raw=f.read(10485761); b=os.fstat(f.fileno())
            assert (a.st_size,a.st_mtime_ns,a.st_ino)==(b.st_size,b.st_mtime_ns,b.st_ino)
        digest=hashlib.sha256(raw).hexdigest()
        results.append(dict(name=name,size=len(raw),sha256=digest,match=len(raw)==row['size'] and digest==row['sha256']))
    except Exception as e:
        results.append(dict(name=name,match=False,error=type(e).__name__+': '+str(e)))
print(json.dumps(dict(candidate_sha256=request['candidate_sha256'],root=str(root),files=results,
    status='REMOTE_AUDIO_BYTES_PASS' if all(x['match'] for x in results) else 'REMOTE_AUDIO_BYTES_FAIL',
    elapsed_seconds=time.monotonic()-begin,jobs_submitted=0,remote_files_written=False)))
'''

def local_inventory():
    candidate=json.loads(checked(HERE/'E1_CANDIDATE_2000_20260926.json',CANDIDATE_SHA))
    bank={int(r['trial_id']):r for r in csv.DictReader(io.StringIO(checked(BANK,BANK_SHA).decode()),delimiter='\t')}
    anchors=list(csv.DictReader(io.StringIO(gzip.decompress(checked(HERE/'E1_REMOTE_VALIDATION_ANCHORS_20260926.tsv.gz',ANCHOR_SHA)).decode()),delimiter='\t'))
    names=set(); count=0
    for tid in candidate['trial_ids']:
        row=bank[tid]
        # Conservative superset: includes stored probe cue even on noncontrol mixed.
        for role in ROLES:
            if row[role+'_path']:
                anchor_check(row,role,anchors); count+=1
                names.add(row[role+'_path'])
    files=[]
    for name in sorted(names):
        require(Path(name).name==name,'UNSAFE_PATH')
        p=LOCAL/name
        require(p.is_file() and not p.is_symlink(),'LOCAL_CLIP_MISSING_OR_SYMLINK')
        a=p.stat(); require(0<a.st_size<=10485760,'CLIP_SIZE')
        raw=p.read_bytes(); b=p.stat()
        require((a.st_size,a.st_mtime_ns,a.st_ino)==(b.st_size,b.st_mtime_ns,b.st_ino),'CLIP_CHANGED')
        files.append(dict(name=name,size=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
    # Preserve byte identity of prior clean decode evidence.
    clean=json.loads((HERE/'E1_CLEAN_DECODE_20260926.json').read_text())
    require(clean['candidate_sha256']==CANDIDATE_SHA,'CLEAN_BINDING')
    byname={r['name']:r for r in files}
    require(all(byname[n]['sha256']==v['sha256'] for n,v in clean['clips'].items()),'CLEAN_BYTES_CHANGED')
    return dict(candidate_sha256=CANDIDATE_SHA,bank_sha256=BANK_SHA,anchor_sha256=ANCHOR_SHA,
                anchor_role_checks=count,files=files,total_bytes=sum(r['size'] for r in files))

def main():
    out=Path(sys.argv[1]); out.mkdir(mode=0o700,exist_ok=False)
    request=local_inventory()
    def save(name,value):
        with (out/name).open('x') as f: json.dump(value,f,sort_keys=True,indent=2)
    save('LOCAL_INVENTORY.json',request)
    print(json.dumps(dict(stage='LOCAL_INVENTORY_PASS',files=len(request['files']),bytes=request['total_bytes'],anchor_role_checks=request['anchor_role_checks'])),flush=True)
    argv=['/usr/bin/ssh','-S',SOCKET,'-o','BatchMode=yes','-o','ProxyCommand=false','-o','ConnectTimeout=12',
          's2510040@hakusan1', '/home/s2510040/miniconda3/envs/attn/bin/python -I -B -c '+shlex.quote(REMOTE_CODE)]
    save('REQUEST.json',dict(argv=argv,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),automatic_retry=False))
    result=subprocess.run(argv,input=json.dumps(request),text=True,capture_output=True,timeout=270)
    save('TRANSPORT.json',dict(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
    require(result.returncode==0,'SSH_FAILED_NO_RETRY')
    response=json.loads(result.stdout)
    save('REMOTE_INVENTORY.json',response)
    require(response['candidate_sha256']==CANDIDATE_SHA,'RESPONSE_BINDING')
    require([{k:r[k] for k in ('name','size','sha256')} for r in response['files']]==request['files'],'REMOTE_BYTES_DIFFER')
    require(response['status']=='REMOTE_AUDIO_BYTES_PASS','REMOTE_FAIL')
    save('VERIFIED.json',dict(status='E1_ALL_SELECTED_AUDIO_BYTES_VERIFIED',files=len(request['files']),
         candidate_sha256=CANDIDATE_SHA,remote_files_written=False,jobs_submitted=0))
    print('E1_ALL_SELECTED_AUDIO_BYTES_VERIFIED',flush=True)

if __name__=='__main__': main()

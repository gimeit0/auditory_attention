"""One bounded read-only CPU probe; no model, GPU, remote source files or retries."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
from select_e1 import HERE,checked,require
from check_e1_clean_audio import CANDIDATE_SHA

FREEZE_SHA='6c4df571e897a2c13aa6c693a86783c83ac8620b1f24b7f932ddbe6d93ab62fe'
CODE=r'''
import ast,__future__,hashlib,json,sys,types,platform,time
from pathlib import Path
from collections import OrderedDict
started=time.monotonic()
request=json.load(sys.stdin)
import numpy as np
import pandas as pd
import soundfile as sf
import torch
import torchaudio
assert platform.python_version()=='3.11.5' and torch.__version__=='2.1.1+cu118'
torch.set_num_threads(1); torch.set_num_interop_threads(1)
assert not torch.cuda.is_initialized()
root=Path('/home/s2510040/selective_listening_repro/code/auditory_attention/selftrain/experiments/runs/fullpilot4_accum9_20260815_181000/snapshot/files')
clips=Path('/home/s2510040/selective_listening_repro/code/auditory_attention/cv_train/clips')
def extract(rel,digest,names,env):
    path=root/rel; assert path.is_file() and not path.is_symlink()
    raw=path.read_bytes(); assert hashlib.sha256(raw).hexdigest()==digest
    tree=ast.parse(raw)
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    assert {n.name for n in nodes}==set(names)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec',flags=__future__.annotations.compiler_flag),env)
    return env
env=dict(np=np,torch=torch,torchaudio=torchaudio,sf=sf,OrderedDict=OrderedDict,
         SAMPLE_RATE=44100,CROP_SAMPLES=110250,HALF_CROP=55125)
env=extract('selftrain/data/diotic_attention.py','26b5cf965aec1652f2d77be517f867bb284a2f53c2f53706b2c5aa2cc0ad9e8a',
            ['WaveformCache','crop_centered','sum_equal_rms','rms'],env)
m=types.ModuleType('selftrain.data.diotic_attention')
for key in ('CROP_SAMPLES','crop_centered','sum_equal_rms'): setattr(m,key,env[key])
sys.modules[m.__name__]=m
native=extract('selftrain/scripts/eval_full_pilot.py','29414207e3fac53ff8805e61fcf4cee48fb155c4c60d0e736e35526c80dfae5b',
               ['_role_batch','_raw_scene_batch','_correct_cue_batch'],dict(np=np))
source=request['clean_source']; assert hashlib.sha256(source.encode()).hexdigest()==request['clean_source_sha256']
adapter={}; exec(compile(source,'<verified_e1_clean_input>','exec'),adapter)
def audio_hashes():
    for record in request['clips']:
        assert Path(record['name']).name==record['name']
        p=clips/record['name']; assert not p.is_symlink() and p.is_file()
        a=p.stat(); assert a.st_size==record['size'] and 0<a.st_size<=10485760
        raw=p.read_bytes(); b=p.stat()
        assert (a.st_size,a.st_mtime_ns,a.st_ino)==(b.st_size,b.st_mtime_ns,b.st_ino)
        assert hashlib.sha256(raw).hexdigest()==record['sha256']
audio_hashes()
frame=pd.DataFrame(request['rows'])
for k in ('trial_id','target_label'): frame[k]=frame[k].astype(int)
frame['scene_kind']='clean'; frame['distractor_count']=0; frame['control_subset']=0
assert len(frame)==200 and frame.trial_id.is_unique
cache=env['WaveformCache'](max_items=128)
provider=adapter['CleanBatchProvider'](frame,request['batches'],cache,clips,
             raw_scene_batch=native['_raw_scene_batch'],role_batch=native['_role_batch'])
byid=frame.set_index('trial_id',drop=False)
reports=[]
def digest(t): return hashlib.sha256(t.contiguous().numpy().tobytes()).hexdigest()
for i,ids in enumerate(request['batches']):
    pair=provider(i,ids)
    s,c,l=pair['target_only_correct_cue']; z,zero,zl=pair['target_only_zero_cue']
    original=native['_raw_scene_batch'](byid.loc[ids],cache,clips)
    oldcue=native['_correct_cue_batch'](byid.loc[ids],cache,clips)
    expected=native['_role_batch'](byid.loc[ids],'correct_cue',cache,clips)
    assert digest(s)==digest(z)==digest(original)
    assert digest(c)==digest(expected) and digest(zero)==digest(oldcue)
    assert torch.equal(l,zl) and l.tolist()==byid.loc[ids].target_label.tolist()
    assert torch.any((c!=0).reshape(len(ids),-1),dim=1).all() and not torch.any(zero)
    reports.append(dict(batch=i,trial_ids=ids,scene_sha256=digest(s),correct_cue_sha256=digest(c),
                        zero_cue_sha256=digest(zero),shape=list(s.shape),status='PAIRED_INPUT_BITS_PASS'))
assert [len(r['trial_ids']) for r in reports]==[16]*12+[8]
audio_hashes()
assert not torch.cuda.is_initialized()
print(json.dumps(dict(status='E1_NATIVE_CLEAN_REAL_AUDIO_INPUT_PASS',freeze_sha256=request['freeze_sha256'],
      clean_source_sha256=request['clean_source_sha256'],candidate_sha256=request['candidate_sha256'],
      python=platform.python_version(),torch=torch.__version__,threads=torch.get_num_threads(),
      trials=200,clips=len(request['clips']),batches=reports,elapsed_seconds=time.monotonic()-started,
      cuda_initialized=False,checkpoint_loaded=False,jobs_submitted=0,remote_files_written=False,
      scope='pinned native function bodies plus real audio; NOT full production importer/worker or model acceptance')))
'''

def main():
    out=Path(sys.argv[1]); out.mkdir(mode=0o700,exist_ok=False)
    freeze=json.loads(checked(HERE/'E1_DATA_FREEZE_20260926_v1.json',FREEZE_SHA))
    candidate=json.loads(checked(HERE/'E1_CANDIDATE_2000_20260926.json',CANDIDATE_SHA))
    source_path=HERE/'e1_clean_input_v2.py'
    record={'sha256':'1bd244b5c71aeed62c14a0da6c2f4b981c5201ccf7953b6d445225ca58231e7b'}
    source=checked(source_path,record['sha256']).decode()
    names={r[role+'_path'] for r in candidate['clean_sources'] for role in ('target','correct_cue')}
    payload=dict(freeze_sha256=FREEZE_SHA,candidate_sha256=CANDIDATE_SHA,clean_source=source,
                 clean_source_sha256=record['sha256'],rows=candidate['clean_sources'],batches=candidate['clean_batches'],
                 clips=[r for r in freeze['audio_files'] if r['name'] in names])
    require(len(payload['clips'])==309,'CLIPS')
    remote='/usr/bin/env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 /usr/bin/timeout --signal=TERM --kill-after=5s 90s /home/s2510040/miniconda3/envs/attn/bin/python -I -B -c '+shlex.quote(CODE)
    argv=['/usr/bin/ssh','-S','/Users/gigi/发表/超算/.hakusan-control/master.sock','-o','BatchMode=yes',
          '-o','ProxyCommand=false','-o','ConnectTimeout=12','s2510040@hakusan1',remote]
    def save(n,value):
        with (out/n).open('x') as f: json.dump(value,f,sort_keys=True,indent=2)
    save('INTENT.json',dict(adapter_version='v2',parent_data_freeze_sha256=FREEZE_SHA,clean_source_sha256=record['sha256'],argv=argv,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                           payload_sha256=hashlib.sha256(json.dumps(payload).encode()).hexdigest(),retry=False))
    try: result=subprocess.run(argv,input=json.dumps(payload),text=True,capture_output=True,timeout=110)
    except BaseException as e:
        save('TRANSPORT_FAILED.json',dict(error=repr(e),retry=False)); raise
    save('TRANSPORT.json',dict(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
    require(result.returncode==0,'NATIVE_PROBE_FAILED_NO_RETRY')
    report=json.loads(result.stdout)
    require(report['status']=='E1_NATIVE_CLEAN_REAL_AUDIO_INPUT_PASS' and report['freeze_sha256']==FREEZE_SHA
            and report['clean_source_sha256']==record['sha256'] and report['candidate_sha256']==CANDIDATE_SHA,'RECEIPT')
    require([r['trial_ids'] for r in report['batches']]==candidate['clean_batches'],'BATCH_RECEIPT')
    require(report['trials']==200 and report['clips']==309 and report['threads']==1,'SCOPE_COUNTS')
    require(report['cuda_initialized'] is False and report['checkpoint_loaded'] is False and report['jobs_submitted']==0 and report['remote_files_written'] is False,'SCOPE_FLAGS')
    require(all(r['status']=='PAIRED_INPUT_BITS_PASS' and r['shape']==[len(r['trial_ids']),2,110250] for r in report['batches']),'BATCH_SHAPES')
    save('VERIFIED.json',report)
    print(json.dumps({k:report[k] for k in ('status','trials','clips','elapsed_seconds','checkpoint_loaded','jobs_submitted')}))

if __name__=='__main__': main()

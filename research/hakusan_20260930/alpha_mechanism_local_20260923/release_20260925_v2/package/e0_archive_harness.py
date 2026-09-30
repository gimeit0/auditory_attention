"""Synthetic-only E0 archive rehearsal, NOT a production model coordinator.

A/B are logical test labels in one worker, not independent model processes.
The parent enforces a worker deadline and verifies artifacts before completion.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
from e0_layout_reference import canonical, condition_ids, validate_logits, require, CONDITIONS

HERE=Path(__file__).resolve().parent
LAYOUT_SHA='f28160c857512c90533837d7a4f54a761a6deef6d6cf86aafadecd34138f7e90'
SCOPE='SYNTHETIC_ARCHIVE_ONLY'

def layout():
    raw=(HERE/'E0_LAYOUT_96.json').read_bytes()
    require(hashlib.sha256(raw).hexdigest()==LAYOUT_SHA,'LAYOUT_SHA')
    return json.loads(raw)

def schedule(spec):
    return [(p,n) for p in spec['processes'] for n in
            spec['passes']+(['alpha_05_observed'] if p=='A' else [])]

def write_json(path,value):
    with path.open('xb') as f:
        f.write(canonical(value))
        f.flush()
        os.fsync(f.fileno())

def identity(path):
    require(path.is_file() and not path.is_symlink(),'INVALID_ARTIFACT')
    return dict(size=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())

def synthetic_logits(ids,name,condition):
    # Deterministic fixture intentionally satisfies endpoints; no scientific output.
    family=('original' if name=='alpha_1' else 'explicit_bypass' if name=='alpha_0'
            else 'alpha_05' if name=='alpha_05_observed' else name)
    condition_code=0 if family=='explicit_bypass' else CONDITIONS.index(condition)
    offset=sum(family.encode())%17+condition_code
    classes=np.arange(800,dtype=np.float32)[None,:]
    trials=np.array(ids,dtype=np.float32)[:,None]
    return ((classes+trials+offset)%31/16).astype(np.float32)

def nll_from(logits,labels):
    x=logits.astype(np.float64)
    m=x.max(1)
    return (m+np.log(np.exp(x-m[:,None]).sum(1))-x[np.arange(len(labels)),labels]).astype(np.float32)

def worker(root,fault):
    spec=layout()
    rows=[]
    if fault=='hang': time.sleep(5)
    for index,(process,name) in enumerate(schedule(spec)):
        if fault=='worker_error' and index==2: raise RuntimeError('INJECTED_WORKER_ERROR')
        arrays={}
        for c in CONDITIONS:
            ids=condition_ids(spec,c)
            labels=np.array([spec['target_labels'][str(i)] for i in ids],dtype=np.int64)
            logits=synthetic_logits(ids,name,c)
            if fault=='endpoint' and process=='B' and name=='alpha_1': logits[0,0]+=1
            arrays[c+'_ids']=np.array(ids,dtype=np.int64)
            arrays[c+'_logits']=logits
            arrays[c+'_nll']=nll_from(logits,labels)
        filename=f'{index:02d}_{process}_{name}.npz'
        with (root/filename).open('xb') as f: np.savez(f,**arrays)
        rows.append(dict(process=process,pass_name=name,file=filename,**identity(root/filename)))
    write_json(root/'MANIFEST.json',dict(scope=SCOPE,layout_sha256=LAYOUT_SHA,
               worker_pid=os.getpid(),logical_processes_not_cold_repeats=True,passes=rows))

def verify(root):
    root=Path(root)
    require(not (root/'FAILED.json').exists(),'FAILED_ATTEMPT')
    require(all(p.is_file() and not p.is_symlink() for p in root.iterdir()),'INVALID_ARTIFACT')
    require(sum(p.stat().st_size for p in root.iterdir())<=128*1024**2,'ARCHIVE_BUDGET')
    spec=layout()
    require(not (root/'MANIFEST.json').is_symlink(),'MANIFEST_SYMLINK')
    m=json.loads((root/'MANIFEST.json').read_text())
    require(m['scope']==SCOPE and m['layout_sha256']==LAYOUT_SHA
            and m['logical_processes_not_cold_repeats'] is True,'SCOPE')
    expected=schedule(spec)
    require(len(m['passes'])==len(expected)==21,'PASS_COUNT')
    wanted={'MANIFEST.json','worker.stdout','worker.stderr'}
    saved={}
    saved_nll={}
    predictions=0
    max_nll=0.
    for index,((process,name),row) in enumerate(zip(expected,m['passes'])):
        filename=f'{index:02d}_{process}_{name}.npz'
        require(row['process']==process and row['pass_name']==name and row['file']==filename,'PASS_IDENTITY')
        wanted.add(filename)
        path=root/filename
        require(identity(path)=={'size':row['size'],'sha256':row['sha256']},'ARTIFACT_SHA')
        with np.load(path,allow_pickle=False) as z:
            require(set(z.files)=={c+s for c in CONDITIONS for s in ('_ids','_logits','_nll')},'ARRAY_KEYS')
            for c in CONDITIONS:
                ids=condition_ids(spec,c)
                require(z[c+'_ids'].dtype==np.int64 and z[c+'_ids'].tolist()==ids,'TRIAL_ORDER')
                labels=np.array([spec['target_labels'][str(i)] for i in ids])
                logits=z[c+'_logits']
                max_nll=max(max_nll,validate_logits(logits,ids,labels,z[c+'_nll']))
                saved[(process,name,c)]=logits.copy()
                saved_nll[(process,name,c)]=z[c+'_nll'].copy()
                predictions+=len(ids)
    for process in ('A','B'):
        for c in CONDITIONS:
            for left,right in (('original','alpha_1'),('explicit_bypass','alpha_0')):
                require(saved[process,left,c].tobytes()==saved[process,right,c].tobytes(),'ENDPOINT_BITS')
                require(saved_nll[process,left,c].tobytes()==saved_nll[process,right,c].tobytes(),'ENDPOINT_NLL_BITS')
        # Controls are first four full 16-trial batches, same shape as correct rows.
        for c in CONDITIONS[1:]:
            require(saved[process,'alpha_0','correct'][:64].tobytes()==saved[process,'alpha_0',c].tobytes(),'CUE_INDEPENDENCE')
    for name in spec['passes']:
        for c in CONDITIONS:
            require(saved['A',name,c].tobytes()==saved['B',name,c].tobytes(),'REPEAT_BITS')
            require(saved_nll['A',name,c].tobytes()==saved_nll['B',name,c].tobytes(),'REPEAT_NLL_BITS')
    for c in CONDITIONS:
        require(saved['A','alpha_05',c].tobytes()==saved['A','alpha_05_observed',c].tobytes(),'OBSERVER_BITS')
        require(saved_nll['A','alpha_05',c].tobytes()==saved_nll['A','alpha_05_observed',c].tobytes(),'OBSERVER_NLL_BITS')
    require(predictions==6048,'PREDICTIONS')
    complete=root/'SYNTHETIC_COMPLETE.json'
    if complete.exists(): wanted.add(complete.name)
    require({p.name for p in root.iterdir()}==wanted,'UNEXPECTED_OR_MISSING_FILE')
    require(sum(p.stat().st_size for p in root.iterdir())<=128*1024**2,'ARCHIVE_BUDGET')
    result=dict(status='SYNTHETIC_ARCHIVE_VERIFIED',scope=SCOPE,passes=21,predictions=predictions,
                manifest_sha256=identity(root/'MANIFEST.json')['sha256'],cpu_nll_max_abs=max_nll,
                production_gates_passed=False,checkpoint_loaded=False,jobs_submitted=0)
    if complete.exists():
        require(not complete.is_symlink() and json.loads(complete.read_text())==result,'COMPLETE_MISMATCH')
    return result

def run(root,timeout_seconds=60,fault='none'):
    require(fault in ('none','hang','worker_error','endpoint'),'FAULT')
    require(type(timeout_seconds) in (int,float) and 0<timeout_seconds<=60,'TIMEOUT_BUDGET')
    root=Path(root)
    root.mkdir(mode=0o700,exist_ok=False)  # never overwrite/retry the same attempt
    started=time.monotonic()
    try:
        with (root/'worker.stdout').open('xb') as out,(root/'worker.stderr').open('xb') as err:
            process=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'worker',str(root),fault],stdout=out,stderr=err)
            try: rc=process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise TimeoutError('SYNTHETIC_WORKER_DEADLINE') from None
            except BaseException:
                process.kill()
                process.wait()
                raise
        require(rc==0,'WORKER_NONZERO')
        require(time.monotonic()-started<timeout_seconds,'SYNTHETIC_DEADLINE')
        result=verify(root)
        require(time.monotonic()-started<timeout_seconds,'SYNTHETIC_DEADLINE')
        write_json(root/'SYNTHETIC_COMPLETE.json',result)
        return result
    except BaseException as error:
        write_json(root/'FAILED.json',dict(scope=SCOPE,status='SYNTHETIC_FAILED',
                   error_type=type(error).__name__,error=str(error),elapsed_seconds=time.monotonic()-started,
                   preserved_files=sorted(p.name for p in root.iterdir()),retry_attempted=False))
        raise

if __name__=='__main__':
    require(len(sys.argv)==4 and sys.argv[1]=='worker','SYNTHETIC_WORKER_ONLY')
    worker(Path(sys.argv[2]),sys.argv[3])

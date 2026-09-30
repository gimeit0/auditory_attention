"""Explicit small-random-model CPU rehearsal; never loads a checkpoint."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import numpy as np
import torch
from e0_archive_harness import identity,write_json,verify,SCOPE,LAYOUT_SHA
from e0_layout_reference import HERE,CONDITIONS
from model_stage_driver import execute_stages
from test_gain_observer_and_stages import fixture,provider

def main():
    root=Path(tempfile.mkdtemp(prefix='e0-model-stage-rehearsal-',dir=HERE))
    archive=root/'attempt'
    archive.mkdir(mode=0o700)
    for name in ('worker.stdout','worker.stderr'):
        with (archive/name).open('xb'): pass
    spec=json.loads((HERE/'E0_LAYOUT_96.json').read_text())
    rows=[]
    summaries=[]
    trace=[]
    def sink(process,name,data,events):
        filename=f'{len(rows):02d}_{process}_{name}.npz'
        arrays={}
        for c in CONDITIONS:
            arrays[c+'_ids']=np.array(data[c]['trial_ids'],dtype=np.int64)
            arrays[c+'_logits']=data[c]['logits']
            arrays[c+'_nll']=data[c]['nll']
        with (archive/filename).open('xb') as f: np.savez(f,**arrays)
        rows.append(dict(process=process,pass_name=name,file=filename,**identity(archive/filename)))
        trace.extend(events)
    try:
        for process in ('A','B'):
            f=fixture()
            summaries.append(execute_stages(f.core,f.base,f.outer,f.arch,f.gain,spec,process,
                         provider(spec),f.device,sink,deadline_seconds=60))
        write_json(archive/'MANIFEST.json',dict(scope=SCOPE,layout_sha256=LAYOUT_SHA,
                   worker_pid=os.getpid(),logical_processes_not_cold_repeats=True,passes=rows))
        result=verify(archive)
        write_json(archive/'SYNTHETIC_COMPLETE.json',result)
        write_json(root/'OBSERVER.json',dict(scope='SMALL_RANDOM_MODEL_CPU',records=trace))
        sources={}
        for name in ('gain_observer.py','gain_formula_check.py','model_stage_driver.py','loaded_model_adapter.py',
                     'architecture_adapter.py','pinned_architecture.py','test_gain_observer_and_stages.py',
                     'test_loaded_model_adapter.py','e0_archive_harness.py','e0_layout_reference.py',
                     'run_local_stage_rehearsal.py'):
            sources[name]=identity(HERE/name)
        report=dict(status='LOCAL_SMALL_MODEL_STAGE_REHEARSAL_PASS',archive=str(archive),
                    stages=summaries,archive_verification=result,observer=identity(root/'OBSERVER.json'),
                    source_files=sources,torch=torch.__version__,device='cpu',
                    model='pinned architecture; random weights; reduced dimensions; synthetic audio interface',
                    independent_model_objects=2,model_processes=1,checkpoint_loaded=False,
                    production_verified=False,remote_access=False,jobs_submitted=0)
        write_json(root/'REPORT.json',report)
        print(json.dumps(dict(report_path=str(root/'REPORT.json'),status=report['status'],
                             predictions=sum(s['predictions'] for s in summaries),observer_events=len(trace)),indent=2))
    except BaseException as error:
        write_json(root/'FAILED.json',dict(status='LOCAL_REHEARSAL_FAILED',error_type=type(error).__name__,
                   error=str(error),production_verified=False))
        raise

if __name__=='__main__': main()

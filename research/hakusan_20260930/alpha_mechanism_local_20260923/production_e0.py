"""Allocated E0 worker/coordinator. Invoked only through verified bootstrap."""
import json
import os
from pathlib import Path
import sys
import numpy as np
from e0_archive_harness import identity,write_json,layout
from e0_layout_reference import CONDITIONS,require
from loaded_model_adapter import FORMAL_SHA
from loaded_worker_bridge import bridging_sink
from portable_reference import load_reference
from rehearse_model_pair import verify as verify_arrays
from two_process_supervisor import run_pair

SCOPE='E0_FORMAL40_NATIVE_20260925_V2'

def worker(package,label,directory,release):
    from audited_model_session import audited_session
    from loaded_worker_bridge import run_loaded_worker
    spec=layout()
    rows=[]
    def sink(process,name,payload,events):
        filename=f'{len(rows):02d}_{name}.npz'
        arrays={}
        for c in CONDITIONS:
            arrays[c+'_ids']=np.array(payload[c]['trial_ids'],dtype=np.int64)
            arrays[c+'_logits']=payload[c]['logits']
            arrays[c+'_nll']=payload[c]['nll']
        with (directory/filename).open('xb') as out: np.savez(out,**arrays)
        rows.append(dict(name=name,file=filename,**identity(directory/filename)))
        if events: write_json(directory/'OBSERVER.json',events)
    # No success marker is published until the loading session's postchecks finish.
    with audited_session(spec) as context:
        result=run_loaded_worker(**context,layout=spec,process=label,sink=sink,
                  reference_directory=package/'reference',reference_sha256=release['reference_sha256'])
        load_report=context['load_report']
    write_json(directory/'STAGES.json',result['stage'])
    write_json(directory/'PROVENANCE.json',dict(scope=SCOPE,label=label,pid=os.getpid(),
          job_id=os.environ['SLURM_JOB_ID'],checkpoint_sha256=FORMAL_SHA,
          reference_sha256=release['reference_sha256'],load_report=load_report,
          bridge=result['historical_checks'],postchecks_completed=True))
    write_json(directory/'WORKER.json',dict(scope=SCOPE,label=label,pid=os.getpid(),passes=rows,
         stages=identity(directory/'STAGES.json'),provenance=identity(directory/'PROVENANCE.json'),
         observer=identity(directory/'OBSERVER.json') if label=='A' else None))

def verify(root,records,package,release,job_id):
    result=verify_arrays(root,records,scope=SCOPE,extra_files=('PROVENANCE.json',))
    refs=load_reference(package/'reference',layout(),release['reference_sha256'])
    for r in records:
        d=root/r['label']
        m=json.loads((d/'WORKER.json').read_text())
        require(identity(d/'PROVENANCE.json')==m['provenance'],'PROVENANCE_SHA')
        p=json.loads((d/'PROVENANCE.json').read_text())
        require(p['scope']==SCOPE and p['label']==r['label'] and p['pid']==r['pid']
                and p['job_id']==job_id and p['checkpoint_sha256']==FORMAL_SHA
                and p['reference_sha256']==release['reference_sha256']
                and p['postchecks_completed'] is True,'PROVENANCE_BINDING')
        report=p['load_report']
        require(report['loaded_trainable_numel_ratio']==1. and report['trainable_numel']>0
                and report['loaded_trainable_numel']==report['trainable_numel'],'LOAD_REPORT_COVERAGE')
        checks=[]
        check=bridging_sink(refs,lambda *a:None,checks)
        for i,name in enumerate(('original','alpha_1')):
            with np.load(d/f'{i:02d}_{name}.npz',allow_pickle=False) as z:
                data={c:dict(trial_ids=z[c+'_ids'].tolist(),logits=z[c+'_logits'],nll=z[c+'_nll']) for c in CONDITIONS}
                check(r['label'],name,data,[])
        require(checks==p['bridge'],'BRIDGE_REPORT')
        with np.load(d/'03_alpha_0.npz',allow_pickle=False) as z:
            for c in CONDITIONS[1:]:
                require(z['correct_logits'][:64].tobytes()==z[c+'_logits'].tobytes(),'OFFLINE_CUE_INDEPENDENCE')
    return dict(result,status='E0_ARTIFACTS_VERIFIED',reference_job_id='728520',
                evaluation_role='REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST')

def coordinator(package,attempt,release,digest):
    require(sys.platform=='linux' and os.environ.get('SLURM_JOB_ID','').isdigit(),'ALLOCATED_ONLY')
    receipt=json.loads((attempt.parent/'SUBMISSION.json').read_text())
    require(receipt['job_id']==os.environ['SLURM_JOB_ID'] and receipt['release_sha256']==digest,'JOB_RECEIPT')
    entry=package/'e0_entry.py'
    result=run_pair(attempt,lambda label,d:[sys.executable,'-I','-B',str(entry),'worker',digest,label,str(d)],
                    lambda root,records:verify(root,records,package,release,os.environ['SLURM_JOB_ID']),
                    timeout_seconds=1500)
    from e0_entry import verify_package
    verify_package(package,digest)
    write_json(attempt/'E0_COMPLETE.json',dict(status='E0_ENDPOINT_PASS',job_id=os.environ['SLURM_JOB_ID'],
               release_sha256=digest,pair_record=identity(attempt/'PAIR_EXECUTION.json'),
               verification=result['verification'],scientific_alpha_result=False))

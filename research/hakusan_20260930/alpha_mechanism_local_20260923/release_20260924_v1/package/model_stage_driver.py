"""One already-loaded model's staged forward driver; no load/SSH/submission.

Production coordinator must supply verified inputs, provenance and process-level
deadline. Callback boundary checks here are cooperative, not a worker watchdog.
"""
from contextlib import nullcontext
import hashlib
import time
import numpy as np
from e0_layout_reference import CONDITIONS,canonical,condition_ids,validate_logits,require
from loaded_model_adapter import pass_context
from gain_observer import GainObserver
from gain_formula_check import check_installed_gains

LAYOUT_SHA='f28160c857512c90533837d7a4f54a761a6deef6d6cf86aafadecd34138f7e90'

def execute_stages(core,base,outer,architecture_type,gain_type,layout,process,
                   batch_provider,device,sink,*,deadline_seconds=1500,clock=time.monotonic):
    require(hashlib.sha256(canonical(layout)).hexdigest()==LAYOUT_SHA,'STAGE_LAYOUT')
    require(process in ('A','B'),'PROCESS_LABEL')
    require(type(deadline_seconds) in (int,float) and 0<deadline_seconds<=1500,'DEADLINE')
    start=clock()
    def check_time():
        if clock()-start>=deadline_seconds: raise TimeoutError('STAGE_DEADLINE')
    names=layout['passes']+(['alpha_05_observed'] if process=='A' else [])
    input_identity={}
    comparisons={}
    seen_predictions=0
    observed_records=[]
    formula_reports=[]
    for name in names:
        check_time()
        observed=name=='alpha_05_observed'
        payload={c:dict(trial_ids=[],logits=[],nll=[]) for c in CONDITIONS}
        with pass_context(core,outer,architecture_type,gain_type,'alpha_05' if observed else name):
            formula_reports.append(check_installed_gains(outer.model,'alpha_05' if observed else name))
            check_time()
            observer=GainObserver(outer.model) if observed else None
            with observer if observed else nullcontext():
                # Historical execution order: each full scene batch then its controls.
                for batch_index in range(len(layout['batches'])):
                    for c in CONDITIONS:
                        ids=layout['condition_batches'][c][batch_index]
                        if not ids: continue
                        check_time()
                        scene,cue,labels,probes=batch_provider(batch_index,c,list(ids))
                        require(labels.tolist()==[layout['target_labels'][str(i)] for i in ids],'STAGE_LABELS')
                        require(len(scene)==len(cue)==len(labels)==len(probes)==len(ids),'STAGE_BATCH_SIZE')
                        identity=(tuple(base._tensor_hashes(scene)),tuple(base._tensor_hashes(cue)))
                        key=(batch_index,c)
                        if key not in input_identity: input_identity[key]=identity
                        require(input_identity[key]==identity,'STAGE_INPUT_CHANGED')
                        with observer.batch(batch_index,c,list(ids)) if observed else nullcontext():
                            values,logits=core.predict(base,outer,scene,cue,labels,probes,device)
                        check_time()
                        payload[c]['trial_ids'].extend(ids)
                        payload[c]['logits'].append(logits)
                        payload[c]['nll'].append(values['nll'])
                if observed:
                    require(len(observer.records)==144,'OBSERVER_PASS_EVENT_COUNT')
                    observed_records=observer.records
        for c,item in payload.items():
            item['logits']=np.concatenate(item['logits'])
            item['nll']=np.concatenate(item['nll'])
            require(item['trial_ids']==condition_ids(layout,c),'STAGE_ORDER')
            labels=np.array([layout['target_labels'][str(i)] for i in item['trial_ids']])
            validate_logits(item['logits'],item['trial_ids'],labels,item['nll'])
        # Local endpoint checks are not a replacement for historical/process bridging.
        baseline={'alpha_1':'original','alpha_0':'explicit_bypass','alpha_05_observed':'alpha_05'}.get(name)
        if baseline:
            for c in CONDITIONS:
                for field in ('logits','nll'):
                    require(payload[c][field].tobytes()==comparisons[baseline][c][field].tobytes(),'STAGE_ENDPOINT_BITS')
        if name in ('original','explicit_bypass','alpha_05'):
            comparisons[name]={c:{k:v.copy() if isinstance(v,np.ndarray) else list(v) for k,v in item.items()} for c,item in payload.items()}
        if name=='alpha_0':
            for c in CONDITIONS[1:]:
                require(payload['correct']['logits'][:64].tobytes()==payload[c]['logits'].tobytes(),'STAGE_CUE_INDEPENDENCE')
        check_time()
        sink(process,name,payload,observed_records if observed else [])
        check_time()
        seen_predictions+=sum(len(p['trial_ids']) for p in payload.values())
    return dict(status='LOADED_MODEL_STAGES_FINISHED_NOT_QUALIFIED',process_label=process,
                passes=len(names),predictions=seen_predictions,observer_events=len(observed_records),
                gain_formula_reports=formula_reports,
                elapsed_seconds=clock()-start,production_verified=False)

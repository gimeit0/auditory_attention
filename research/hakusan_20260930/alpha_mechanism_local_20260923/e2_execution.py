"""E2 loaded-stage body derived from E1; stage loading and archive gates external."""
import time
import platform
import resource
import numpy as np
from e0_layout_reference import require,validate_logits
from e1_execution import utc_now
from e2_matrix import stage_jobs

def execute_stage(c,completed_epochs,core,base,outer,architecture_type,gain_type,provider,device,sink,
                   *,seconds=9000,clock=time.monotonic,mode='matrix'):
    """Caller owns strict loading, process isolation, provenance and hard timeout.

    provider(domain,batch_index,condition,ids) returns scene,cue,labels,probes.
    This body does not certify an arbitrary caller's contract or input callbacks.
    """
    from loaded_model_adapter import pass_context
    from gain_formula_check import check_installed_gains
    require(0<seconds<=9000,'E2_TIME_BUDGET')
    import torch
    start=clock(); identities={}; formulas=[]; predictions=0; resources=[]
    process_started=utc_now()
    use_cuda=torch.cuda.is_available() and str(device).startswith('cuda')
    rss_unit='bytes' if platform.system()=='Darwin' else 'KiB'
    def check():
        if clock()-start>=seconds: raise TimeoutError('E2_WORKER_DEADLINE')
    grouped={}
    for key,batches in stage_jobs(c,completed_epochs,mode): grouped.setdefault(key[:3],[]).append((key,batches))
    for (proc,domain,name),conditions in grouped.items():
        check()
        payload={key:dict(trial_ids=[],logits=[],nll=[]) for key,_ in conditions}
        pass_started=utc_now(); pass_clock=clock()
        if use_cuda: torch.cuda.reset_peak_memory_stats(device)
        with pass_context(core,outer,architecture_type,gain_type,name):
            formulas.append(dict(domain=domain,pass_name=name,report=check_installed_gains(outer.model,name)))
            # Parent batch then control branches: preserve native construction order.
            for bi in range(len(conditions[0][1])):
                for key,batches in conditions:
                    ids=batches[bi]
                    if not ids: continue
                    check()
                    scene,cue,labels,probes=provider(domain,bi,key[3],list(ids))
                    require(labels.tolist()==[c['labels'][str(i)] for i in ids],'E2_LABELS')
                    require(len(scene)==len(cue)==len(labels)==len(probes)==len(ids),'E2_BATCH_SIZE')
                    identity=(tuple(base._tensor_hashes(scene)),tuple(base._tensor_hashes(cue)))
                    ikey=(domain,bi,key[3]); identities.setdefault(ikey,identity)
                    require(identities[ikey]==identity,'E2_INPUT_CHANGED')
                    values,logits=core.predict(base,outer,scene,cue,labels,probes,device)
                    check(); p=payload[key]
                    p['trial_ids']+=list(ids); p['logits'].append(logits); p['nll'].append(values['nll'])
        for key,p in payload.items():
            p['logits']=np.concatenate(p['logits']); p['nll']=np.concatenate(p['nll'])
            validate_logits(p['logits'],p['trial_ids'],np.array([c['labels'][str(i)] for i in p['trial_ids']]),p['nll'])
            check(); sink(key,p); check(); predictions+=len(p['trial_ids'])
        resources.append(dict(domain=domain,pass_name=name,started_utc=pass_started,finished_utc=utc_now(),
            elapsed_seconds=clock()-pass_clock,
            cuda_max_memory_allocated_bytes=int(torch.cuda.max_memory_allocated(device)) if use_cuda else None,
            cuda_max_memory_reserved_bytes=int(torch.cuda.max_memory_reserved(device)) if use_cuda else None,
            host_max_rss_ru_maxrss=int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),ru_maxrss_unit=rss_unit))
    runtime_values=getattr(core,'runtime_values',None)
    return dict(status='E2_LOADED_BODY_FINISHED_NOT_QUALIFIED',predictions=predictions,
                gain_formula_reports=formulas,elapsed_seconds=clock()-start,
                process_started_utc=process_started,process_finished_utc=utc_now(),
                runtime_values=runtime_values() if callable(runtime_values) else None,
                pass_resources=resources)

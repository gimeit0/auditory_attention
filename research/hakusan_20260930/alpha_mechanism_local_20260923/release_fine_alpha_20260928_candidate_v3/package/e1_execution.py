"""E1 loaded-model body and independent array verifier. Not a submit/load entry."""
import datetime
import hashlib
import json
import platform
import resource
import time
from pathlib import Path
import numpy as np
from e0_layout_reference import require,validate_logits

from e1_inputs import FREEZE_SHA,build_contract
# Decision B (2026-09-27, doc 27 §9): .875 replaces .25 after the E0 pilot (job 746603).
# The intervention formula is unchanged (decision A); prediction count stays 20400+3600*5.
ALPHAS=['alpha_0','alpha_05','alpha_075','alpha_875','alpha_1']
ALPHA_GRID=[0,.5,.75,.875,1]
PREVIOUS_ALPHA_GRID=[0,.25,.5,.75,1]
PASS_ALPHA_MODE={'original':(1.,'native_gain'),'explicit_bypass':(0.,'bypass_module'),
                 'alpha_0':(0.,'alpha'),'alpha_05':(.5,'alpha'),'alpha_075':(.75,'alpha'),
                 'alpha_875':(.875,'alpha'),'alpha_1':(1.,'alpha'),
                 'uniform_05':(.5,'uniform'),'conv_only_05':(.5,'conv_only'),
                 'fc_mean_preserved_05':(.5,'fc_mean_preserved')}
E0_JOB_ID='746603'
E0_CORRECT_TRIAL_IDS=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 2256, 2257, 2258, 2259, 2260, 2261, 2262, 2263, 2264, 2265, 2266, 2267, 2268, 2269, 2270, 2271, 4512, 4513, 4514, 4515, 4516, 4517, 4518, 4519, 4520, 4521, 4522, 4523, 4524, 4525, 4526, 4527, 6752, 6753, 6754, 6755, 6756, 6757, 6758, 6759, 6760, 6761, 6762, 6763, 6764, 6765, 6766, 6767, 8992, 8993, 8994, 8995, 8996, 8997, 8998, 8999, 9000, 9001, 9002, 9003, 9004, 9005, 9006, 9007, 9008, 9009, 9010, 9011, 9012, 9013, 9014, 9015, 9016, 9017, 9018, 9019, 9020, 9021, 9022, 9023]
PROVENANCE_FIELDS_REQUIRED=('environment','runtime_values','process_started_utc',
                            'process_finished_utc','pass_resources')
ENVIRONMENT_KEYS=('python','torch','cuda','cudnn','device_name','hostname','slurm_job_id','slurm_cpus_per_task')
PASS_RESOURCE_KEYS=('domain','pass_name','started_utc','finished_utc','elapsed_seconds',
                    'cuda_max_memory_allocated_bytes','cuda_max_memory_reserved_bytes',
                    'host_max_rss_ru_maxrss','ru_maxrss_unit')

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def pilot_exposure(c):
    e1={int(k) for k in c['labels']}
    clean={i for b in c['clean_batches'] for i in b}
    overlap=sorted(set(E0_CORRECT_TRIAL_IDS)&e1)
    return dict(e0_job_id=E0_JOB_ID,e0_correct_trials=len(E0_CORRECT_TRIAL_IDS),
                overlap_trial_ids=overlap,overlap_count=len(overlap),
                overlap_clean_count=sum(i in clean for i in overlap),
                handling='decision C: keep, disclose, flag in analysis, add sensitivity version excluding overlap',
                status='PILOT_DRIVEN_EXPLORATORY_REVISION_NOT_UNTOUCHED_CONFIRMATION')
MAIN=['original','explicit_bypass']+ALPHAS+['uniform_05','conv_only_05','fc_mean_preserved_05']
CLEAN=['original','explicit_bypass']+ALPHAS

def contract(directory=None):
    return build_contract(directory)

def jobs(c,process):
    require(process in ('A','B'),'PROCESS')
    for domain,passes,conditions in [('main',MAIN,('correct','shuffled','silent','distractor')),
                                     ('clean',CLEAN,('correct_cue','zero_cue'))]:
        for name in (passes if process=='A' else ['alpha_1']):
            for condition in conditions:
                batches=c['clean_batches'] if domain=='clean' else c['main_batches'] if condition=='correct' else c['control_batches']
                yield (process,domain,name,condition),batches

def inventory(c):
    return {key:[i for b in batches for i in b] for process in ('A','B') for key,batches in jobs(c,process)}

def execution_spec(c):
    return dict(model_id='formal40',alpha_grid=ALPHA_GRID,
                alpha_grid_revision=dict(previous=PREVIOUS_ALPHA_GRID,decision='B3a',decided='2026-09-27',
                    basis='E0 pilot job 746603 readout (doc 26) and decision draft (doc 27); intervention formula unchanged'),
                pass_map={k:dict(alpha=a,mode=m) for k,(a,m) in PASS_ALPHA_MODE.items()},
                pilot_exposure=pilot_exposure(c),
                provenance_fields_required=list(PROVENANCE_FIELDS_REQUIRED),
                main_passes=MAIN,clean_passes=CLEAN,process_order=['A','B','VERIFY'],
                records=[dict(key=list(k),predictions=len(ids)) for k,ids in inventory(c).items()],
                runtime=dict(mode='eager_fp32',seed=20260829,deterministic_algorithms=True,
                             cudnn_deterministic=True,cudnn_benchmark=False,matmul_precision='highest',
                             matmul_tf32=False,cudnn_tf32=False),
                historical_bridge='E0 job746603; E1 endpoints use the NEW same-layout reference',
                paired_metric_policy='FULL_D_WITH_OBSERVED_ALPHA0_RESIDUAL_NOT_FORCED_ZERO',
                scope='REUSED_VALIDATION_BANK_DEVELOPMENT_NOT_INDEPENDENT_TEST')

def paired_readout(c,records):
    """Measured paired terms; batch-shape residuals must never be replaced by zero.

    This is an arithmetic audit, not a bootstrap/statistical acceptance decision.
    Called only after archive array/identity validation.
    """
    ids=records[('A','main','alpha_0','shuffled')]['trial_ids']
    labels=np.array([c['labels'][str(i)] for i in ids])
    terms={}
    for name in ALPHAS:
        correct=records[('A','main',name,'correct')]
        shuffled=records[('A','main',name,'shuffled')]
        require(shuffled['trial_ids']==ids,'PAIRED_IDS')
        positions={i:j for j,i in enumerate(correct['trial_ids'])}
        idx=[positions[i] for i in ids]
        a=correct['logits'][idx]; b=shuffled['logits']
        diff=correct['nll'][idx].astype(np.float64)-shuffled['nll'].astype(np.float64)
        terms[name]=dict(accuracy_difference=(
            (a.argmax(1)==labels).astype(np.int64)-(b.argmax(1)==labels).astype(np.int64)).tolist(),
            nll_difference=diff.tolist(),nll_mean=float(diff.mean()),nll_std=float(diff.std()),
            nll_max_abs=float(np.abs(diff).max()),
            prediction_disagreements=int(np.count_nonzero(a.argmax(1)!=b.argmax(1))))
    baseline=np.array(terms['alpha_0']['accuracy_difference'])
    return dict(policy='FULL_D_WITH_OBSERVED_ALPHA0_RESIDUAL_NOT_FORCED_ZERO',
        trial_ids=ids,terms=terms,
        D=(np.array(terms['alpha_1']['accuracy_difference'])-baseline).tolist(),
        D_alpha={name:(np.array(terms[name]['accuracy_difference'])-baseline).tolist() for name in ALPHAS},
        inferential_status='ARITHMETIC_ONLY_NO_SCIENTIFIC_LABEL')

def verify_arrays(c,records):
    expected=inventory(c)
    require(set(records)==set(expected),'E1_INVENTORY')
    total=0
    for key,ids in expected.items():
        r=records[key]
        require(r['trial_ids']==ids,'E1_IDS')
        require(r['nll'].dtype==np.float32,'E1_NLL_DTYPE')
        validate_logits(r['logits'],ids,np.array([c['labels'][str(i)] for i in ids]),r['nll'])
        total+=len(ids)
    def same(a,b):
        require(records[a]['trial_ids']==records[b]['trial_ids'],'E1_COMPARISON_IDS')
        for f in ('logits','nll'):
            require(records[a][f].tobytes()==records[b][f].tobytes(),'E1_ENDPOINT_OR_REPEAT_BITS')
    for domain,conditions in [('main',('correct','shuffled','silent','distractor')),('clean',('correct_cue','zero_cue'))]:
        for condition in conditions:
            same(('A',domain,'original',condition),('A',domain,'alpha_1',condition))
            same(('A',domain,'explicit_bypass',condition),('A',domain,'alpha_0',condition))
            same(('A',domain,'alpha_1',condition),('B',domain,'alpha_1',condition))
    same(('A','clean','alpha_0','correct_cue'),('A','clean','alpha_0','zero_cue'))
    require(total==c['predictions']==38400,'E1_PREDICTION_COUNT')
    return dict(status='E1_ARRAYS_VERIFIED_NOT_PROVENANCE_QUALIFIED',predictions=total,
                records=len(records),production_verified=False,
                paired_readout=paired_readout(c,records),
                mixed_cross_batch_cue_independence='not a bitwise acceptance gate')

def execute_loaded(c,process,core,base,outer,architecture_type,gain_type,provider,device,sink,
                   *,seconds=9000,clock=time.monotonic):
    """Caller owns strict loading, process isolation, provenance and hard timeout.

    provider(domain,batch_index,condition,ids) returns scene,cue,labels,probes.
    This body does not certify an arbitrary caller's contract or input callbacks.
    """
    from loaded_model_adapter import pass_context
    from gain_formula_check import check_installed_gains
    require(0<seconds<=9000,'E1_TIME_BUDGET')
    import torch
    start=clock(); identities={}; formulas=[]; predictions=0; resources=[]
    process_started=utc_now()
    use_cuda=torch.cuda.is_available() and str(device).startswith('cuda')
    rss_unit='bytes' if platform.system()=='Darwin' else 'KiB'
    def check():
        if clock()-start>=seconds: raise TimeoutError('E1_WORKER_DEADLINE')
    grouped={}
    for key,batches in jobs(c,process): grouped.setdefault(key[:3],[]).append((key,batches))
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
                    require(labels.tolist()==[c['labels'][str(i)] for i in ids],'E1_LABELS')
                    require(len(scene)==len(cue)==len(labels)==len(probes)==len(ids),'E1_BATCH_SIZE')
                    identity=(tuple(base._tensor_hashes(scene)),tuple(base._tensor_hashes(cue)))
                    ikey=(domain,bi,key[3]); identities.setdefault(ikey,identity)
                    require(identities[ikey]==identity,'E1_INPUT_CHANGED')
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
    return dict(status='E1_LOADED_BODY_FINISHED_NOT_QUALIFIED',predictions=predictions,
                gain_formula_reports=formulas,elapsed_seconds=clock()-start,
                process_started_utc=process_started,process_finished_utc=utc_now(),
                runtime_values=runtime_values() if callable(runtime_values) else None,
                pass_resources=resources)

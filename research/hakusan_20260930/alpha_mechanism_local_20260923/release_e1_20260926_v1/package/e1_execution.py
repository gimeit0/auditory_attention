"""E1 loaded-model body and independent array verifier. Not a submit/load entry."""
import hashlib
import json
import time
from pathlib import Path
import numpy as np
from e0_layout_reference import require,validate_logits

from e1_inputs import FREEZE_SHA,build_contract
ALPHAS=['alpha_0','alpha_025','alpha_05','alpha_075','alpha_1']
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
    return dict(model_id='formal40',alpha_grid=[0,.25,.5,.75,1],
                main_passes=MAIN,clean_passes=CLEAN,process_order=['A','B','VERIFY'],
                records=[dict(key=list(k),predictions=len(ids)) for k,ids in inventory(c).items()],
                runtime=dict(mode='eager_fp32',seed=20260829,deterministic_algorithms=True,
                             cudnn_deterministic=True,cudnn_benchmark=False,matmul_precision='highest',
                             matmul_tf32=False,cudnn_tf32=False),
                historical_bridge='E0 job746603; E1 endpoints use the NEW same-layout reference',
                scope='REUSED_VALIDATION_BANK_DEVELOPMENT_NOT_INDEPENDENT_TEST')

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
    start=clock(); identities={}; formulas=[]; predictions=0
    def check():
        if clock()-start>=seconds: raise TimeoutError('E1_WORKER_DEADLINE')
    grouped={}
    for key,batches in jobs(c,process): grouped.setdefault(key[:3],[]).append((key,batches))
    for (proc,domain,name),conditions in grouped.items():
        check()
        payload={key:dict(trial_ids=[],logits=[],nll=[]) for key,_ in conditions}
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
    return dict(status='E1_LOADED_BODY_FINISHED_NOT_QUALIFIED',predictions=predictions,
                gain_formula_reports=formulas,elapsed_seconds=clock()-start)

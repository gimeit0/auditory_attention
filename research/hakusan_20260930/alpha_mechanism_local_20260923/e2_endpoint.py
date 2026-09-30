"""Per-stage native vs alpha=1 endpoint on fixed existing batch layouts."""
import numpy as np
from loaded_model_adapter import pass_context
from e0_layout_reference import validate_logits

def probe_spec(layout):
    bi=next(i for i,b in enumerate(layout['control_batches']) if b)
    specs=[('main',bi,'correct',layout['main_batches'][bi])]
    specs += [('main',bi,c,layout['control_batches'][bi]) for c in ('shuffled','silent','distractor')]
    specs += [('clean',0,c,layout['clean_batches'][0]) for c in ('correct_cue','zero_cue')]
    return specs

def check_endpoint(layout,ctx,sink=None):
    results={}
    for name in ('original','alpha_1'):
        with pass_context(ctx['core'],ctx['outer'],ctx['architecture_type'],ctx['gain_type'],name):
            for domain,bi,condition,ids in probe_spec(layout):
                scene,cue,labels,probes=ctx['batch_provider'](domain,bi,condition,list(ids))
                wanted=np.array([layout['labels'][str(i)] for i in ids])
                if labels.tolist()!=wanted.tolist(): raise ValueError('ENDPOINT_LABELS')
                values,logits=ctx['core'].predict(ctx['base'],ctx['outer'],scene,cue,labels,probes,ctx['device'])
                validate_logits(logits,list(ids),wanted,values['nll'])
                results[(name,domain,condition)]=(logits.copy(),np.asarray(values['nll']).copy())
                if sink is not None:
                    sink((name,domain,condition),dict(trial_ids=list(ids),logits=logits.copy(),nll=np.asarray(values['nll']).copy()))
    for domain,bi,condition,ids in probe_spec(layout):
        for a,b in zip(results[('original',domain,condition)],results[('alpha_1',domain,condition)]):
            if a.shape!=b.shape or a.dtype!=b.dtype or a.tobytes()!=b.tobytes():
                raise ValueError('E2_STAGE_ENDPOINT_BITS: '+domain+'/'+condition)
    return dict(status='E2_STAGE_ENDPOINT_BITS_PASS',
                predictions=2*sum(len(ids) for *_,ids in probe_spec(layout)),
                scope='six conditions on fixed first control-bearing main batch and first clean batch',
                batches=[dict(domain=d,batch_index=b,condition=c,trial_ids=ids) for d,b,c,ids in probe_spec(layout)])

def verify_saved_endpoint(root,layout,inventory):
    from pathlib import Path
    from e1_artifacts import identity
    root=Path(root); rows={}; names=set()
    expected={(name,d,c):ids for name in ('original','alpha_1') for d,b,c,ids in probe_spec(layout)}
    for row in inventory:
        key=tuple(row['key']); name=row['file']
        if key not in expected or key in rows or Path(name).name!=name or name in names:
            raise ValueError('ENDPOINT_INVENTORY')
        names.add(name); p=root/name
        if identity(p)!={'size':row['size'],'sha256':row['sha256']}: raise ValueError('ENDPOINT_FILE_SHA')
        with np.load(p,allow_pickle=False) as z:
            if set(z.files)!={'trial_ids','logits','nll'}: raise ValueError('ENDPOINT_ARRAYS')
            if z['trial_ids'].dtype!=np.int64 or z['trial_ids'].tolist()!=expected[key]: raise ValueError('ENDPOINT_IDS')
            logits=z['logits']; nll=z['nll']
        validate_logits(logits,expected[key],np.array([layout['labels'][str(i)] for i in expected[key]]),nll)
        rows[key]=(logits,nll)
    if set(rows)!=set(expected) or {p.name for p in root.iterdir()}!=names: raise ValueError('ENDPOINT_MISSING_OR_EXTRA')
    for d,b,c,ids in probe_spec(layout):
        for a,b in zip(rows[('original',d,c)],rows[('alpha_1',d,c)]):
            if a.dtype!=b.dtype or a.shape!=b.shape or a.tobytes()!=b.tobytes(): raise ValueError('ENDPOINT_SAVED_BITS')
    return True

"""Local E0 layout/reference reader. No model loading, SSH or submission."""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from check_e0_proposal import check, ROOT

HERE=Path(__file__).resolve().parent
PROPOSAL_SHA='8d562e56ec4980b45fb1aa4e338b01dfcc026587f6ab7703009b1b2ab1a11aef'
CONDITIONS=('correct','shuffled','silent','distractor')

def require(ok,message):
    if not ok: raise ValueError(message)

def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def make_layout():
    raw=(HERE/'E0_SAMPLE_PROPOSAL.json').read_bytes()
    require(hashlib.sha256(raw).hexdigest()==PROPOSAL_SHA,'PROPOSAL_CHANGED')
    check()  # Verify local historical files before reading their contents.
    p=json.loads(raw)
    root=ROOT/p['archive']
    with (root/'bank.csv').open(newline='') as f: bank=list(csv.DictReader(f))
    require([int(r['trial_id']) for r in bank]==list(range(10000)),'BANK_ORDER')
    batches=[list(range(start,start+16)) for start in p['original_batch_start_trial_ids']]
    ids=[i for batch in batches for i in batch]
    control=[[i for i in b if int(bank[i]['control_subset'])==1] for b in batches]
    condition_batches={c:batches if c=='correct' else control for c in CONDITIONS}
    return dict(schema_version=1,protocol='e0_formal40_layout_20260923_v1',
                scope='LOCAL_CANDIDATE_NOT_AUTHORIZED',proposal_sha256=PROPOSAL_SHA,
                reference_job_id='728520',model_id='formal40',
                checkpoint_sha256=p['checkpoint_sha256'],reference_sha256=p['reference_sha256'],
                batch_size=16,trial_ids=ids,batches=batches,condition_batches=condition_batches,
                target_labels={str(i):int(bank[i]['target_label']) for i in ids},
                processes=['A','B'],passes=p['passes_per_process'],
                observed_pass={'process':'A','pass':'alpha_05_observed'},expected_predictions=6048)

def validate_layout(layout):
    require(canonical(layout)==canonical(make_layout()),'LAYOUT_MISMATCH')

def condition_ids(layout,condition):
    return [i for b in layout['condition_batches'][condition] for i in b]

def reference(layout):
    validate_layout(layout)
    p=json.loads((HERE/'E0_SAMPLE_PROPOSAL.json').read_text())
    root=ROOT/p['archive']
    with (root/'bank.csv').open(newline='') as f: bank=list(csv.DictReader(f))
    with (root/'results.csv').open(newline='') as f: results=list(csv.DictReader(f))
    require([int(r['trial_id']) for r in results]==list(range(10000)),'RESULT_ORDER')
    archive_controls=[int(r['trial_id']) for r in bank if int(r['control_subset'])==1]
    output={}
    with np.load(root/'logits.npz',allow_pickle=False) as z:
        for c in CONDITIONS:
            ids=condition_ids(layout,c)
            positions={tid:k for k,tid in enumerate(range(10000) if c=='correct' else archive_controls)}
            full=z['formal40__'+c]
            require(full.shape==(len(positions),800) and full.dtype==np.float32,'REFERENCE_SHAPE_DTYPE')
            arr=full[[positions[i] for i in ids]].copy()
            prefix='formal40_' if c=='correct' else 'formal40_'+c+'_'
            saved_nll=np.array([float(results[i][prefix+'nll']) for i in ids])
            labels=np.array([layout['target_labels'][str(i)] for i in ids])
            validate_logits(arr,ids,labels,saved_nll)
            predictions=np.array([float(results[i][prefix+'pred_label']) for i in ids])
            require(np.isfinite(predictions).all() and np.equal(predictions,np.floor(predictions)).all(),'REFERENCE_LABEL_INTEGER')
            require(np.array_equal(arr.argmax(1),predictions),'REFERENCE_LABEL')
            output[c]=dict(trial_ids=ids,logits=arr,nll=saved_nll,labels=labels)
    return output

def validate_logits(logits, ids, labels, nll):
    require(type(ids) is list and len(ids)==len(set(ids)) and all(type(i) is int for i in ids),'TRIAL_IDS')
    require(isinstance(logits,np.ndarray) and logits.dtype==np.float32 and logits.shape==(len(ids),800),'LOGITS_SHAPE_DTYPE')
    require(np.isfinite(logits).all(),'NONFINITE_LOGITS')
    labels=np.asarray(labels)
    nll=np.asarray(nll)
    require(labels.shape==(len(ids),) and labels.dtype.kind in 'iu' and ((labels>=0)&(labels<800)).all(),'LABELS')
    require(nll.shape==(len(ids),) and np.isfinite(nll).all(),'NLL')
    x=logits.astype(np.float64)
    maximum=x.max(1)
    computed=maximum+np.log(np.exp(x-maximum[:,None]).sum(1))-x[np.arange(len(ids)),labels]
    require(np.allclose(computed,nll,atol=2e-5,rtol=2e-6),'NLL_RECOMPUTE')
    return float(np.max(np.abs(computed-nll)))

def bitwise_bridge(expected, ids, actual):
    require(ids==expected['trial_ids'],'BRIDGE_ORDER')
    baseline=expected['logits']
    require(isinstance(actual,np.ndarray) and actual.dtype==baseline.dtype and actual.shape==baseline.shape,'BRIDGE_SHAPE_DTYPE')
    require(actual.tobytes(order='C')==baseline.tobytes(order='C'),'BRIDGE_BITS')

def validate_prediction_inventory(layout, records):
    """Count/order contract only; does NOT implement state or numerical E0 gates."""
    expected={}
    for process in layout['processes']:
        passes=layout['passes']+(['alpha_05_observed'] if process=='A' else [])
        for name in passes:
            for c in CONDITIONS: expected[(process,name,c)]=condition_ids(layout,c)
    require(len(records)==len(expected),'INVENTORY_COUNT')
    seen=set()
    total=0
    for r in records:
        require(set(r)=={'process','pass','condition','trial_ids'},'INVENTORY_FIELDS')
        key=(r['process'],r['pass'],r['condition'])
        require(key in expected and key not in seen,'INVENTORY_IDENTITY')
        require(r['trial_ids']==expected[key],'INVENTORY_ORDER')
        seen.add(key)
        total+=len(r['trial_ids'])
    require(total==layout['expected_predictions'],'PREDICTION_COUNT')
    return total

def report():
    layout=make_layout()
    refs=reference(layout)
    return dict(status='E0_LAYOUT_REFERENCE_LOCAL_PASS',
                layout_sha256=hashlib.sha256(canonical(layout)).hexdigest(),
                reference_job_id='728520',conditions={c:dict(rows=len(r['trial_ids']),
                logits_sha256=hashlib.sha256(r['logits'].tobytes()).hexdigest(),
                cpu_nll_max_abs=validate_logits(r['logits'],r['trial_ids'],r['labels'],r['nll'])) for c,r in refs.items()},
                checkpoint_loaded=False,remote_access=False,jobs_submitted=0,
                limitation='Historical subset and local gates only; not a new model execution or E0 endpoint pass')

if __name__=='__main__': print(json.dumps(report(),ensure_ascii=False,indent=2))

"""Post-hoc descriptive readout of the E0 job 746603 arrays. Local, read-only inputs.

No model inference, no SSH, no bootstrap or hypothesis test: only counts, means and
bitwise comparisons over the archived npz arrays. E0 was an engineering acceptance
(E0_ENDPOINT_PASS, scientific_alpha_result=false); this readout changes no status.
Evaluation role stays REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
DEFAULT_STATE=HERE/'release_20260925_v2'/'collect-746603-SlcKgK'/'state'/'attempt'
DEFAULT_BANK=HERE/'release_e1_20260926_v1'/'package_ready'/'frozen_bank.tsv'
BANK_SHA='d03404f2bca5aeb8a5d096b84f6ef758b6b07d0ee5efbd44ded59135bced0091'
CONDITIONS=('correct','shuffled','silent','distractor')
PROCESSES=('A','B')
CLASSES=800
# 05_E0_REAL_MODEL_ACCEPTANCE_PLAN §5: CPU float64 recompute vs saved FP32 NLL tolerance.
# It is a derived-quantity tolerance, not a logits bridging tolerance.
NLL_ATOL,NLL_RTOL=2e-5,2e-6
# Predefined descriptive pairs (process A, correct logits). Not hypothesis tests.
PAIRS=(('original','alpha_1'),('alpha_0','explicit_bypass'),('alpha_05','alpha_05_observed'),
       ('original','alpha_075'),('alpha_05','alpha_0'),('alpha_025','alpha_0'),
       ('alpha_05','conv_only_05'),('alpha_05','fc_mean_preserved_05'),
       ('conv_only_05','fc_mean_preserved_05'),('uniform_05','alpha_0'))
STATUS='E0_READOUT_DESCRIPTIVE_NOT_INFERENTIAL'
EVALUATION_ROLE='REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST'
STATE_FILES=('E0_COMPLETE.json','PAIR_EXECUTION.json')
PROCESS_FILES=('WORKER.json','PROVENANCE.json','STAGES.json','OBSERVER.json','LAUNCH.json')

def require(ok,message):
    if not ok: raise ValueError(message)

def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def num(value):
    value=float(value)
    return value if np.isfinite(value) else None

def identity(path):
    path=Path(path)
    require(path.is_file() and not path.is_symlink(),'INVALID_INPUT:'+path.name)
    raw=path.read_bytes()
    return dict(size=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def load_bank(path,expected_sha=BANK_SHA):
    """Verify the frozen bank bytes, then map trial_id -> target_label (class index) and scene_kind."""
    path=Path(path)
    ident=identity(path)
    require(ident['sha256']==expected_sha,'BANK_SHA')
    table=pd.read_csv(path,sep='\t',dtype=str,keep_default_na=False)
    for column in ('trial_id','target_label','scene_kind'):
        require(column in table.columns,'BANK_COLUMN:'+column)
    ids=table['trial_id'].astype(int)
    require(bool(ids.is_unique),'BANK_TRIAL_ID_DUPLICATE')
    labels=table['target_label'].astype(int)  # class index; target_index is an audio-pool index, not a class.
    require(bool(((labels>=0)&(labels<CLASSES)).all()),'BANK_LABEL_RANGE')
    kinds=table['scene_kind']
    require(bool(kinds.isin(('clean','mixed')).all()),'BANK_SCENE_KIND')
    return dict(identity=ident,rows=int(len(table)),
                labels=dict(zip(ids.tolist(),labels.tolist())),kinds=dict(zip(ids.tolist(),kinds.tolist())))

def load_arrays(path):
    with np.load(path,allow_pickle=False) as z:
        require(set(z.files)=={c+s for c in CONDITIONS for s in ('_ids','_logits','_nll')},'ARRAY_KEYS:'+Path(path).name)
        return {k:z[k] for k in z.files}

def load_process(state,label):
    """Read WORKER.json and every pass npz; each npz must match its manifest sha256 and size."""
    directory=Path(state)/label
    manifest=json.loads((directory/'WORKER.json').read_text())
    require(manifest.get('label')==label,'WORKER_LABEL:'+label)
    passes=[]
    for entry in manifest['passes']:
        path=directory/entry['file']
        ident=identity(path)
        require(ident['sha256']==entry['sha256'] and ident['size']==entry['size'],'PASS_SHA:'+label+'/'+entry['file'])
        require(entry['name'] not in [p['name'] for p in passes],'PASS_DUPLICATE:'+label+'/'+entry['name'])
        passes.append(dict(name=entry['name'],file=entry['file'],identity=ident,arrays=load_arrays(path)))
    require(passes,'NO_PASSES:'+label)
    inputs={name:identity(directory/name) for name in PROCESS_FILES if (directory/name).is_file()}
    return dict(label=label,passes=passes,inputs=inputs,pid=manifest.get('pid'),scope=manifest.get('scope'))

def recomputed_nll(logits,labels):
    x=np.asarray(logits,dtype=np.float64)
    maximum=x.max(1)
    return maximum+np.log(np.exp(x-maximum[:,None]).sum(1))-x[np.arange(len(labels)),labels]

def condition_readout(arrays,condition,bank):
    ids=arrays[condition+'_ids']; logits=arrays[condition+'_logits']; saved=arrays[condition+'_nll']
    n=int(len(ids))
    require(ids.ndim==1 and len(set(ids.tolist()))==n,'IDS:'+condition)
    require(logits.shape==(n,CLASSES) and logits.dtype==np.float32,'LOGITS_SHAPE_DTYPE:'+condition)
    require(saved.shape==(n,),'NLL_SHAPE:'+condition)
    require(all(int(i) in bank['labels'] for i in ids),'TRIAL_NOT_IN_BANK:'+condition)
    labels=np.array([bank['labels'][int(i)] for i in ids],dtype=np.int64)
    finite=bool(np.isfinite(logits).all() and np.isfinite(saved).all())
    predicted=logits.argmax(1)
    hits=predicted==labels
    values,counts=np.unique(predicted,return_counts=True)
    out=dict(n=n,accuracy=float(hits.mean()),correct_count=int(hits.sum()),
             nll_saved_mean=num(saved.astype(np.float64).mean()),
             logit_abs_max=num(np.abs(logits.astype(np.float64)).max()),finite=finite,
             distinct_predicted_classes=int(len(values)),
             most_frequent_predicted_count=int(counts.max()),
             most_frequent_predicted_classes=[int(v) for v in values[counts==counts.max()]],
             most_frequent_predicted_class=(int(values[counts.argmax()]) if int((counts==counts.max()).sum())==1 else None),
             nll_recomputed_float64_mean=None,nll_max_abs_err=None,nll_within_e0_tolerance=False)
    if finite:
        recomputed=recomputed_nll(logits,labels)
        err=np.abs(recomputed-saved.astype(np.float64))
        out.update(nll_recomputed_float64_mean=num(recomputed.mean()),nll_max_abs_err=num(err.max()),
                   nll_within_e0_tolerance=bool(np.allclose(recomputed,saved,atol=NLL_ATOL,rtol=NLL_RTOL)))
    if condition=='correct':
        kinds=np.array([bank['kinds'][int(i)] for i in ids])
        out['by_scene_kind']={k:dict(n=int((kinds==k).sum()),
                                     accuracy=float(hits[kinds==k].mean()) if (kinds==k).any() else None,
                                     correct_count=int(hits[kinds==k].sum())) for k in ('clean','mixed')}
    return out

def control_pairing(arrays,bank):
    """Descriptive correct-minus-shuffled top-1 difference on the control trials. No inference."""
    ids_c=arrays['correct_ids'].tolist(); ids_s=arrays['shuffled_ids'].tolist()
    require(set(ids_s)<=set(ids_c),'CONTROL_NOT_SUBSET')
    position={t:k for k,t in enumerate(ids_c)}
    rows=[position[t] for t in ids_s]
    labels=np.array([bank['labels'][t] for t in ids_s],dtype=np.int64)
    lc=arrays['correct_logits'][rows]; ls=arrays['shuffled_logits']
    ic=(lc.argmax(1)==labels).astype(int); is_=(ls.argmax(1)==labels).astype(int)
    return dict(n=len(ids_s),correct_accuracy_on_control=float(ic.mean()),shuffled_accuracy=float(is_.mean()),
                correct_minus_shuffled_accuracy=float((ic-is_).mean()),
                rows_correct_equals_shuffled_bitwise=int(sum(lc[k].tobytes()==ls[k].tobytes() for k in range(len(ids_s)))))

def bitwise_equal(a,b):
    if set(a)!=set(b): return False
    return all(a[k].dtype==b[k].dtype and a[k].shape==b[k].shape and a[k].tobytes()==b[k].tobytes() for k in a)

def compare_passes(by_name,left,right):
    a=by_name[left]['arrays']['correct_logits']; b=by_name[right]['arrays']['correct_logits']
    a64=a.astype(np.float64); b64=b.astype(np.float64)
    return dict(left=left,right=right,
                bitwise_equal=bool(a.dtype==b.dtype and a.shape==b.shape and a.tobytes()==b.tobytes()),
                argmax_agreement=float((a.argmax(1)==b.argmax(1)).mean()),
                max_abs_logit_diff=num(np.abs(a64-b64).max()))

def readout(state,bank_path,bank_sha=BANK_SHA):
    state=Path(state)
    bank=load_bank(bank_path,bank_sha)
    processes=[load_process(state,label) for label in PROCESSES]
    first=processes[0]['passes'][0]['arrays']
    for proc in processes:
        for p in proc['passes']:
            for c in CONDITIONS:
                require(np.array_equal(p['arrays'][c+'_ids'],first[c+'_ids']),'IDS_ORDER_DIFFERS:'+proc['label']+'/'+p['name'])
    by_name={proc['label']:{p['name']:p for p in proc['passes']} for proc in processes}
    a_names=list(by_name['A']); b_names=list(by_name['B'])
    ab=[dict(pass_name=n,a_file=by_name['A'][n]['file'],b_file=by_name['B'][n]['file'],
             bitwise_equal=bitwise_equal(by_name['A'][n]['arrays'],by_name['B'][n]['arrays'])) for n in a_names if n in by_name['B']]
    ab_equal={r['pass_name']:r['bitwise_equal'] for r in ab}
    rows=[]
    for proc in processes:
        for p in proc['passes']:
            rows.append(dict(process=proc['label'],pass_name=p['name'],file=p['file'],
                             sha256=p['identity']['sha256'],size=p['identity']['size'],sha256_matches_worker=True,
                             a_equals_b=ab_equal.get(p['name']),
                             conditions={c:condition_readout(p['arrays'],c,bank) for c in CONDITIONS},
                             control_pairing=control_pairing(p['arrays'],bank)))
    kinds=np.array([bank['kinds'][int(i)] for i in first['correct_ids']])
    acceptance=None
    if (state/'E0_COMPLETE.json').is_file():
        complete=json.loads((state/'E0_COMPLETE.json').read_text())
        acceptance=dict(status=complete.get('status'),job_id=complete.get('job_id'),
                        scientific_alpha_result=complete.get('scientific_alpha_result'),
                        evaluation_role=complete.get('verification',{}).get('evaluation_role'),
                        release_sha256=complete.get('release_sha256'))
    inputs=dict(bank=dict(bank['identity'],path=str(Path(bank_path)),rows=bank['rows']),
                state={name:identity(state/name) for name in STATE_FILES if (state/name).is_file()},
                processes={proc['label']:dict(proc['inputs'],pid=proc['pid'],scope=proc['scope'],
                           passes={p['file']:p['identity'] for p in proc['passes']}) for proc in processes})
    return dict(status=STATUS,evaluation_role=EVALUATION_ROLE,job_id=acceptance['job_id'] if acceptance else None,
                acceptance=acceptance,
                sample=dict(correct_trials=int(len(first['correct_ids'])),
                            control_trials={c:int(len(first[c+'_ids'])) for c in CONDITIONS[1:]},
                            clean_trials=int((kinds=='clean').sum()),mixed_trials=int((kinds=='mixed').sum()),
                            clean_trial_ids=[int(i) for i,k in zip(first['correct_ids'],kinds) if k=='clean'],
                            total_predictions=int(sum(r['conditions'][c]['n'] for r in rows for c in CONDITIONS))),
                nll_tolerance=dict(atol=NLL_ATOL,rtol=NLL_RTOL,source='05_E0_REAL_MODEL_ACCEPTANCE_PLAN.md §5'),
                passes=rows,
                a_vs_b=dict(shared_passes=ab,all_shared_bitwise_equal=bool(ab) and all(r['bitwise_equal'] for r in ab),
                            a_only=[n for n in a_names if n not in by_name['B']],
                            b_only=[n for n in b_names if n not in by_name['A']]),
                pass_pairs_process_a=[compare_passes(by_name['A'],l,r) for l,r in PAIRS if l in by_name['A'] and r in by_name['A']],
                inputs=inputs,script=dict(file=Path(__file__).name,**identity(Path(__file__))),
                limitation='Descriptive readout of archived arrays: 96 fixed trials, one model, one job, no confidence intervals, no bootstrap, no hypothesis test; not an independent test set and not evidence that the alpha mechanism holds.')

def table_rows(result):
    rows=[]
    for r in result['passes']:
        row=dict(process=r['process'],pass_name=r['pass_name'],file=r['file'],sha256=r['sha256'],
                 sha256_matches_worker=r['sha256_matches_worker'],
                 a_equals_b='' if r['a_equals_b'] is None else r['a_equals_b'])
        for c in CONDITIONS:
            v=r['conditions'][c]
            for key in ('n','accuracy','nll_saved_mean','nll_recomputed_float64_mean','nll_max_abs_err',
                        'nll_within_e0_tolerance','logit_abs_max','finite','distinct_predicted_classes'):
                row[c+'_'+key]=v[key]
        split=r['conditions']['correct']['by_scene_kind']
        for k in ('clean','mixed'):
            row['correct_'+k+'_n']=split[k]['n']; row['correct_'+k+'_accuracy']=split[k]['accuracy']
        row['control_correct_minus_shuffled_accuracy']=r['control_pairing']['correct_minus_shuffled_accuracy']
        row['control_rows_correct_equals_shuffled_bitwise']=r['control_pairing']['rows_correct_equals_shuffled_bitwise']
        rows.append(row)
    return rows

def write_outputs(result,out):
    out=Path(out)
    out.mkdir(parents=True,exist_ok=True)
    json_path=out/'E0_READOUT.json'; csv_path=out/'e0_readout_table.csv'
    csv_text=pd.DataFrame(table_rows(result)).to_csv(index=False,lineterminator='\n')
    with json_path.open('xb') as f: f.write(canonical(result))  # refuse to overwrite evidence
    with csv_path.open('x',encoding='utf-8',newline='') as f: f.write(csv_text)
    return {json_path.name:identity(json_path),csv_path.name:identity(csv_path)}

def run(state,bank,out,bank_sha=BANK_SHA):
    result=readout(state,bank,bank_sha)
    written=write_outputs(result,out)
    return dict(status=result['status'],out=str(Path(out)),written=written,
                total_predictions=result['sample']['total_predictions'],
                all_shared_bitwise_equal=result['a_vs_b']['all_shared_bitwise_equal'],a_only=result['a_vs_b']['a_only'])

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--state',default=str(DEFAULT_STATE),help='collected state/attempt directory containing A/ and B/')
    parser.add_argument('--bank',default=str(DEFAULT_BANK),help='frozen_bank.tsv (sha256 verified)')
    parser.add_argument('--out',required=True,help='output directory (new files only; existing outputs are not overwritten)')
    args=parser.parse_args(argv)
    print(json.dumps(run(args.state,args.bank,args.out),ensure_ascii=False,indent=2))

if __name__=='__main__': main()

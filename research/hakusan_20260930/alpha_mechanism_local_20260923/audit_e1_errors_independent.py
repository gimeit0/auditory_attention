"""Rebuild every role-hit flag from raw outputs; never imports the classifier."""
import csv
from collections import Counter,defaultdict
import json
from pathlib import Path
import tempfile
import numpy as np
from audit_e1_statistics_independent import ROOT,PKG,COL,identity,independent_ci,check_values

ERRORS=ROOT/'error-analysis-750474-0tkyayan'
OVERLAP={3,11,15,2257,2259,2264,4517,4518,4527,6753,6757,6758,6761,6764,9007,9008,9015,9018,9023}
CATS=('label_collision','target','distractor','cue_word','other')

def rebuild(bankrow,pred,domain,condition):
    target=int(bankrow['target_label'])
    distractors=[int(bankrow[f'distractor_{k}_label']) for k in range(1,int(bankrow['distractor_count'])+1)]
    cue_field={'correct':'correct_cue_label','correct_cue':'correct_cue_label',
               'shuffled':'shuffled_cue_label','distractor':'probe_distractor_cue_label'}.get(condition)
    if domain=='main' and condition=='correct' and bankrow['scene_kind']=='clean': cue_field=None
    cue=int(bankrow[cue_field]) if cue_field else None
    flags={'target_hit':pred==target,'distractor_label_hit':pred in distractors,
           'cue_label_hit':cue is not None and pred==cue,'target_distractor_collision':target in distractors}
    hits=[flags['target_distractor_collision'],flags['target_hit'],flags['distractor_label_hit'],flags['cue_label_hit'],True]
    return dict(category=CATS[hits.index(True)],cue_label=cue,
                distractor_cue_overlap_hit=flags['distractor_label_hit'] and flags['cue_label_hit'],**flags)

def main():
    out=Path(tempfile.mkdtemp(prefix='independent-error-audit-750474-',dir=ROOT)); print('OUTPUT='+str(out),flush=True)
    report=json.loads((ERRORS/'REPORT.json').read_bytes())
    sources=dict(report['sources'])
    if any(identity(Path(p))!=v for p,v in sources.items()): raise ValueError('SOURCE_SHA')
    if identity(ERRORS/'ERROR_TRIALS.csv')!=report['trial_file']: raise ValueError('CSV_SHA')
    with (PKG/'frozen_bank.tsv').open() as f: bank={int(r['trial_id']):r for r in csv.DictReader(f,delimiter='\t')}
    expected=[]; grouped=defaultdict(list); lookup={}
    for process in ('A','B'):
        worker=json.loads((COL/'state/attempt'/process/'WORKER.json').read_bytes())
        for artifact in worker['outputs']:
            _,domain,p,condition=artifact['key']
            with np.load(COL/'state/attempt'/process/artifact['file'],allow_pickle=False) as z:
                for tid,pred in zip(z['trial_ids'],z['logits'].argmax(1)):
                    i=int(tid); pred=int(pred); b=bank[i]
                    row=dict(process=process,domain=domain,pass_name=p,condition=condition,scene_kind=b['scene_kind'],
                             trial_id=i,predicted_label=pred,e0_overlap=i in OVERLAP,**rebuild(b,pred,domain,condition))
                    expected.append(row); grouped[process,domain,p,condition].append(row)
                    key=(process,domain,p,condition,i)
                    if key in lookup: raise ValueError('DUPLICATE_RAW_KEY')
                    lookup[key]=row
    with (ERRORS/'ERROR_TRIALS.csv').open() as f: actual=list(csv.DictReader(f))
    if len(actual)!=len(expected) or len(actual)!=38400: raise ValueError('ROW_COUNT')
    for a,e in zip(actual,expected):
        strings={k:'' if v is None else str(v) for k,v in e.items()}
        if a!=strings: raise ValueError('PER_PREDICTION_CLASSIFICATION')
    total_summaries=0; metrics=0
    for process,pr in report['processes'].items():
        for section in ('summaries','scene_summaries'):
            for key,record in pr[section].items():
                parts=key.split('/'); domain,p,cond=parts[:3]
                rows=grouped[process,domain,p,cond]
                if len(parts)==4: rows=[r for r in rows if 'scene_'+r['scene_kind']==parts[3]]
                counts=Counter(r['category'] for r in rows)
                want=dict(trials=len(rows),counts={c:counts[c] for c in CATS},
                          collision_trial_ids=[r['trial_id'] for r in rows if r['target_distractor_collision']],
                          raw_target_hits=sum(r['target_hit'] for r in rows),
                          distractor_cue_overlap_hits=sum(r['distractor_cue_overlap_hit'] for r in rows))
                if want!=record: raise ValueError('SUMMARY: '+key)
                total_summaries+=1
        for group in pr['intervals']:
            ids=group['trial_ids']; stats=group['statistics']; names=list(stats['metrics'])
            vectors=[]
            for name in names:
                parts=name.split('/'); domain,p,cond=parts[:3]; category=parts[-1]
                if len(parts)==5 and any('scene_'+bank[i]['scene_kind']!=parts[3] for i in ids): raise ValueError('SCENE_UNIT')
                vectors.append([100*int(lookup[process,domain,p,cond,i]['category']==category) for i in ids])
            values=np.array(vectors,dtype=float).T
            ci,digest,counts=independent_ci([bank[i]['target_speaker'] for i in ids],values)
            if ci is not None and digest!=stats['info']['shared_draw_indices_sha256']: raise ValueError('DRAW_SHA')
            for j,name in enumerate(names):
                check_values(stats['metrics'][name]['estimate'],values[:,j].mean(),name+'/mean')
                if ci is None:
                    if stats['metrics'][name]['ci95'] is not None: raise ValueError('SMALL_CLUSTER')
                else: check_values(stats['metrics'][name]['ci95'],ci[:,j],name+'/CI')
                metrics+=1
    sources.update({str(ERRORS/'REPORT.json'):identity(ERRORS/'REPORT.json'),
                    str(ERRORS/'ERROR_TRIALS.csv'):identity(ERRORS/'ERROR_TRIALS.csv')})
    if any(identity(Path(p))!=v for p,v in sources.items()): raise ValueError('POST_SHA')
    result=dict(status='INDEPENDENT_ERROR_STRUCTURE_PASS',predictions=len(expected),summaries=total_summaries,
                interval_metrics=metrics,all_raw_flags_checked=True,scene_split_checked=True,
                sources=sources,code=identity(Path(__file__)),scientific_conclusion=False)
    (out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='sources'}))

if __name__=='__main__': main()

"""Word-label error taxonomy, preserving collisions and overlapping roles."""
import numpy as np
from e1_cluster_statistics import bootstrap,OVERLAP

CATEGORIES=('label_collision','target','distractor','cue_word','other')
POLICY=('Target/distractor label-collision trials form a separate category. On other trials '
        'exclusive precedence is target > distractor > cue_word > other. Raw role-hit flags '
        'are retained to expose distractor/cue overlap. This reporting convention does not '
        'change accuracy, trial inclusion, the primary metric, or its bootstrap.')

def label(value):
    if isinstance(value,bool): raise ValueError('LABEL')
    n=int(value)
    if str(n)!=str(value) or not 0<=n<800: raise ValueError('LABEL')
    return n

def classify(row,prediction,domain,condition):
    target=label(row['target_label']); prediction=label(prediction)
    count=int(row['distractor_count'])
    if count not in range(5): raise ValueError('DISTRACTOR_COUNT')
    distractors={label(row[f'distractor_{i}_label']) for i in range(1,count+1)}
    if domain=='clean':
        if count!=0 or row['scene_kind']!='clean': raise ValueError('CLEAN_SEMANTICS')
        if condition not in ('correct_cue','zero_cue'): raise ValueError('CLEAN_CONDITION')
        cue=label(row['correct_cue_label']) if condition=='correct_cue' else None
    elif domain=='main':
        if condition=='correct':
            cue=label(row['correct_cue_label']) if row['scene_kind']!='clean' else None
        elif condition=='shuffled': cue=label(row['shuffled_cue_label'])
        elif condition=='distractor': cue=label(row['probe_distractor_cue_label'])
        elif condition=='silent': cue=None
        else: raise ValueError('MAIN_CONDITION')
    else: raise ValueError('DOMAIN')
    target_hit=prediction==target
    distractor_hit=prediction in distractors
    cue_hit=cue is not None and prediction==cue
    collision=target in distractors
    category=('label_collision' if collision else 'target' if target_hit else
              'distractor' if distractor_hit else 'cue_word' if cue_hit else 'other')
    return dict(category=category,target_hit=target_hit,distractor_label_hit=distractor_hit,
                cue_label_hit=cue_hit,target_distractor_collision=collision,
                distractor_cue_overlap_hit=distractor_hit and cue_hit,cue_label=cue)

def summarize_records(ids,records):
    return dict(trials=len(ids),counts={c:sum(r['category']==c for r in records) for c in CATEGORIES},
                collision_trial_ids=[i for i,r in zip(ids,records) if r['target_distractor_collision']],
                raw_target_hits=sum(r['target_hit'] for r in records),
                distractor_cue_overlap_hits=sum(r['distractor_cue_overlap_hit'] for r in records))

def analyze_errors(arrays,bank):
    rows=[]; summaries={}; scene_summaries={}; groups={}
    for (domain,p,condition),a in arrays.items():
        ids=list(map(int,a['trial_ids'])); pred=a['logits'].argmax(1).tolist()
        key='/'.join((domain,p,condition))
        records=[]
        for i,v in zip(ids,pred):
            rec=classify(bank[i],v,domain,condition)
            rows.append(dict(domain=domain,pass_name=p,condition=condition,scene_kind=bank[i]['scene_kind'],trial_id=i,
                             predicted_label=v,e0_overlap=i in OVERLAP,**rec))
            records.append(rec)
        columns={key+'/'+c:100*np.array([r['category']==c for r in records],dtype=float) for c in CATEGORIES}
        summaries[key]=summarize_records(ids,records)
        # Same ordered analysis unit shares draws across passes/conditions.
        group=groups.setdefault(tuple(ids),{})
        group.update(columns)
        for scene in ('clean','mixed'):
            index=[j for j,i in enumerate(ids) if bank[i]['scene_kind']==scene]
            if not index: continue
            selected_ids=[ids[j] for j in index]; selected_records=[records[j] for j in index]
            scene_key=key+'/scene_'+scene
            scene_summaries[scene_key]=summarize_records(selected_ids,selected_records)
            groups.setdefault(tuple(selected_ids),{}).update({
                scene_key+'/'+c:100*np.array([r['category']==c for r in selected_records],dtype=float)
                for c in CATEGORIES})
    intervals=[]
    for ids,columns in groups.items():
        speakers=[bank[i]['target_speaker'] for i in ids]
        intervals.append(dict(trial_ids=list(ids),statistics=bootstrap(speakers,columns)))
    return dict(status='DESCRIPTIVE_ERROR_TAXONOMY_COMPLETE',policy=POLICY,summaries=summaries,
                scene_summaries=scene_summaries,intervals=intervals,rows=rows,scientific_claim=False)

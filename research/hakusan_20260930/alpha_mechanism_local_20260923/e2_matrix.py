"""Preselected exploratory E2 matrix; no submission authorization."""
import numpy as np
from e0_layout_reference import validate_logits
from e2_catalog import stage_record

STAGES=(0,1,2,4,8,16,24,40)
SCAN_STAGES=(0,4,16,40)
ALPHAS=('alpha_0','alpha_05','alpha_075','alpha_875','alpha_1')

def stage_jobs(layout, rounds, mode='matrix'):
    stage_record(rounds)
    if mode not in ('matrix','cold_alpha1','pilot','pilot_cold') or (mode in ('cold_alpha1','pilot_cold') and rounds!=40):
        raise ValueError('E2_MODE')
    stage_id='completed_epochs_'+str(rounds)
    names=ALPHAS if rounds in SCAN_STAGES and mode in ('matrix','pilot') else ('alpha_1',)
    for domain,conditions in [('main',('correct','shuffled','silent','distractor')),
                              ('clean',('correct_cue','zero_cue'))]:
        for name in names:
            for condition in conditions:
                batches=layout['clean_batches'] if domain=='clean' else layout['main_batches'] if condition=='correct' else layout['control_batches']
                if mode in ('pilot','pilot_cold'):
                    # Empty earlier batches preserve provider batch indices and full batch shape.
                    selected=0 if domain=='clean' else next(i for i,b in enumerate(layout['control_batches']) if b)
                    batches=[list(b) if i==selected else [] for i,b in enumerate(batches)]
                yield (stage_id,domain,name,condition),batches

def expected_records(layout,rounds,mode='matrix'):
    return {key:[i for b in batches for i in b] for key,batches in stage_jobs(layout,rounds,mode)}

def prediction_count(layout):
    return sum(len(ids) for r in STAGES for ids in expected_records(layout,r).values())

def verify_stage_arrays(layout,rounds,records,mode='matrix'):
    expected=expected_records(layout,rounds,mode)
    if set(records)!=set(expected): raise ValueError('E2_RECORD_INVENTORY')
    count=0
    for key,ids in expected.items():
        row=records[key]
        if row['trial_ids']!=ids: raise ValueError('E2_TRIAL_ORDER')
        labels=np.array([layout['labels'][str(i)] for i in ids])
        validate_logits(row['logits'],ids,labels,row['nll'])
        count+=len(ids)
    return dict(status='E2_STAGE_ARRAYS_PASS_NOT_PROVENANCE_OR_BRIDGE',predictions=count,
                completed_epochs=rounds,records=len(expected),production_verified=False)

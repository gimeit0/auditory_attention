"""Exploratory alpha-grid extension (V4: 0.50-0.95); no training or GPU authorization."""
import hashlib
from e1_artifacts import canonical
from e1_inputs import FORMAL_SHA, FREEZE_SHA, BANK_SHA

# V4: fills the unsampled 0.50-0.75 interval of job 756262 at 0.01 (0.50 and 0.75 are re-run as
# bitwise anchors to 756262), plus 0.80/0.85/0.90/0.95 at 0.05. No alpha=0 or alpha=1 science pass:
# alpha=1 is the per-process reference pass, bridged bitwise to 750474.
CODES = (500,) + tuple(range(510, 741, 10)) + (750, 800, 850, 900, 950)
BLOCKS = ('A', 'B')
PER_BLOCK = 15
VALIDATION_PASSES = ('original', 'reference')
CONDITIONS = {'main': ('correct', 'shuffled', 'silent', 'distractor'),
              'clean': ('correct_cue', 'zero_cue')}
PREDICTIONS_PER_PASS = 3600      # 2000 main correct + 3 x 400 control + 2 x 200 clean (checked in contract())
SCIENCE_PREDICTIONS = len(CODES) * PREDICTIONS_PER_PASS
PREDICTIONS = (len(CODES) + len(VALIDATION_PASSES) * len(BLOCKS)) * PREDICTIONS_PER_PASS
SCOPE = 'FINE_ALPHA_002_20260929_V4'
REMOTE = '/home/s2510040/audattn_fine_alpha/fine_alpha_20260929_v4'
BUDGET = dict(gpus=1, gpu_type='a100', cpus=8, host_memory_gib=64,
              wall_minutes=240, coordinator_deadline_seconds=13800,
              worker_deadline_seconds=7800, verify_reserve_seconds=300)

def name(code):
    if type(code) is not int or code not in CODES:
        raise ValueError('FINE_ALPHA_CODE')
    return f'alpha_{code:04d}'

def decode(pass_name):
    for code in CODES:
        if name(code) == pass_name:
            return code / 1000
    raise ValueError('FINE_ALPHA_NAME')

def passes(block):
    if block not in BLOCKS:
        raise ValueError('FINE_ALPHA_BLOCK')
    start = BLOCKS.index(block) * PER_BLOCK
    return VALIDATION_PASSES + tuple(name(c) for c in CODES[start:start + PER_BLOCK])

def batches(layout, domain, condition):
    if domain not in CONDITIONS or condition not in CONDITIONS[domain]:
        raise ValueError('FINE_CONDITION')
    return layout['clean_batches'] if domain == 'clean' else layout[
        'main_batches' if condition == 'correct' else 'control_batches']

def inventory(layout, block=None):
    if block is not None and block not in BLOCKS:
        raise ValueError('FINE_ALPHA_BLOCK')
    return {(b, domain, p, condition): [i for batch in batches(layout, domain, condition) for i in batch]
            for b in (BLOCKS if block is None else (block,)) for p in passes(b)
            for domain, conditions in CONDITIONS.items() for condition in conditions}

def check_production_counts(spec):
    """The real E1 layout must give exactly the frozen V4 counts (synthetic test layouts are smaller)."""
    if spec['predictions'] != PREDICTIONS or spec['science_predictions'] != SCIENCE_PREDICTIONS:
        raise ValueError('FINE_PREDICTION_COUNTS')
    return spec

def contract(layout):
    counts = {b: sum(map(len, inventory(layout, b).values())) for b in BLOCKS}
    per_pass = sum(len(v) for k, v in inventory(layout, BLOCKS[0]).items() if k[2] == 'reference')
    science = len(CODES)*per_pass
    return dict(scope=SCOPE, alpha_integer_milli=list(CODES), alpha_denominator=1000,
                formula='1-alpha*(1-g)', model_id='formal40', checkpoint_sha256=FORMAL_SHA,
                bank_sha256=BANK_SHA, data_freeze_sha256=FREEZE_SHA,
                layout_sha256=hashlib.sha256(canonical(layout)).hexdigest(),
                process_order=list(BLOCKS), block_passes={b: list(passes(b)) for b in BLOCKS},
                predictions=sum(counts.values()), block_predictions=counts,
                science_predictions=science, budget=BUDGET, historical_job='750474',
                anchor_job='756262', anchor_alpha_integer_milli=[500, 750],
                evaluation_role='EXPLORATORY_REUSED_VALIDATION_BANK_NOT_INDEPENDENT_TEST',
                age_mapping_validated=False, training=False)

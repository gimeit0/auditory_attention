"""Exploratory low-alpha extension; no training or GPU authorization."""
import hashlib
from e1_artifacts import canonical
from e1_inputs import FORMAL_SHA, FREEZE_SHA, BANK_SHA

CODES = tuple(range(0, 501, 10)) + (750, 875, 1000)
BLOCKS = ('A', 'B', 'C')
CONDITIONS = {'main': ('correct', 'shuffled', 'silent', 'distractor'),
              'clean': ('correct_cue', 'zero_cue')}
SCOPE = 'FINE_ALPHA_001_20260928_V1'
REMOTE = '/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v1'
BUDGET = dict(gpus=1, gpu_type='a100', cpus=8, host_memory_gib=64,
              wall_minutes=360, coordinator_deadline_seconds=21000,
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
    start = BLOCKS.index(block) * 18
    return ('original', 'reference') + (('explicit_bypass',) if block == 'A' else ()) + tuple(
        name(c) for c in CODES[start:start + 18])

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

def contract(layout):
    counts = {b: sum(map(len, inventory(layout, b).values())) for b in BLOCKS}
    return dict(scope=SCOPE, alpha_integer_milli=list(CODES), alpha_denominator=1000,
                formula='1-alpha*(1-g)', model_id='formal40', checkpoint_sha256=FORMAL_SHA,
                bank_sha256=BANK_SHA, data_freeze_sha256=FREEZE_SHA,
                layout_sha256=hashlib.sha256(canonical(layout)).hexdigest(),
                process_order=list(BLOCKS), block_passes={b: list(passes(b)) for b in BLOCKS},
                predictions=sum(counts.values()), block_predictions=counts,
                science_predictions=len(CODES)*sum(len(v) for k, v in inventory(layout, 'A').items() if k[2] == 'reference'),
                budget=BUDGET, historical_job='750474',
                evaluation_role='EXPLORATORY_REUSED_VALIDATION_BANK_NOT_INDEPENDENT_TEST',
                age_mapping_validated=False, training=False)

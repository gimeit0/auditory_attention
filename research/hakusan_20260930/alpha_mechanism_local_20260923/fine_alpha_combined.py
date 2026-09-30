"""Combined 0-1 alpha curve: job 756262 (0-0.50 at 0.01, .75, .875, 1) + job 757288 (0.51-0.74 at 0.01, .80-.95).

0.50 and 0.75 exist in both jobs and must be bitwise identical (anchors); the combined curve takes them from
756262. The unmodified ("original") pass must also be bitwise identical across the two jobs. Statistics reuse the
E1 contract machinery (summaries, collapse rule, target-speaker cluster bootstrap: PCG64 seed 20260926, 10,000
draws, shared draws within a unit). Pointwise intervals only; nothing is smoothed; alpha is not mapped to age.
"""
import numpy as np
from e1_cluster_statistics import bootstrap, OVERLAP
from e1_secondary_statistics import summarize, collapse
from e1_error_structure import classify, CATEGORIES
from analyze_e1_primary import align

MAIN = ('correct', 'shuffled', 'silent', 'distractor')
CLEAN = ('correct_cue', 'zero_cue')
OLD = tuple(range(0, 501, 10)) + (750, 875, 1000)                                   # job 756262
NEW = (500,) + tuple(range(510, 741, 10)) + (750, 800, 850, 900, 950)                  # job 757288
GRID = tuple(sorted(set(OLD) | set(NEW)))                                             # 82 points
FINE_REGION = tuple(c for c in GRID if c <= 750)                                      # 0-0.75 at 0.01 (76 points)
OLD_BLOCK = {c: 'A' if i < 18 else 'B' if i < 36 else 'C' for i, c in enumerate(OLD)}
NEW_BLOCK = {c: 'A' if i < 15 else 'B' for i, c in enumerate(NEW)}
LEVELS_PP = (1.0, 5.0, 10.0)
RELATIVE = (0.25, 0.5, 0.75, 0.9)


def code(c): return f'alpha_{c:04d}'
def value(c): return c/1000


def assemble(old_blocks, new_blocks):
    """Combined arrays keyed (domain, code_name, condition), plus the cross-job identity checks."""
    arrays = {}; source = {}
    for c in GRID:
        use_old = c in OLD
        blocks, block = (old_blocks, OLD_BLOCK[c]) if use_old else (new_blocks, NEW_BLOCK[c])
        for d, conds in (('main', MAIN), ('clean', CLEAN)):
            for cond in conds: arrays[d, code(c), cond] = blocks[block][block, d, code(c), cond]
        source[code(c)] = ('756262' if use_old else '757288', block)
    checks = {}
    for d, conds in (('main', MAIN), ('clean', CLEAN)):
        for cond in conds:
            arrays[d, 'original', cond] = old_blocks['A']['A', d, 'original', cond]
            a, b = old_blocks['A']['A', d, 'original', cond], new_blocks['A']['A', d, 'original', cond]
            checks[f'original_cross_job/{d}/{cond}'] = all(np.array_equal(a[k], b[k]) for k in ('trial_ids', 'logits', 'nll'))
    return arrays, source, checks


def labels_of(ids, bank): return np.array([int(bank[i]['target_label']) for i in ids])


def indicators(arrays, domain, p, cond, ids, bank):
    a = arrays[domain, p, cond]
    logits = align(a['trial_ids'], ids, a['logits']); nll = align(a['trial_ids'], ids, a['nll'].astype(np.float64))
    return (logits.argmax(1) == labels_of(ids, bank)).astype(np.float64), nll


def unit(ids, columns, bank):
    r = bootstrap([bank[i]['target_speaker'] for i in ids], columns)
    r['trial_ids'] = list(ids); r['e0_overlap_trial_ids'] = [i for i in ids if i in OVERLAP]
    r['inference'] = 'DESCRIPTIVE_POINTWISE_NOT_SIMULTANEOUS'
    return r


def subset_summaries(arrays, ids, bank):
    out = {}
    for p in (*map(code, GRID), 'original'):
        a = arrays['main', p, 'correct']
        out[p] = summarize(align(a['trial_ids'], ids, a['logits']), align(a['trial_ids'], ids, a['nll']), labels_of(ids, bank))
    return out


def sustained_onset(values, curve, level):
    """Smallest grid alpha from which the curve stays >= level up to alpha=1 (None if never)."""
    ok = np.asarray(curve) >= level
    for j in range(len(curve)):
        if ok[j:].all(): return values[j]
    return None


def transitions(arrays, ids, bank, seed=20260926, replicates=10000):
    """Exploratory, not preregistered: sustained-onset alphas and the steepest 0.01 step, target-speaker bootstrap."""
    speakers = [bank[i]['target_speaker'] for i in ids]
    unique, index, counts = np.unique(speakers, return_inverse=True, return_counts=True)
    names = [*map(code, GRID), 'original']
    acc = np.column_stack([indicators(arrays, 'main', p, 'correct', ids, bank)[0] for p in names])
    sums = np.zeros((len(unique), acc.shape[1])); np.add.at(sums, index, acc)
    vals = [value(c) for c in GRID]
    fine_idx = [GRID.index(c) for c in FINE_REGION]
    def describe(curve, original):
        out = {f'{x:g}pp': sustained_onset(vals, curve, x) for x in LEVELS_PP}
        out.update({f'{r:g}_of_original': sustained_onset(vals, curve, r*original) for r in RELATIVE})
        steps = np.diff(curve[fine_idx])
        j = int(steps.argmax()); out['steepest_step_from'] = value(FINE_REGION[j]); out['steepest_step_pp'] = float(steps[j])
        return out
    point_curve = 100*acc.mean(0)
    point = describe(point_curve[:-1], point_curve[-1])
    rng = np.random.default_rng(seed); draws = {k: [] for k in point}
    for _ in range(replicates):
        s = rng.integers(0, len(unique), size=len(unique))
        both = 100*sums[s].sum(0)/counts[s].sum()
        for k, v in describe(both[:-1], both[-1]).items(): draws[k].append(v)
    intervals = {}
    for k, v in point.items():
        if k == 'steepest_step_pp':
            x = np.array(draws[k]); intervals[k] = [float(np.quantile(x, .025)), float(np.quantile(x, .975))]; continue
        reached = np.array([d for d in draws[k] if d is not None])
        intervals[k] = dict(not_reached=int(replicates-len(reached)),
                            interval_95=([float(np.quantile(reached, .025, method='lower')), float(np.quantile(reached, .975, method='higher'))]
                                         if len(reached) == replicates else None))
    steps = np.diff(point_curve[:-1])
    return dict(point=point, bootstrap=intervals, trials=len(ids), seed=seed, replicates=replicates,
                monotonicity=dict(decreasing_steps=int(np.sum(steps < 0)),
                                  decreases=[dict(from_alpha=vals[j], to_alpha=vals[j+1], change_pp=float(steps[j]))
                                             for j in np.flatnonzero(steps < 0)]),
                method=('sustained onset on the full 0-1 grid (smallest grid alpha after which accuracy never falls below the '
                        'level); steepest step within the 0.01-spaced 0-0.75 region; relative levels paired per draw; '
                        'grid-valued intervals use lower/higher quantiles; exploratory, not preregistered'))


def collapse_boundary(partition):
    """Smallest grid alpha from which every larger grid alpha is collapse-free, separately per criterion."""
    out = {}
    for crit in ('accuracy_below_half_original', 'logit_above_ten_times_original', 'collapse'):
        flags = [partition[code(c)][crit] for c in GRID]
        onset = None
        for j in range(len(GRID)):
            if not any(flags[j:]): onset = value(GRID[j]); break
        last = max((value(c) for c, f in zip(GRID, flags) if f), default=None)
        out[crit] = dict(first_free_alpha=onset, last_flagged_alpha=last)
    return out


def analyze(arrays, bank):
    main_ids = list(map(int, arrays['main', 'original', 'correct']['trial_ids']))
    control = list(map(int, arrays['main', 'original', 'shuffled']['trial_ids']))
    clean = list(map(int, arrays['clean', 'original', 'correct_cue']['trial_ids']))
    mixed = [i for i in main_ids if bank[i]['scene_kind'] == 'mixed']
    if (len(main_ids), len(control), len(clean), len(mixed)) != (2000, 400, 200, 1800): raise ValueError('UNIT_SIZES')
    names = [*map(code, GRID), 'original']
    mixed_summ = subset_summaries(arrays, mixed, bank)
    mixed_partition = {p: collapse(mixed_summ[p], mixed_summ['original']) for p in map(code, GRID)}
    pooled = {p: summarize(arrays['main', p, 'correct']['logits'], arrays['main', p, 'correct']['nll'],
                           labels_of(list(map(int, arrays['main', p, 'correct']['trial_ids'])), bank)) for p in names}
    pooled_partition = {p: collapse(pooled[p], pooled['original']) for p in map(code, GRID)}
    units = {}
    cols = {}
    for p in names:
        a, n = indicators(arrays, 'main', p, 'correct', mixed, bank); cols[p+'/accuracy_pp'] = 100*a; cols[p+'/nll'] = n
    units['main_mixed'] = unit(mixed, cols, bank)
    keep = np.array([i not in OVERLAP for i in mixed])
    units['main_mixed_excluding_e0_overlap'] = unit(np.array(mixed)[keep].tolist(), {k: v[keep] for k, v in cols.items()}, bank)
    ccols = {}
    for p in names:
        c, nc = indicators(arrays, 'main', p, 'correct', control, bank)
        for cond in MAIN:
            a, n = indicators(arrays, 'main', p, cond, control, bank)
            ccols[f'{p}/{cond}/accuracy_pp'] = 100*a
            if cond != 'correct': ccols[f'{p}/correct_minus_{cond}/accuracy_pp'] = 100*(c-a)
    units['control'] = unit(control, ccols, bank)
    kcols = {}
    for p in names:
        ca, cn = indicators(arrays, 'clean', p, 'correct_cue', clean, bank); za, zn = indicators(arrays, 'clean', p, 'zero_cue', clean, bank)
        kcols[f'{p}/correct_cue/accuracy_pp'] = 100*ca; kcols[f'{p}/zero_cue/accuracy_pp'] = 100*za
        kcols[f'{p}/correct_minus_zero/accuracy_pp'] = 100*(ca-za)
    units['clean'] = unit(clean, kcols, bank)
    snr = {}
    for b in range(5):
        ids = [i for i in mixed if int(bank[i]['snr_bin']) == b]
        edges = {(bank[i]['snr_bin_low'], bank[i]['snr_bin_high']) for i in ids}
        if len(ids) != 360 or len(edges) != 1: raise ValueError('SNR_BIN')
        sc = {}
        for p in names:
            a, n = indicators(arrays, 'main', p, 'correct', ids, bank); sc[p+'/accuracy'] = a; sc[p+'/cross_entropy_nats'] = n
        low, high = (float(x) for x in edges.pop())
        snr[str(b)] = dict(snr_db=[low, high], trials=len(ids), statistics=unit(ids, sc, bank))
    errors = {}
    for p in map(code, GRID):
        a = arrays['main', p, 'correct']; ids = list(map(int, a['trial_ids'])); pred = a['logits'].argmax(1).tolist()
        recs = [classify(bank[i], v, 'main', 'correct') for i, v in zip(ids, pred) if bank[i]['scene_kind'] == 'mixed']
        errors[p] = {c: sum(r['category'] == c for r in recs) for c in CATEGORIES}
    return dict(status='FINE_ALPHA_COMBINED_DESCRIPTIVE_READOUT_NOT_AGE_MAPPED', scientific_labels=[],
                research_role='EXPLORATORY_REUSED_VALIDATION_BANK_SINGLE_FORMAL40_MODEL',
                grid=[value(c) for c in GRID], main_mixed_summaries=mixed_summ, main_pooled_summaries=pooled,
                collapse_mixed=mixed_partition, collapse_pooled=pooled_partition,
                collapse_boundary=dict(mixed=collapse_boundary(mixed_partition), pooled=collapse_boundary(pooled_partition)),
                units=units, snr_bins=snr, error_counts_mixed=errors,
                transitions=dict(mixed=transitions(arrays, mixed, bank), pooled=transitions(arrays, main_ids, bank)),
                age_mapping_validated=False)

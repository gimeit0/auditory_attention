"""54-point fine-alpha readout statistics (doc 46 §4). Descriptive only; no GPU/network.

Reuses the E1 contract machinery unchanged: per-array summaries and collapse rule
(e1_secondary_statistics), target-speaker cluster bootstrap (e1_cluster_statistics:
seed 20260926, PCG64, 10000 draws, shared draws within a unit), and the word-label
error taxonomy (e1_error_structure). Nothing here smooths the curve, drops grid
points, or maps alpha to age.
"""
import numpy as np
from e1_cluster_statistics import bootstrap, OVERLAP
from e1_secondary_statistics import summarize, collapse
from e1_error_structure import classify, CATEGORIES
from analyze_e1_primary import align

CODES = tuple(f'alpha_{m:04d}' for m in (*range(0, 501, 10), 750, 875, 1000))
FINE = CODES[:51]
MAIN = ('correct', 'shuffled', 'silent', 'distractor')
CLEAN = ('correct_cue', 'zero_cue')
BLOCK_OF = {c: 'A' if i < 18 else 'B' if i < 36 else 'C' for i, c in enumerate(CODES)}
E1_BRIDGE = {'alpha_0': 'alpha_0000', 'alpha_05': 'alpha_0500', 'alpha_075': 'alpha_0750',
             'alpha_875': 'alpha_0875', 'alpha_1': 'alpha_1000'}
# Accuracy levels (percent) for exploratory first-passage points on the main/correct curve.
ACCURACY_LEVELS_PP = (1.0, 5.0, 10.0)
RELATIVE_LEVELS = (0.25, 0.5)          # fractions of the unmodified (original) accuracy


def value(code): return int(code[6:]) / 1000


def check_grid(arrays):
    missing = [(d, p, c) for p in CODES for d, conds in (('main', MAIN), ('clean', CLEAN)) for c in conds
               if (d, p, c) not in arrays]
    if missing: raise ValueError(f'MISSING_ARRAYS {missing[:3]}')
    ids = {}
    for (d, p, c), a in arrays.items():
        key = (d, c)
        t = tuple(map(int, a['trial_ids']))
        if len(t) != len(set(t)): raise ValueError('DUPLICATE_TRIAL')
        if ids.setdefault(key, t) != t: raise ValueError(f'TRIAL_ORDER {d}/{c}/{p}')
    return ids


def labels_of(ids, bank): return np.array([int(bank[i]['target_label']) for i in ids])


def indicators(arrays, domain, p, cond, ids, bank):
    a = arrays[domain, p, cond]
    logits = align(a['trial_ids'], ids, a['logits'])
    nll = align(a['trial_ids'], ids, a['nll'].astype(np.float64))
    return (logits.argmax(1) == labels_of(ids, bank)).astype(np.float64), nll


def unit(ids, columns, bank):
    r = bootstrap([bank[i]['target_speaker'] for i in ids], columns)
    r['trial_ids'] = list(ids)
    r['e0_overlap_trial_ids'] = [i for i in ids if i in OVERLAP]
    r['inference'] = 'DESCRIPTIVE_POINTWISE_NOT_SIMULTANEOUS'
    return r


def with_sensitivity(name, ids, columns, bank, units):
    units[name] = unit(ids, columns, bank)
    mask = np.array([i not in OVERLAP for i in ids])
    units[name+'_excluding_e0_overlap'] = unit(np.array(ids)[mask].tolist(), {k: v[mask] for k, v in columns.items()}, bank)


def main_columns(arrays, ids, bank):
    cols = {}
    for p in CODES:
        a, n = indicators(arrays, 'main', p, 'correct', ids, bank)
        cols[p+'/accuracy_pp'] = 100*a; cols[p+'/nll'] = n
    return cols


def control_columns(arrays, ids, bank):
    cols = {}; effect = {}
    for p in CODES:
        c, nc = indicators(arrays, 'main', p, 'correct', ids, bank)
        for cond in MAIN:
            a, n = indicators(arrays, 'main', p, cond, ids, bank)
            cols[f'{p}/{cond}/accuracy_pp'] = 100*a; cols[f'{p}/{cond}/nll'] = n
            if cond != 'correct':
                effect[p, cond] = c-a
                cols[f'{p}/correct_minus_{cond}/accuracy_pp'] = 100*(c-a)
                cols[f'{p}/correct_minus_{cond}/nll'] = nc-n
    # D_alpha keeps the measured alpha=0 residual (not forced to zero), as in E1.
    for p in CODES:
        cols[f'{p}/D_pp'] = 100*(effect[p, 'shuffled']-effect['alpha_0000', 'shuffled'])
    return cols


def clean_columns(arrays, ids, bank):
    cols = {}
    for p in CODES:
        ca, cn = indicators(arrays, 'clean', p, 'correct_cue', ids, bank)
        za, zn = indicators(arrays, 'clean', p, 'zero_cue', ids, bank)
        cols[f'{p}/correct_cue/accuracy_pp'] = 100*ca; cols[f'{p}/correct_cue/nll'] = cn
        cols[f'{p}/zero_cue/accuracy_pp'] = 100*za; cols[f'{p}/zero_cue/nll'] = zn
        cols[f'{p}/correct_minus_zero/accuracy_pp'] = 100*(ca-za); cols[f'{p}/correct_minus_zero/nll'] = cn-zn
    return cols


def first_passage(curve, level):
    """Smallest fine-grid alpha from which the curve stays >= level for the rest of the 0-0.50 grid."""
    curve = np.asarray(curve, dtype=np.float64)
    ok = curve >= level
    for j in range(len(curve)):
        if ok[j:].all(): return value(FINE[j])
    return None


def monotonicity(curve):
    d = np.diff(np.asarray(curve, dtype=np.float64))
    down = np.flatnonzero(d < 0)
    return dict(steps=int(len(d)), decreasing_steps=int(len(down)),
                decreases=[dict(from_alpha=value(FINE[j]), to_alpha=value(FINE[j+1]), change=float(d[j])) for j in down],
                largest_increase=dict(from_alpha=value(FINE[int(d.argmax())]), to_alpha=value(FINE[int(d.argmax())+1]),
                                      change=float(d.max())))


def passage_intervals(ids, arrays, bank, seed=20260926, replicates=10000):
    """Exploratory: bootstrap distribution of first-passage alphas, resampling target speakers with the
    contract generator. Relative levels are recomputed in every draw from the SAME resampled trials of the
    unmodified (original) pass, so numerator and denominator stay paired. A passage never reached in a draw
    is counted as 'not reached'. Because alpha is grid-valued, the interval uses the conservative
    'lower'/'higher' quantiles (always grid points) instead of linear interpolation."""
    speakers = [bank[i]['target_speaker'] for i in ids]
    unique, index, counts = np.unique(speakers, return_inverse=True, return_counts=True)
    acc = np.column_stack([indicators(arrays, 'main', p, 'correct', ids, bank)[0] for p in (*FINE, 'original')])
    sums = np.zeros((len(unique), acc.shape[1])); np.add.at(sums, index, acc)
    absolute = {f'{x:g}pp': x for x in ACCURACY_LEVELS_PP}
    relative = {f'{r:g}_of_original': r for r in RELATIVE_LEVELS}
    rng = np.random.default_rng(seed)
    draws = {k: [] for k in (*absolute, *relative)}
    for _ in range(replicates):
        sampled = rng.integers(0, len(unique), size=len(unique))
        both = 100*sums[sampled].sum(0)/counts[sampled].sum()
        curve, original = both[:-1], both[-1]
        for k, lv in absolute.items(): draws[k].append(first_passage(curve, lv))
        for k, r in relative.items(): draws[k].append(first_passage(curve, r*original))
    point = 100*acc.mean(0); out = {}
    for k in draws:
        lv = absolute[k] if k in absolute else relative[k]*point[-1]
        reached = np.array([d for d in draws[k] if d is not None])
        out[k] = dict(level_pp_at_point_estimate=float(lv), point=first_passage(point[:-1], lv),
                      draws_not_reached=int(replicates-len(reached)),
                      draws_at_last_two_grid_points=int(np.sum(reached >= 0.49)) if len(reached) else 0,
                      interval_95=([float(np.quantile(reached, .025, method='lower')), float(np.quantile(reached, .975, method='higher'))]
                                   if len(reached) == replicates else None))
    return dict(method=('exploratory onset of sustained exceedance on the 0-0.50 grid (right-censored at 0.50); '
                        'target_speaker bootstrap, relative levels paired per draw; lower/higher quantiles; not preregistered'),
                trials=len(ids), seed=seed, replicates=replicates, levels=out)


def probe_label(row):
    position = int(row['probe_distractor_position'])
    return int(row[f'distractor_{position}_label']) if position > 0 else None


def error_structure(arrays, bank):
    """Word-label taxonomy for every array, plus (main/correct) scene-kind and SNR x distractor-count splits.
    probe_hit is a raw flag: prediction equals the label of the distractor whose cue is used as the probe."""
    counts = {}; mixed_columns = {}; by_scene = {}; by_cell = {}
    for p in CODES:
        for d, conds in (('main', MAIN), ('clean', CLEAN)):
            for cond in conds:
                a = arrays[d, p, cond]; ids = list(map(int, a['trial_ids'])); pred = a['logits'].argmax(1).tolist()
                recs = [classify(bank[i], v, d, cond) for i, v in zip(ids, pred)]
                row = {c: sum(r['category'] == c for r in recs) for c in CATEGORIES}
                if d == 'main':
                    row['probe_distractor_hit'] = sum(bank[i]['scene_kind'] == 'mixed' and v == probe_label(bank[i])
                                                      for i, v in zip(ids, pred))
                counts[f'{d}/{p}/{cond}'] = row
                if (d, cond) != ('main', 'correct'): continue
                for scene in ('clean', 'mixed'):
                    sel = [r for i, r in zip(ids, recs) if bank[i]['scene_kind'] == scene]
                    by_scene[f'{p}/{scene}'] = dict(n=len(sel), **{c: sum(r['category'] == c for r in sel) for c in CATEGORIES})
                mixed = [(i, r) for i, r in zip(ids, recs) if bank[i]['scene_kind'] == 'mixed']
                for c in CATEGORIES:
                    mixed_columns[f'{p}/{c}_pp'] = 100*np.array([r['category'] == c for _, r in mixed], float)
                for i, r in mixed:
                    cell = f"snr{bank[i]['snr_bin']}_distractors{bank[i]['distractor_count']}"
                    by_cell.setdefault(f'{p}/{cell}', {c: 0 for c in CATEGORIES})[r['category']] += 1
    mixed_ids = [i for i in map(int, arrays['main', 'original', 'correct']['trial_ids']) if bank[i]['scene_kind'] == 'mixed']
    return counts, mixed_ids, mixed_columns, by_scene, by_cell


def alpha0_residual(arrays, control, bank):
    """Contract 29 section 2: measured alpha=0 correct-vs-shuffled residual on the control trials."""
    c, nc = indicators(arrays, 'main', 'alpha_0000', 'correct', control, bank)
    s_, ns = indicators(arrays, 'main', 'alpha_0000', 'shuffled', control, bank)
    pc = align(arrays['main', 'alpha_0000', 'correct']['trial_ids'], control, arrays['main', 'alpha_0000', 'correct']['logits']).argmax(1)
    ps = align(arrays['main', 'alpha_0000', 'shuffled']['trial_ids'], control, arrays['main', 'alpha_0000', 'shuffled']['logits']).argmax(1)
    r0 = c-s_; dis = pc != ps; nll = nc-ns
    return dict(top1_indicator_nonzero=int(np.count_nonzero(r0)), prediction_disagreements=int(dis.sum()),
                prediction_disagreement_trial_ids=np.array(control)[dis].tolist(),
                nll_mean=float(nll.mean()), nll_std_ddof0=float(nll.std(ddof=0)), nll_max_abs=float(np.abs(nll).max()),
                flag='MAIN_CROSS_BATCH_RESIDUAL_PRESENT' if np.count_nonzero(r0) else None)


def subset_summaries(arrays, ids, bank):
    out = {}
    for p in (*CODES, 'original'):
        a = arrays['main', p, 'correct']
        out[p] = summarize(align(a['trial_ids'], ids, a['logits']), align(a['trial_ids'], ids, a['nll']), labels_of(ids, bank))
    return out


def analyze(arrays, bank, e1_arrays=None):
    ids = check_grid(arrays)
    main_ids = list(ids['main', 'correct']); control = list(ids['main', 'shuffled']); clean = list(ids['clean', 'correct_cue'])
    if (len(main_ids), len(control), len(clean)) != (2000, 400, 200): raise ValueError('UNIT_SIZES')
    summaries = {}
    for (d, p, c), a in arrays.items():
        summaries[f'{d}/{p}/{c}'] = summarize(a['logits'], a['nll'], labels_of(list(map(int, a['trial_ids'])), bank))
    partitions = {}
    for d, correct in (('main', 'correct'), ('clean', 'correct_cue')):
        original = summaries[f'{d}/original/{correct}']
        for p in CODES: partitions[f'{d}/{p}'] = collapse(summaries[f'{d}/{p}/{correct}'], original)
    units = {}
    mc = main_columns(arrays, main_ids, bank)
    with_sensitivity('main_correct_all', main_ids, mc, bank, units)
    for kind in ('clean', 'mixed'):
        m = np.array([bank[i]['scene_kind'] == kind for i in main_ids])
        with_sensitivity('main_correct_'+kind, np.array(main_ids)[m].tolist(), {k: v[m] for k, v in mc.items()}, bank, units)
    control_cols = control_columns(arrays, control, bank)
    with_sensitivity('control', control, control_cols, bank, units)
    with_sensitivity('clean', clean, clean_columns(arrays, clean, bank), bank, units)
    strata = {}
    for snr in range(5):
        for count in range(1, 5):
            name = f'snr{snr}_distractors{count}'
            m = np.array([int(bank[i]['snr_bin']) == snr and int(bank[i]['distractor_count']) == count for i in main_ids])
            cm = np.array([int(bank[i]['snr_bin']) == snr and int(bank[i]['distractor_count']) == count for i in control])
            if cm.sum() != 20: raise ValueError('CONTROL_STRATUM_QUOTA')
            strata[name] = unit(np.array(main_ids)[m].tolist(), {k: v[m] for k, v in mc.items() if k.endswith('accuracy_pp')}, bank)
            strata[name+'/control'] = unit(np.array(control)[cm].tolist(),
                                           {k: v[cm] for k, v in control_cols.items() if '/correct_minus_' in k and k.endswith('accuracy_pp')}, bank)
    counts, mixed_ids, err_cols, err_scene, err_cells = error_structure(arrays, bank)
    if len(mixed_ids) != 1800: raise ValueError('MIXED_SIZE')
    units['main_mixed_error_categories'] = unit(mixed_ids, err_cols, bank)
    mixed_summaries = subset_summaries(arrays, mixed_ids, bank)
    transitions = {}
    for label, subset, summ in (('main_mixed_correct_cue', mixed_ids, mixed_summaries),
                                ('main_all_pooled', main_ids, {p: summaries[f'main/{p}/correct'] for p in (*CODES, 'original')})):
        curve = [100*summ[p]['accuracy'] for p in FINE]
        transitions[label] = dict(monotonicity=monotonicity(curve), first_passage=passage_intervals(subset, arrays, bank),
                                  original_accuracy_pp=100*summ['original']['accuracy'])
    transitions['collapse_free_fine_points'] = [value(p) for p in FINE if not partitions[f'main/{p}']['collapse']]
    transitions['collapse_free_all_points'] = [value(p) for p in CODES if not partitions[f'main/{p}']['collapse']]
    mixed_partition = {p: collapse(mixed_summaries[p], mixed_summaries['original']) for p in CODES}
    transitions['mixed_collapse_free_all_points'] = [value(p) for p in CODES if not mixed_partition[p]['collapse']]
    bridge = None
    if e1_arrays is not None:
        bridge = {}
        for old, new in E1_BRIDGE.items():
            for d, conds in (('main', MAIN), ('clean', CLEAN)):
                for c in conds:
                    a, b = e1_arrays.get((d, old, c)), arrays[d, new, c]
                    if a is None: continue
                    same_ids = np.array_equal(a['trial_ids'], b['trial_ids'])
                    bridge[f'{d}/{old}->{new}/{c}'] = dict(
                        same_trial_order=bool(same_ids),
                        bitwise_logits=bool(same_ids and np.array_equal(a['logits'], b['logits'])),
                        max_abs_logit_difference=float(np.abs(a['logits'].astype(np.float64)-b['logits'].astype(np.float64)).max())
                        if same_ids else None,
                        accuracy_e1=summaries_of(a, bank)['accuracy'], accuracy_fine=summaries[f'{d}/{new}/{c}']['accuracy'])
    return dict(status='FINE_ALPHA_DESCRIPTIVE_READOUT_NOT_AGE_MAPPED', scientific_labels=[],
                research_role='EXPLORATORY_REUSED_VALIDATION_BANK_SINGLE_FORMAL40_MODEL',
                grid=[value(p) for p in CODES], summaries=summaries, main_mixed_summaries=mixed_summaries,
                collapse=partitions, main_mixed_collapse=mixed_partition, units=units,
                strata=strata, error_counts=counts, error_by_scene=err_scene, error_by_mixed_cell=err_cells,
                alpha0_residual=alpha0_residual(arrays, control, bank), transitions=transitions, e1_bridge=bridge,
                semantics=dict(main_correct_pooled=('main/correct has 2000 trials: 1800 mixed scenes with the correct cue and '
                                                    '200 clean scenes whose "correct" column is the old ZERO-cue semantics '
                                                    '(contract 28 section 5.6; doc 33). Primary correct-cue curve = 1800 mixed.'),
                               strata='SNR x distractor-count strata contain only mixed scenes (20 cells x 90 main, 20 control each).'),
                deviations_from_plan=[
                    'Error categories use any-distractor precedence (E1 taxonomy); the probe distractor is a separate raw hit count, not an exclusive category.',
                    'Error structure per SNR x distractor cell is reported as counts only (no per-cell intervals).',
                    'First-passage alphas are an added exploratory descriptor, not part of doc 46 section 4.'])


def summaries_of(a, bank):
    return summarize(a['logits'], a['nll'], labels_of(list(map(int, a['trial_ids'])), bank))

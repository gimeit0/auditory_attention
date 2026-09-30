"""Per-SNR alpha curves for job 756262: one accuracy and one cross-entropy figure per SNR bin (10 figures).

Mixed scenes with the correct cue only (the 200 clean scenes in main/correct are zero-cue), 360 trials per bin.
Arrays are re-checked against their WORKER SHA before use. Uncertainty: pointwise 95% target_speaker cluster
bootstrap (contract generator: PCG64 seed 20260926, 10,000 draws); not simultaneous bands. No smoothing;
0.50-0.75 was not sampled and is shaded; .75/.875/1 are separate points, never connected.
"""
import csv
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from analyze_fine_alpha_756262 import COLLECTED, PACKAGE, RELEASE, DIGEST, JOB, load_block
from fine_alpha_statistics import CODES, FINE, BLOCK_OF, MAIN, value, indicators, unit

SKILL = Path('/Users/gigi/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/'
             '6f3b8628-1d9b-4af5-9062-95c719df29c0/e8c8b27c-1089-4288-abed-d59061c80136/skills/scientific-visualization/scripts')
sys.path.insert(0, str(SKILL))
from style_presets import style_context   # noqa: E402
from figure_export import export_figure   # noqa: E402

READOUT = RELEASE/'readout-756262-y71mc3m7'
BLUE, GREY = '#0072B2', '#6E6E6E'
MM = 1/25.4
COARSE = CODES[51:]
X_FINE = np.array([value(p) for p in FINE]); X_COARSE = np.array([value(p) for p in COARSE])
TICKS = ([0, .1, .2, .3, .4, .5, .75, .875, 1], ['0', '.1', '.2', '.3', '.4', '.5', '.75', '.875', '1'])
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()


def compute():
    sources = {}
    blocks = {b: load_block(COLLECTED/'state/attempt'/b/'output', sources) for b in 'ABC'}
    arrays = {('main', p, 'correct'): blocks[BLOCK_OF[p]][BLOCK_OF[p], 'main', p, 'correct'] for p in CODES}
    arrays['main', 'original', 'correct'] = blocks['A']['A', 'main', 'original', 'correct']
    with (PACKAGE/'frozen_bank.tsv').open() as f:
        bank = {int(r['trial_id']): r for r in csv.DictReader(f, delimiter='\t')}
    all_ids = list(map(int, arrays['main', 'original', 'correct']['trial_ids']))
    bins = {}
    for b in range(5):
        ids = [i for i in all_ids if bank[i]['scene_kind'] == 'mixed' and int(bank[i]['snr_bin']) == b]
        edges = {(bank[i]['snr_bin_low'], bank[i]['snr_bin_high']) for i in ids}
        if len(ids) != 360 or len(edges) != 1: raise ValueError('SNR_BIN')
        cols = {}
        for p in (*CODES, 'original'):
            a, n = indicators(arrays, 'main', p, 'correct', ids, bank)
            cols[p+'/accuracy'] = a; cols[p+'/cross_entropy_nats'] = n
        r = unit(ids, cols, bank)
        low, high = (float(x) for x in edges.pop())
        bins[b] = dict(snr_db=[low, high], trials=len(ids), clusters=r['info']['clusters'], statistics=r)
    return bins, sources, bank


def gap(ax):
    ax.axvspan(0.505, 0.745, color='#EDEDED', zorder=0, lw=0)
    ax.text(0.625, 0.96, 'not\nsampled', transform=ax.get_xaxis_transform(), ha='center', va='top', fontsize=6.5, color=GREY)


def draw(ax, m, metric):
    get = lambda p, k: m[f'{p}/{metric}'][k]
    y = np.array([get(p, 'estimate') for p in FINE]); lo, hi = np.array([get(p, 'ci95') for p in FINE]).T
    ax.fill_between(X_FINE, lo, hi, color=BLUE, alpha=0.18, lw=0, label='95% CI (target-speaker bootstrap)')
    ax.plot(X_FINE, y, color=BLUE, marker='o', ms=2.8, lw=1.1, label=r'formal40, gains scaled by $\alpha$')
    yc = np.array([get(p, 'estimate') for p in COARSE]); clo, chi = np.array([get(p, 'ci95') for p in COARSE]).T
    ax.errorbar(X_COARSE, yc, yerr=[yc-clo, chi-yc], fmt='o', color=BLUE, ms=3.6, lw=0.9, capsize=2)
    ax.axhline(get('original', 'estimate'), color='0.25', ls='--', lw=0.8,
               label=f"unmodified model, same trials ({get('original', 'estimate'):.3g})")


def zoom_figure(b, info, limits, zoom_top, prov, out):
    """Accuracy: left = full alpha range (shared 0-0.7), right = the 0-0.50 fine grid enlarged (shared y range)."""
    from matplotlib.patches import Rectangle
    m = info['statistics']['metrics']; low, high = info['snr_db']
    with style_context('default', palette_name='okabe_ito_on_white'):
        fig, (ax, az) = plt.subplots(1, 2, figsize=(175*MM, 80*MM), layout='constrained', width_ratios=[1.35, 1])
        gap(ax); draw(ax, m, 'accuracy')
        ax.axhline(1/800, color=GREY, ls=':', lw=0.8, label='chance (1/800)')
        ax.set_ylim(*limits); ax.set_xticks(*TICKS); ax.set_xlim(-0.03, 1.03)
        ax.add_patch(Rectangle((-0.015, 0), 0.53, zoom_top, fill=False, ls='--', lw=0.7, ec='0.35'))
        ax.text(0.515, zoom_top, 'enlarged at right', ha='right', va='bottom', fontsize=6, color='0.35')
        ax.set_ylabel('Top-1 accuracy (800 words)')
        ax.set_xlabel(r'$\alpha$ (0 = all eight gains flattened, 1 = unmodified gains)')
        ax.set_title('full range', fontsize=7.5, loc='left')
        y = np.array([m[f'{p}/accuracy']['estimate'] for p in FINE]); lo, hi = np.array([m[f'{p}/accuracy']['ci95'] for p in FINE]).T
        az.fill_between(X_FINE, lo, hi, color=BLUE, alpha=0.18, lw=0)
        az.plot(X_FINE, y, color=BLUE, marker='o', ms=3, lw=1.1)
        az.axhline(1/800, color=GREY, ls=':', lw=0.8)
        az.set_xlim(-0.01, 0.51); az.set_ylim(0, zoom_top)
        az.set_xticks(np.round(np.arange(0, 0.51, 0.05), 2), [f'{v:.2f}'.lstrip('0') if v else '0' for v in np.arange(0, 0.51, 0.05)])
        az.set_xlabel(r'$\alpha$, 0–0.50 at 0.01 steps (51 points)')
        az.set_title('0–0.50 enlarged (same y range in all five SNR bins)', fontsize=7.5, loc='left')
        for a in (ax, az): a.grid(True, axis='y', lw=0.4, alpha=0.5)
        handles, labels = ax.get_legend_handles_labels()
        fig.legend(handles, labels, loc='outside lower center', ncol=4, frameon=False, fontsize=6.5)
        fmt = lambda v: f'{v:g}'.replace('-', '\u2212')
        fig.suptitle(f"SNR {fmt(low)}\u2026{fmt(high)} dB: mixed scenes, correct cue (n = {info['trials']}, {info['clusters']} target speakers)", fontsize=8.5)
        return export_figure(fig, out/f'snr{b}_accuracy', formats=['png', 'pdf'], dpi=600, provenance=prov, write_manifest=True)


def figure(b, info, metric, limits, prov, out):
    m = info['statistics']['metrics']; low, high = info['snr_db']
    with style_context('default', palette_name='okabe_ito_on_white'):
        fig, ax = plt.subplots(figsize=(110*MM, 80*MM), layout='constrained')
        gap(ax); draw(ax, m, metric)
        if metric == 'accuracy':
            ax.axhline(1/800, color=GREY, ls=':', lw=0.8, label='chance (1/800)')
            ax.set_ylabel('Top-1 accuracy (800 words)'); ax.set_ylim(*limits)
        else:
            ax.set_yscale('log'); ax.set_ylim(*limits)
            ax.set_ylabel('Cross-entropy (nats, log scale)')
        ax.set_xticks(*TICKS); ax.set_xlim(-0.03, 1.03)
        ax.set_xlabel(r'$\alpha$ (0 = all eight gains flattened, 1 = unmodified gains)')
        ax.grid(True, axis='y', lw=0.4, alpha=0.5)
        handles, labels = ax.get_legend_handles_labels()
        fig.legend(handles, labels, loc='outside lower center', ncol=2, frameon=False, fontsize=6.5)
        fmt = lambda v: f'{v:g}'.replace('-', '\u2212')
        ax.set_title(f"SNR {fmt(low)}\u2026{fmt(high)} dB: mixed scenes, correct cue "
                     f"(n = {info['trials']}, {info['clusters']} target speakers)", fontsize=8, loc='left')
        name = f"snr{b}_{'accuracy' if metric == 'accuracy' else 'cross_entropy'}"
        return export_figure(fig, out/name, formats=['png', 'pdf'], dpi=600, provenance=prov, write_manifest=True)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accuracy-ylim', choices=['full', 'shared07', 'perbin', 'shared07zoom'], default='full',
                        help="full: 0-1; shared07: 0-0.7 for all bins; perbin: each bin's max CI rounded up to 0.1")
    args = parser.parse_args()
    out = READOUT/{'full': 'snr_figures', 'shared07': 'snr_figures_ylim_shared07', 'perbin': 'snr_figures_ylim_perbin',
                   'shared07zoom': 'snr_figures_A_with_zoom'}[args.accuracy_ylim]
    out.mkdir(exist_ok=False)
    bins, sources, bank = compute()
    # Self-consistency: pooled bin accuracy must equal the mean of its four equal-size cells in REPORT.json.
    report = json.loads((READOUT/'REPORT.json').read_text())
    for b in range(5):
        for p in CODES:
            cells = np.mean([report['strata'][f'snr{b}_distractors{d}']['metrics'][f'{p}/accuracy_pp']['estimate'] for d in range(1, 5)])
            if abs(100*bins[b]['statistics']['metrics'][f'{p}/accuracy']['estimate'] - cells) > 1e-9: raise ValueError('STRATA_MISMATCH')
    rows = []
    for b, info in bins.items():
        for p in (*CODES, 'original'):
            m = info['statistics']['metrics']
            rows.append(dict(snr_bin=b, snr_low_db=info['snr_db'][0], snr_high_db=info['snr_db'][1], alpha=value(p) if p != 'original' else '',
                             pass_name=p, n=info['trials'], accuracy=m[p+'/accuracy']['estimate'],
                             accuracy_ci95_low=m[p+'/accuracy']['ci95'][0], accuracy_ci95_high=m[p+'/accuracy']['ci95'][1],
                             cross_entropy_nats=m[p+'/cross_entropy_nats']['estimate'],
                             cross_entropy_ci95_low=m[p+'/cross_entropy_nats']['ci95'][0],
                             cross_entropy_ci95_high=m[p+'/cross_entropy_nats']['ci95'][1]))
    with (out/'SNR_CURVES.csv').open('x', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    (out/'SNR_REPORT.json').write_text(json.dumps(dict(
        accuracy_ylim=args.accuracy_ylim, job_id=JOB, release_sha256=DIGEST, unit='mixed scenes, correct cue; 360 trials per SNR bin',
        statistics_note='pointwise 95% target_speaker cluster bootstrap, PCG64 seed 20260926, 10000 draws; accuracy as proportion',
        bins={str(b): v for b, v in bins.items()}, array_sources=sources,
        bank_sha256=sha(PACKAGE/'frozen_bank.tsv'), script_sha256=sha(__file__),
        consistency='bin accuracy equals mean of the four REPORT.json strata cells at all 54 alphas'), indent=2, allow_nan=False)+'\n')
    prov = dict(raw_data=str(out/'SNR_CURVES.csv'), raw_data_sha256=sha(out/'SNR_CURVES.csv'), figure_script_sha256=sha(__file__),
                helper_sha256={n: sha(SKILL/n) for n in ('style_presets.py', 'figure_export.py', '_common.py')},
                source_job=JOB, release_sha256=DIGEST,
                transformations=['per-alpha trial means within one SNR bin; no smoothing', '0.50-0.75 unsampled, shaded; .75/.875/1 not connected',
                                 'cross-entropy = mean stored target NLL (nats), log10 axis'],
                uncertainty='pointwise 95% target_speaker cluster bootstrap, seed 20260926, 10000 draws; not simultaneous',
                missing_data='none')
    acc_hi = max(v['statistics']['metrics'][k]['ci95'][1] for v in bins.values() for k in v['statistics']['metrics'] if k.endswith('/accuracy'))
    ce = [v['statistics']['metrics'][k]['ci95'] for v in bins.values() for k in v['statistics']['metrics'] if k.endswith('/cross_entropy_nats')]
    # Never clip data: every choice keeps each bin's largest CI upper bound inside the axis.
    per_bin = {b: float(np.ceil(max(v['statistics']['metrics'][k]['ci95'][1] for k in v['statistics']['metrics']
                                    if k.endswith('/accuracy'))*10-1e-9)/10) for b, v in bins.items()}
    acc_limits = {b: (0.0, {'full': 1.0, 'shared07': 0.7, 'shared07zoom': 0.7, 'perbin': per_bin[b]}[args.accuracy_ylim]) for b in bins}
    fine_hi = max(v['statistics']['metrics'][f'{p}/accuracy']['ci95'][1] for v in bins.values() for p in FINE)
    zoom_top = float(np.ceil(fine_hi*20-1e-9)/20)   # shared, rounded up to 0.05, never clips the 0-0.50 data
    if any(acc_limits[b][1] < per_bin[b] for b in bins): raise ValueError('AXIS_WOULD_CLIP_DATA')
    ce_limits = (10**np.floor(np.log10(min(c[0] for c in ce))), 10**np.ceil(np.log10(max(c[1] for c in ce))))
    for b, info in bins.items():
        if args.accuracy_ylim == 'shared07zoom': zoom_figure(b, info, acc_limits[b], zoom_top, prov, out)
        else: figure(b, info, 'accuracy', acc_limits[b], prov, out)
        figure(b, info, 'cross_entropy_nats', ce_limits, prov, out)
    print(json.dumps({b: dict(snr=v['snr_db'], clusters=v['clusters'],
                              acc={a: round(v['statistics']['metrics'][f'alpha_{int(a*1000):04d}/accuracy']['estimate'], 4) for a in (0, .3, .4, .5, .75, 1)},
                              ce={a: round(v['statistics']['metrics'][f'alpha_{int(a*1000):04d}/cross_entropy_nats']['estimate'], 2) for a in (0, .3, .4, .5, .75, 1)})
                      for b, v in bins.items()}), flush=True)
    print('limits', acc_limits, ce_limits)


if __name__ == '__main__': main()

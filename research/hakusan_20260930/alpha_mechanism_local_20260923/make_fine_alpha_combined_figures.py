"""Figures for the combined 0-1 readout (756262 + v4 job). Reads REPORT.json only; raw grid values, no smoothing.

0-0.75 is sampled every 0.01 and drawn as a connected line; 0.80/0.85/0.875/0.90/0.95/1 are separate points with
CI bars (never connected). Intervals: pointwise 95% target-speaker cluster bootstrap, not simultaneous bands.
Outputs: fig_main_combined + one accuracy (full range | 0-0.50 enlarged) and one cross-entropy figure per SNR bin.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import fine_alpha_combined as fc

SKILL = Path('/Users/gigi/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/'
             '6f3b8628-1d9b-4af5-9062-95c719df29c0/e8c8b27c-1089-4288-abed-d59061c80136/skills/scientific-visualization/scripts')
sys.path.insert(0, str(SKILL))
from style_presets import style_context   # noqa: E402
from figure_export import export_figure   # noqa: E402

BLUE, VERM, GREEN, PINK, BLACK, GREY = '#0072B2', '#D55E00', '#009E73', '#CC79A7', '#000000', '#6E6E6E'
MM = 1/25.4
FINE = [fc.code(c) for c in fc.FINE_REGION]; COARSE = [fc.code(c) for c in fc.GRID if c > 750]
XF = np.array([fc.value(c) for c in fc.FINE_REGION]); XC = np.array([fc.value(c) for c in fc.GRID if c > 750])
TICKS = ([0, .1, .2, .3, .4, .5, .6, .7, .75, .8, .9, 1], ['0', '.1', '.2', '.3', '.4', '.5', '.6', '.7', '', '.8', '.9', '1'])
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
fmt = lambda v: f'{v:g}'.replace('-', '−')


def series(ax, get, color=BLUE, marker='o', label=None, ci=True, ms=2.6):
    y = np.array([get(p)[0] for p in FINE]); ax.plot(XF, y, color=color, marker=marker, ms=ms, lw=1.0, label=label)
    yc = np.array([get(p)[0] for p in COARSE])
    if ci:
        lo, hi = np.array([get(p)[1] for p in FINE]).T; ax.fill_between(XF, lo, hi, color=color, alpha=0.18, lw=0)
        clo, chi = np.array([get(p)[1] for p in COARSE]).T
        ax.errorbar(XC, yc, yerr=[yc-clo, chi-yc], fmt=marker, color=color, ms=3.2, lw=0.9, capsize=2)
    else: ax.plot(XC, yc, ls='none', color=color, marker=marker, ms=3.2)


def anchors(ax, get):
    for c in (500, 750):
        ax.plot([fc.value(c)], [get(fc.code(c))[0]], ls='none', marker='D', ms=6, mfc='none', mec=VERM, mew=1.0,
                label='anchor, identical in both jobs' if c == 500 else None)


def fig_main(r, prov, out):
    mx = r['main_mixed_summaries']; m = r['units']['main_mixed']['metrics']; info = r['units']['main_mixed']['info']
    acc = lambda p: (m[p+'/accuracy_pp']['estimate'], m[p+'/accuracy_pp']['ci95'])
    b = r['collapse_boundary']['mixed']['collapse']
    with style_context('default', palette_name='okabe_ito_on_white'):
        fig, axes = plt.subplots(3, 1, figsize=(125*MM, 150*MM), sharex=True, layout='constrained')
        ax = axes[0]; series(ax, acc, label='accuracy (95% CI)'); anchors(ax, acc)
        ax.axhline(100*mx['original']['accuracy'], color=BLACK, ls='--', lw=0.8, label=f"unmodified {100*mx['original']['accuracy']:.1f}%")
        ax.axhline(50*mx['original']['accuracy'], color=VERM, ls=':', lw=0.9, label='collapse threshold (half of unmodified)')
        if b['first_free_alpha'] is not None:
            ax.axvline(b['first_free_alpha'], color=GREY, ls='-.', lw=0.8, label=f"first collapse-free alpha: {b['first_free_alpha']:g}")
        ax.set_ylabel('Accuracy (%)'); ax.set_ylim(0, 50); ax.legend(fontsize=6, frameon=False, loc='center left', bbox_to_anchor=(0, 0.6))
        ax.set_title(f"a  mixed scenes, correct cue (n={info['trials']}, {info['clusters']} target speakers); "
                     f"jobs 756262 + {r['jobs']['new']}", loc='left', fontsize=8)
        ax = axes[1]; nll = lambda p: (mx[p]['mean_nll'], None); series(ax, nll, ci=False)
        ax.axhline(mx['original']['mean_nll'], color=BLACK, ls='--', lw=0.8); ax.set_yscale('log')
        ax.set_ylabel('Mean NLL (nats, log10)'); ax.set_title('b  cross-entropy of the target word', loc='left', fontsize=8)
        ax = axes[2]; top = lambda p: (100*mx[p]['most_frequent_count']/info['trials'], None)
        cls = lambda p: (100*mx[p]['predicted_classes']/800, None)
        series(ax, top, color=PINK, marker='s', label='trials on the single most frequent word (%)', ci=False)
        series(ax, cls, color=GREEN, marker='^', label='distinct predicted words (% of 800)', ci=False)
        ax.set_ylabel('Percent'); ax.set_ylim(-3, 103); ax.legend(fontsize=6, frameon=False, loc='center right')
        ax.set_title('c  prediction concentration', loc='left', fontsize=8)
        ax.set_xticks(*TICKS); ax.set_xlabel(r'$\alpha$ (0 = eight gains flattened, 1 = unmodified); 0-0.75 every 0.01')
        for a_ in axes: a_.grid(True, axis='y', lw=0.4, alpha=0.5)
        return export_figure(fig, out/'fig_main_combined', formats=['png', 'pdf'], dpi=600, provenance=prov, write_manifest=True)


def fig_snr(r, b, info, prov, out, zoom_top):
    m = info['statistics']['metrics']; low, high = info['snr_db']
    acc = lambda p: (m[p+'/accuracy']['estimate'], m[p+'/accuracy']['ci95'])
    ce = lambda p: (m[p+'/cross_entropy_nats']['estimate'], m[p+'/cross_entropy_nats']['ci95'])
    title = f"SNR {fmt(low)}…{fmt(high)} dB: mixed scenes, correct cue (n = {info['trials']}, {info['statistics']['info']['clusters']} target speakers)"
    with style_context('default', palette_name='okabe_ito_on_white'):
        fig, (ax, az) = plt.subplots(1, 2, figsize=(175*MM, 80*MM), layout='constrained', width_ratios=[1.35, 1])
        series(ax, acc, label=r'formal40, gains scaled by $\alpha$ (95% CI)'); anchors(ax, acc)
        ax.axhline(m['original/accuracy']['estimate'], color='0.25', ls='--', lw=0.8,
                   label=f"unmodified model, same trials ({m['original/accuracy']['estimate']:.3f})")
        ax.axhline(1/800, color=GREY, ls=':', lw=0.8, label='chance (1/800)')
        ax.set_ylim(0, 0.7); ax.set_xticks(*TICKS); ax.set_xlim(-0.03, 1.03)
        from matplotlib.patches import Rectangle
        ax.add_patch(Rectangle((-0.015, 0), 0.53, zoom_top, fill=False, ls='--', lw=0.7, ec='0.35'))
        ax.set_ylabel('Top-1 accuracy (800 words)'); ax.set_xlabel(r'$\alpha$ (0-0.75 every 0.01)'); ax.set_title('full range', fontsize=7.5, loc='left')
        y = np.array([acc(p)[0] for p in FINE]); lo, hi = np.array([acc(p)[1] for p in FINE]).T
        sel = XF <= 0.5
        az.fill_between(XF[sel], lo[sel], hi[sel], color=BLUE, alpha=0.18, lw=0); az.plot(XF[sel], y[sel], color=BLUE, marker='o', ms=3, lw=1.1)
        az.axhline(1/800, color=GREY, ls=':', lw=0.8); az.set_xlim(-0.01, 0.51); az.set_ylim(0, zoom_top)
        az.set_xticks(np.round(np.arange(0, 0.51, 0.05), 2), [f'{v:.2f}'.lstrip('0') if v else '0' for v in np.arange(0, 0.51, 0.05)])
        az.set_xlabel(r'$\alpha$, 0-0.50'); az.set_title('0-0.50 enlarged (same y range in all five SNR bins)', fontsize=7.5, loc='left')
        for a_ in (ax, az): a_.grid(True, axis='y', lw=0.4, alpha=0.5)
        h, l = ax.get_legend_handles_labels(); fig.legend(h, l, loc='outside lower center', ncol=2, frameon=False, fontsize=6.5)
        fig.suptitle(title, fontsize=8.5)
        export_figure(fig, out/f'snr{b}_accuracy', formats=['png', 'pdf'], dpi=600, provenance=prov, write_manifest=True)
    with style_context('default', palette_name='okabe_ito_on_white'):
        fig, ax = plt.subplots(figsize=(110*MM, 80*MM), layout='constrained')
        series(ax, ce, label=r'formal40, gains scaled by $\alpha$ (95% CI)'); anchors(ax, ce)
        ax.axhline(m['original/cross_entropy_nats']['estimate'], color='0.25', ls='--', lw=0.8,
                   label=f"unmodified model, same trials ({m['original/cross_entropy_nats']['estimate']:.2f})")
        ax.set_yscale('log'); ax.set_ylim(1, 1000); ax.set_xticks(*TICKS); ax.set_xlim(-0.03, 1.03)
        ax.set_ylabel('Cross-entropy (nats, log scale)'); ax.set_xlabel(r'$\alpha$ (0-0.75 every 0.01)')
        ax.grid(True, axis='y', lw=0.4, alpha=0.5)
        h, l = ax.get_legend_handles_labels(); fig.legend(h, l, loc='outside lower center', ncol=2, frameon=False, fontsize=6.5)
        ax.set_title(title, fontsize=8, loc='left')
        return export_figure(fig, out/f'snr{b}_cross_entropy', formats=['png', 'pdf'], dpi=600, provenance=prov, write_manifest=True)


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('readout', type=Path); a = p.parse_args()
    r = json.loads((a.readout/'REPORT.json').read_text()); out = a.readout/'figures'; out.mkdir(exist_ok=False)
    prov = dict(raw_data=str(a.readout/'REPORT.json'), raw_data_sha256=sha(a.readout/'REPORT.json'), figure_script_sha256=sha(__file__),
                helper_sha256={n: sha(SKILL/n) for n in ('style_presets.py', 'figure_export.py', '_common.py')}, jobs=r['jobs'],
                transformations=['per-alpha trial means; no smoothing', '0-0.75 connected (0.01 grid); >=0.80 separate points'],
                uncertainty='pointwise 95% target_speaker cluster bootstrap, seed 20260926, 10000 draws; not simultaneous')
    fig_main(r, prov, out)
    hi = max(r['snr_bins'][b]['statistics']['metrics'][f'{p}/accuracy']['ci95'][1] for b in r['snr_bins'] for p in FINE if fc.value(int(p[6:])) <= 0.5)
    zoom_top = float(np.ceil(hi*20-1e-9)/20)
    for b, info in r['snr_bins'].items(): fig_snr(r, b, info, prov, out, zoom_top)
    print('figures in', out, 'zoom_top', zoom_top)


if __name__ == '__main__': main()

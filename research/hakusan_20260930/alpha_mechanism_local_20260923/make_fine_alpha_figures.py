"""Figures for the 756262 fine-alpha readout. Reads REPORT.json only; plots raw grid values (no smoothing).

The 0.50-0.75 interval was not sampled; lines never cross it and it is shaded.
Uncertainty: pointwise 95% target_speaker cluster bootstrap (seed 20260926, 10,000 draws), not simultaneous bands.
"""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

SKILL = Path('/Users/gigi/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/'
             '6f3b8628-1d9b-4af5-9062-95c719df29c0/e8c8b27c-1089-4288-abed-d59061c80136/skills/scientific-visualization/scripts')
sys.path.insert(0, str(SKILL))
from style_presets import style_context          # noqa: E402
from figure_export import export_figure          # noqa: E402
from fine_alpha_statistics import CODES, FINE, value  # noqa: E402

BLUE, VERM, GREEN, PINK, BLACK, GREY = '#0072B2', '#D55E00', '#009E73', '#CC79A7', '#000000', '#6E6E6E'
COARSE = CODES[51:]
X_FINE = np.array([value(p) for p in FINE]); X_COARSE = np.array([value(p) for p in COARSE])


def gap(ax):
    ax.axvspan(0.505, 0.745, color='#EDEDED', zorder=0, lw=0)
    ax.text(0.625, 0.97, 'not sampled', transform=ax.get_xaxis_transform(), ha='center', va='top', fontsize=6.5, color=GREY)


def series(ax, metrics, key, color, marker, label, ci=True, ls='-'):
    """Fine grid: connected line + CI ribbon. .75/.875/1: separate markers with CI bars, never connected."""
    y = np.array([metrics[key.format(p=p)]['estimate'] for p in FINE])
    ax.plot(X_FINE, y, ls=ls, color=color, marker=marker, ms=2.6, lw=1.0, label=label)
    yc = np.array([metrics[key.format(p=p)]['estimate'] for p in COARSE])
    if ci:
        lo, hi = np.array([metrics[key.format(p=p)]['ci95'] for p in FINE]).T
        ax.fill_between(X_FINE, lo, hi, color=color, alpha=0.18, lw=0)
        clo, chi = np.array([metrics[key.format(p=p)]['ci95'] for p in COARSE]).T
        ax.errorbar(X_COARSE, yc, yerr=[yc-clo, chi-yc], fmt=marker, color=color, ms=3.2, lw=0.9, capsize=2)
    else:
        ax.plot(X_COARSE, yc, ls='none', color=color, marker=marker, ms=3.2)


def plain(ax, xs_fine, y_fine, xs_c, y_c, **kw):
    label = kw.pop('label', None); kw.pop('ls', None); ls = kw.pop('linestyle', '-')
    ax.plot(xs_fine, y_fine, label=label, ls=ls, **kw)
    kw.pop('lw', None); ax.plot(xs_c, y_c, ls='none', **kw)


def fig_main(r, prov, out):
    mix = r['main_mixed_summaries']; m = r['units']['main_correct_mixed']['metrics']; info = r['units']['main_correct_mixed']['info']
    s = {f'main/{p}/correct': v for p, v in mix.items()}   # 1800 mixed scenes with the correct cue
    orig = mix['original']; n = info['trials']
    with style_context('default', palette_name='okabe_ito_on_white'):
        fig, axes = plt.subplots(4, 1, figsize=(120/25.4, 175/25.4), sharex=True, layout='constrained')
        ax = axes[0]; gap(ax)
        series(ax, m, '{p}/accuracy_pp', BLUE, 'o', 'accuracy (95% CI)')
        ax.axhline(100*orig['accuracy'], color=BLACK, ls='--', lw=0.8, label=f"unmodified model {100*orig['accuracy']:.1f}%")
        ax.axhline(50*orig['accuracy'], color=VERM, ls=':', lw=0.9, label='collapse threshold (half of unmodified)')
        ax.axhline(100/800, color=GREY, ls='-.', lw=0.8, label='chance 1/800 = 0.125%')
        ax.set_ylabel('Accuracy (%)'); ax.set_ylim(-1, 50); ax.legend(fontsize=6, loc='center left', bbox_to_anchor=(0, 0.635), frameon=False)
        ax.set_title(f"a  mixed scenes with the correct cue (n={n} trials, {info['clusters']} target-speaker clusters)", loc='left', fontsize=8)
        ax = axes[1]; gap(ax)
        plain(ax, X_FINE, [s[f'main/{p}/correct']['mean_nll'] for p in FINE], X_COARSE,
              [s[f'main/{p}/correct']['mean_nll'] for p in COARSE], color=BLUE, marker='o', ms=2.6, lw=1.0)
        ax.axhline(orig['mean_nll'], color=BLACK, ls='--', lw=0.8, label=f"unmodified {orig['mean_nll']:.2f}")
        ax.set_yscale('log'); ax.set_ylabel('Mean NLL (nats, log10 axis)'); ax.legend(fontsize=6, frameon=False, loc='upper right')
        ax.set_title('b  mean negative log-likelihood of the target word', loc='left', fontsize=8)
        ax = axes[2]; gap(ax)
        plain(ax, X_FINE, [100*s[f'main/{p}/correct']['most_frequent_count']/n for p in FINE], X_COARSE,
              [100*s[f'main/{p}/correct']['most_frequent_count']/n for p in COARSE], color=PINK, marker='s', ms=2.4, lw=1.0,
              label='trials predicted as the single most frequent word (%)')
        plain(ax, X_FINE, [100*s[f'main/{p}/correct']['predicted_classes']/800 for p in FINE], X_COARSE,
              [100*s[f'main/{p}/correct']['predicted_classes']/800 for p in COARSE], color=GREEN, marker='^', ms=2.6, lw=1.0, linestyle='--',
              label='distinct predicted words, % of 800-word vocabulary')
        ax.set_ylabel('Percent'); ax.set_ylim(-3, 103); ax.legend(fontsize=6, frameon=False, loc='center left')
        ax.set_title('c  prediction concentration', loc='left', fontsize=8)
        ax = axes[3]; gap(ax)
        plain(ax, X_FINE, [s[f'main/{p}/correct']['logit_max_abs'] for p in FINE], X_COARSE,
              [s[f'main/{p}/correct']['logit_max_abs'] for p in COARSE], color=BLACK, marker='D', ms=2.2, lw=1.0, label='largest |logit| over all trials')
        ax.axhline(10*orig['logit_max_abs'], color=VERM, ls=':', lw=0.9, label='collapse threshold (10 x unmodified)')
        ax.set_yscale('log'); ax.set_ylabel('Max |logit| (log10 axis)'); ax.legend(fontsize=6, frameon=False, loc='lower left')
        ax.set_title('d  logit magnitude', loc='left', fontsize=8)
        ax.set_xlabel('alpha (gain scaling; 0 = all eight gains flattened, 1 = unmodified gains)')
        ax.set_xticks([0, .1, .2, .3, .4, .5, .75, .875, 1]); ax.set_xticklabels(['0', '.1', '.2', '.3', '.4', '.5', '.75', '.875', '1'])
        return export_figure(fig, out/'fig1_main_correct', formats=['png', 'pdf'], dpi=300, provenance=prov, write_manifest=True)


def fig_cues(r, prov, out):
    c = r['units']['control']['metrics']; ci = r['units']['control']['info']
    k = r['units']['clean']['metrics']; ki = r['units']['clean']['info']
    with style_context('default', palette_name='okabe_ito_on_white'):
        fig, axes = plt.subplots(3, 1, figsize=(120/25.4, 150/25.4), sharex=True, layout='constrained')
        ax = axes[0]; gap(ax)
        for cond, col, mk, ls in (('correct', BLUE, 'o', '-'), ('silent', GREEN, '^', '--'),
                                  ('shuffled', VERM, 's', '-.'), ('distractor', PINK, 'D', ':')):
            series(ax, c, '{p}/'+cond+'/accuracy_pp', col, mk, cond+' cue', ci=False, ls=ls)
        ax.set_ylabel('Accuracy (%)'); ax.legend(fontsize=6, frameon=False, loc='upper left', ncol=2)
        ax.set_title(f"a  control subset by cue condition (n={ci['trials']}, {ci['clusters']} clusters)", loc='left', fontsize=8)
        ax = axes[1]; gap(ax)
        series(ax, c, '{p}/correct_minus_shuffled/accuracy_pp', BLUE, 'o', 'correct - shuffled cue (95% CI)')
        ax.axhline(0, color=BLACK, lw=0.7); ax.set_ylabel('Paired difference (pp)')
        ax.legend(fontsize=6, frameon=False, loc='upper left')
        ax.set_title('b  cue benefit on the same 400 trials (measured alpha=0 residual r0 = 0, so D = c)', loc='left', fontsize=8)
        ax = axes[2]; gap(ax)
        series(ax, k, '{p}/correct_cue/accuracy_pp', BLUE, 'o', 'correct cue (95% CI)')
        series(ax, k, '{p}/zero_cue/accuracy_pp', VERM, 's', 'zero cue (95% CI)', ls='--')
        ax.set_ylabel('Accuracy (%)'); ax.legend(fontsize=6, frameon=False, loc='upper left')
        ax.set_title(f"c  clean single-speaker inputs (n={ki['trials']}, {ki['clusters']} clusters)", loc='left', fontsize=8)
        ax.set_xlabel('alpha'); ax.set_xticks([0, .1, .2, .3, .4, .5, .75, .875, 1])
        ax.set_xticklabels(['0', '.1', '.2', '.3', '.4', '.5', '.75', '.875', '1'])
        return export_figure(fig, out/'fig2_cues', formats=['png', 'pdf'], dpi=300, provenance=prov, write_manifest=True)


def fig_errors_strata(r, prov, out):
    e = r['units']['main_mixed_error_categories']['metrics']
    ticks = dict(ticks=[0, .1, .2, .3, .4, .5, .75, .875, 1], labels=['0', '.1', '.2', '.3', '.4', '.5', '.75', '.875', '1'])
    with style_context('default', palette_name='okabe_ito_on_white'):
        fig, axes = plt.subplots(3, 1, figsize=(120/25.4, 165/25.4), layout='constrained', sharex=True)
        ax = axes[0]; gap(ax)
        for cat, col, mk, ls in (('target', BLUE, 'o', '-'), ('distractor', VERM, 's', '--'),
                                 ('cue_word', GREEN, '^', '-.'), ('other', BLACK, 'D', ':')):
            series(ax, e, '{p}/'+cat+'_pp', col, mk, {'target': 'target word', 'distractor': 'distractor word', 'cue_word': 'cue word', 'other': 'other word'}[cat], ls=ls)
        ax.set_yscale('symlog', linthresh=1); ax.set_ylabel('Share of 1800 trials (%)\n(symlog; linear below 1%)')
        ax.legend(fontsize=6, frameon=False, loc='center', bbox_to_anchor=(0.625, 0.45))
        ax.set_title('a  which word was predicted (mixed scenes, correct cue; 95% CI)', loc='left', fontsize=8)
        # Every stratum cell has n=90, so the plain mean over cells equals the pooled trial mean.
        cells = {(s_, d): r['strata'][f'snr{s_}_distractors{d}'] for s_ in range(5) for d in range(1, 5)}
        if {c['info']['trials'] for c in cells.values()} != {90}: raise ValueError('STRATUM_SIZES')
        styles = [(BLUE, 'o', '-'), (VERM, 's', '--'), (GREEN, '^', '-.'), (PINK, 'D', ':'), (BLACK, 'v', '-')]
        for ax, groups, name, title in (
                (axes[1], [(f'SNR bin {k} (n=360)', [(k, d) for d in range(1, 5)]) for k in range(5)], 'snr',
                 'b  mixed scenes by SNR bin (0 = lowest); point estimates'),
                (axes[2], [(f'{d} distractor(s) (n=450)', [(k, d) for k in range(5)]) for d in range(1, 5)], 'count',
                 'c  mixed scenes by distractor count; point estimates')):
            gap(ax)
            for (label, members), (col, mk, ls) in zip(groups, styles):
                y = {p: np.mean([cells[m]['metrics'][f'{p}/accuracy_pp']['estimate'] for m in members]) for p in CODES}
                plain(ax, X_FINE, [y[p] for p in FINE], X_COARSE, [y[p] for p in COARSE],
                      color=col, marker=mk, ms=2.2, lw=0.9, linestyle=ls, label=label)
            ax.set_ylabel('Accuracy (%)'); ax.legend(fontsize=5.5, frameon=False, loc='upper left')
            ax.set_title(title, loc='left', fontsize=8)
        axes[2].set_xlabel('alpha'); axes[2].set_xticks(**ticks)
        return export_figure(fig, out/'fig3_errors_strata', formats=['png', 'pdf'], dpi=300, provenance=prov, write_manifest=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('readout', type=Path)
    args = parser.parse_args()
    r = json.loads((args.readout/'REPORT.json').read_text())
    out = args.readout/'figures'; out.mkdir(exist_ok=False)
    import hashlib
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    prov = dict(raw_data=str(args.readout/'REPORT.json'), raw_data_sha256=sha(args.readout/'REPORT.json'),
                figure_script_sha256=sha(__file__), helper_sha256={n: sha(SKILL/n) for n in ('style_presets.py', 'figure_export.py', '_common.py')},
                source_job=r['job_id'], release_sha256=r['release_sha256'],
                transformations=['per-alpha trial means; no smoothing', '0.50-0.75 unsampled gap shaded; .75/.875/1 plotted as separate points, not connected',
                                 'main curve = 1800 mixed scenes with the correct cue (the 200 clean scenes in main/correct are zero-cue)'],
                uncertainty='pointwise 95% target_speaker cluster bootstrap, PCG64 seed 20260926, 10000 draws; not simultaneous',
                missing_data='none; all 54 grid points present')
    for f in (fig_main, fig_cues, fig_errors_strata): print(json.dumps(f(r, prov, out), default=str)[:300])


if __name__ == '__main__': main()

"""Per-SNR split of P10 figure 1 (panels a and c): 5 SNR bins x {accuracy, cross-entropy} = 10 figures.

Supervisor request 2026-09-29. Each figure shows one SNR bin; x = number of distractors (1-4),
one line per model, correct-cue condition, n = 450 trials per point (Job 728520 full10k).

Point estimates are recomputed from results.csv and must equal the frozen P09 record
(STATISTICS.json cell strata) exactly; the script refuses to draw otherwise.
Error bars are NEW descriptive 95% percentile intervals from a target_speaker cluster bootstrap
(10,000 draws per cell), computed here; they are not part of the frozen P09 record and are not
paired-difference tests. Style and export reuse p10_figures.py (Okabe-Ito colours, markers,
PDF Type 42 + 600 dpi opaque RGB PNG). Refuses to overwrite existing outputs.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "docs/superpowers/evidence/p08full-production-20260919-r2/frozen/collect-vvv4ed4a/collected/received/full10k/results.csv"
RESULTS_SHA = "c705f29ed97d61d29c2e0ecf7433c03ec05957ad63969019f8d02e523654c921"
STATS = ROOT / "docs/superpowers/evidence/p09-statistics-20260919/STATISTICS.json"
STATS_SHA = "c609fa726b30e60faca2b9a3dd648b466e3bdaa770e56f2209202a41ba3e341d"
DRAWS = 10_000
SEED = 20260929
DIS = [1, 2, 3, 4]


def _load_p10():
    spec = importlib.util.spec_from_file_location("p10_figures", Path(__file__).with_name("p10_figures.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P10 = _load_p10()
plt = P10.plt
MM = P10.MM


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cluster_ci(values, clusters, rng):
    """Percentile 95% CI of the trial-weighted mean, resampling target speakers with replacement."""
    codes, inverse = np.unique(clusters, return_inverse=True)
    sums = np.bincount(inverse, weights=values, minlength=len(codes))
    counts = np.bincount(inverse, minlength=len(codes)).astype(float)
    picks = rng.integers(0, len(codes), size=(DRAWS, len(codes)))
    boot = sums[picks].sum(1) / counts[picks].sum(1)
    low, high = np.percentile(boot, [2.5, 97.5])
    return float(low), float(high), int(len(codes))


def compute(results, stats):
    rows = []
    for b in range(5):
        for d in DIS:
            cell = results[(results.snr_bin == b) & (results.distractor_count == d)]
            if len(cell) != 450:
                raise ValueError(f"cell snr_bin {b} distractors {d} has {len(cell)} trials, expected 450")
            key = f"distractors_{d}__snr_bin_{b}"
            for m in P10.MODELS:
                frozen = stats["v4_summary"]["models"][m]["strata"][key]
                for metric, column, frozen_key in (("accuracy", f"{m}_correct", "accuracy"),
                                                   ("cross_entropy", f"{m}_nll", "cross_entropy")):
                    values = cell[column].astype(float).to_numpy()
                    point = float(values.mean())
                    if abs(point - frozen[frozen_key]) > 1e-12 or frozen["trials"] != 450:
                        raise ValueError(f"{key} {m} {metric}: recomputed {point} != frozen {frozen[frozen_key]}")
                    offset = 100 * b + 10 * d + list(P10.MODELS).index(m) + (0 if metric == "accuracy" else 5)
                    low, high, n_clusters = cluster_ci(values, cell["target_speaker"].astype(str).to_numpy(),
                                                       np.random.default_rng(SEED + offset))
                    rows.append(dict(snr_bin=b, snr_label=P10.SNR_LABELS[b], distractors=d, model=m, metric=metric,
                                     n=450, target_speakers=n_clusters, point=point, ci_low=low, ci_high=high,
                                     bootstrap_seed=SEED + offset))
    return pd.DataFrame(rows)


def draw(table, b, metric, out, provenance):
    fig, ax = plt.subplots(figsize=(88 * MM, 76 * MM), layout="constrained")
    dodge = {m: k for m, k in zip(P10.MODELS, (-0.09, 0.0, 0.09))}
    for m, st in P10.MODELS.items():
        t = table[(table.snr_bin == b) & (table.metric == metric) & (table.model == m)].sort_values("distractors")
        x = np.array(DIS) + dodge[m]
        y = t.point.to_numpy()
        ax.errorbar(x, y, yerr=[y - t.ci_low.to_numpy(), t.ci_high.to_numpy() - y], color=st["color"],
                    marker=st["marker"], ls=st["ls"], lw=1.2, ms=4.5, capsize=2, elinewidth=0.8, label=st["label"])
    ax.set_xticks(DIS)
    ax.set_xlim(0.6, 4.4)
    ax.set_xlabel("Number of distractors (n = 450 trials per point)")
    if metric == "accuracy":
        ax.set_ylim(0, 1)
        ax.set_ylabel("Top-1 accuracy (800 words)")
    else:
        ax.set_ylim(0, 6)
        ax.set_ylabel("Cross-entropy (nats)")
    ax.grid(axis="y", color="0.9", lw=0.6)
    ax.set_axisbelow(True)
    ax.set_title(f"SNR {P10.SNR_LABELS[b]} dB, correct cue (Job 728520)", fontsize=8.5)
    # Legend outside the axes so it can never cover points or intervals.
    fig.legend(*ax.get_legend_handles_labels(), loc="outside lower center", ncol=2, frameon=False, fontsize=6.5)
    stem = f"snr{b}_{'accuracy' if metric == 'accuracy' else 'cross_entropy'}"
    record = P10.export(fig, stem, out, provenance)
    plt.close(fig)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sha256(RESULTS) != RESULTS_SHA or sha256(STATS) != STATS_SHA:
        raise ValueError("input SHA mismatch")
    args.output.mkdir(parents=True, exist_ok=False)
    results = pd.read_csv(RESULTS, low_memory=False)
    stats = json.loads(STATS.read_text())
    table = compute(results, stats)
    table_path = args.output / "cell_metrics_with_ci.csv"
    table.to_csv(table_path, index=False, float_format="%.6f")
    provenance = dict(results_csv_sha256=RESULTS_SHA, statistics_sha256=STATS_SHA,
                      script_sha256=sha256(__file__), bootstrap=dict(draws=DRAWS, base_seed=SEED,
                      unit="target_speaker cluster within cell", interval="percentile 95%",
                      status="new descriptive interval, not part of frozen P09 record"))
    with plt.style.context(P10.style_path()):
        records = [draw(table, b, metric, args.output, provenance)
                   for b in range(5) for metric in ("accuracy", "cross_entropy")]
    manifest = dict(figures=records, table=dict(path=str(table_path), sha256=sha256(table_path)), **provenance)
    (args.output / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(dict(figures=len(records), table=str(table_path)), ensure_ascii=False))


if __name__ == "__main__":
    main()

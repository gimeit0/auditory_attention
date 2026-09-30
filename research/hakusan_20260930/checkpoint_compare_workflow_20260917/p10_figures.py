"""P10 publication figures from the P09 statistics record (read-only, deterministic).

Every number is taken from STATISTICS.json (Job 728520); nothing is recomputed or
smoothed. Uncertainty shown is the fixed-configuration 95% target_speaker cluster
bootstrap interval from the original v4 rules (10,000 draws, seed 20260829 with the
fixed stratum offsets). Publisher-specific size/format choices are provisional.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATS = ROOT / "docs/superpowers/evidence/p09-statistics-20260919/STATISTICS.json"
SKILL = Path(
    "/Users/gigi/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin"
    "/6f3b8628-1d9b-4af5-9062-95c719df29c0/e8c8b27c-1089-4288-abed-d59061c80136"
    "/skills/scientific-visualization"
)
MM = 1 / 25.4
# Okabe–Ito (colour-vision-safe) plus distinct markers: colour is never the only cue.
MODELS = {
    "formal40": dict(label="formal40 (ours, epoch 40)", color="#0072B2", marker="o", ls="-"),
    "author_external": dict(label="author checkpoint", color="#D55E00", marker="s", ls="--"),
    "valbest33": dict(label="valbest33 (ours, epoch 33)", color="#009E73", marker="^", ls=":"),
}
SNR_KEYS = [f"snr_bin_{k}" for k in range(5)]
SNR_LABELS = ["−10…−6", "−6…−2", "−2…2", "2…6", "6…10"]
DIS_KEYS = [f"distractors_{k}" for k in range(1, 5)]
ACC = "accuracy_difference_a_minus_b_positive_favors_a"
CE = "cross_entropy_improvement_b_minus_a_positive_favors_a"
CI_TEXT = "95% target-speaker cluster bootstrap CI (10,000 draws, fixed configuration)"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def style_path():
    candidate = SKILL / "assets/publication.mplstyle"
    return str(candidate) if candidate.exists() else "default"


def export(fig, stem, out, provenance):
    """Explicit export: PDF (vector, Type 42 fonts) + PNG 600 dpi; refuses overwrite."""
    out = Path(out)
    meta = {"Title": stem, "Creator": "p10_figures.py", "Subject": "Job 728520 P09 statistics"}
    written = {}
    for fmt in ("pdf", "png"):
        target = out / f"{stem}.{fmt}"
        if target.exists():
            raise FileExistsError(target)
        with matplotlib.rc_context({"pdf.fonttype": 42, "ps.fonttype": 42}):
            fig.savefig(target, format=fmt, dpi=600, facecolor="white", metadata=meta if fmt == "pdf" else None)
        if fmt == "png":
            # Opaque RGB, no alpha channel: contrast must not depend on the viewer's background.
            from PIL import Image

            with Image.open(target) as image:
                dpi = image.info.get("dpi", (600, 600))
                rgb = image.convert("RGB")
            rgb.save(target, format="PNG", dpi=dpi, optimize=True)
        written[fmt] = {"path": str(target), "sha256": sha256(target), "bytes": target.stat().st_size}
    w, h = fig.get_size_inches()
    return {"figure": stem, "size_mm": [round(w / MM, 1), round(h / MM, 1)], "files": written, **provenance}


def model_curves(s):
    """Figure 1: accuracy and cross-entropy of each model by SNR bin / clean and by distractor count."""
    fig, axes = plt.subplots(2, 2, figsize=(180 * MM, 120 * MM), layout="constrained", sharex="col")
    x_snr = list(range(5)) + [6]  # gap before the clean (no-cue, no-distractor) condition
    for m, st in MODELS.items():
        strata = s["models"][m]["strata"]
        acc = [strata[k]["accuracy"] for k in SNR_KEYS] + [strata["clean"]["accuracy"]]
        ce = [strata[k]["cross_entropy"] for k in SNR_KEYS] + [strata["clean"]["cross_entropy"]]
        for ax, y in ((axes[0, 0], acc), (axes[1, 0], ce)):
            ax.plot(x_snr[:5], y[:5], color=st["color"], marker=st["marker"], ls=st["ls"], label=st["label"], ms=5)
            ax.plot(x_snr[5:], y[5:], color=st["color"], marker=st["marker"], ls="none", ms=5)
        acc_d = [strata[k]["accuracy"] for k in DIS_KEYS]
        ce_d = [strata[k]["cross_entropy"] for k in DIS_KEYS]
        axes[0, 1].plot(range(1, 5), acc_d, color=st["color"], marker=st["marker"], ls=st["ls"], ms=5)
        axes[1, 1].plot(range(1, 5), ce_d, color=st["color"], marker=st["marker"], ls=st["ls"], ms=5)
    for ax in axes[:, 0]:
        ax.set_xticks(x_snr)
        ax.set_xticklabels(SNR_LABELS + ["clean\n(no cue)"])
        ax.axvline(5.5, color="0.6", lw=0.6)
    axes[1, 0].set_xlabel("SNR bin (dB), mixed scenes (n = 1,800 each); clean n = 1,000")
    axes[1, 1].set_xlabel("Number of distractors, mixed scenes (n = 2,250 each)")
    axes[1, 1].set_xticks(range(1, 5))
    axes[0, 0].set_ylabel("Top-1 accuracy (800 words)")
    axes[1, 0].set_ylabel("Cross-entropy (nats)")
    axes[0, 0].set_ylim(0, 1)
    axes[0, 1].set_ylim(0, 1)
    for ax in axes[1, :]:
        ax.set_ylim(0, 5.2)
    for ax, tag in zip(axes.flat, "abcd"):
        ax.text(-0.12, 1.04, tag, transform=ax.transAxes, fontweight="bold", fontsize=10)
        ax.grid(True, axis="y", lw=0.4, alpha=0.5)
    axes[0, 0].legend(loc="upper left", frameon=False, fontsize=7)
    fig.suptitle("Correct-cue performance on the frozen 10,000-trial bank (Job 728520; point estimates)", fontsize=9)
    return fig


def paired_forest(s):
    """Figure 2: paired differences vs author checkpoint with 95% cluster-bootstrap CI."""
    strata = [("overall", "all (n=10,000)"), ("mixed", "mixed (n=9,000)"), ("clean", "clean, no cue (n=1,000)")]
    strata += [(k, f"SNR {lab} dB (n=1,800)") for k, lab in zip(SNR_KEYS, SNR_LABELS)]
    strata += [(k, f"{k[-1]} distractor{'s' if k[-1] != '1' else ''} (n=2,250)") for k in DIS_KEYS]
    strata += [("target_gender_female", "female target (n=5,000)"), ("target_gender_male", "male target (n=5,000)")]
    pairs = [("formal40_vs_author_external", MODELS["formal40"], -0.18), ("valbest33_vs_author_external", MODELS["valbest33"], 0.18)]
    fig, axes = plt.subplots(1, 2, figsize=(180 * MM, 105 * MM), layout="constrained", sharey=True)
    y = list(range(len(strata)))[::-1]
    for ax, metric, scale, xlabel in (
        (axes[0], ACC, 100.0, "Accuracy difference, model − author (percentage points)"),
        (axes[1], CE, 1.0, "Cross-entropy improvement, author − model (nats)"),
    ):
        ax.axvline(0, color="0.3", lw=0.8)
        for pair, st, dy in pairs:
            rec = s["paired_model_differences"][pair]["strata"]
            means, lo, hi, ys = [], [], [], []
            for (key, _), yy in zip(strata, y):
                r = rec[key][metric]
                ci = r["target_speaker_cluster_bootstrap_95ci"]
                means.append(r["mean"] * scale)
                lo.append((r["mean"] - ci[0]) * scale)
                hi.append((ci[1] - r["mean"]) * scale)
                ys.append(yy + dy)
            ax.errorbar(means, ys, xerr=[lo, hi], fmt=st["marker"], color=st["color"], ms=4.5, capsize=2, lw=0.9,
                        label=f"{st['label'].split(' (')[0]} − author", mfc=st["color"] if pair.startswith("formal") else "white")
        for boundary in (2.5, 7.5, 11.5):
            ax.axhline(len(strata) - 1 - boundary, color="0.85", lw=0.6)
        ax.set_xlabel(xlabel)
        ax.grid(True, axis="x", lw=0.4, alpha=0.5)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([label for _, label in strata], fontsize=7)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=2, frameon=False, fontsize=7)
    for ax, tag in zip(axes, "ab"):
        ax.text(-0.04 if tag == "b" else -0.55, 1.02, tag, transform=ax.transAxes, fontweight="bold", fontsize=10)
    fig.suptitle(f"Paired per-trial differences with {CI_TEXT}; positive favours our model", fontsize=8.5)
    return fig


def controls(s):
    """Figure 3: cue-control subset (2,000 trials): accuracy per cue, paired drops, probe-probability shift."""
    conds = [("correct", "correct"), ("shuffled", "shuffled"), ("silent", "silent"), ("distractor", "distractor")]
    fig, axes = plt.subplots(1, 3, figsize=(180 * MM, 62 * MM), layout="constrained", width_ratios=[1.2, 1.2, 0.8])
    offsets = {"formal40": -0.2, "author_external": 0.0, "valbest33": 0.2}
    for m, st in MODELS.items():
        c = s["models"][m]["cue_controls"]
        accs = [c[f"{k}_accuracy"] if k != "correct" else c["correct_accuracy"] for k, _ in conds]
        axes[0].plot([i + offsets[m] for i in range(4)], accs, color=st["color"], marker=st["marker"], ls="none", ms=5, label=st["label"])
        means, lo, hi = [], [], []
        for k, _ in conds[1:]:
            r = c[f"correct_minus_{k}"]
            ci = r["target_speaker_cluster_bootstrap_95ci"]
            means.append(r["mean"] * 100)
            lo.append((r["mean"] - ci[0]) * 100)
            hi.append((ci[1] - r["mean"]) * 100)
        axes[1].errorbar([i + offsets[m] for i in range(3)], means, yerr=[lo, hi], fmt=st["marker"], color=st["color"], ms=4.5, capsize=2, lw=0.9)
        r = c["distractor_cue_p_probe_delta"]
        ci = r["target_speaker_cluster_bootstrap_95ci"]
        axes[2].errorbar([offsets[m]], [r["mean"]], yerr=[[r["mean"] - ci[0]], [ci[1] - r["mean"]]], fmt=st["marker"], color=st["color"], ms=4.5, capsize=2, lw=0.9)
    axes[0].set_xticks(range(4))
    axes[0].set_xticklabels([lab for _, lab in conds])
    axes[0].set(ylim=(0, 0.6), ylabel="Top-1 accuracy", xlabel="Cue condition (n = 2,000)")
    axes[1].set_xticks(range(3))
    axes[1].set_xticklabels(["− shuffled", "− silent", "− distractor"])
    axes[1].set(ylim=(0, 45), ylabel="Accuracy drop from correct cue (pp)",
                xlabel="Paired difference, correct cue minus control")
    axes[1].axhline(0, color="0.3", lw=0.8)
    axes[2].set_xticks([0])
    axes[2].set_xticklabels(["distractor cue"])
    axes[2].set(xlim=(-0.6, 0.6), ylim=(0, 0.25), ylabel="Δ P(probe word) vs correct cue")
    axes[2].axhline(0, color="0.3", lw=0.8)
    axes[0].legend(loc="upper right", frameon=False, fontsize=6.5)
    for ax, tag in zip(axes, "abc"):
        ax.text(-0.2, 1.04, tag, transform=ax.transAxes, fontweight="bold", fontsize=10)
        ax.grid(True, axis="y", lw=0.4, alpha=0.5)
    fig.suptitle(f"Cue controls on the 2,000-trial control subset; error bars: {CI_TEXT}", fontsize=8)
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--statistics", type=Path, default=STATS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stats = json.loads(args.statistics.read_text(encoding="utf-8"))
    s = stats["v4_summary"]
    out = args.output.absolute()
    out.mkdir(mode=0o700)
    provenance = {
        "source_statistics": str(args.statistics), "source_sha256": sha256(args.statistics),
        "job_id": stats["source"]["job_id"], "results_csv_sha256": stats["source"]["results_csv_sha256"],
        "uncertainty": CI_TEXT + f"; seed {s['bootstrap']['seed']} with fixed stratum offsets",
        "transformations": "none; point estimates and CI bounds plotted as stored; accuracy differences scaled to percentage points",
        "missing_data": "none; every predeclared stratum is populated",
        "publisher": "not specified; general manuscript layout (180 mm width), pending verification",
        "matplotlib": matplotlib.__version__,
    }
    manifest = []
    with plt.style.context(style_path()):
        for builder, stem in ((model_curves, "fig1_model_performance_by_condition"),
                              (paired_forest, "fig2_paired_differences_vs_author"),
                              (controls, "fig3_cue_controls")):
            fig = builder(s)
            manifest.append(export(fig, stem, out, provenance))
            plt.close(fig)
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps([{"figure": m["figure"], "size_mm": m["size_mm"], "png_sha256": m["files"]["png"]["sha256"][:16]} for m in manifest], indent=1))


if __name__ == "__main__":
    sys.exit(main())

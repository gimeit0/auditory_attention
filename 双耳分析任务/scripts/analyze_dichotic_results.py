#!/usr/bin/env python3
"""Summarize formal dichotic-listening results and generate a compact plot."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return math.nan, math.nan
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return center - margin, center + margin


def metric_row(name: str, successes: int, total: int) -> dict:
    low, high = wilson(successes, total)
    return {
        "metric": name,
        "successes": successes,
        "n": total,
        "rate": successes / total if total else math.nan,
        "ci95_low": low,
        "ci95_high": high,
    }


def speaker_bootstrap_ci(
    values: pd.Series,
    speakers: pd.Series,
    resamples: int = 20_000,
    seed: int = 20_260_721,
) -> tuple[float, float]:
    """Percentile CI after resampling speakers, preserving within-speaker trials."""
    frame = pd.DataFrame(
        {"value": values.astype(float).to_numpy(), "speaker": speakers.to_numpy()}
    )
    speaker_means = frame.groupby("speaker")["value"].mean().to_numpy()
    rng = np.random.default_rng(seed)
    samples = speaker_means[
        rng.integers(0, len(speaker_means), size=(resamples, len(speaker_means)))
    ].mean(axis=1)
    low, high = np.quantile(samples, [0.025, 0.975])
    return float(low), float(high)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--results",
        type=Path,
        default=REPO / "双耳分析任务/results/dichotic_results.csv",
    )
    ap.add_argument(
        "--summary",
        type=Path,
        default=REPO / "双耳分析任务/results/dichotic_summary.csv",
    )
    ap.add_argument(
        "--report",
        type=Path,
        default=REPO / "双耳分析任务/results/dichotic_summary.md",
    )
    ap.add_argument(
        "--figure",
        type=Path,
        default=REPO / "双耳分析任务/results/dichotic_summary.png",
    )
    ap.add_argument(
        "--error-audit",
        type=Path,
        default=REPO / "双耳分析任务/results/dichotic_error_audit.csv",
    )
    args = ap.parse_args()

    data = pd.read_csv(args.results)
    data = data[data["status"] == "ok"].copy()
    total = len(data)
    hit = int((data["dichotic_outcome"] == "hit").sum())
    confusion = int((data["dichotic_outcome"] == "ear_confusion").sum())
    other = total - hit - confusion
    presented = hit + confusion

    rows = [
        metric_row("dichotic_hit", hit, total),
        metric_row("ear_confusion", confusion, total),
        metric_row("other_word", other, total),
        metric_row("routing_given_presented_word", hit, presented),
        metric_row(
            "monaural_matched_correct",
            int(data["monaural_matched_correct"].sum()),
            total,
        ),
        metric_row(
            "diotic_clean_correct", int(data["diotic_clean_correct"].sum()), total
        ),
    ]
    for ear in ("left", "right"):
        subset = data[data["cue_ear"] == ear]
        rows.append(
            metric_row(
                f"dichotic_hit_{ear}",
                int((subset["dichotic_outcome"] == "hit").sum()),
                len(subset),
            )
        )
    summary = pd.DataFrame(rows)
    summary["speaker_bootstrap_low"] = math.nan
    summary["speaker_bootstrap_high"] = math.nan
    cluster_metrics = {
        "dichotic_hit": data["dichotic_outcome"].eq("hit"),
        "ear_confusion": data["dichotic_outcome"].eq("ear_confusion"),
        "other_word": data["dichotic_outcome"].eq("other"),
        "monaural_matched_correct": data["monaural_matched_correct"],
        "diotic_clean_correct": data["diotic_clean_correct"],
    }
    for metric, values in cluster_metrics.items():
        low, high = speaker_bootstrap_ci(values, data["speaker"])
        summary.loc[summary["metric"] == metric, [
            "speaker_bootstrap_low", "speaker_bootstrap_high"
        ]] = low, high
    for ear in ("left", "right"):
        subset = data[data["cue_ear"] == ear]
        low, high = speaker_bootstrap_ci(
            subset["dichotic_outcome"].eq("hit"), subset["speaker"]
        )
        summary.loc[summary["metric"] == f"dichotic_hit_{ear}", [
            "speaker_bootstrap_low", "speaker_bootstrap_high"
        ]] = low, high
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.summary, index=False)

    lookup = summary.set_index("metric")
    left = lookup.loc["dichotic_hit_left", "rate"]
    right = lookup.loc["dichotic_hit_right", "rate"]
    hit_low = lookup.loc["dichotic_hit", "ci95_low"]
    hit_high = lookup.loc["dichotic_hit", "ci95_high"]
    hit_cluster_low = lookup.loc["dichotic_hit", "speaker_bootstrap_low"]
    hit_cluster_high = lookup.loc["dichotic_hit", "speaker_bootstrap_high"]
    confusion_high = lookup.loc["ear_confusion", "ci95_high"]
    routing_low = lookup.loc["routing_given_presented_word", "ci95_low"]
    monaural_low = lookup.loc["monaural_matched_correct", "ci95_low"]
    monaural_high = lookup.loc["monaural_matched_correct", "ci95_high"]
    diotic_low = lookup.loc["diotic_clean_correct", "ci95_low"]
    diotic_high = lookup.loc["diotic_clean_correct", "ci95_high"]

    dichotic_correct = data["dichotic_outcome"].eq("hit")
    monaural_correct = data["monaural_matched_correct"].astype(bool)
    diotic_correct = data["diotic_clean_correct"].astype(bool)
    dichotic_and_diotic = int((dichotic_correct & diotic_correct).sum())
    dichotic_only = int((dichotic_correct & ~diotic_correct).sum())
    diotic_only = int((~dichotic_correct & diotic_correct).sum())
    neither_dichotic_nor_diotic = int((~dichotic_correct & ~diotic_correct).sum())

    errors = data.loc[~dichotic_correct].copy()
    errors.insert(
        0,
        "error_class",
        np.where(
            errors["diotic_clean_correct"].astype(bool),
            "dichotic_specific_error",
            "baseline_and_dichotic_error",
        ),
    )
    audit_columns = [
        "error_class", "trial_id", "pair_id", "speaker", "cue_ear",
        "assignment", "cued_word", "opposite_word", "pred_dichotic",
        "p_cued_dichotic", "p_opposite_dichotic", "pred_monaural_matched",
        "monaural_matched_correct", "pred_diotic_clean",
        "diotic_clean_correct", "cue_path", "cued_path", "opposite_path",
        "cued_center_s",
    ]
    errors = errors[audit_columns].sort_values(
        ["error_class", "p_cued_dichotic", "trial_id"]
    )
    errors.to_csv(args.error_audit, index=False)

    # Every target recording appears once in the left ear and once in the right
    # ear, so this is a target-matched descriptive ear comparison.
    ear_pairs = data.assign(hit=dichotic_correct).pivot(
        index=["pair_id", "cued_path"], columns="cue_ear", values="hit"
    )
    both_ears = int((ear_pairs["left"] & ear_pairs["right"]).sum())
    left_only = int((ear_pairs["left"] & ~ear_pairs["right"]).sum())
    right_only = int((~ear_pairs["left"] & ear_pairs["right"]).sum())
    neither_ear = int((~ear_pairs["left"] & ~ear_pairs["right"]).sum())

    report = [
        "# Dichotic-listening evaluation summary",
        "",
        f"- Valid trials: {total} (speakers: {data['speaker'].nunique()})",
        f"- Dichotic exact hit: {hit}/{total} = {hit/total:.1%} "
        f"(95% Wilson CI {hit_low:.1%}–{hit_high:.1%}; "
        f"speaker-bootstrap CI {hit_cluster_low:.1%}–{hit_cluster_high:.1%})",
        f"- Opposite-ear word: {confusion}/{total} = {confusion/total:.1%} "
        f"(95% Wilson upper bound {confusion_high:.1%})",
        f"- Other word: {other}/{total} = {other/total:.1%}",
        f"- Routing fidelity conditional on a presented-word response: "
        f"{hit}/{presented} = {hit/presented:.1%} "
        f"(95% Wilson lower bound {routing_low:.1%})" if presented else "- Routing fidelity: undefined",
        f"- Matched-level monaural correct: {monaural_correct.mean():.1%} "
        f"(95% Wilson CI {monaural_low:.1%}–{monaural_high:.1%})",
        f"- Standard diotic-clean correct: {diotic_correct.mean():.1%} "
        f"(95% Wilson CI {diotic_low:.1%}–{diotic_high:.1%})",
        f"- Left-cued vs right-cued hit: {left:.1%} vs {right:.1%}",
        "",
        "## Paired descriptive checks",
        "",
        f"- Dichotic / diotic-clean contingency: both correct {dichotic_and_diotic}, "
        f"dichotic only {dichotic_only}, diotic only {diotic_only}, "
        f"neither {neither_dichotic_nor_diotic}.",
        f"- Among the {int(diotic_correct.sum())} trials recognized in the standard "
        f"diotic-clean condition, dichotic accuracy was "
        f"{dichotic_and_diotic}/{int(diotic_correct.sum())} = "
        f"{dichotic_and_diotic/int(diotic_correct.sum()):.1%}.",
        f"- Target-matched left/right outcomes ({len(ear_pairs)} targets): "
        f"both correct {both_ears}, left only {left_only}, right only {right_only}, "
        f"neither {neither_ear}.",
        "",
        "## Interpretation",
        "",
        "Routing fidelity and absolute word recognition are separate. Zero "
        "opposite-ear responses strongly supports correct ear selection, but 78.9% "
        "absolute accuracy does not meet the adult-near-100% criterion. The "
        "diotic-clean comparison shows both baseline recognition errors and an "
        "additional dichotic cost. The unilateral monaural condition is an "
        "input-format control, not an upper bound: its silent second channel differs "
        "from the binaural input distribution used to train the model.",
    ]
    args.report.write_text("\n".join(report) + "\n", encoding="utf-8")

    names = ["Dichotic", "Monaural\nmatched", "Diotic\nclean"]
    metrics = ["dichotic_hit", "monaural_matched_correct", "diotic_clean_correct"]
    rates = np.asarray([lookup.loc[m, "rate"] for m in metrics])
    low = np.asarray([lookup.loc[m, "speaker_bootstrap_low"] for m in metrics])
    high = np.asarray([lookup.loc[m, "speaker_bootstrap_high"] for m in metrics])
    fig, ax = plt.subplots(figsize=(6.6, 4.6))
    ax.bar(names, rates, color=["#31588A", "#7AA6C2", "#A9C7D8"])
    ax.errorbar(
        np.arange(3), rates, yerr=[rates - low, high - rates],
        fmt="none", color="black", capsize=4,
    )
    ax.axhline(1.0, color="#777777", linewidth=1, linestyle="--")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Exact target-word accuracy")
    ax.set_title("Same-speaker dichotic listening")
    ax.spines[["top", "right"]].set_visible(False)
    for index, rate in enumerate(rates):
        ax.text(index, high[index] + 0.025, f"{rate:.1%}", ha="center")
    fig.tight_layout()
    fig.savefig(args.figure, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.3f}"))
    print(f"report:  {args.report}")
    print(f"figure:  {args.figure}")
    print(f"errors:  {args.error_audit}")


if __name__ == "__main__":
    main()

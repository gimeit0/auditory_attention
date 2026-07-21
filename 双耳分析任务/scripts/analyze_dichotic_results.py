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
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.summary, index=False)

    lookup = summary.set_index("metric")
    left = lookup.loc["dichotic_hit_left", "rate"]
    right = lookup.loc["dichotic_hit_right", "rate"]
    report = [
        "# Dichotic-listening evaluation summary",
        "",
        f"- Valid trials: {total}",
        f"- Dichotic exact hit: {hit}/{total} = {hit/total:.1%}",
        f"- Opposite-ear word: {confusion}/{total} = {confusion/total:.1%}",
        f"- Other word: {other}/{total} = {other/total:.1%}",
        f"- Routing fidelity conditional on a presented-word response: {hit}/{presented} = {hit/presented:.1%}" if presented else "- Routing fidelity: undefined",
        f"- Matched-level monaural correct: {data['monaural_matched_correct'].mean():.1%}",
        f"- Standard diotic-clean correct: {data['diotic_clean_correct'].mean():.1%}",
        f"- Left-cued vs right-cued hit: {left:.1%} vs {right:.1%}",
        "",
        "Interpretation: routing fidelity and absolute word recognition are separate. "
        "A low opposite-ear rate supports ear selection, while comparison with the "
        "monaural and diotic controls shows how much accuracy is lost because of "
        "dichotic competition rather than baseline word-recognition failure.",
    ]
    args.report.write_text("\n".join(report) + "\n", encoding="utf-8")

    names = ["Dichotic", "Monaural\nmatched", "Diotic\nclean"]
    metrics = ["dichotic_hit", "monaural_matched_correct", "diotic_clean_correct"]
    rates = np.asarray([lookup.loc[m, "rate"] for m in metrics])
    low = np.asarray([lookup.loc[m, "ci95_low"] for m in metrics])
    high = np.asarray([lookup.loc[m, "ci95_high"] for m in metrics])
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
        ax.text(index, rate + 0.035, f"{rate:.1%}", ha="center")
    fig.tight_layout()
    fig.savefig(args.figure, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.3f}"))
    print(f"report:  {args.report}")
    print(f"figure:  {args.figure}")


if __name__ == "__main__":
    main()

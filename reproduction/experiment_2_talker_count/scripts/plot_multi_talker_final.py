"""Create paper-aligned multi-talker figures for the final group-meeting deck."""

from pathlib import Path
import pickle
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from num2words import num2words


PROJECT = Path(__file__).resolve().parents[3]
EXPERIMENT_1_DIR = PROJECT / "reproduction/experiment_1_gender"
RESULT_DIR = Path(__file__).resolve().parents[1]
SAMPLE_CSV = EXPERIMENT_1_DIR / "data/samples_expanded.csv"
VOCAB_PATH = PROJECT / "cv_800_word_label_to_int_dict.pkl"

RESULT_CSV = RESULT_DIR / "results/multi_talker_results.csv"
MAIN_OUT = RESULT_DIR / "figures/fig_multi_talker_final.png"
ISSN_OUT = RESULT_DIR / "figures/fig_issn_information_masking_final.png"
SUMMARY_OUT = RESULT_DIR / "results/multi_talker_summary_final.csv"

SNRS = [-9.0, -6.0, -3.0, 0.0, 3.0]
CONDITION_ORDER = ["one_talker", "two_talker", "four_talker", "babble"]
COLORS = {
    "one_talker": "#F0A5C0",
    "two_talker": "#D84C98",
    "four_talker": "#9C2E6D",
    "babble": "#5D2E7C",
    "issn": "#6D6D6D",
}
LABELS = {
    "one_talker": "One-talker (pooled sex)",
    "two_talker": "Two-talker",
    "four_talker": "Four-talker",
    "babble": "8-talker babble",
    "issn": "ISSN (matched stationary noise)",
}


def normalize_token(token: str) -> list[str]:
    clean = re.sub(r"[^a-z0-9' ]+", "", str(token).lower())
    if not clean:
        return []
    if clean.isdigit():
        return num2words(clean).replace("-", " ").split()
    return [clean]


def sentence_words(sentence: str, vocab: set[str]) -> set[str]:
    words = set()
    for token in str(sentence).split():
        words.update(word for word in normalize_token(token) if word in vocab)
    return words


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    results = pd.read_csv(RESULT_CSV)
    samples = pd.read_csv(SAMPLE_CSV)
    with VOCAB_PATH.open("rb") as handle:
        vocab = set(pickle.load(handle))

    target_wordsets = {
        row.trial_id: sentence_words(row.target_sentence, vocab)
        for row in samples.itertuples()
    }
    results["target_score"] = [
        int(pred in target_wordsets[trial_id])
        for trial_id, pred in zip(results.trial_id, results.pred)
    ]

    speaker_map = samples.set_index("trial_id")["target_speaker"]
    results["target_speaker"] = results.trial_id.map(speaker_map)

    results["paper_condition"] = results.condition.replace(
        {"one_same": "one_talker", "one_diff": "one_talker"}
    )

    finite = results[results.snr.astype(str) != "inf"].copy()
    finite["snr_num"] = finite.snr.astype(float)
    per_trial = (
        finite.groupby(
            ["trial_id", "target_speaker", "paper_condition", "snr_num"],
            as_index=False,
        )[["target_score", "is_exact", "conf_sent"]]
        .mean()
    )

    clean = results[results.condition == "no_distractor"].copy()
    clean = clean[["trial_id", "target_speaker", "target_score", "is_exact"]]
    return per_trial, clean


def cluster_bootstrap(
    data: pd.DataFrame,
    condition: str,
    snr: float,
    metric: str,
    rng: np.random.Generator,
    n_boot: int = 4000,
) -> tuple[float, float, float]:
    selected = data[(data.paper_condition == condition) & (data.snr_num == snr)]
    grouped = selected.groupby("target_speaker")[metric].agg(["sum", "count"])
    cluster_sums = grouped["sum"].to_numpy(dtype=float)
    cluster_counts = grouped["count"].to_numpy(dtype=float)
    cluster_count = len(grouped)
    draws = rng.integers(0, cluster_count, size=(n_boot, cluster_count))
    estimates = cluster_sums[draws].sum(axis=1) / cluster_counts[draws].sum(axis=1)
    mean = selected[metric].mean()
    low, high = np.quantile(estimates, [0.025, 0.975])
    return float(mean), float(low), float(high)


def clean_bootstrap(
    clean: pd.DataFrame,
    metric: str,
    rng: np.random.Generator,
    n_boot: int = 4000,
) -> tuple[float, float, float]:
    grouped = clean.groupby("target_speaker")[metric].agg(["sum", "count"])
    cluster_sums = grouped["sum"].to_numpy(dtype=float)
    cluster_counts = grouped["count"].to_numpy(dtype=float)
    cluster_count = len(grouped)
    draws = rng.integers(0, cluster_count, size=(n_boot, cluster_count))
    estimates = cluster_sums[draws].sum(axis=1) / cluster_counts[draws].sum(axis=1)
    mean = clean[metric].mean()
    low, high = np.quantile(estimates, [0.025, 0.975])
    return float(mean), float(low), float(high)


def build_summary(data: pd.DataFrame, clean: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(20260716)
    rows = []
    for condition in [*CONDITION_ORDER, "issn"]:
        for snr in SNRS:
            for metric in ["target_score", "is_exact", "conf_sent"]:
                mean, low, high = cluster_bootstrap(
                    data, condition, snr, metric, rng
                )
                rows.append(
                    {
                        "condition": condition,
                        "snr": snr,
                        "metric": metric,
                        "mean": mean,
                        "ci_low": low,
                        "ci_high": high,
                    }
                )
    for metric in ["target_score", "is_exact"]:
        mean, low, high = clean_bootstrap(clean, metric, rng)
        rows.append(
            {
                "condition": "no_distractor",
                "snr": np.inf,
                "metric": metric,
                "mean": mean,
                "ci_low": low,
                "ci_high": high,
            }
        )
    summary = pd.DataFrame(rows)
    summary.to_csv(SUMMARY_OUT, index=False)
    return summary


def values(summary: pd.DataFrame, condition: str, metric: str):
    selected = summary[
        (summary.condition == condition) & (summary.metric == metric)
    ].sort_values("snr")
    return (
        selected["mean"].to_numpy(),
        selected["ci_low"].to_numpy(),
        selected["ci_high"].to_numpy(),
    )


def style_axis(axis, ylabel: str, include_inf: bool):
    axis.spines[["top", "right"]].set_visible(False)
    axis.set_ylim(-0.02, 1.0)
    axis.set_yticks(np.arange(0, 1.01, 0.2))
    axis.set_ylabel(ylabel)
    axis.set_xlabel("SNR (dB)")
    ticks = np.arange(6 if include_inf else 5)
    labels = ["-9", "-6", "-3", "0", "3"] + (["inf"] if include_inf else [])
    axis.set_xticks(ticks, labels)
    axis.set_xlim(-0.5, len(ticks) - 0.5)
    axis.grid(axis="y", color="#E8E8E8", linewidth=0.7, zorder=0)


def plot_main(summary: pd.DataFrame):
    plt.rcParams.update(
        {
            "font.family": "Arial",
            "font.size": 11,
            "axes.linewidth": 1.0,
            "figure.facecolor": "white",
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(12.2, 5.2))
    x = np.arange(5)

    for axis, metric, ylabel in [
        (axes[0], "target_score", "Prop. target word"),
        (axes[1], "conf_sent", "Prop. distractor word"),
    ]:
        for condition in CONDITION_ORDER:
            mean, low, high = values(summary, condition, metric)
            axis.plot(
                x,
                mean,
                "-o",
                color=COLORS[condition],
                linewidth=2.4,
                markersize=7,
                markeredgecolor="white",
                markeredgewidth=0.9,
                label=LABELS[condition],
                zorder=3,
            )
            axis.fill_between(x, low, high, color=COLORS[condition], alpha=0.18)
        style_axis(axis, ylabel, include_inf=(metric == "target_score"))

    clean = summary[
        (summary.condition == "no_distractor") & (summary.metric == "target_score")
    ].iloc[0]
    axes[0].errorbar(
        [5],
        [clean["mean"]],
        yerr=[[clean["mean"] - clean["ci_low"]], [clean["ci_high"] - clean["mean"]]],
        fmt="o",
        color="black",
        markersize=8,
        capsize=3,
        label="No distractor",
        zorder=5,
    )
    axes[0].set_title("Accuracy", fontweight="bold", pad=10)
    axes[1].set_title("Distractor-word confusions", fontweight="bold", pad=10)
    axes[0].text(-0.08, 1.035, "a", transform=axes[0].transAxes, fontsize=20, fontweight="bold")
    axes[1].text(-0.08, 1.035, "d", transform=axes[1].transAxes, fontsize=20, fontweight="bold")

    handles, labels = axes[0].get_legend_handles_labels()
    no_index = labels.index("No distractor")
    order = [no_index] + [index for index in range(len(labels)) if index != no_index]
    axes[0].legend(
        [handles[index] for index in order],
        [labels[index] for index in order],
        frameon=False,
        loc="upper left",
        bbox_to_anchor=(0.02, 0.98),
        fontsize=9.5,
    )
    fig.suptitle(
        "Experiment 1: Number of distractors",
        fontsize=18,
        fontweight="bold",
        y=1.01,
    )
    fig.text(
        0.5,
        0.01,
        "Single pretrained checkpoint · N = 600 trials / 149 target speakers · "
        "95% cluster-bootstrap CI · One-talker pools same- and different-sex trials",
        ha="center",
        color="#555555",
        fontsize=9.5,
    )
    fig.tight_layout(rect=[0, 0.05, 1, 0.97])
    fig.savefig(MAIN_OUT, dpi=220, bbox_inches="tight")
    plt.close(fig)


def plot_issn(summary: pd.DataFrame):
    plt.rcParams.update({"font.family": "Arial", "font.size": 12})
    fig, axis = plt.subplots(figsize=(8.8, 5.7))
    x = np.arange(5)
    for condition in ["one_talker", "four_talker", "babble", "issn"]:
        mean, low, high = values(summary, condition, "target_score")
        line_style = "--" if condition == "issn" else "-"
        marker = "s" if condition == "issn" else "o"
        axis.plot(
            x,
            mean * 100,
            line_style,
            marker=marker,
            color=COLORS[condition],
            linewidth=2.6,
            markersize=7,
            label=LABELS[condition],
        )
        axis.fill_between(
            x, low * 100, high * 100, color=COLORS[condition], alpha=0.16
        )
    axis.spines[["top", "right"]].set_visible(False)
    axis.set_xticks(x, ["-9", "-6", "-3", "0", "3"])
    axis.set_xlabel("Target-to-total-masker SNR (dB)")
    axis.set_ylabel("Target-word accuracy (%)")
    axis.set_ylim(0, 82)
    axis.grid(axis="y", color="#E8E8E8", linewidth=0.7)
    axis.legend(frameon=False, loc="upper left", fontsize=10)
    fig.suptitle(
        "Speech maskers remain harder than matched stationary noise",
        fontsize=16,
        fontweight="bold",
        y=0.98,
    )
    fig.text(
        0.5,
        0.92,
        "Pattern is consistent with information masking beyond temporal glimpsing",
        ha="center",
        color="#555555",
        fontsize=11,
    )
    fig.text(
        0.5,
        0.01,
        "Paper-compatible target scoring · 95% cluster-bootstrap CI by target speaker",
        ha="center",
        color="#555555",
        fontsize=9.5,
    )
    fig.tight_layout(rect=[0, 0.05, 1, 0.89])
    fig.savefig(ISSN_OUT, dpi=220, bbox_inches="tight")
    plt.close(fig)


def main():
    data, clean = load_data()
    summary = build_summary(data, clean)
    plot_main(summary)
    plot_issn(summary)
    print(f"saved: {MAIN_OUT}")
    print(f"saved: {ISSN_OUT}")
    print(f"saved: {SUMMARY_OUT}")


if __name__ == "__main__":
    main()

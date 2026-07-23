#!/usr/bin/env python3
"""Create a reproducible acoustic audit and a manual-review queue.

The primary 347/440 exact-hit result is never rescored here.  This script adds
diagnostic measurements for the model's central two-second crop, separates
baseline-recognition failures from dichotic-specific failures, and creates
blank columns for a human listener to review the 93 error trials.
"""

from __future__ import annotations

import argparse
import difflib
import math
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from slice_stimuli import load_44k, slice_centered, slice_middle


SR = 44_100
INPUT_SECONDS = 2.5
MODEL_SECONDS = 2.0
RMS_LEVEL = 0.02
FRAME_SAMPLES = int(0.020 * SR)
HOP_SAMPLES = int(0.010 * SR)
LOW_ENERGY_RATIO = 0.01  # -40 dB relative to the largest frame RMS.
DEFAULT_CLIPS = Path(
    os.environ.get(
        "CV_CLIPS",
        "/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en/clips",
    )
)


def mono_norm(wav: np.ndarray, level: float = RMS_LEVEL) -> np.ndarray:
    wav = wav.astype(np.float32, copy=False) - float(np.mean(wav))
    value = float(np.sqrt(np.mean(np.square(wav, dtype=np.float64))))
    return wav * (level / value) if value > 0 else wav


def center_crop(wav: np.ndarray, seconds: float = MODEL_SECONDS) -> np.ndarray:
    samples = int(round(seconds * SR))
    if len(wav) < samples:
        raise ValueError(f"waveform has {len(wav)} samples; need {samples}")
    start = (len(wav) - samples) // 2
    return wav[start:start + samples]


def rms(wav: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(wav, dtype=np.float64))))


def low_energy_fraction(wav: np.ndarray) -> float:
    """Fraction of 20-ms frames below -40 dB of this crop's peak frame RMS.

    This is an energy proxy, not a voice-activity detector and not a manual
    judgement that speech is absent.
    """
    frames = []
    for start in range(0, len(wav) - FRAME_SAMPLES + 1, HOP_SAMPLES):
        frame = wav[start:start + FRAME_SAMPLES]
        frames.append(rms(frame))
    values = np.asarray(frames)
    peak = float(values.max(initial=0.0))
    if peak == 0:
        return 1.0
    return float(np.mean(values < peak * LOW_ENERGY_RATIO))


def segment_metrics(segment: np.ndarray, active_scale: float = 1.0) -> dict:
    normalized = mono_norm(segment) * active_scale
    cropped = center_crop(normalized)
    return {
        "central2_rms": rms(cropped),
        "central2_low_energy_fraction": low_energy_fraction(cropped),
    }


def safe_spearman(x: pd.Series, y: pd.Series) -> tuple[float, float]:
    result = spearmanr(x, y)
    return float(result.statistic), float(result.pvalue)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--results",
        type=Path,
        default=REPO / "双耳分析任务/results/dichotic_results.csv",
    )
    ap.add_argument("--clips", type=Path, default=DEFAULT_CLIPS)
    ap.add_argument(
        "--trial-audit",
        type=Path,
        default=REPO / "双耳分析任务/results/dichotic_acoustic_audit.csv",
    )
    ap.add_argument(
        "--error-review",
        type=Path,
        default=REPO / "双耳分析任务/results/dichotic_manual_review.csv",
    )
    ap.add_argument(
        "--report",
        type=Path,
        default=REPO / "双耳分析任务/results/dichotic_error_audit_summary.md",
    )
    ap.add_argument(
        "--figure",
        type=Path,
        default=REPO / "双耳分析任务/results/dichotic_error_audit.png",
    )
    args = ap.parse_args()

    data = pd.read_csv(args.results)
    data = data[data["status"].eq("ok")].copy()
    if len(data) == 0:
        raise ValueError("no status=ok trials in results")

    audio_cache: dict[str, np.ndarray] = {}
    target_cache: dict[tuple[str, float], dict] = {}
    cue_cache: dict[str, dict] = {}

    def audio(path: str) -> np.ndarray:
        if path not in audio_cache:
            audio_cache[path] = load_44k(str(args.clips / path))
        return audio_cache[path]

    def target_metrics(path: str, center_s: float) -> dict:
        key = (path, float(center_s))
        if key not in target_cache:
            segment = slice_centered(audio(path), float(center_s))
            if segment is None:
                raise ValueError(f"invalid target slice: {path} @ {center_s}")
            target_cache[key] = segment_metrics(segment)
        return target_cache[key]

    def cue_metrics(path: str) -> dict:
        if path not in cue_cache:
            segment = slice_middle(audio(path))
            if segment is None:
                raise ValueError(f"invalid cue slice: {path}")
            # A unilateral cue is globally normalized across one active and one
            # zero channel, making the active channel sqrt(2) times mono RMS.
            cue_cache[path] = segment_metrics(segment, active_scale=math.sqrt(2))
        return cue_cache[path]

    rows = []
    for row in data.itertuples(index=False):
        if row.cue_ear == "left":
            opposite_path = row.right_path
            opposite_center_s = float(row.right_center_s)
        else:
            opposite_path = row.left_path
            opposite_center_s = float(row.left_center_s)

        cued = target_metrics(row.cued_path, float(row.cued_center_s))
        opposite = target_metrics(opposite_path, opposite_center_s)
        cue = cue_metrics(row.cue_path)
        level_db = 20 * math.log10(
            cued["central2_rms"] / opposite["central2_rms"]
        )
        is_hit = row.dichotic_outcome == "hit"
        if is_hit:
            error_class = "hit"
        elif row.dichotic_outcome == "ear_confusion":
            error_class = "ear_confusion"
        elif bool(row.diotic_clean_correct):
            error_class = "dichotic_specific_error"
        else:
            error_class = "baseline_and_dichotic_error"

        similarity = difflib.SequenceMatcher(
            None, str(row.cued_word), str(row.pred_dichotic)
        ).ratio()
        record = row._asdict()
        record.update(
            {
                "is_dichotic_hit": int(is_hit),
                "error_class": error_class,
                "cued_central2_rms": cued["central2_rms"],
                "opposite_central2_rms": opposite["central2_rms"],
                "effective_cued_minus_opposite_db": level_db,
                "absolute_effective_level_gap_db": abs(level_db),
                "cued_low_energy_fraction": cued[
                    "central2_low_energy_fraction"
                ],
                "opposite_low_energy_fraction": opposite[
                    "central2_low_energy_fraction"
                ],
                "cue_active_central2_rms": cue["central2_rms"],
                "cue_low_energy_fraction": cue[
                    "central2_low_energy_fraction"
                ],
                "target_prediction_string_similarity": similarity,
                "near_label_string_ge_0_8": int(similarity >= 0.8),
                "same_wrong_prediction_as_diotic": int(
                    not bool(row.diotic_clean_correct)
                    and row.pred_dichotic == row.pred_diotic_clean
                ),
            }
        )
        rows.append(record)

    audited = pd.DataFrame(rows)
    speaker_errors = (
        audited.groupby("speaker")["is_dichotic_hit"]
        .apply(lambda values: int((values == 0).sum()))
    )
    audited["speaker_dichotic_errors_out_of_4"] = audited["speaker"].map(
        speaker_errors
    )

    args.trial_audit.parent.mkdir(parents=True, exist_ok=True)
    audited.to_csv(args.trial_audit, index=False)

    errors = audited[audited["is_dichotic_hit"].eq(0)].copy()
    priority = {
        "baseline_and_dichotic_error": "1_check_target_alignment_and_quality",
        "dichotic_specific_error": "2_check_competition_and_cue_match",
        "ear_confusion": "3_check_ear_routing",
    }
    errors.insert(0, "review_priority", errors["error_class"].map(priority))
    errors = errors.sort_values(
        ["review_priority", "p_cued_dichotic", "trial_id"]
    ).reset_index(drop=True)
    errors.insert(0, "review_order", np.arange(1, len(errors) + 1))
    manual_columns = (
        "manual_target_word_audible_yes_no",
        "manual_alignment_center_ok_yes_no",
        "manual_transcript_matches_audio_yes_no",
        "manual_audio_quality_ok_yes_no",
        "manual_label_equivalent_yes_no",
        "manual_exclude_for_objective_reason_yes_no",
        "manual_notes",
    )
    existing_review = pd.DataFrame()
    if args.error_review.exists():
        existing_review = pd.read_csv(args.error_review, keep_default_na=False)
        if "trial_id" in existing_review:
            existing_review = existing_review.set_index("trial_id")
    for column in manual_columns:
        if column in existing_review:
            errors[column] = errors["trial_id"].map(existing_review[column]).fillna("")
        else:
            errors[column] = ""

    review_columns = [
        "review_order",
        "review_priority",
        "error_class",
        "trial_id",
        "pair_id",
        "speaker",
        "cue_ear",
        "cued_word",
        "opposite_word",
        "pred_dichotic",
        "pred_diotic_clean",
        "p_cued_dichotic",
        "p_opposite_dichotic",
        "target_prediction_string_similarity",
        "near_label_string_ge_0_8",
        "same_wrong_prediction_as_diotic",
        "effective_cued_minus_opposite_db",
        "absolute_effective_level_gap_db",
        "cued_low_energy_fraction",
        "opposite_low_energy_fraction",
        "cue_low_energy_fraction",
        "speaker_dichotic_errors_out_of_4",
        "cue_path",
        "cued_path",
        "cued_center_s",
        "opposite_path",
        "left_path",
        "left_center_s",
        "right_path",
        "right_center_s",
        "manual_target_word_audible_yes_no",
        "manual_alignment_center_ok_yes_no",
        "manual_transcript_matches_audio_yes_no",
        "manual_audio_quality_ok_yes_no",
        "manual_label_equivalent_yes_no",
        "manual_exclude_for_objective_reason_yes_no",
        "manual_notes",
    ]
    errors[review_columns].to_csv(args.error_review, index=False)

    hit = audited["is_dichotic_hit"].astype(bool)
    signed_rho, signed_p = safe_spearman(
        audited["effective_cued_minus_opposite_db"], hit.astype(int)
    )
    absolute_rho, absolute_p = safe_spearman(
        audited["absolute_effective_level_gap_db"], hit.astype(int)
    )
    speaker_table = audited.groupby("speaker").agg(
        errors=("is_dichotic_hit", lambda values: int((values == 0).sum())),
        cue_low_energy_fraction=("cue_low_energy_fraction", "first"),
    )
    cue_rho, cue_p = safe_spearman(
        speaker_table["cue_low_energy_fraction"], speaker_table["errors"]
    )

    baseline_errors = errors[errors["error_class"].eq(
        "baseline_and_dichotic_error"
    )]
    dichotic_errors = errors[errors["error_class"].eq(
        "dichotic_specific_error"
    )]
    near_errors = int(errors["near_label_string_ge_0_8"].sum())
    repeated_baseline = int(
        baseline_errors["same_wrong_prediction_as_diotic"].sum()
    )
    over_1 = int((audited["absolute_effective_level_gap_db"] > 1).sum())
    over_2 = int((audited["absolute_effective_level_gap_db"] > 2).sum())
    level_quantiles = audited["effective_cued_minus_opposite_db"].quantile(
        [0.025, 0.5, 0.975]
    )
    speaker_distribution = speaker_errors.value_counts().sort_index()

    report = [
        "# Dichotic error and central-two-second acoustic audit",
        "",
        "## Scope and method",
        "",
        f"- Valid trials audited: {len(audited)}",
        f"- Error trials queued for manual review: {len(errors)}",
        "- RMS was measured after the same full-2.5-second normalization used "
        "by the evaluation, followed by the model's central-2-second crop.",
        "- The low-energy value is the fraction of 20-ms frames below -40 dB "
        "of that crop's peak frame RMS. It is an energy proxy, not VAD.",
        "- These diagnostics do not alter the primary exact-word score.",
        "",
        "## Error decomposition",
        "",
        f"- Baseline and dichotic errors: {len(baseline_errors)}",
        f"- Dichotic-specific errors: {len(dichotic_errors)}",
        f"- Opposite-ear confusions: "
        f"{int(errors['error_class'].eq('ear_confusion').sum())}",
        f"- Error strings with target/prediction similarity >= 0.8: "
        f"{near_errors}/{len(errors)}",
        f"- Baseline errors repeating the same wrong diotic prediction: "
        f"{repeated_baseline}/{len(baseline_errors)}",
        "",
        "## Effective central-two-second level",
        "",
        f"- Median cued-minus-opposite level: {level_quantiles.loc[0.5]:+.2f} dB",
        f"- Central 95% range: {level_quantiles.loc[0.025]:+.2f} to "
        f"{level_quantiles.loc[0.975]:+.2f} dB",
        f"- Absolute imbalance > 1 dB: {over_1}/{len(audited)}",
        f"- Absolute imbalance > 2 dB: {over_2}/{len(audited)}",
        f"- Signed effective level vs hit: Spearman rho={signed_rho:.3f}, "
        f"p={signed_p:.3f}",
        f"- Absolute effective gap vs hit: Spearman rho={absolute_rho:.3f}, "
        f"p={absolute_p:.3f}",
        "",
        "Interpretation: the AB/BA and left/right swaps make the signed level "
        "distribution symmetric. There is no evidence that a louder cued central "
        "crop explains the overall result. Absolute-gap associations are "
        "descriptive and confounded with recording/word difficulty.",
        "",
        "## Cue low-energy proxy and speaker clustering",
        "",
        f"- Cue low-energy fraction vs errors per speaker: Spearman rho={cue_rho:.3f}, "
        f"p={cue_p:.3f}",
        "- Speakers by number of dichotic errors out of four: "
        + ", ".join(
            f"{int(error_count)} errors: {int(count)} speakers"
            for error_count, count in speaker_distribution.items()
        ),
        "",
        "Interpretation: the energy proxy does not show that cue silence is the "
        "main error source. Manual listening is still required for alignment, "
        "audibility, transcription and recording-quality judgements.",
        "",
        "## Manual-review rule",
        "",
        "Review the CSV in `review_order`. Keep the original 440-trial primary "
        "result unchanged. Any exclusion must use an objective audio/alignment "
        "criterion defined independently of the model prediction; normalized-label "
        "results, if reported, must be a separate sensitivity analysis.",
    ]
    args.report.write_text("\n".join(report) + "\n", encoding="utf-8")

    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.0))
    axes[0].boxplot(
        [
            audited.loc[~hit, "effective_cued_minus_opposite_db"],
            audited.loc[hit, "effective_cued_minus_opposite_db"],
        ],
        tick_labels=["Error", "Hit"],
        showfliers=True,
    )
    axes[0].axhline(0, color="#777777", linestyle="--", linewidth=1)
    axes[0].set_ylabel("Cued minus opposite level (dB)")
    axes[0].set_title("Central 2-s effective level")

    axes[1].boxplot(
        [
            audited.loc[audited["diotic_clean_correct"].eq(0),
                        "cued_low_energy_fraction"],
            audited.loc[audited["diotic_clean_correct"].eq(1),
                        "cued_low_energy_fraction"],
        ],
        tick_labels=["Diotic error", "Diotic hit"],
        showfliers=True,
    )
    axes[1].set_ylabel("Low-energy frame fraction")
    axes[1].set_title("Target energy proxy")

    x = np.arange(5)
    counts = np.asarray([speaker_distribution.get(value, 0) for value in x])
    axes[2].bar(x, counts, color="#31588A")
    axes[2].set_xticks(x)
    axes[2].set_xlabel("Dichotic errors per speaker (of 4)")
    axes[2].set_ylabel("Speakers")
    axes[2].set_title("Error clustering")
    for axis in axes:
        axis.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(args.figure, dpi=180, bbox_inches="tight")
    plt.close(fig)

    print(f"trial audit:   {args.trial_audit}")
    print(f"manual review: {args.error_review}")
    print(f"report:        {args.report}")
    print(f"figure:        {args.figure}")
    print(
        f"errors: baseline={len(baseline_errors)}, "
        f"dichotic-specific={len(dichotic_errors)}, total={len(errors)}"
    )


if __name__ == "__main__":
    main()

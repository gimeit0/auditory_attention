#!/usr/bin/env python3
"""Audit silence and effective SNR for the two reproduction experiments.

The mixing code sets SNR from the RMS of the complete 2.5 s target and masker,
after removing each waveform's DC component.  The cochleagram front end then
uses the central 2.0 s.  This script measures the resulting SNR offset:

    central-2-s effective SNR - nominal full-2.5-s SNR

Experiment 1 is reconstructed exactly from ``samples_expanded.csv``.  The
Experiment 2 result CSV does not contain masker IDs, so its acoustic audit is a
deterministic reconstruction of the documented balanced/nested design.  The
output never presents those reconstructed identities as the original run.

Silence is estimated from 20 ms frame RMS.  A frame is labelled low-energy
when it is at least 40 dB below the clip's 95th-percentile frame RMS.  This is
an energy-based diagnostic, not a phonetic voice-activity annotation.
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys
from functools import lru_cache
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from slice_stimuli import SR, SEG_N, load_44k, slice_centered, slice_middle


EXP1 = REPO / "reproduction/experiment_1_gender"
EXP2 = REPO / "reproduction/experiment_2_talker_count"
DEFAULT_AUDIO = Path(
    os.environ.get(
        "CV_CLIPS",
        "/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en/clips",
    )
)
CENTER_N = int(2.0 * SR)
CENTER_START = (SEG_N - CENTER_N) // 2
CENTER_END = CENTER_START + CENTER_N
EPS = 1e-12


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


def demean(x: np.ndarray) -> np.ndarray:
    return x.astype(np.float64, copy=False) - float(np.mean(x, dtype=np.float64))


def center2(x: np.ndarray) -> np.ndarray:
    return x[CENTER_START:CENTER_END]


def frame_rms(x: np.ndarray, frame_ms: float = 20.0, hop_ms: float = 10.0) -> np.ndarray:
    frame = int(round(SR * frame_ms / 1000.0))
    hop = int(round(SR * hop_ms / 1000.0))
    if len(x) < frame:
        return np.asarray([rms(x)])
    starts = np.arange(0, len(x) - frame + 1, hop)
    return np.asarray([rms(x[s:s + frame]) for s in starts])


def low_energy_fraction(x: np.ndarray, threshold_db: float = -40.0) -> float:
    """Fraction of frames >=40 dB below the clip's p95 frame energy."""
    fr = frame_rms(demean(x))
    ref = float(np.percentile(fr, 95))
    if ref <= EPS:
        return 1.0
    threshold = ref * (10.0 ** (threshold_db / 20.0))
    return float(np.mean(fr < threshold))


def edge_low_energy_seconds(x: np.ndarray, threshold_db: float = -40.0) -> tuple[float, float]:
    fr = frame_rms(demean(x))
    ref = float(np.percentile(fr, 95))
    if ref <= EPS:
        return len(x) / SR, len(x) / SR
    quiet = fr < ref * (10.0 ** (threshold_db / 20.0))
    lead = 0
    for q in quiet:
        if not q:
            break
        lead += 1
    trail = 0
    for q in quiet[::-1]:
        if not q:
            break
        trail += 1
    # Frame count is converted by the 10 ms hop. This is a diagnostic estimate.
    return lead * 0.010, trail * 0.010


def activity_sample_mask(x: np.ndarray, threshold_db: float = -40.0) -> np.ndarray:
    """Expand an energy-based frame activity decision to a sample mask."""
    xd = demean(x)
    frame = int(round(SR * 0.020))
    hop = int(round(SR * 0.010))
    starts = np.arange(0, len(xd) - frame + 1, hop)
    vals = np.asarray([rms(xd[s:s + frame]) for s in starts])
    ref = float(np.percentile(vals, 95)) if len(vals) else 0.0
    mask = np.zeros(len(xd), dtype=bool)
    if ref <= EPS:
        return mask
    active = vals >= ref * (10.0 ** (threshold_db / 20.0))
    for s in starts[active]:
        mask[s:s + frame] = True
    return mask


def waveform_stats(x: np.ndarray, prefix: str) -> dict[str, float]:
    lead, trail = edge_low_energy_seconds(x)
    return {
        f"{prefix}_full_low_energy_fraction": low_energy_fraction(x),
        f"{prefix}_center2_low_energy_fraction": low_energy_fraction(center2(x)),
        f"{prefix}_leading_low_energy_s": lead,
        f"{prefix}_trailing_low_energy_s": trail,
        f"{prefix}_near_zero_sample_fraction": float(np.mean(np.abs(x) <= 1e-7)),
    }


def pair_stats(target: np.ndarray, masker: np.ndarray) -> dict[str, float]:
    """Reproduce 0 dB full-wave scaling and measure central/active SNR."""
    target_dm = demean(target)
    masker_dm = demean(masker)
    target_full_rms = rms(target_dm)
    masker_full_rms = rms(masker_dm)
    if target_full_rms <= EPS or masker_full_rms <= EPS:
        return {
            "full25_snr_db": math.nan,
            "center2_snr_db_at_nominal_0": math.nan,
            "center2_snr_offset_db": math.nan,
            "target_active_snr_db_at_nominal_0": math.nan,
        }

    scale = target_full_rms / masker_full_rms  # nominal SNR = 0 dB
    masker_scaled = masker_dm * scale
    full_snr = 20.0 * math.log10(target_full_rms / rms(masker_scaled))
    target_c = center2(target_dm)
    masker_c = center2(masker_scaled)
    center_snr = 20.0 * math.log10((rms(target_c) + EPS) / (rms(masker_c) + EPS))

    active = activity_sample_mask(center2(target))
    if int(active.sum()) >= int(0.05 * SR):
        active_snr = 20.0 * math.log10(
            (rms(target_c[active]) + EPS) / (rms(masker_c[active]) + EPS)
        )
    else:
        active_snr = math.nan

    out = {
        "full25_snr_db": full_snr,
        "center2_snr_db_at_nominal_0": center_snr,
        "center2_snr_offset_db": center_snr - full_snr,
        "target_active_snr_db_at_nominal_0": active_snr,
    }
    out.update(waveform_stats(target, "target"))
    out.update(waveform_stats(masker, "masker"))
    return out


@lru_cache(maxsize=384)
def load_audio(path: str) -> np.ndarray:
    return load_44k(path)


def target_slice(audio_dir: Path, row: dict) -> np.ndarray | None:
    return slice_centered(
        load_audio(str(audio_dir / row["target_path"])),
        float(row["target_center_s"]),
    )


def anchored_pool_slice(audio_dir: Path, row: dict) -> np.ndarray | None:
    return slice_centered(
        load_audio(str(audio_dir / row["path"])),
        float(row["dist_center_s"]),
    )


def audit_experiment_1(samples: pd.DataFrame, audio_dir: Path) -> pd.DataFrame:
    rows: list[dict] = []
    for i, r in enumerate(samples.to_dict("records")):
        target = target_slice(audio_dir, r)
        if target is None:
            continue
        for condition, col in (("same_sex", "same_dist_path"), ("different_sex", "diff_dist_path")):
            masker = slice_middle(load_audio(str(audio_dir / r[col])))
            if masker is None:
                continue
            rec = {
                "experiment": "experiment_1_gender",
                "audit_status": "exact_from_saved_stimulus_metadata",
                "trial_id": r["trial_id"],
                "condition": condition,
                "n_talkers": 1,
                "target_path": r["target_path"],
                "masker_paths": r[col],
            }
            rec.update(pair_stats(target, masker))
            rows.append(rec)
        if (i + 1) % 100 == 0:
            print(f"Experiment 1: {i + 1}/{len(samples)} targets")
    return pd.DataFrame(rows)


def equal_rms_sum(slices: list[np.ndarray]) -> np.ndarray:
    """Match Experiment 2: align each raw slice RMS, then sum."""
    ref = rms(slices[0])
    return np.sum([x * (ref / (rms(x) + EPS)) for x in slices], axis=0).astype(np.float32)


def audit_experiment_2(
    samples: pd.DataFrame,
    pool: pd.DataFrame,
    audio_dir: Path,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reconstruct documented gender-balanced, nested masker selections."""
    pool_records = pool.to_dict("records")
    pool_by_gender: dict[str, list[dict]] = {}
    for p in pool_records:
        pool_by_gender.setdefault(str(p["gender"]), []).append(p)

    # Component-level audit is exact because each pool row stores its anchor.
    component_rows = []
    for i, p in enumerate(pool_records):
        seg = anchored_pool_slice(audio_dir, p)
        if seg is None:
            continue
        rec = {
            "path": p["path"],
            "speaker": p["speaker"],
            "gender": p["gender"],
            "dist_norm": p["dist_norm"],
        }
        rec.update(waveform_stats(seg, "masker"))
        component_rows.append(rec)
        if (i + 1) % 200 == 0:
            print(f"Experiment 2 pool: {i + 1}/{len(pool_records)} clips")

    rows: list[dict] = []
    for i, r in enumerate(samples.to_dict("records")):
        target = target_slice(audio_dir, r)
        if target is None:
            continue
        target_gender = str(r["target_gender"])
        other_genders = [g for g in pool_by_gender if g != target_gender]
        same_candidates = [p for p in pool_by_gender.get(target_gender, []) if p["speaker"] != r["target_speaker"]]
        diff_candidates = [p for g in other_genders for p in pool_by_gender[g] if p["speaker"] != r["target_speaker"]]
        rng = random.Random(seed * 100003 + i)
        if len(same_candidates) < 4 or len(diff_candidates) < 4:
            continue
        same = rng.sample(same_candidates, 4)
        diff = rng.sample(diff_candidates, 4)
        balanced = [v for pair in zip(same, diff) for v in pair]
        condition_draws = {
            "one_same": [same[0]],
            "one_diff": [diff[0]],
            "two_talker": balanced[:2],
            "four_talker": balanced[:4],
            "babble": balanced[:8],
        }
        for condition, chosen in condition_draws.items():
            slices = [anchored_pool_slice(audio_dir, p) for p in chosen]
            if any(x is None for x in slices):
                continue
            masker = equal_rms_sum(slices)  # type: ignore[arg-type]
            rec = {
                "experiment": "experiment_2_talker_count",
                "audit_status": "reconstructed_from_documented_design_seed_0",
                "trial_id": r["trial_id"],
                "condition": condition,
                "n_talkers": len(chosen),
                "target_path": r["target_path"],
                "masker_paths": ";".join(str(p["path"]) for p in chosen),
            }
            rec.update(pair_stats(target, masker))
            rows.append(rec)
        if (i + 1) % 100 == 0:
            print(f"Experiment 2 reconstruction: {i + 1}/{len(samples)} targets")
    return pd.DataFrame(rows), pd.DataFrame(component_rows)


def summarize(audit: pd.DataFrame) -> pd.DataFrame:
    records = []
    for (experiment, condition, status), g in audit.groupby(
        ["experiment", "condition", "audit_status"], sort=False
    ):
        x = g["center2_snr_offset_db"].dropna().to_numpy()
        records.append(
            {
                "experiment": experiment,
                "condition": condition,
                "audit_status": status,
                "n": len(x),
                "mean_offset_db": float(np.mean(x)),
                "median_offset_db": float(np.median(x)),
                "sd_offset_db": float(np.std(x, ddof=1)),
                "min_offset_db": float(np.min(x)),
                "max_offset_db": float(np.max(x)),
                "mean_abs_offset_db": float(np.mean(np.abs(x))),
                "p95_abs_offset_db": float(np.percentile(np.abs(x), 95)),
                "n_abs_gt_1db": int(np.sum(np.abs(x) > 1.0)),
                "n_abs_gt_3db": int(np.sum(np.abs(x) > 3.0)),
                "max_abs_offset_db": float(np.max(np.abs(x))),
                "mean_target_low_energy_fraction": float(g["target_full_low_energy_fraction"].mean()),
                "mean_masker_low_energy_fraction": float(g["masker_full_low_energy_fraction"].mean()),
            }
        )
    return pd.DataFrame(records)


def save_figure(audit: pd.DataFrame, out: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    exp1 = audit[audit["experiment"] == "experiment_1_gender"]
    for condition, g in exp1.groupby("condition"):
        axes[0].hist(
            g["center2_snr_offset_db"], bins=np.linspace(-6, 6, 49),
            alpha=0.55, label=condition,
        )
    axes[0].axvline(0, color="black", linewidth=1)
    axes[0].set_title("Experiment 1: central-2-s SNR offset")
    axes[0].set_xlabel("effective SNR - nominal SNR (dB)")
    axes[0].set_ylabel("stimulus count")
    axes[0].legend(frameon=False)

    labels, values = [], []
    for (experiment, condition), g in audit.groupby(["experiment", "condition"], sort=False):
        labels.append(("E1" if "_1_" in experiment else "E2") + "\n" + condition.replace("_", " "))
        values.append(g["center2_snr_offset_db"].dropna().to_numpy())
    axes[1].boxplot(values, tick_labels=labels, showfliers=True)
    axes[1].axhline(0, color="black", linewidth=1)
    axes[1].set_title("Offset by condition")
    axes[1].set_ylabel("effective SNR - nominal SNR (dB)")
    axes[1].tick_params(axis="x", labelrotation=35)
    fig.tight_layout()
    fig.savefig(out, dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_japanese_summary(summary: pd.DataFrame, audit: pd.DataFrame, out: Path) -> None:
    e1 = audit[audit["experiment"] == "experiment_1_gender"]
    x = e1["center2_snr_offset_db"].dropna().to_numpy()
    worst = e1.loc[e1["center2_snr_offset_db"].abs().nlargest(5).index]
    lines = [
        "# SNR算出時の無音区間：確認結果（PPT用）",
        "",
        "## 実装上の事実",
        "",
        "- 2.5秒の区間は元のCommon Voice音声から直接切り出しており、人工的なゼロ埋めは行っていない。",
        "- ターゲットはアンカー語を中心に2.5秒、実験1の妨害音声は録音中央の2.5秒を切り出した。",
        "- SNRは、DC成分を除去した2.5秒波形全体のRMSから設定した。したがって、元音声中の低エネルギー区間も計算に含まれる。",
        "- 蝸牛表現の生成時には中央2秒のみがモデル入力として残る。",
        "",
        "## 実験1の厳密な再計算",
        "",
        f"設定SNRに対する中央2秒の実効SNR差は、全刺激平均で {np.mean(x):+.2f} dB、中央値で {np.median(x):+.2f} dB であった。",
        f"絶対差の95パーセンタイルは {np.percentile(np.abs(x), 95):.2f} dB、最大は {np.max(np.abs(x)):.2f} dB であった。",
        f"|差| > 1 dB は {int(np.sum(np.abs(x) > 1))}/{len(x)} 刺激、|差| > 3 dB は {int(np.sum(np.abs(x) > 3))}/{len(x)} 刺激であった。",
        "したがって、全体平均の偏りは小さいが、個別刺激の絶対的なSNRには注意が必要である。",
        "",
        "## 実験2について",
        "",
        "実験2の最終結果CSVには各試行で用いた妨害音声IDが保存されていないため、最終実行の実効SNRを完全には復元できない。",
        "本監査では、保存済みのターゲットと妨害音声プールを用い、文書化された同性・異性バランスおよび2⊂4⊂8話者の構造をseed=0で再構成した。",
        "そのため、実験2の数値は刺激設計の妥当性確認には使えるが、最終実行の個々の試行と同一であるとは断定しない。ISSN条件も生成情報不足のため対象外とした。",
        "",
        "## 発表での短い回答",
        "",
        "> 本研究では、Common Voiceから2.5秒を直接切り出し、ゼロ埋めは行っていません。SNRは低エネルギー区間を含む2.5秒全体のRMSで設定しました。一方、モデルは中央2秒を使用するため、その区間でも再計算しました。実験1では平均差は小さかったものの、一部刺激では差が大きく、絶対値の解釈には注意が必要です。",
        "",
        "## 実験1：絶対差が大きい刺激（上位5件）",
        "",
        "|trial|条件|差 (dB)|target|masker|",
        "|---|---|---:|---|---|",
    ]
    for _, r in worst.iterrows():
        lines.append(
            f"|{r['trial_id']}|{r['condition']}|{r['center2_snr_offset_db']:+.2f}|{r['target_path']}|{r['masker_paths']}|"
        )
    lines += [
        "",
        "## 静音推定の定義",
        "",
        "ここでいう低エネルギー区間は、20 msフレームRMSが各クリップの95パーセンタイルRMSより40 dB以上低いフレームである。これは診断用のエネルギー基準であり、音素境界やVADの正解ラベルではない。",
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO)
    ap.add_argument("--samples", type=Path, default=EXP1 / "data/samples_expanded.csv")
    ap.add_argument("--pool", type=Path, default=EXP2 / "data/distractor_pool.csv")
    ap.add_argument("--out-dir", type=Path, default=REPO / "reproduction/analysis/silence_snr")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0, help="Smoke test on the first N targets/pool rows")
    args = ap.parse_args()

    if not args.audio_dir.is_dir():
        raise FileNotFoundError(f"Common Voice clips directory not found: {args.audio_dir}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    samples = pd.read_csv(args.samples)
    pool = pd.read_csv(args.pool)
    if args.limit:
        samples = samples.head(args.limit)
        pool = pool.head(max(args.limit * 8, 40))

    exp1 = audit_experiment_1(samples, args.audio_dir)
    exp2, pool_stats = audit_experiment_2(samples, pool, args.audio_dir, args.seed)
    audit = pd.concat([exp1, exp2], ignore_index=True)
    summary = summarize(audit)

    audit.to_csv(args.out_dir / "stimulus_snr_audit.csv", index=False)
    pool_stats.to_csv(args.out_dir / "distractor_pool_silence_audit.csv", index=False)
    summary.to_csv(args.out_dir / "silence_snr_summary.csv", index=False)
    save_figure(audit, args.out_dir / "silence_snr_audit.png")
    write_japanese_summary(summary, audit, args.out_dir / "PPT_SNR説明_日本語.md")
    print("\nSummary")
    print(summary.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print(f"\nOutputs: {args.out_dir}")


if __name__ == "__main__":
    main()

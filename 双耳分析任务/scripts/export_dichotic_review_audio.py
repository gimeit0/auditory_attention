#!/usr/bin/env python3
"""Export small, local WAV batches for manual dichotic-error review.

WAV files are ignored by git.  The default batch is ten review rows so a
listener can fill `dichotic_manual_review.csv` without creating a large export.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from slice_stimuli import SR, load_44k, slice_centered, slice_middle


RMS_LEVEL = 0.02
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


def global_stereo_norm(stereo: np.ndarray, level: float = RMS_LEVEL) -> np.ndarray:
    stereo = stereo.astype(np.float32, copy=False) - float(np.mean(stereo))
    value = float(np.sqrt(np.mean(np.square(stereo, dtype=np.float64))))
    return stereo * (level / value) if value > 0 else stereo


def safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value)).strip("-")
    return value[:40] or "word"


def require_segment(segment: np.ndarray | None, description: str) -> np.ndarray:
    if segment is None:
        raise ValueError(f"invalid slice for {description}")
    return segment


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--review",
        type=Path,
        default=REPO / "双耳分析任务/results/dichotic_manual_review.csv",
    )
    ap.add_argument("--clips", type=Path, default=DEFAULT_CLIPS)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=REPO / "双耳分析任务/local_review_audio",
    )
    ap.add_argument("--start", type=int, default=1, help="first review_order")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--all", action="store_true", help="export all remaining rows")
    args = ap.parse_args()

    review = pd.read_csv(args.review, keep_default_na=False)
    required = {
        "review_order", "cued_word", "opposite_word", "pred_dichotic",
        "cue_path", "left_path", "left_center_s", "right_path",
        "right_center_s",
    }
    missing = sorted(required - set(review.columns))
    if missing:
        raise ValueError(
            "review CSV is missing columns; rerun audit_dichotic_errors.py: "
            + ", ".join(missing)
        )
    selected = review[review["review_order"].ge(args.start)].copy()
    if not args.all:
        selected = selected.head(args.limit)
    if selected.empty:
        raise ValueError("no review rows selected")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    audio_cache: dict[str, np.ndarray] = {}

    def audio(path: str) -> np.ndarray:
        if path not in audio_cache:
            audio_cache[path] = load_44k(str(args.clips / path))
        return audio_cache[path]

    for row in selected.itertuples(index=False):
        left = require_segment(
            slice_centered(audio(row.left_path), float(row.left_center_s)),
            f"left {row.left_path}",
        )
        right = require_segment(
            slice_centered(audio(row.right_path), float(row.right_center_s)),
            f"right {row.right_path}",
        )
        cue = require_segment(slice_middle(audio(row.cue_path)), f"cue {row.cue_path}")
        target = left if row.cue_ear == "left" else right
        opposite = right if row.cue_ear == "left" else left

        left_norm = mono_norm(left)
        right_norm = mono_norm(right)
        dichotic = global_stereo_norm(np.stack([left_norm, right_norm], axis=0))
        stem = (
            f"{int(row.review_order):03d}_"
            f"{safe_name(row.error_class)}_"
            f"target-{safe_name(row.cued_word)}_"
            f"pred-{safe_name(row.pred_dichotic)}"
        )
        sf.write(args.out_dir / f"{stem}_01_target.wav", mono_norm(target), SR)
        sf.write(
            args.out_dir / f"{stem}_02_opposite-{safe_name(row.opposite_word)}.wav",
            mono_norm(opposite),
            SR,
        )
        sf.write(args.out_dir / f"{stem}_03_cue.wav", mono_norm(cue), SR)
        sf.write(args.out_dir / f"{stem}_04_dichotic.wav", dichotic.T, SR)

    print(
        f"exported {len(selected)} review rows ({len(selected) * 4} WAV files) "
        f"to {args.out_dir}"
    )
    print(
        "Listen in _01 target, _02 opposite, _03 cue, _04 dichotic order; "
        "then fill the manual_* columns in dichotic_manual_review.csv."
    )


if __name__ == "__main__":
    main()

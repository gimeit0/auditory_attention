#!/usr/bin/env python3
"""Run formal same-speaker dichotic evaluation with matched baselines."""

from __future__ import annotations

import argparse
import os
import pickle
import sys
from pathlib import Path

import scipy.signal
if not hasattr(scipy.signal, "hann"):
    scipy.signal.hann = scipy.signal.windows.hann

import numpy as np
import pandas as pd
import torch
import yaml


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

_torch_load = torch.load


def _load_full(*args, **kwargs):
    kwargs["weights_only"] = False
    return _torch_load(*args, **kwargs)


torch.load = _load_full

from slice_stimuli import load_44k, slice_centered, slice_middle
from src.spatial_attn_lightning import BinauralAttentionModule


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


def dichotic(left: np.ndarray, right: np.ndarray) -> torch.Tensor:
    # Equal active-ear levels. With both channels present, global RMS is 0.02.
    stereo = np.stack([mono_norm(left), mono_norm(right)], axis=0)
    return torch.from_numpy(global_stereo_norm(stereo)).unsqueeze(0).float()


def unilateral(wav: np.ndarray, ear: int, global_level: bool) -> torch.Tensor:
    stereo = np.zeros((2, len(wav)), dtype=np.float32)
    stereo[ear] = mono_norm(wav)
    if global_level:
        stereo = global_stereo_norm(stereo)
    return torch.from_numpy(stereo).unsqueeze(0).float()


def diotic(wav: np.ndarray) -> torch.Tensor:
    normalized = mono_norm(wav)
    return torch.from_numpy(np.stack([normalized, normalized])).unsqueeze(0).float()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--manifest",
        type=Path,
        default=REPO / "双耳分析任务/data/dichotic_manifest.csv",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO / "双耳分析任务/results/dichotic_results.csv",
    )
    ap.add_argument("--clips", type=Path, default=DEFAULT_CLIPS)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="0=auto (CPU: 1, CUDA: 4). Large CPU batches can exhaust RAM.",
    )
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = ap.parse_args()

    if args.device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = args.device
    batch_size = args.batch_size or (4 if device == "cuda" else 1)
    if device == "cpu" and batch_size > 1:
        print(
            f"CPU batch-size {batch_size} may exhaust memory; using 1 instead."
        )
        batch_size = 1
    manifest = pd.read_csv(args.manifest, dtype=str, keep_default_na=False)
    if args.limit:
        manifest = manifest.head(args.limit)

    existing = pd.DataFrame()
    completed: set[str] = set()
    if args.resume and args.out.exists():
        existing = pd.read_csv(args.out, dtype=str, keep_default_na=False)
        completed = set(existing["trial_id"])
        print(f"resume: {len(completed)} completed trials")

    cfg_path = REPO / "config/binaural_attn/word_task_v10_main_feature_gain_config.yaml"
    with cfg_path.open() as handle:
        config = yaml.load(handle, Loader=yaml.FullLoader)
    checkpoint = sorted(
        (
            REPO
            / "attn_cue_models/word_task_v10_main_feature_gain_config/checkpoints"
        ).glob("*.ckpt")
    )[0]
    model = BinauralAttentionModule.load_from_checkpoint(
        checkpoint_path=str(checkpoint), config=config, strict=False
    ).eval().to(device)
    coch = model.coch_gram.to(device)
    with (REPO / "cv_800_word_label_to_int_dict.pkl").open("rb") as handle:
        word_to_ix = pickle.load(handle)
    ix_to_word = {index: word for word, index in word_to_ix.items()}

    audio_cache: dict[str, np.ndarray] = {}

    def audio(path: str) -> np.ndarray:
        if path not in audio_cache:
            audio_cache[path] = load_44k(str(args.clips / path))
        return audio_cache[path]

    @torch.no_grad()
    def cochleagram(wav: torch.Tensor) -> torch.Tensor:
        value, _ = coch(wav.to(device), None)
        return value

    @torch.no_grad()
    def classify_batch(
        cue_cg: torch.Tensor,
        stimulus_cg: torch.Tensor,
        prepared: list[dict],
    ) -> list[dict]:
        probabilities = model(cue_cg, stimulus_cg).softmax(-1)
        prediction_indices = probabilities.argmax(dim=1).tolist()
        output = []
        for index, item in enumerate(prepared):
            cued = item["row"]["cued_word"]
            opposite = item["row"]["opposite_word"]
            output.append(
                {
                    "prediction": ix_to_word[prediction_indices[index]],
                    "p_cued": float(probabilities[index, word_to_ix[cued]].item()),
                    "p_opposite": float(
                        probabilities[index, word_to_ix[opposite]].item()
                    ),
                }
            )
        return output

    new_rows: list[dict] = []
    pending = manifest[~manifest["trial_id"].isin(completed)]
    records = pending.to_dict("records")
    # On CPU, keep cochleagrams only for the current four-trial speaker pair.
    # This avoids recomputing the same cue, dichotic mixture and clean target
    # while keeping memory bounded. CUDA uses small batches instead.
    cg_cache: dict[tuple, torch.Tensor] = {}
    cached_pair_id: str | None = None
    for start in range(0, len(records), batch_size):
        batch_rows = records[start:start + batch_size]
        prepared: list[dict] = []
        for row in batch_rows:
            left = slice_centered(
                audio(row["left_path"]), float(row["left_center_s"])
            )
            right = slice_centered(
                audio(row["right_path"]), float(row["right_center_s"])
            )
            cue = slice_middle(audio(row["cue_path"]))
            if left is None or right is None or cue is None:
                rec = dict(row)
                rec.update({"status": "invalid_slice"})
                new_rows.append(rec)
                continue
            ear = 0 if row["cue_ear"] == "left" else 1
            cued_audio = left if ear == 0 else right
            prepared.append(
                {
                    "row": row,
                    "unilateral_cue": unilateral(cue, ear, global_level=True),
                    "dichotic": dichotic(left, right),
                    # Same active-ear target RMS (0.02) as dichotic condition.
                    "monaural": unilateral(cued_audio, ear, global_level=False),
                    "diotic_cue": diotic(cue),
                    "diotic_target": diotic(cued_audio),
                }
            )

        if prepared:
            def stack(key: str) -> torch.Tensor:
                return torch.cat([item[key] for item in prepared], dim=0)

            if batch_size == 1:
                item = prepared[0]
                row = item["row"]
                if row["pair_id"] != cached_pair_id:
                    cg_cache.clear()
                    cached_pair_id = row["pair_id"]

                def cached(key: tuple, waveform_key: str) -> torch.Tensor:
                    if key not in cg_cache:
                        cg_cache[key] = cochleagram(item[waveform_key])
                    return cg_cache[key]

                cue_key = ("unilateral_cue", row["cue_ear"])
                unilateral_cue_cg = cached(cue_key, "unilateral_cue")
                dichotic_results = classify_batch(
                    unilateral_cue_cg,
                    cached(("dichotic", row["assignment"]), "dichotic"),
                    prepared,
                )
                monaural_results = classify_batch(
                    unilateral_cue_cg,
                    cached(
                        ("monaural", row["cued_path"], row["cue_ear"]),
                        "monaural",
                    ),
                    prepared,
                )
                diotic_results = classify_batch(
                    cached(("diotic_cue",), "diotic_cue"),
                    cached(("diotic_target", row["cued_path"]), "diotic_target"),
                    prepared,
                )
            else:
                # Small CUDA batches reduce launch overhead. Do not use a
                # large CPU batch: the cochlear intermediate tensors are big.
                unilateral_cue_cg = cochleagram(stack("unilateral_cue"))
                dichotic_results = classify_batch(
                    unilateral_cue_cg, cochleagram(stack("dichotic")), prepared
                )
                monaural_results = classify_batch(
                    unilateral_cue_cg, cochleagram(stack("monaural")), prepared
                )
                del unilateral_cue_cg
                diotic_results = classify_batch(
                    cochleagram(stack("diotic_cue")),
                    cochleagram(stack("diotic_target")),
                    prepared,
                )

            for item, dichotic_result, monaural_result, diotic_result in zip(
                prepared, dichotic_results, monaural_results, diotic_results
            ):
                row = item["row"]
                prediction = dichotic_result["prediction"]
                if prediction == row["cued_word"]:
                    outcome = "hit"
                elif prediction == row["opposite_word"]:
                    outcome = "ear_confusion"
                else:
                    outcome = "other"
                rec = dict(row)
                rec.update(
                    {
                        "status": "ok",
                        "checkpoint": checkpoint.name,
                        "device": device,
                        "pred_dichotic": prediction,
                        "dichotic_outcome": outcome,
                        "p_cued_dichotic": dichotic_result["p_cued"],
                        "p_opposite_dichotic": dichotic_result["p_opposite"],
                        "pred_monaural_matched": monaural_result["prediction"],
                        "monaural_matched_correct": int(
                            monaural_result["prediction"] == row["cued_word"]
                        ),
                        "pred_diotic_clean": diotic_result["prediction"],
                        "diotic_clean_correct": int(
                            diotic_result["prediction"] == row["cued_word"]
                        ),
                    }
                )
                new_rows.append(rec)

        count = min(start + batch_size, len(records))
        combined = pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(args.out, index=False)
        print(f"{count}/{len(records)} new trials -> {args.out}")


if __name__ == "__main__":
    main()

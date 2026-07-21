"""Run structural checks on the small self-training diotic dataset."""

from __future__ import annotations

import argparse
import json

import numpy as np

from selftrain.data.diotic_attention import (
    CROP_SAMPLES,
    DioticAttentionDataset,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260721)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = {}
    for mode in ("train", "val"):
        dataset = DioticAttentionDataset(
            mode=mode,
            batch_size=args.batch_size,
            examples_per_epoch=args.batch_size * 2,
            validation_examples=args.batch_size * 2,
            cue_free_percentage=0.0,
            seed=args.seed,
            cache_items=32,
        )
        cue, target, background, labels = dataset[0]
        expected_shape = (args.batch_size, 2, CROP_SAMPLES)
        if cue.shape != expected_shape:
            raise RuntimeError(f"Unexpected cue shape: {cue.shape}")
        if target.shape != expected_shape:
            raise RuntimeError(f"Unexpected target shape: {target.shape}")
        if background.shape != expected_shape:
            raise RuntimeError(
                f"Unexpected background shape: {background.shape}"
            )
        for name, array in (
            ("cue", cue),
            ("target", target),
            ("background", background),
        ):
            if not np.isfinite(array).all():
                raise RuntimeError(f"{mode} {name} contains non-finite values")
            if not np.array_equal(array[:, 0], array[:, 1]):
                raise RuntimeError(f"{mode} {name} is not diotic")
        if not ((0 <= labels) & (labels < 800)).all():
            raise RuntimeError(f"{mode} labels outside [0, 799]")

        rng = np.random.default_rng(args.seed)
        metadata_examples = []
        for _ in range(8):
            _, _, _, _, metadata = dataset.sample_example(rng)
            if metadata["target_speaker"] != metadata["cue_speaker"]:
                raise RuntimeError("Cue and target speakers differ")
            if metadata["target_path"] == metadata["cue_path"]:
                raise RuntimeError("Cue and target use the same recording")
            if metadata["target_word"] == metadata["cue_word"]:
                raise RuntimeError("Cue and target use the same anchor word")
            if metadata["target_speaker"] in metadata["distractor_speakers"]:
                raise RuntimeError("Target speaker appears among distractors")
            if len(metadata["distractor_speakers"]) != len(
                set(metadata["distractor_speakers"])
            ):
                raise RuntimeError("Distractor speakers are duplicated")
            metadata_examples.append(metadata)

        results[mode] = {
            "dataset_batches": len(dataset),
            "batch_shape": list(cue.shape),
            "labels": labels.tolist(),
            "available_anchor_rows": len(dataset.anchors),
            "available_speakers": int(dataset.anchors["speaker"].nunique()),
            "example_metadata": metadata_examples[:2],
        }

    cue_free_dataset = DioticAttentionDataset(
        mode="train",
        batch_size=2,
        examples_per_epoch=2,
        cue_free_percentage=1.0,
        seed=args.seed,
        cache_items=16,
    )
    cue, target, background, _ = cue_free_dataset[0]
    if np.any(cue) or np.any(background):
        raise RuntimeError("Cue-free examples must have silent cue/background")
    if not np.any(target):
        raise RuntimeError("Cue-free target must remain audible")
    results["cue_free_check"] = {
        "cue_is_silent": True,
        "background_is_silent": True,
        "target_is_audible": True,
    }

    print(json.dumps(results, ensure_ascii=False, indent=2))
    print("Diotic dataset checks: PASS")


if __name__ == "__main__":
    main()

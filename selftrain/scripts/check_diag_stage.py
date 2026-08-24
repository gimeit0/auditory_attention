"""Validate staged learnability-diagnostic configs before GPU training.

The manifest dataset accepts unknown keyword arguments, so a misspelled YAML
field can otherwise silently fall back to the difficult 1--4 distractor/10%
cue-free defaults.  This checker deliberately uses exact, stage-specific
expectations and exercises the real foreground/background mixing transform.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml

from src.audio_transforms import BinauralCombineWithRandomDBSNRPerExample
from selftrain.data.diotic_attention import DioticAttentionDataset


class DiagnosticConfigError(ValueError):
    """Raised when a diagnostic config does not match its declared stage."""


COMMON_EXPECTED = {
    "corpus.dataset_type": "diotic_manifest",
    "corpus.cue_type": "voice",
    "corpus.task": "word",
    "corpus.examples_per_epoch": 150000,
    "corpus.validation_examples": 10000,
    "corpus.seed": 20260721,
    "audio.per_example_leveling": True,
    "hparas.valid_step": 0.5,
    "hparas.epochs": 4,
    "hparas.lr": 0.00005,
    "hparas.batch_size": 32,
    "hparas.accumulate_grad_batches": 1,
    "hparas.mask_cues": False,
    "model.num_classes.num_words": 800,
}

STAGE_EXPECTED = {
    "clean": {
        "model_name": "diotic_selftrain_diag_clean",
        "corpus.min_distractors": 1,
        "corpus.max_distractors": 4,
        "corpus.cue_free_percentage": 0.1,
        "noise_kwargs.low_snr": "clean",
        "noise_kwargs.high_snr": "clean",
    },
    "1dist-p10db": {
        "model_name": "diotic_selftrain_diag_1dist_p10db",
        "corpus.min_distractors": 1,
        "corpus.max_distractors": 1,
        "corpus.cue_free_percentage": 0.0,
        "noise_kwargs.low_snr": 10.0,
        "noise_kwargs.high_snr": 10.0,
    },
    "1dist-0db": {
        "model_name": "diotic_selftrain_diag_1dist_0db",
        "corpus.min_distractors": 1,
        "corpus.max_distractors": 1,
        "corpus.cue_free_percentage": 0.0,
        "noise_kwargs.low_snr": 0.0,
        "noise_kwargs.high_snr": 0.0,
    },
    "1dist-0db-20ep": {
        "model_name": "diotic_selftrain_diag_1dist_0db_20ep",
        "corpus.min_distractors": 1,
        "corpus.max_distractors": 1,
        "corpus.cue_free_percentage": 0.0,
        "noise_kwargs.low_snr": 0.0,
        "noise_kwargs.high_snr": 0.0,
        "hparas.epochs": 20,
        "hparas.checkpoint_every_n_epochs": 0,
    },
}


def _lookup(config: dict[str, Any], dotted_path: str) -> Any:
    value: Any = config
    for key in dotted_path.split("."):
        if not isinstance(value, dict) or key not in value:
            raise DiagnosticConfigError(f"Missing required field: {dotted_path}")
        value = value[key]
    return value


def _validate_expected(config: dict[str, Any], stage: str) -> None:
    expected = {**COMMON_EXPECTED, **STAGE_EXPECTED[stage]}
    mismatches = []
    for dotted_path, wanted in expected.items():
        actual = _lookup(config, dotted_path)
        if isinstance(wanted, bool):
            matches = type(actual) is bool and actual is wanted
        elif isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
            matches = (
                isinstance(actual, (int, float))
                and not isinstance(actual, bool)
                and float(actual) == float(wanted)
            )
        else:
            matches = actual == wanted
        if not matches:
            mismatches.append(f"{dotted_path}: expected {wanted!r}, got {actual!r}")
    if mismatches:
        raise DiagnosticConfigError("\n".join(mismatches))


def _validate_real_transform(config: dict[str, Any], stage: str) -> dict[str, Any]:
    low_snr = _lookup(config, "noise_kwargs.low_snr")
    high_snr = _lookup(config, "noise_kwargs.high_snr")
    transform = BinauralCombineWithRandomDBSNRPerExample(low_snr, high_snr)

    generator = torch.Generator().manual_seed(20260811)
    foreground = torch.randn((4, 2, 4096), generator=generator)
    background = torch.randn((4, 2, 4096), generator=generator)
    mixture, metadata = transform(foreground, background)
    if metadata is not None:
        raise AssertionError("The diagnostic mixer unexpectedly returned metadata")

    if stage == "clean":
        if not torch.equal(mixture, foreground):
            raise AssertionError("The clean stage did not return foreground unchanged")
        return {"background_ignored": True}

    dims = (-2, -1)
    demeaned_foreground = foreground - foreground.mean(dim=dims, keepdim=True)
    scaled_background = mixture - demeaned_foreground
    foreground_rms = torch.sqrt(
        torch.mean(torch.square(demeaned_foreground), dim=dims)
    )
    background_rms = torch.sqrt(
        torch.mean(torch.square(scaled_background), dim=dims)
    )
    measured_snr_db = 20.0 * torch.log10(foreground_rms / background_rms)
    expected_snr_value = float(low_snr)
    expected_snr = torch.full_like(measured_snr_db, expected_snr_value)
    if not torch.allclose(measured_snr_db, expected_snr, atol=1e-4, rtol=0.0):
        raise AssertionError(
            f"Expected {expected_snr_value:g} dB per example, "
            f"measured {measured_snr_db.tolist()}"
        )
    if torch.equal(mixture, foreground):
        raise AssertionError(f"The {stage} stage unexpectedly behaved like clean")
    return {
        "measured_snr_db": [round(float(value), 6) for value in measured_snr_db],
        "background_present": True,
    }


def _validate_real_dataset(config: dict[str, Any], stage: str) -> dict[str, Any]:
    """Sample real validation clips and verify the intended cue/scene semantics."""
    if stage == "clean":
        return {}

    corpus = dict(config["corpus"])
    dataset = DioticAttentionDataset(mode="val", batch_size=1, **corpus)
    rng = np.random.default_rng(20260812)
    examples = []
    for _ in range(4):
        cue, target, background, label, metadata = dataset.sample_example(rng)
        if metadata["target_speaker"] != metadata["cue_speaker"]:
            raise AssertionError("Cue and target speakers differ")
        if metadata["target_path"] == metadata["cue_path"]:
            raise AssertionError("Cue and target use the same recording")
        if metadata["target_word"] == metadata["cue_word"]:
            raise AssertionError("Cue and target use the same anchor word")
        if metadata["target_speaker"] in metadata["distractor_speakers"]:
            raise AssertionError("Target speaker appears among distractors")
        if metadata["distractor_count"] != 1:
            raise AssertionError(
                f"Expected one distractor, got {metadata['distractor_count']}"
            )
        if metadata["cue_free"]:
            raise AssertionError("Numeric-SNR diagnostic unexpectedly sampled cue-free")
        if not np.any(cue):
            raise AssertionError("Correct cue is silent")
        if not np.any(target):
            raise AssertionError("Target is silent")
        if not np.any(background):
            raise AssertionError("Background is silent")
        examples.append(
            {
                "label": int(label),
                "target_path": metadata["target_path"],
                "cue_path": metadata["cue_path"],
                "distractor_count": int(metadata["distractor_count"]),
                "cue_free": bool(metadata["cue_free"]),
            }
        )
    return {
        "correct_cue_examples_checked": len(examples),
        "examples": examples,
    }


def validate(config_path: Path, stage: str) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise DiagnosticConfigError("Top-level YAML value must be a mapping")
    _validate_expected(config, stage)
    transform_result = _validate_real_transform(config, stage)
    dataset_result = _validate_real_dataset(config, stage)

    examples = int(_lookup(config, "corpus.examples_per_epoch"))
    batch_size = int(_lookup(config, "hparas.batch_size"))
    accumulation = int(_lookup(config, "hparas.accumulate_grad_batches"))
    epochs = int(_lookup(config, "hparas.epochs"))
    train_batches_per_epoch = math.ceil(examples / batch_size)
    attempts_per_epoch = math.ceil(train_batches_per_epoch / accumulation)
    return {
        "status": "PASS",
        "stage": stage,
        "config": str(config_path),
        "train_batches_per_epoch": train_batches_per_epoch,
        "optimizer_attempts_per_epoch": attempts_per_epoch,
        "total_optimizer_attempts": attempts_per_epoch * epochs,
        "validation_checks": int(epochs / float(_lookup(config, "hparas.valid_step"))),
        "transform_check": transform_result,
        "dataset_check": dataset_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--stage", required=True, choices=sorted(STAGE_EXPECTED))
    args = parser.parse_args()
    print(json.dumps(validate(args.config, args.stage), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

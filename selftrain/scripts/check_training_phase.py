"""Fail-closed guard for the staged formal full-training schedule."""

from __future__ import annotations

import argparse
import json
import math
import pathlib

import yaml


EXPECTED = {
    "corpus.examples_per_epoch": 499968,
    "corpus.validation_examples": 10000,
    "corpus.min_distractors": 1,
    "corpus.max_distractors": 4,
    "corpus.cue_free_percentage": 0.1,
    "noise_kwargs.low_snr": -10,
    "noise_kwargs.high_snr": 10,
    "hparas.epochs": 40,
    "hparas.batch_size": 32,
    "hparas.accumulate_grad_batches": 9,
    "hparas.valid_step": 1.0,
}


def _nested(config: dict, dotted: str):
    value = config
    for component in dotted.split("."):
        value = value[component]
    return value


def validate(config_path: str | pathlib.Path, phase: str) -> dict:
    path = pathlib.Path(config_path).resolve()
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    for dotted, expected in EXPECTED.items():
        actual = _nested(config, dotted)
        if actual != expected:
            raise ValueError(
                f"Formal phase config mismatch at {dotted}: "
                f"actual={actual!r}, expected={expected!r}"
            )
    if config["hparas"].get("early_stopping") is not None:
        raise ValueError("Formal phase must not use automatic early stopping")
    examples = int(config["corpus"]["examples_per_epoch"])
    batch_size = int(config["hparas"]["batch_size"])
    accumulate = int(config["hparas"]["accumulate_grad_batches"])
    train_batches = math.ceil(examples / batch_size)
    attempts_per_epoch = math.ceil(train_batches / accumulate)
    if examples != train_batches * batch_size:
        raise ValueError("examples_per_epoch is not microbatch-aligned")
    if train_batches != attempts_per_epoch * accumulate:
        raise ValueError("epoch has a partial gradient-accumulation group")
    phase_epochs = {"pilot4": 4, "full": 40}[phase]
    return {
        "status": "PASS",
        "phase": phase,
        "configured_epochs": int(config["hparas"]["epochs"]),
        "phase_epochs": phase_epochs,
        "last_completed_epoch_index": phase_epochs - 1,
        "expected_completed_epochs": phase_epochs,
        "acceptable_checkpoint_epoch_values": [
            phase_epochs - 1,
            phase_epochs,
        ],
        "examples_per_epoch": examples,
        "train_batches_per_epoch": train_batches,
        "optimizer_attempts_per_epoch": attempts_per_epoch,
        "expected_final_global_step": attempts_per_epoch * phase_epochs,
        "effective_batch_size": batch_size * accumulate,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--phase", choices=("pilot4", "full"), required=True)
    parser.add_argument("--tsv", action="store_true")
    args = parser.parse_args()
    result = validate(args.config, args.phase)
    if args.tsv:
        print(
            result["expected_completed_epochs"],
            result["expected_final_global_step"],
        )
    else:
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

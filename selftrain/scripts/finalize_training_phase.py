"""Validate a phase-final checkpoint and atomically publish its state."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import tempfile

import torch

from selftrain.scripts.check_training_phase import validate as validate_phase


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: pathlib.Path) -> dict:
    try:
        checkpoint = torch.load(
            path, map_location="cpu", weights_only=False
        )
    except TypeError:
        checkpoint = torch.load(path, map_location="cpu")
    if not isinstance(checkpoint, dict):
        raise ValueError("Final checkpoint payload is not a mapping")
    return checkpoint


def validate_checkpoint(
    checkpoint_path: str | pathlib.Path,
    config_path: str | pathlib.Path,
    phase: str,
    run_id: str,
    job_id: str,
    source_semantic_sha256: str,
    config_sha256: str,
) -> dict:
    path_argument = pathlib.Path(checkpoint_path).expanduser()
    if path_argument.is_symlink():
        raise ValueError("Explicit final checkpoint must not be a symlink")
    path = path_argument.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Explicit final checkpoint is missing: {path}")
    schedule = validate_phase(config_path, phase)
    checkpoint = _load(path)
    epoch = int(checkpoint.get("epoch", -1))
    global_step = int(checkpoint.get("global_step", -1))
    epoch_progress = (
        checkpoint.get("loops", {})
        .get("fit_loop", {})
        .get("epoch_progress", {})
    )
    completed_epochs = int(
        epoch_progress.get("total", {}).get("completed", -1)
    )
    acceptable_epochs = set(schedule["acceptable_checkpoint_epoch_values"])
    if (
        epoch not in acceptable_epochs
        or completed_epochs != schedule["expected_completed_epochs"]
        or global_step != schedule["expected_final_global_step"]
    ):
        raise ValueError(
            "Training returned before the guarded phase boundary: "
            f"actual=(checkpoint_epoch={epoch}, "
            f"completed_epochs={completed_epochs}, step={global_step}), "
            f"expected=(completed_epochs="
            f"{schedule['expected_completed_epochs']}, "
            f"step={schedule['expected_final_global_step']})"
        )
    amp_state = checkpoint.get("audattn_amp_state_v1") or {}
    attempts = int(amp_state.get("total_optimizer_attempts", -1))
    successful = int(amp_state.get("successful_optimizer_steps", -1))
    overflows = int(amp_state.get("total_overflows", -1))
    if attempts != global_step or successful + overflows != attempts:
        raise ValueError(
            "Final checkpoint AMP accounting is inconsistent: "
            f"attempts={attempts}, successful={successful}, "
            f"overflows={overflows}, global_step={global_step}"
        )
    expected_metadata = {
        "run_id": run_id,
        "source_semantic_sha256": source_semantic_sha256,
        "config_sha256": config_sha256,
    }
    if checkpoint.get("audattn_run_metadata_v1") != expected_metadata:
        raise ValueError("Final checkpoint run metadata mismatch")
    return {
        "schema_version": 1,
        "status": (
            "COMPUTATION_COMPLETE_PENDING_SCIENTIFIC_REVIEW"
            if phase == "pilot4"
            else "COMPLETE"
        ),
        "run_id": run_id,
        "run_phase": phase,
        "job_id": job_id,
        "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "checkpoint_epoch": epoch,
        "completed_epochs": completed_epochs,
        "last_completed_epoch_index": completed_epochs - 1,
        "global_step": global_step,
        "successful_optimizer_steps": successful,
        "amp_overflows": overflows,
        "checkpoint": str(path),
        "checkpoint_basename": path.name,
        "checkpoint_sha256": _sha256(path),
        "schedule": schedule,
    }


def _atomic_json(path: pathlib.Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(f"Phase state already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = pathlib.Path(handle.name)
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--phase", choices=("pilot4", "full"), required=True)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    required_environment = (
        "RUN_ID",
        "SLURM_JOB_ID",
        "AUDATTN_SOURCE_SHA256",
        "AUDATTN_CONFIG_SHA256",
    )
    missing = [name for name in required_environment if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Missing phase-finalization environment: {missing}")
    result = validate_checkpoint(
        args.checkpoint,
        args.config,
        args.phase,
        os.environ["RUN_ID"],
        os.environ["SLURM_JOB_ID"],
        os.environ["AUDATTN_SOURCE_SHA256"],
        os.environ["AUDATTN_CONFIG_SHA256"],
    )
    _atomic_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""One-off, fail-closed recovery for the 2026-08-28 full-run finalizer bug.

This tool is intentionally bound to one run and one failure signature.  It does
not weaken the normal finalizer and it never edits a checkpoint or frozen run
snapshot.  In check mode it is read-only.  In publish mode it writes a recovery
sidecar first and then the original schema-v1 COMPLETE record, both without
overwriting an existing file.
"""

from __future__ import annotations

import argparse
import datetime as dt
import errno
import fcntl
import hashlib
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile
from typing import Iterable


TOOL_SCHEMA_VERSION = 1
EXPECTED_RUN_ID = "fullpilot4_accum9_20260815_181000"
EXPECTED_FINAL_JOB_ID = "628071"
EXPECTED_LIGHTNING_VERSION = "2.1.1"
EXPECTED_EPOCH = 40
EXPECTED_COMPLETED_EPOCHS = 40
EXPECTED_RAW_TOTAL_COMPLETED = 38
EXPECTED_GLOBAL_STEP = 69440
EXPECTED_ATTEMPTS_PER_EPOCH = 1736
EXPECTED_SUCCESSFUL = 69414
EXPECTED_OVERFLOWS = 26

PROVENANCE_DIRECTORIES = (
    "src",
    "corpus",
    "selftrain/data",
    "selftrain/scripts",
    "selftrain/configs",
    "selftrain/hakusan",
)
PROVENANCE_SUFFIXES = {".py", ".yaml", ".yml", ".sh", ".sbatch"}

SEGMENTS = (
    {
        "job_id": "575142",
        "phase": "pilot4",
        "requested_mode": "new",
        "job_mode": "new",
        "epochs": tuple(range(0, 4)),
        "input_step": None,
        "input_basename": None,
        "output_step": 6944,
    },
    {
        "job_id": "587802",
        "phase": "full",
        "requested_mode": "resume",
        "job_mode": "resume",
        "epochs": tuple(range(4, 17)),
        "input_step": 6944,
        "input_basename": "pilot4-final.ckpt",
        "output_step": 29512,
    },
    {
        "job_id": "614647",
        "phase": "full",
        "requested_mode": "resume",
        "job_mode": "resume",
        "epochs": tuple(range(17, 30)),
        "input_step": 29512,
        "input_basename": "last.ckpt",
        "output_step": 52080,
    },
    {
        "job_id": "628071",
        "phase": "full",
        "requested_mode": "resume",
        "job_mode": "resume",
        "epochs": tuple(range(30, 40)),
        "input_step": 52080,
        "input_basename": "last.ckpt",
        "output_step": 69440,
    },
)

EXPECTED_SCHEDULE = {
    "status": "PASS",
    "phase": "full",
    "configured_epochs": 40,
    "phase_epochs": 40,
    "last_completed_epoch_index": 39,
    "expected_completed_epochs": 40,
    "acceptable_checkpoint_epoch_values": [39, 40],
    "examples_per_epoch": 499968,
    "train_batches_per_epoch": 15624,
    "optimizer_attempts_per_epoch": 1736,
    "expected_final_global_step": 69440,
    "effective_batch_size": 288,
}

SUMMARY_PATTERN = re.compile(
    r"AMP epoch summary: epoch=(?P<epoch>\d+), "
    r"epoch_overflows=(?P<epoch_overflows>\d+), "
    r"epoch_attempts=(?P<epoch_attempts>\d+), "
    r"epoch_successful_steps=(?P<epoch_successful>\d+), "
    r"total_overflows=(?P<total_overflows>\d+), "
    r"total_attempts=(?P<total_attempts>\d+), "
    r"total_successful_steps=(?P<total_successful>\d+)"
)

FATAL_MARKERS = (
    "FloatingPointError",
    "Non-finite",
    "CUDA out of memory",
    "Out of memory",
    "No space left",
    "Disk quota",
    "PytorchStreamWriter failed",
)

FINAL_SUMMARY_MARKER = "AMP epoch summary: epoch=39"
FINAL_STOP_MARKER = "`Trainer.fit` stopped: `max_epochs=40` reached."
FINAL_TRACEBACK_MARKER = "Traceback (most recent call last):"
FINAL_ERROR_MARKER = "ERROR: line 424 exited with 1"
FINAL_VALUE_ERROR_MARKER = (
    "ValueError: Training returned before the guarded phase boundary: "
    "actual=(checkpoint_epoch=40, completed_epochs=38, step=69440), "
    "expected=(completed_epochs=40, step=69440)"
)

RECOVERY_REASON = (
    "PyTorch Lightning 2.1.1 epoch-end last.ckpt resumes left "
    "fit_loop.epoch_progress.total.completed two behind while all "
    "authoritative current/processed, step, AMP, and log evidence "
    "proved 40 completed epochs."
)
RECOVERY_SLURM_HISTORY = "FAILED/1:0 (post-fit finalizer only)"


class RecoveryError(RuntimeError):
    """Raised when any fail-closed recovery condition is not satisfied."""


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: dict) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def safe_file(path: pathlib.Path, label: str) -> pathlib.Path:
    if path.is_symlink():
        raise RecoveryError(f"{label} must not be a symbolic link: {path}")
    resolved = path.resolve()
    if not resolved.is_file():
        raise RecoveryError(f"{label} is missing: {resolved}")
    return resolved


def safe_directory(path: pathlib.Path, label: str) -> pathlib.Path:
    if path.is_symlink():
        raise RecoveryError(f"{label} must not be a symbolic link: {path}")
    resolved = path.resolve()
    if not resolved.is_dir():
        raise RecoveryError(f"{label} is missing: {resolved}")
    return resolved


def open_existing_run_lock(path: pathlib.Path, *, writable: bool):
    """Open an existing ordinary lock file without creating or following links."""
    parent = safe_directory(path.parent, "Run state directory")
    if path.parent.resolve() != parent:
        raise RecoveryError(f"Run-state lock has an unsafe parent: {path}")
    flags = os.O_RDWR if writable else os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(path, flags)
    except OSError as error:
        raise RecoveryError(
            f"Existing ordinary run-state lock is required: {path}: {error}"
        ) from error
    try:
        opened = os.fstat(file_descriptor)
        named = os.lstat(path)
        if not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(named.st_mode):
            raise RecoveryError(f"Run-state lock is not an ordinary file: {path}")
        if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise RecoveryError(f"Run-state lock changed while opening: {path}")
        mode = "r+b" if writable else "rb"
        return os.fdopen(file_descriptor, mode, closefd=True)
    except Exception:
        os.close(file_descriptor)
        raise


def read_json(path: pathlib.Path, label: str) -> dict:
    resolved = safe_file(path, label)
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecoveryError(f"{label} is not valid JSON: {resolved}") from error
    if not isinstance(value, dict):
        raise RecoveryError(f"{label} must contain a JSON object: {resolved}")
    return value


def _digest_entries(entries: list[dict]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(
            f"{entry['sha256']}  {entry['path']}\n".encode("utf-8")
        )
    return digest.hexdigest()


def verify_snapshot(run_root: pathlib.Path) -> dict:
    snapshot = safe_directory(run_root / "snapshot", "Snapshot directory")
    files_root = safe_directory(snapshot / "files", "Snapshot files directory")
    manifest_path = snapshot / "manifest.json"
    manifest = read_json(manifest_path, "Snapshot manifest")
    if manifest.get("schema_version") != 2:
        raise RecoveryError("Snapshot manifest schema is not 2")

    verified: dict[str, tuple[str, int]] = {}
    for collection in ("semantic_files", "provenance_files"):
        entries = manifest.get(collection)
        if not isinstance(entries, list) or not entries:
            raise RecoveryError(f"Snapshot manifest has no {collection}")
        actual_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise RecoveryError(f"Malformed manifest entry in {collection}")
            relative = pathlib.PurePosixPath(str(entry.get("path", "")))
            if relative.is_absolute() or ".." in relative.parts:
                raise RecoveryError(f"Unsafe manifest path: {relative}")
            candidate = files_root.joinpath(*relative.parts)
            resolved = safe_file(candidate, f"Frozen input {relative}")
            try:
                resolved.relative_to(files_root)
            except ValueError as error:
                raise RecoveryError(f"Frozen input escapes snapshot: {relative}") from error
            actual_hash = sha256(resolved)
            actual_size = resolved.stat().st_size
            if actual_hash != entry.get("sha256") or actual_size != int(entry.get("size", -1)):
                raise RecoveryError(f"Frozen input changed: {relative}")
            verified[str(relative)] = (actual_hash, actual_size)
            actual_entries.append(
                {"path": str(relative), "sha256": actual_hash, "size": actual_size}
            )
        digest_key = collection.replace("_files", "_combined_sha256")
        if _digest_entries(actual_entries) != manifest.get(digest_key):
            raise RecoveryError(f"Snapshot combined digest mismatch: {digest_key}")

    semantic_paths = {
        str(entry["path"]) for entry in manifest["semantic_files"]
    }
    discovered = set(semantic_paths)
    for directory_name in PROVENANCE_DIRECTORIES:
        directory = files_root / directory_name
        if not directory.is_dir():
            raise RecoveryError(f"Frozen provenance directory is missing: {directory}")
        for path in directory.rglob("*"):
            if (
                path.is_file()
                and path.suffix in PROVENANCE_SUFFIXES
                and "__pycache__" not in path.parts
            ):
                discovered.add(path.relative_to(files_root).as_posix())
    expected_provenance = {
        str(entry["path"]) for entry in manifest["provenance_files"]
    }
    if discovered != expected_provenance:
        raise RecoveryError(
            "Frozen provenance inventory mismatch: "
            f"missing={sorted(expected_provenance - discovered)}, "
            f"added={sorted(discovered - expected_provenance)}"
        )
    return {
        "manifest": manifest,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": sha256(manifest_path.resolve()),
        "files_root": str(files_root),
    }


def run_frozen_validator(
    snapshot_files: pathlib.Path,
    module: str,
    arguments: list[str],
) -> dict:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(snapshot_files)
    # Importing the frozen modules must not create __pycache__ inside the
    # immutable run snapshot.
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, "-m", module, *arguments]
    result = subprocess.run(
        command,
        cwd=snapshot_files,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RecoveryError(
            f"Frozen validator failed ({module}): "
            f"stdout={result.stdout[-2000:].strip()!r}, "
            f"stderr={result.stderr[-2000:].strip()!r}"
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RecoveryError(
            f"Frozen validator returned non-JSON output ({module})"
        ) from error
    if not isinstance(value, dict):
        raise RecoveryError(f"Frozen validator output is not an object: {module}")
    return value


def verify_frozen_guards(run_root: pathlib.Path, snapshot: dict) -> dict:
    files = pathlib.Path(snapshot["files_root"])
    manifest = pathlib.Path(snapshot["manifest_path"])
    config = files / "selftrain/configs/full.yaml"
    pass_path = run_root / "snapshot/numerics_PASS.json"
    cue_release = run_root / "state/cue_control_release.json"
    results = {}
    results["run_integrity"] = run_frozen_validator(
        files,
        "selftrain.scripts.run_integrity",
        ["verify", "--root", str(files), "--manifest", str(manifest)],
    )
    results["numerics_pass"] = run_frozen_validator(
        files,
        "selftrain.scripts.run_integrity",
        [
            "validate-pass",
            "--pass-path",
            str(pass_path),
            "--manifest",
            str(manifest),
        ],
    )
    results["cue_control_release"] = run_frozen_validator(
        files,
        "selftrain.scripts.check_cue_control_release",
        ["--release-record", str(cue_release)],
    )
    results["pilot_release"] = run_frozen_validator(
        files,
        "selftrain.scripts.pilot_release",
        ["validate", "--run-root", str(run_root)],
    )
    results["full_started"] = run_frozen_validator(
        files,
        "selftrain.scripts.full_started",
        [
            "validate",
            "--run-root",
            str(run_root),
            "--checkpoint-global-step",
            str(EXPECTED_GLOBAL_STEP),
        ],
    )
    schedule = run_frozen_validator(
        files,
        "selftrain.scripts.check_training_phase",
        ["--config", str(config), "--phase", "full"],
    )
    if schedule != EXPECTED_SCHEDULE:
        raise RecoveryError(
            f"Frozen schedule mismatch: actual={schedule}, expected={EXPECTED_SCHEDULE}"
        )
    results["schedule"] = schedule
    return results


def validate_checkpoint_payload(
    checkpoint: dict,
    expected_run_id: str,
    expected_source_sha256: str,
    expected_config_sha256: str,
) -> dict:
    if not isinstance(checkpoint, dict):
        raise RecoveryError("Final checkpoint payload is not a mapping")
    if checkpoint.get("pytorch-lightning_version") != EXPECTED_LIGHTNING_VERSION:
        raise RecoveryError(
            "Unexpected Lightning version: "
            f"{checkpoint.get('pytorch-lightning_version')!r}"
        )
    epoch = int(checkpoint.get("epoch", -1))
    global_step = int(checkpoint.get("global_step", -1))
    if epoch != EXPECTED_EPOCH or global_step != EXPECTED_GLOBAL_STEP:
        raise RecoveryError(
            f"Final checkpoint boundary mismatch: epoch={epoch}, step={global_step}"
        )
    progress = (
        checkpoint.get("loops", {})
        .get("fit_loop", {})
        .get("epoch_progress", {})
    )
    total = progress.get("total")
    current = progress.get("current")
    if not isinstance(total, dict) or not isinstance(current, dict):
        raise RecoveryError("Final checkpoint has no epoch progress trackers")
    for key in ("ready", "started", "processed", "completed"):
        if int(current.get(key, -1)) != EXPECTED_COMPLETED_EPOCHS:
            raise RecoveryError(
                f"Current epoch tracker mismatch: {key}={current.get(key)!r}"
            )
    for key in ("ready", "started", "processed"):
        if int(total.get(key, -1)) != EXPECTED_COMPLETED_EPOCHS:
            raise RecoveryError(
                f"Total epoch tracker mismatch: {key}={total.get(key)!r}"
            )
    if int(total.get("completed", -1)) != EXPECTED_RAW_TOTAL_COMPLETED:
        raise RecoveryError(
            "This tool accepts only the exact two-resume bookkeeping lag: "
            f"total.completed={total.get('completed')!r}"
        )
    amp = checkpoint.get("audattn_amp_state_v1")
    if not isinstance(amp, dict):
        raise RecoveryError("Final checkpoint has no AMP state")
    attempts = int(amp.get("total_optimizer_attempts", -1))
    successful = int(amp.get("successful_optimizer_steps", -1))
    overflows = int(amp.get("total_overflows", -1))
    if (
        attempts != EXPECTED_GLOBAL_STEP
        or successful != EXPECTED_SUCCESSFUL
        or overflows != EXPECTED_OVERFLOWS
        or successful + overflows != attempts
    ):
        raise RecoveryError(
            "Final checkpoint AMP accounting mismatch: "
            f"attempts={attempts}, successful={successful}, overflows={overflows}"
        )
    metadata = checkpoint.get("audattn_run_metadata_v1")
    expected_metadata = {
        "run_id": expected_run_id,
        "source_semantic_sha256": expected_source_sha256,
        "config_sha256": expected_config_sha256,
    }
    if metadata != expected_metadata:
        raise RecoveryError(
            f"Final checkpoint run metadata mismatch: {metadata!r}"
        )
    return {
        "lightning_version": EXPECTED_LIGHTNING_VERSION,
        "epoch": epoch,
        "global_step": global_step,
        "epoch_progress": {"total": dict(total), "current": dict(current)},
        "amp": {
            "attempts": attempts,
            "successful": successful,
            "overflows": overflows,
        },
        "run_metadata": metadata,
    }


def load_and_validate_checkpoint(
    checkpoint_path: pathlib.Path,
    manifest: dict,
    config_path: pathlib.Path,
) -> dict:
    path = safe_file(checkpoint_path, "Formal final checkpoint")
    expected_parent = checkpoint_path.parent.resolve()
    if path.parent != expected_parent or path.name != "formal-final.ckpt":
        raise RecoveryError(f"Unexpected final checkpoint path: {path}")
    checkpoint_hash_before = sha256(path)
    stat_before = path.stat()
    try:
        import torch
    except ImportError as error:
        raise RecoveryError("PyTorch is required to inspect the checkpoint") from error
    try:
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:
        checkpoint = torch.load(path, map_location="cpu")
    result = validate_checkpoint_payload(
        checkpoint,
        EXPECTED_RUN_ID,
        str(manifest["semantic_combined_sha256"]),
        sha256(config_path),
    )
    del checkpoint
    checkpoint_hash_after = sha256(path)
    stat_after = path.stat()
    if (
        checkpoint_hash_before != checkpoint_hash_after
        or stat_before.st_size != stat_after.st_size
        or stat_before.st_mtime_ns != stat_after.st_mtime_ns
    ):
        raise RecoveryError("Formal final checkpoint changed during audit")
    result.update(
        {
            "path": str(path),
            "basename": path.name,
            "size": path.stat().st_size,
            "sha256": checkpoint_hash_after,
        }
    )
    return result


def iter_normalized_lines(path: pathlib.Path) -> Iterable[str]:
    buffer = ""
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            buffer += chunk.replace("\r", "\n")
            pieces = buffer.split("\n")
            buffer = pieces.pop()
            yield from pieces
    if buffer:
        yield buffer


def parse_log(
    path: pathlib.Path,
    final_job: bool = False,
    expected_final_checkpoint: pathlib.Path | None = None,
) -> dict:
    resolved = safe_file(path, "Training log")
    summaries = []
    fatal_hits = []
    marker_positions: dict[str, int] = {}
    marker_counts: dict[str, int] = {}
    tracebacks = 0
    if final_job:
        if expected_final_checkpoint is None:
            raise RecoveryError("Final-log validation requires the checkpoint path")
        final_markers = (
            FINAL_SUMMARY_MARKER,
            FINAL_STOP_MARKER,
            (
                "Saved explicit final checkpoint: "
                f"{expected_final_checkpoint.resolve()} "
                "(epoch=40, global_step=69440, fit_max_epochs=40)"
            ),
            FINAL_TRACEBACK_MARKER,
            FINAL_VALUE_ERROR_MARKER,
            FINAL_ERROR_MARKER,
        )
    else:
        final_markers = ()
    for line_number, line in enumerate(iter_normalized_lines(resolved), start=1):
        for marker in FATAL_MARKERS:
            if marker in line:
                fatal_hits.append({"line": line_number, "marker": marker})
        if "Traceback (most recent call last):" in line:
            tracebacks += 1
        match = SUMMARY_PATTERN.search(line)
        if match:
            summary = {key: int(value) for key, value in match.groupdict().items()}
            if final_job and summary["epoch"] == 39:
                if "val_loss_epoch=2.990, val_acc=0.434" not in line:
                    raise RecoveryError(
                        "Final epoch summary does not contain the post-validation "
                        "metrics val_loss=2.990/val_acc=0.434"
                    )
            summaries.append(summary)
        if final_job:
            if "FORMAL TRAINING RUN COMPLETE" in line:
                raise RecoveryError("Final log incorrectly claims formal completion")
            if "ERROR:" in line and FINAL_ERROR_MARKER not in line:
                raise RecoveryError(f"Unexpected ERROR marker in final log: {line}")
            for marker in final_markers:
                if marker in line:
                    marker_counts[marker] = marker_counts.get(marker, 0) + 1
                    marker_positions.setdefault(marker, line_number)
        elif "ERROR:" in line:
            raise RecoveryError(f"Unexpected ERROR marker in earlier log: {line}")
    if fatal_hits:
        raise RecoveryError(f"Fatal marker found in {resolved}: {fatal_hits}")
    if final_job:
        missing = [marker for marker in final_markers if marker not in marker_positions]
        if missing:
            raise RecoveryError(f"Final log is missing recovery markers: {missing}")
        repeated = {
            marker: marker_counts.get(marker, 0)
            for marker in final_markers
            if marker_counts.get(marker, 0) != 1
        }
        if repeated:
            raise RecoveryError(f"Final log marker counts are not exact: {repeated}")
        positions = [marker_positions[marker] for marker in final_markers]
        if positions != sorted(positions):
            raise RecoveryError(
                f"Final log recovery markers are out of order: {marker_positions}"
            )
        if tracebacks != 1:
            raise RecoveryError(
                f"Final log must contain exactly the expected finalizer traceback; got {tracebacks}"
            )
    elif tracebacks:
        raise RecoveryError(f"Unexpected traceback found in earlier log: {resolved}")
    return {
        "path": str(resolved),
        "size": resolved.stat().st_size,
        "sha256": sha256(resolved),
        "summaries": summaries,
        "marker_positions": marker_positions,
        "tracebacks": tracebacks,
    }


def validate_summaries(logs: dict[str, dict]) -> dict:
    by_epoch: dict[int, tuple[str, dict]] = {}
    previous_total_overflows = 0
    for segment in SEGMENTS:
        job_id = str(segment["job_id"])
        actual_epochs = tuple(summary["epoch"] for summary in logs[job_id]["summaries"])
        if actual_epochs != segment["epochs"]:
            raise RecoveryError(
                f"Job {job_id} completed-epoch sequence mismatch: "
                f"actual={actual_epochs}, expected={segment['epochs']}"
            )
        for summary in logs[job_id]["summaries"]:
            epoch = summary["epoch"]
            if epoch in by_epoch:
                raise RecoveryError(f"Duplicate AMP epoch summary: epoch={epoch}")
            by_epoch[epoch] = (job_id, summary)
    if set(by_epoch) != set(range(EXPECTED_COMPLETED_EPOCHS)):
        raise RecoveryError(
            f"Completed epoch summaries are not exactly 0..39: {sorted(by_epoch)}"
        )
    for epoch in range(EXPECTED_COMPLETED_EPOCHS):
        _, summary = by_epoch[epoch]
        if summary["epoch_attempts"] != EXPECTED_ATTEMPTS_PER_EPOCH:
            raise RecoveryError(f"Epoch {epoch} attempt count mismatch")
        if summary["epoch_successful"] + summary["epoch_overflows"] != summary["epoch_attempts"]:
            raise RecoveryError(f"Epoch {epoch} local AMP accounting mismatch")
        expected_total = (epoch + 1) * EXPECTED_ATTEMPTS_PER_EPOCH
        if summary["total_attempts"] != expected_total:
            raise RecoveryError(
                f"Epoch {epoch} cumulative attempts mismatch: {summary['total_attempts']}"
            )
        if summary["total_successful"] + summary["total_overflows"] != expected_total:
            raise RecoveryError(f"Epoch {epoch} cumulative AMP accounting mismatch")
        if summary["total_overflows"] - previous_total_overflows != summary["epoch_overflows"]:
            raise RecoveryError(f"Epoch {epoch} overflow increment mismatch")
        previous_total_overflows = summary["total_overflows"]
    final = by_epoch[39][1]
    if (
        final["total_attempts"] != EXPECTED_GLOBAL_STEP
        or final["total_successful"] != EXPECTED_SUCCESSFUL
        or final["total_overflows"] != EXPECTED_OVERFLOWS
    ):
        raise RecoveryError(f"Final log AMP totals mismatch: {final}")
    return {
        "epochs": [0, 39],
        "count": 40,
        "final": final,
    }


def find_job_log(log_dir: pathlib.Path, job_id: str) -> pathlib.Path:
    matches = [
        path for path in log_dir.glob(f"*_{job_id}.log") if path.is_file()
    ]
    if len(matches) != 1:
        raise RecoveryError(
            f"Expected one log for Job {job_id}, found {len(matches)}: {matches}"
        )
    return matches[0]


def _normal_step(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def validate_lineage(run_root: pathlib.Path, log_dir: pathlib.Path) -> dict:
    records = {}
    logs = {}
    last_resume_count = 0
    for segment in SEGMENTS:
        job_id = str(segment["job_id"])
        submission_path = run_root / f"state/submissions/{job_id}.json"
        job_path = run_root / f"state/jobs/{job_id}.json"
        submission = read_json(submission_path, f"Submission record {job_id}")
        job = read_json(job_path, f"Job record {job_id}")
        for label, record in (("submission", submission), ("job", job)):
            if str(record.get("job_id")) != job_id:
                raise RecoveryError(f"{label} Job ID mismatch for {job_id}")
            if record.get("run_id") != EXPECTED_RUN_ID:
                raise RecoveryError(f"{label} run_id mismatch for {job_id}")
            if record.get("run_phase") != segment["phase"]:
                raise RecoveryError(f"{label} phase mismatch for {job_id}")
            if _normal_step(record.get("expected_checkpoint_global_step")) != segment["input_step"]:
                raise RecoveryError(f"{label} input step mismatch for {job_id}")
            if record.get("expected_checkpoint_basename") != segment["input_basename"]:
                raise RecoveryError(f"{label} input checkpoint mismatch for {job_id}")
        for key in (
            "expected_checkpoint_sha256",
            "expected_checkpoint_basename",
            "expected_checkpoint_global_step",
        ):
            submission_value = submission.get(key)
            job_value = job.get(key)
            if key == "expected_checkpoint_global_step":
                submission_value = _normal_step(submission_value)
                job_value = _normal_step(job_value)
            if submission_value != job_value:
                raise RecoveryError(
                    f"Submission/job checkpoint binding mismatch for {job_id}: {key}"
                )
        if submission.get("requested_mode") != segment["requested_mode"]:
            raise RecoveryError(f"Submission requested_mode mismatch for {job_id}")
        if submission.get("job_mode") != segment["job_mode"]:
            raise RecoveryError(f"Submission job_mode mismatch for {job_id}")
        if job.get("mode") != segment["job_mode"]:
            raise RecoveryError(f"Runtime mode mismatch for {job_id}")
        if not str(submission.get("submitted_at", "")).strip():
            raise RecoveryError(f"Submission timestamp missing for {job_id}")
        if not str(job.get("started_at", "")).strip():
            raise RecoveryError(f"Runtime timestamp missing for {job_id}")
        if segment["phase"] == "full":
            if submission.get("resume_kind") != "epoch" or job.get("resume_kind") != "epoch":
                raise RecoveryError(f"Full segment is not an epoch resume: {job_id}")
        if segment["input_step"] is not None:
            bound_hash = submission.get("expected_checkpoint_sha256")
            if not isinstance(bound_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", bound_hash):
                raise RecoveryError(f"Missing checkpoint SHA binding for Job {job_id}")
        elif (
            submission.get("expected_checkpoint_sha256") is not None
            or job.get("expected_checkpoint_sha256") is not None
        ):
            raise RecoveryError("New pilot unexpectedly has a checkpoint SHA binding")
        if segment["input_basename"] == "last.ckpt":
            last_resume_count += 1
        log = parse_log(
            find_job_log(log_dir, job_id),
            final_job=(job_id == EXPECTED_FINAL_JOB_ID),
            expected_final_checkpoint=(
                run_root / "full/checkpoints/formal-final.ckpt"
                if job_id == EXPECTED_FINAL_JOB_ID
                else None
            ),
        )
        logs[job_id] = log
        records[job_id] = {
            "submission": {
                "path": str(submission_path.resolve()),
                "sha256": sha256(submission_path.resolve()),
            },
            "job": {
                "path": str(job_path.resolve()),
                "sha256": sha256(job_path.resolve()),
            },
            "log": {key: value for key, value in log.items() if key != "summaries"},
            "epochs": [segment["epochs"][0], segment["epochs"][-1]],
            "input_step": segment["input_step"],
            "output_step": segment["output_step"],
        }
    if last_resume_count != EXPECTED_COMPLETED_EPOCHS - EXPECTED_RAW_TOTAL_COMPLETED:
        raise RecoveryError(
            f"Lineage does not explain loop-counter lag: last resumes={last_resume_count}"
        )
    summary_evidence = validate_summaries(logs)
    return {
        "last_checkpoint_resume_count": last_resume_count,
        "logical_completed_epochs": EXPECTED_COMPLETED_EPOCHS,
        "raw_total_completed": EXPECTED_RAW_TOTAL_COMPLETED,
        "summary_evidence": summary_evidence,
        "jobs": records,
    }


def query_sacct(job_id: str) -> dict:
    result = subprocess.run(
        [
            "sacct",
            "-j",
            job_id,
            "-X",
            "-n",
            "-P",
            "--format=JobIDRaw,State,ExitCode",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RecoveryError(f"sacct failed: {result.stderr.strip()}")
    rows = []
    for line in result.stdout.splitlines():
        fields = line.strip().split("|")
        if len(fields) >= 3 and fields[0] == job_id:
            rows.append(fields[:3])
    if len(rows) != 1:
        raise RecoveryError(f"Expected one sacct row for Job {job_id}, got {rows}")
    _, state, exit_code = rows[0]
    state = state.rstrip("+")
    if state != "FAILED" or exit_code != "1:0":
        raise RecoveryError(
            f"Final Job state is not the exact recovered failure: {state}/{exit_code}"
        )
    return {"job_id": job_id, "state": state, "exit_code": exit_code}


def evidence_file(path: pathlib.Path, label: str) -> dict:
    resolved = safe_file(path, label)
    return {
        "path": str(resolved),
        "size": resolved.stat().st_size,
        "sha256": sha256(resolved),
    }


def audit(
    run_root: pathlib.Path,
    project_root: pathlib.Path,
    log_dir: pathlib.Path,
    job_id: str,
) -> dict:
    if job_id != EXPECTED_FINAL_JOB_ID:
        raise RecoveryError(f"This recovery tool is bound to Job {EXPECTED_FINAL_JOB_ID}")
    project_root = safe_directory(project_root, "Project root")
    run_root = safe_directory(run_root, "Run root")
    if run_root.name != EXPECTED_RUN_ID:
        raise RecoveryError(f"This recovery tool is bound to RUN_ID={EXPECTED_RUN_ID}")
    expected_root = (
        project_root / f"selftrain/experiments/runs/{EXPECTED_RUN_ID}"
    ).resolve()
    if run_root != expected_root:
        raise RecoveryError(
            f"Run root is not under the expected project root: {run_root}"
        )
    state_dir = safe_directory(run_root / "state", "Run state directory")
    safe_directory(state_dir / "jobs", "Job-record directory")
    safe_directory(state_dir / "submissions", "Submission-record directory")
    full_dir = safe_directory(run_root / "full", "Full-run directory")
    checkpoint_dir = safe_directory(
        full_dir / "checkpoints", "Checkpoint directory"
    )
    expected_log_dir = safe_directory(
        project_root / "selftrain/hakusan/logs", "Training-log directory"
    )
    actual_log_dir = safe_directory(log_dir, "Requested training-log directory")
    if actual_log_dir != expected_log_dir:
        raise RecoveryError(
            "--log-dir must be the canonical project training-log directory: "
            f"{expected_log_dir}"
        )
    complete = state_dir / "COMPLETE"
    if complete.is_symlink():
        raise RecoveryError(f"COMPLETE must not be a symlink: {complete}")

    snapshot = verify_snapshot(run_root)
    frozen = verify_frozen_guards(run_root, snapshot)
    manifest = snapshot["manifest"]
    config = pathlib.Path(snapshot["files_root"]) / "selftrain/configs/full.yaml"
    checkpoint = load_and_validate_checkpoint(
        checkpoint_dir / "formal-final.ckpt",
        manifest,
        config,
    )
    lineage = validate_lineage(run_root, actual_log_dir)
    source_hash = checkpoint["run_metadata"]["source_semantic_sha256"]
    config_hash = checkpoint["run_metadata"]["config_sha256"]
    for segment in SEGMENTS:
        job_id_for_record = str(segment["job_id"])
        job_record = read_json(
            run_root / f"state/jobs/{job_id_for_record}.json",
            f"Job metadata binding {job_id_for_record}",
        )
        if job_record.get("source_semantic_sha256") != source_hash:
            raise RecoveryError(f"Source digest changed at Job {job_id_for_record}")
        if job_record.get("config_sha256") != config_hash:
            raise RecoveryError(f"Config digest changed at Job {job_id_for_record}")
    sacct = query_sacct(job_id)
    state_evidence = {}
    for name in (
        "cue_control_release.json",
        "PILOT4_COMPLETE.json",
        "PILOT4_GO.json",
        "FULL_STARTED.json",
    ):
        state_evidence[name] = evidence_file(
            run_root / "state" / name, f"State evidence {name}"
        )
    state_evidence["numerics_PASS.json"] = evidence_file(
        run_root / "snapshot/numerics_PASS.json", "Numerics PASS"
    )
    return {
        "status": "CHECK_PASS",
        "run_id": EXPECTED_RUN_ID,
        "job_id": job_id,
        "inputs": {
            "project_root": str(project_root),
            "run_root": str(run_root),
            "log_dir": str(actual_log_dir),
            "job_id": job_id,
        },
        "snapshot": {
            key: value for key, value in snapshot.items() if key != "manifest"
        },
        "frozen_validators": frozen,
        "schedule": frozen["schedule"],
        "checkpoint": checkpoint,
        "lineage": lineage,
        "sacct": sacct,
        "state_evidence": state_evidence,
    }


def complete_payload(audit_result: dict, completed_at: str) -> dict:
    checkpoint = audit_result["checkpoint"]
    amp = checkpoint["amp"]
    return {
        "schema_version": 1,
        "status": "COMPLETE",
        "run_id": EXPECTED_RUN_ID,
        "run_phase": "full",
        "job_id": EXPECTED_FINAL_JOB_ID,
        "completed_at": completed_at,
        "checkpoint_epoch": checkpoint["epoch"],
        "completed_epochs": EXPECTED_COMPLETED_EPOCHS,
        "last_completed_epoch_index": EXPECTED_COMPLETED_EPOCHS - 1,
        "global_step": checkpoint["global_step"],
        "successful_optimizer_steps": amp["successful"],
        "amp_overflows": amp["overflows"],
        "checkpoint": checkpoint["path"],
        "checkpoint_basename": checkpoint["basename"],
        "checkpoint_sha256": checkpoint["sha256"],
        "schedule": audit_result["schedule"],
    }


def atomic_create(path: pathlib.Path, data: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Refusing to overwrite existing state: {path}")
    parent = safe_directory(path.parent, f"Parent directory for {path.name}")
    if path.parent.resolve() != parent:
        raise RecoveryError(f"Unsafe parent directory for {path.name}: {path.parent}")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = pathlib.Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            try:
                os.fsync(directory_fd)
            except OSError as error:
                if error.errno not in {errno.EINVAL, errno.ENOTSUP}:
                    raise
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_recovery_sidecar(
    audit_result: dict,
    tool_path: pathlib.Path,
    recovered_at: str,
) -> dict:
    if not isinstance(recovered_at, str) or not recovered_at.strip():
        raise RecoveryError("Recovery timestamp must be a non-empty string")
    audit_bytes = canonical_json(audit_result)
    audit_snapshot = json.loads(audit_bytes)
    complete = complete_payload(audit_snapshot, recovered_at)
    complete_bytes = canonical_json(complete)
    return {
        "schema_version": TOOL_SCHEMA_VERSION,
        "status": "FINALIZER_ONLY_RECOVERY",
        "run_id": EXPECTED_RUN_ID,
        "job_id": EXPECTED_FINAL_JOB_ID,
        "recovered_at": recovered_at,
        "reason": RECOVERY_REASON,
        "slurm_history_preserved": RECOVERY_SLURM_HISTORY,
        "tool": {
            "path": str(tool_path),
            "sha256": sha256(tool_path),
        },
        "audit": audit_snapshot,
        "audit_sha256": sha256_bytes(audit_bytes),
        "checkpoint_sha256": audit_result["checkpoint"]["sha256"],
        "raw_epoch_progress": audit_result["checkpoint"]["epoch_progress"],
        "logical_completed_epochs": EXPECTED_COMPLETED_EPOCHS,
        "amp": audit_result["checkpoint"]["amp"],
        "sacct": audit_result["sacct"],
        "snapshot": audit_result["snapshot"],
        "state_evidence": audit_result["state_evidence"],
        "lineage": audit_result["lineage"],
        "planned_complete_payload": complete,
        "planned_complete_sha256": sha256_bytes(complete_bytes),
    }


def validate_recovery_sidecar(
    sidecar: dict,
    audit_result: dict,
    tool_path: pathlib.Path,
) -> tuple[dict, bytes]:
    recovered_at = sidecar.get("recovered_at")
    if not isinstance(recovered_at, str) or not recovered_at.strip():
        raise RecoveryError("Recovery sidecar has no valid recovered_at timestamp")
    stored_audit = sidecar.get("audit")
    if not isinstance(stored_audit, dict):
        raise RecoveryError("Recovery sidecar has no complete audit snapshot")
    stored_audit_bytes = canonical_json(stored_audit)
    if sha256_bytes(stored_audit_bytes) != sidecar.get("audit_sha256"):
        raise RecoveryError("Recovery sidecar audit hash mismatch")
    fresh_audit_bytes = canonical_json(audit_result)
    if stored_audit_bytes != fresh_audit_bytes:
        raise RecoveryError(
            "Recovery sidecar audit snapshot differs from the current audit"
        )
    if sidecar.get("audit_sha256") != sha256_bytes(fresh_audit_bytes):
        raise RecoveryError("Recovery sidecar is not bound to the current audit hash")
    expected = build_recovery_sidecar(audit_result, tool_path, recovered_at)
    if sidecar != expected:
        differing = sorted(
            key
            for key in set(sidecar) | set(expected)
            if sidecar.get(key) != expected.get(key)
        )
        raise RecoveryError(
            "Recovery sidecar is not fully bound to the current audit; "
            f"differing fields={differing}"
        )
    planned = expected["planned_complete_payload"]
    complete_bytes = canonical_json(planned)
    if sha256_bytes(complete_bytes) != expected["planned_complete_sha256"]:
        raise RecoveryError("Recomputed COMPLETE hash mismatch")
    return planned, complete_bytes


def publish(run_root: pathlib.Path, audit_result: dict) -> dict:
    state_dir = safe_directory(run_root / "state", "Run state directory")
    complete_path = state_dir / "COMPLETE"
    sidecar_path = state_dir / "COMPLETE_RECOVERY.json"
    tool_path = safe_file(pathlib.Path(__file__), "Recovery tool")

    if complete_path.exists() or complete_path.is_symlink():
        if not sidecar_path.is_file() or sidecar_path.is_symlink():
            raise RecoveryError("COMPLETE already exists without a safe recovery sidecar")
        sidecar = read_json(sidecar_path, "Recovery sidecar")
        _, complete_bytes = validate_recovery_sidecar(
            sidecar, audit_result, tool_path
        )
        complete_file = safe_file(complete_path, "Recovered COMPLETE record")
        if complete_file.read_bytes() != complete_bytes:
            raise RecoveryError("Existing COMPLETE does not match recovery sidecar")
        actual_complete_hash = sha256(complete_file)
        return {
            "status": "ALREADY_PUBLISHED_AND_VERIFIED",
            "complete": str(complete_file),
            "complete_sha256": actual_complete_hash,
            "sidecar": str(sidecar_path.resolve()),
        }

    if sidecar_path.exists() or sidecar_path.is_symlink():
        sidecar = read_json(sidecar_path, "Recovery sidecar")
        _, complete_bytes = validate_recovery_sidecar(
            sidecar, audit_result, tool_path
        )
        atomic_create(complete_path, complete_bytes)
        return {
            "status": "PUBLISHED_FROM_EXISTING_SIDECAR",
            "complete": str(complete_path.resolve()),
            "complete_sha256": sha256(complete_path.resolve()),
            "sidecar": str(sidecar_path.resolve()),
        }

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    sidecar = build_recovery_sidecar(audit_result, tool_path, now)
    complete = sidecar["planned_complete_payload"]
    complete_bytes = canonical_json(complete)
    atomic_create(sidecar_path, canonical_json(sidecar))
    atomic_create(complete_path, complete_bytes)
    return {
        "status": "PUBLISHED",
        "complete": str(complete_path.resolve()),
        "complete_sha256": sha256(complete_path.resolve()),
        "sidecar": str(sidecar_path.resolve()),
        "sidecar_sha256": sha256(sidecar_path.resolve()),
    }


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, type=pathlib.Path)
    parser.add_argument("--project-root", required=True, type=pathlib.Path)
    parser.add_argument("--log-dir", type=pathlib.Path)
    parser.add_argument("--job-id", default=EXPECTED_FINAL_JOB_ID)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check-only", action="store_true")
    action.add_argument("--publish", action="store_true")
    parser.add_argument(
        "--confirm-run-id",
        help="Required with --publish; must exactly match the bound RUN_ID",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_root = args.run_root.expanduser().absolute()
    project_root = args.project_root.expanduser().absolute()
    log_dir = (
        args.log_dir.expanduser().absolute()
        if args.log_dir is not None
        else project_root / "selftrain/hakusan/logs"
    )
    if args.publish and args.confirm_run_id != EXPECTED_RUN_ID:
        raise SystemExit(
            "--publish requires --confirm-run-id " + EXPECTED_RUN_ID
        )
    state_dir = safe_directory(run_root / "state", "Run state directory")
    lock_path = state_dir / "run.lock"
    with open_existing_run_lock(lock_path, writable=args.publish) as lock_handle:
        lock_mode = fcntl.LOCK_EX if args.publish else fcntl.LOCK_SH
        try:
            fcntl.flock(lock_handle.fileno(), lock_mode | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SystemExit("Another process holds the run-state lock") from error
        result = audit(run_root, project_root, log_dir, str(args.job_id))
        if args.check_only:
            compact = {
                "status": result["status"],
                "run_id": result["run_id"],
                "job_id": result["job_id"],
                "checkpoint": result["checkpoint"],
                "summary_evidence": result["lineage"]["summary_evidence"],
                "last_checkpoint_resume_count": result["lineage"]["last_checkpoint_resume_count"],
                "sacct": result["sacct"],
                "would_write": [
                    str(run_root / "state/COMPLETE_RECOVERY.json"),
                    str(run_root / "state/COMPLETE"),
                ],
            }
            print(json.dumps(compact, indent=2, sort_keys=True))
            return
        published = publish(run_root, result)
        print(json.dumps(published, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (RecoveryError, FileExistsError) as error:
        raise SystemExit(f"RECOVERY REFUSED: {error}") from error

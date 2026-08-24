"""Create and validate the immutable lower boundary for full continuation."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import tempfile


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: pathlib.Path, label: str) -> dict:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"{label} is missing or unsafe: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _pilot(run_root: pathlib.Path) -> tuple[pathlib.Path, dict]:
    path = run_root / "state/PILOT4_COMPLETE.json"
    pilot = _json(path, "Pilot completion record")
    expected = {
        "status": "COMPUTATION_COMPLETE_PENDING_SCIENTIFIC_REVIEW",
        "run_phase": "pilot4",
        "completed_epochs": 4,
        "global_step": 6944,
    }
    mismatches = {
        key: (pilot.get(key), value)
        for key, value in expected.items()
        if pilot.get(key) != value
    }
    if mismatches:
        raise ValueError(f"Pilot completion mismatch: {mismatches}")
    if not pilot.get("run_id"):
        raise ValueError("Pilot completion has no run_id")
    return path, pilot


def create_record(
    run_root_argument: str | pathlib.Path,
    job_id: str,
) -> dict:
    root = pathlib.Path(run_root_argument).expanduser().resolve()
    pilot_path, pilot = _pilot(root)
    return {
        "schema_version": 1,
        "status": "STARTED",
        "run_id": pilot["run_id"],
        "job_id": str(job_id),
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "initial_checkpoint_basename": pilot["checkpoint_basename"],
        "initial_checkpoint_sha256": pilot["checkpoint_sha256"],
        "initial_checkpoint_global_step": int(pilot["global_step"]),
        "pilot_completion_sha256": _sha256(pilot_path),
    }


def validate_record(
    run_root_argument: str | pathlib.Path,
    checkpoint_global_step: int | None = None,
) -> dict:
    root = pathlib.Path(run_root_argument).expanduser().resolve()
    pilot_path, pilot = _pilot(root)
    record = _json(root / "state/FULL_STARTED.json", "Full-start record")
    expected = {
        "schema_version": 1,
        "status": "STARTED",
        "run_id": pilot["run_id"],
        "initial_checkpoint_basename": pilot["checkpoint_basename"],
        "initial_checkpoint_sha256": pilot["checkpoint_sha256"],
        "initial_checkpoint_global_step": int(pilot["global_step"]),
        "pilot_completion_sha256": _sha256(pilot_path),
    }
    mismatches = {
        key: (record.get(key), value)
        for key, value in expected.items()
        if record.get(key) != value
    }
    if mismatches:
        raise ValueError(f"Full-start record mismatch: {mismatches}")
    if not str(record.get("job_id", "")).strip():
        raise ValueError("Full-start record has no job_id")
    if checkpoint_global_step is not None:
        selected = int(checkpoint_global_step)
        boundary = int(record["initial_checkpoint_global_step"])
        if selected < boundary:
            raise ValueError(
                "Full continuation would roll back before the reviewed pilot "
                f"boundary: selected={selected}, boundary={boundary}"
            )
    return record


def _atomic_write(path: pathlib.Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(f"Full-start record already exists: {path}")
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
    parser.add_argument("command", choices=("create", "validate"))
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--job-id")
    parser.add_argument("--checkpoint-global-step", type=int)
    args = parser.parse_args()
    root = pathlib.Path(args.run_root).expanduser().resolve()
    if args.command == "create":
        if not args.job_id:
            raise SystemExit("create requires --job-id")
        if args.checkpoint_global_step is not None:
            raise SystemExit("create does not accept --checkpoint-global-step")
        result = create_record(root, args.job_id)
        _atomic_write(root / "state/FULL_STARTED.json", result)
    else:
        result = validate_record(root, args.checkpoint_global_step)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

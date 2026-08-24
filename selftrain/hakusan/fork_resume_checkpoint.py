"""Safely import a progress checkpoint into a new frozen training run.

Only the run-binding metadata in the copied checkpoint is changed.  Lineage is
kept in a separate JSON record, while every other checkpoint value is compared
recursively after serialization.  The parent checkpoint is treated as
immutable and is verified before and after import.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import importlib.metadata
import json
import math
import os
import pathlib
import platform
import random
import re
import tempfile

import numpy as np
import torch

from src.spatialtrain import _validate_resume_checkpoint
from selftrain.scripts.run_integrity import validate_numerics_pass


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_checkpoint(path: pathlib.Path) -> dict:
    try:
        return torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:
        return torch.load(path, map_location="cpu")


def _assert_payload_equal(left, right, location: str = "checkpoint") -> None:
    """Recursively prove equality without relying on container pickles.

    Both checkpoints are loaded on CPU.  Tensor and NumPy payloads are checked
    by value and metadata; mappings and sequences are checked in order so loop,
    optimizer, scheduler, callback, AMP, and RNG state cannot change silently.
    """
    if type(left) is not type(right):
        raise RuntimeError(
            f"Fork checkpoint payload type changed at {location}: "
            f"{type(left).__name__} != {type(right).__name__}"
        )
    if isinstance(left, torch.Tensor):
        tensor_metadata = (
            left.dtype,
            left.layout,
            tuple(left.shape),
            tuple(left.stride()),
            left.requires_grad,
        )
        other_metadata = (
            right.dtype,
            right.layout,
            tuple(right.shape),
            tuple(right.stride()),
            right.requires_grad,
        )
        if tensor_metadata != other_metadata or not torch.equal(left, right):
            raise RuntimeError(
                f"Fork checkpoint tensor changed at {location}"
            )
        return
    if isinstance(left, np.ndarray):
        if (
            left.dtype != right.dtype
            or left.shape != right.shape
            or left.strides != right.strides
            or not np.array_equal(left, right, equal_nan=True)
        ):
            raise RuntimeError(
                f"Fork checkpoint NumPy array changed at {location}"
            )
        return
    if isinstance(left, dict):
        if list(left.keys()) != list(right.keys()):
            raise RuntimeError(
                f"Fork checkpoint mapping keys/order changed at {location}"
            )
        for key in left:
            _assert_payload_equal(
                left[key], right[key], f"{location}[{key!r}]"
            )
        return
    if isinstance(left, (list, tuple)):
        if len(left) != len(right):
            raise RuntimeError(
                f"Fork checkpoint sequence length changed at {location}"
            )
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            _assert_payload_equal(
                left_item, right_item, f"{location}[{index}]"
            )
        return
    if isinstance(left, (set, frozenset)):
        if left != right:
            raise RuntimeError(f"Fork checkpoint set changed at {location}")
        return
    if isinstance(left, float) and math.isnan(left) and math.isnan(right):
        return
    try:
        equal = left == right
    except Exception as error:
        raise RuntimeError(
            f"Fork checkpoint value cannot be compared at {location}"
        ) from error
    if isinstance(equal, (torch.Tensor, np.ndarray)):
        equal = bool(equal.all())
    if not bool(equal):
        raise RuntimeError(f"Fork checkpoint value changed at {location}")


def _assert_checkpoint_equivalent(source: dict, target: dict) -> None:
    """Allow exactly the three run-binding values to differ."""
    if list(source.keys()) != list(target.keys()):
        raise RuntimeError("Fork checkpoint top-level keys/order changed")
    source_without_binding = dict(source)
    target_without_binding = dict(target)
    source_without_binding.pop("audattn_run_metadata_v1", None)
    target_without_binding.pop("audattn_run_metadata_v1", None)
    _assert_payload_equal(source_without_binding, target_without_binding)


def _validate_runtime_against_pass(
    numerics_pass: dict, target_manifest: dict
) -> None:
    if numerics_pass.get("status") != "PASS":
        raise RuntimeError("Numerical preflight record is not PASS")
    if (
        numerics_pass.get("source_semantic_sha256")
        != target_manifest.get("semantic_combined_sha256")
    ):
        raise RuntimeError(
            "Numerical preflight PASS is not bound to the child semantic "
            "snapshot"
        )
    environment = numerics_pass.get("environment") or {}
    gpu_name = (environment.get("gpu") or {}).get("name")
    if gpu_name != "NVIDIA A100-PCIE-40GB":
        raise RuntimeError(
            "Fork-resume formal training requires an A100 numerical PASS; "
            f"got gpu={gpu_name!r}"
        )
    expected_packages = environment.get("packages") or {}
    for distribution in ("torch", "numpy", "pytorch-lightning"):
        actual = importlib.metadata.version(distribution)
        expected = expected_packages.get(distribution)
        if actual != expected:
            raise RuntimeError(
                "Checkpoint rewrite runtime differs from the numerical "
                f"preflight: {distribution}={actual!r}, expected={expected!r}"
            )
    if platform.python_version() != environment.get("python"):
        raise RuntimeError(
            "Checkpoint rewrite Python differs from the numerical preflight: "
            f"{platform.python_version()!r} != {environment.get('python')!r}"
        )
    if torch.version.cuda != environment.get("torch_cuda"):
        raise RuntimeError(
            "Checkpoint rewrite Torch CUDA build differs from the numerical "
            f"preflight: {torch.version.cuda!r} != "
            f"{environment.get('torch_cuda')!r}"
        )


def _validate_rng_state(checkpoint: dict) -> None:
    state = checkpoint.get("audattn_rng_state_v1")
    if not isinstance(state, dict):
        raise ValueError("Parent checkpoint RNG state is not a mapping")
    if set(state) != {"python", "numpy", "torch_cpu", "torch_cuda"}:
        raise ValueError(
            f"Parent checkpoint RNG keys are invalid: {sorted(state)}"
        )
    try:
        random.Random().setstate(state["python"])
        np.random.RandomState().set_state(state["numpy"])
    except Exception as error:
        raise ValueError("Parent checkpoint Python/NumPy RNG is invalid") from error
    cpu_state = state["torch_cpu"]
    if not (
        isinstance(cpu_state, torch.Tensor)
        and cpu_state.device.type == "cpu"
        and cpu_state.dtype == torch.uint8
        and cpu_state.ndim == 1
        and cpu_state.numel() > 0
    ):
        raise ValueError("Parent checkpoint Torch CPU RNG state is invalid")
    try:
        torch.Generator(device="cpu").set_state(cpu_state)
    except Exception as error:
        raise ValueError("Parent checkpoint Torch CPU RNG is unrestorable") from error
    cuda_states = state["torch_cuda"]
    if not isinstance(cuda_states, (list, tuple)) or len(cuda_states) != 1:
        raise ValueError(
            "A single-GPU resume requires exactly one CUDA RNG state"
        )
    for cuda_state in cuda_states:
        if not (
            isinstance(cuda_state, torch.Tensor)
            and cuda_state.device.type == "cpu"
            and cuda_state.dtype == torch.uint8
            and cuda_state.ndim == 1
            and cuda_state.numel() > 0
        ):
            raise ValueError("Parent checkpoint CUDA RNG state is invalid")


def _validate_grad_scaler_state(checkpoint: dict) -> None:
    state = checkpoint.get("MixedPrecision")
    if state is None:
        state = checkpoint.get("native_amp_scaling_state")
    if not isinstance(state, dict):
        raise ValueError("Parent checkpoint GradScaler state is not a mapping")
    required = {
        "scale",
        "growth_factor",
        "backoff_factor",
        "growth_interval",
        "_growth_tracker",
    }
    missing = sorted(required.difference(state))
    if missing:
        raise ValueError(
            f"Parent checkpoint GradScaler state is incomplete: {missing}"
        )
    scale = float(state["scale"])
    growth_factor = float(state["growth_factor"])
    backoff_factor = float(state["backoff_factor"])
    growth_interval = int(state["growth_interval"])
    growth_tracker = int(state["_growth_tracker"])
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Parent checkpoint GradScaler scale is invalid")
    if not math.isfinite(growth_factor) or growth_factor <= 1:
        raise ValueError("Parent checkpoint GradScaler growth factor is invalid")
    if not math.isfinite(backoff_factor) or not 0 < backoff_factor < 1:
        raise ValueError("Parent checkpoint GradScaler backoff factor is invalid")
    if growth_interval <= 0 or growth_tracker < 0:
        raise ValueError("Parent checkpoint GradScaler counters are invalid")


def _atomic_write_json(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = pathlib.Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _atomic_save_checkpoint(path: pathlib.Path, checkpoint: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(fd)
    temporary_path = pathlib.Path(temporary_name)
    try:
        torch.save(checkpoint, temporary_path)
        with temporary_path.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


@contextlib.contextmanager
def _run_metadata_environment(metadata: dict):
    mapping = {
        "AUDATTN_RUN_ID": metadata["run_id"],
        "AUDATTN_SOURCE_SHA256": metadata["source_semantic_sha256"],
        "AUDATTN_CONFIG_SHA256": metadata["config_sha256"],
    }
    previous = {key: os.environ.get(key) for key in mapping}
    os.environ.update(mapping)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _manifest_file_map(manifest: dict) -> dict[str, tuple[str, int]]:
    return {
        entry["path"]: (entry["sha256"], int(entry["size"]))
        for entry in manifest["semantic_files"]
    }


def _semantic_changes(source_manifest: dict, target_manifest: dict) -> list[str]:
    source_files = _manifest_file_map(source_manifest)
    target_files = _manifest_file_map(target_manifest)
    missing = sorted(set(source_files).difference(target_files))
    added = sorted(set(target_files).difference(source_files))
    if missing or added:
        raise RuntimeError(
            "Parent and child semantic input sets differ: "
            f"missing={missing}, added={added}"
        )
    return sorted(
        path
        for path in source_files
        if source_files[path] != target_files[path]
    )


def _require_inside(path: pathlib.Path, root: pathlib.Path, label: str) -> None:
    if not path.is_relative_to(root):
        raise ValueError(f"{label} escapes its run directory: {path}")


def prepare_fork(args: argparse.Namespace) -> dict:
    source_run_root = pathlib.Path(args.source_run_root).expanduser().resolve()
    target_run_root = pathlib.Path(args.target_run_root).expanduser().resolve()
    target_logical_run_root = pathlib.Path(
        args.target_logical_run_root
    ).expanduser().resolve()
    source_checkpoint_argument = pathlib.Path(
        args.source_checkpoint
    ).expanduser()
    if source_checkpoint_argument.is_symlink():
        raise ValueError("Source checkpoint must not be a symbolic link")
    source_checkpoint = source_checkpoint_argument.resolve()
    target_checkpoint = pathlib.Path(args.target_checkpoint).expanduser().resolve()
    source_manifest_path = pathlib.Path(args.source_manifest).expanduser().resolve()
    target_manifest_path = pathlib.Path(args.target_manifest).expanduser().resolve()
    numerics_pass_path = pathlib.Path(args.numerics_pass).expanduser().resolve()
    lineage_path = pathlib.Path(args.lineage).expanduser().resolve()

    if source_run_root == target_run_root:
        raise ValueError("Parent and child run directories must differ")
    _require_inside(source_checkpoint, source_run_root, "Source checkpoint")
    _require_inside(target_checkpoint, target_run_root, "Target checkpoint")
    _require_inside(source_manifest_path, source_run_root, "Source manifest")
    _require_inside(target_manifest_path, target_run_root, "Target manifest")
    _require_inside(numerics_pass_path, target_run_root, "Numerical PASS")
    _require_inside(lineage_path, target_run_root, "Lineage record")

    if args.resume_kind == "epoch":
        source_checkpoint_name = source_checkpoint.name
        if re.fullmatch(r"last(?:-v[1-9][0-9]*)?\.ckpt", source_checkpoint_name) is None:
            raise ValueError(
                "Epoch fork source must be last.ckpt or last-vN.ckpt; "
                f"got {source_checkpoint_name!r}"
            )
        target_checkpoint_name = "last.ckpt"
    else:
        source_checkpoint_name = "rolling.ckpt"
        target_checkpoint_name = "rolling.ckpt"
    expected_source = (
        source_run_root / "full" / "checkpoints" / source_checkpoint_name
    ).resolve()
    expected_target = (
        target_run_root / "full" / "checkpoints" / target_checkpoint_name
    ).resolve()
    logical_target_checkpoint = (
        target_logical_run_root
        / "full"
        / "checkpoints"
        / target_checkpoint_name
    ).resolve()
    if source_checkpoint != expected_source:
        raise ValueError(
            f"Source checkpoint must be exactly {expected_source}, "
            f"not {source_checkpoint}"
        )
    if target_checkpoint != expected_target:
        raise ValueError(
            f"Target checkpoint must be exactly {expected_target}, "
            f"not {target_checkpoint}"
        )
    if not source_checkpoint.is_file():
        raise FileNotFoundError(f"Parent checkpoint is missing: {source_checkpoint}")
    if target_checkpoint.exists() or lineage_path.exists():
        raise FileExistsError(
            "Fork target already exists; refusing to overwrite checkpoint "
            f"or lineage: {target_checkpoint}, {lineage_path}"
        )

    source_manifest = _read_json(source_manifest_path)
    target_manifest = _read_json(target_manifest_path)
    numerics_pass = validate_numerics_pass(
        numerics_pass_path, target_manifest_path, check_environment=False
    )
    _validate_runtime_against_pass(numerics_pass, target_manifest)
    changed_paths = _semantic_changes(source_manifest, target_manifest)
    allowed_paths = sorted(set(args.allowed_semantic_change))
    if changed_paths != allowed_paths:
        raise RuntimeError(
            "Unexpected semantic changes across fork: "
            f"changed={changed_paths}, allowed_exactly={allowed_paths}"
        )

    source_config = (
        source_manifest_path.parent / "files/selftrain/configs/full.yaml"
    ).resolve()
    target_config = (
        target_manifest_path.parent / "files/selftrain/configs/full.yaml"
    ).resolve()
    source_config_sha256 = _sha256(source_config)
    target_config_sha256 = _sha256(target_config)
    if source_config_sha256 != target_config_sha256:
        raise RuntimeError(
            "full.yaml changed across the fork; optimizer/model continuation "
            "is unsafe"
        )

    source_sha256_before = _sha256(source_checkpoint)
    source_stat_before = source_checkpoint.stat()
    checkpoint = _load_checkpoint(source_checkpoint)
    checkpoint_lightning_version = checkpoint.get(
        "pytorch-lightning_version"
    )
    runtime_lightning_version = importlib.metadata.version(
        "pytorch-lightning"
    )
    if checkpoint_lightning_version != runtime_lightning_version:
        raise RuntimeError(
            "Checkpoint/runtime PyTorch Lightning version mismatch: "
            f"checkpoint={checkpoint_lightning_version!r}, "
            f"runtime={runtime_lightning_version!r}"
        )
    source_metadata = checkpoint.get("audattn_run_metadata_v1")
    expected_source_metadata = {
        "run_id": args.source_run_id,
        "source_semantic_sha256": source_manifest[
            "semantic_combined_sha256"
        ],
        "config_sha256": source_config_sha256,
    }
    if source_metadata != expected_source_metadata:
        raise ValueError(
            "Parent checkpoint metadata does not match its frozen run: "
            f"actual={source_metadata}, expected={expected_source_metadata}"
        )

    global_step = int(checkpoint.get("global_step", -1))
    epoch = int(checkpoint.get("epoch", -1))
    if global_step != args.expected_global_step:
        raise ValueError(
            "Parent checkpoint global_step mismatch: "
            f"actual={global_step}, expected={args.expected_global_step}"
        )
    amp_state = checkpoint.get("audattn_amp_state_v1", {})
    attempts = int(amp_state.get("total_optimizer_attempts", -1))
    successful = int(amp_state.get("successful_optimizer_steps", -1))
    overflows = int(amp_state.get("total_overflows", -1))
    if attempts != global_step:
        raise ValueError(
            "Parent checkpoint optimizer-attempt count does not match "
            f"global_step: attempts={attempts}, global_step={global_step}"
        )
    if overflows != args.expected_amp_overflows:
        raise ValueError(
            "Parent checkpoint AMP-overflow count mismatch: "
            f"actual={overflows}, expected={args.expected_amp_overflows}"
        )
    if successful + overflows != attempts:
        raise ValueError("Parent checkpoint AMP accounting is inconsistent")
    amp_nonnegative_fields = (
        "consecutive_overflows",
        "total_overflows",
        "total_optimizer_attempts",
        "successful_optimizer_steps",
        "epoch_overflows",
        "epoch_optimizer_attempts",
        "epoch_successful_steps",
    )
    amp_values = {
        name: int(amp_state.get(name, -1)) for name in amp_nonnegative_fields
    }
    if any(value < 0 for value in amp_values.values()):
        raise ValueError(
            f"Parent checkpoint has invalid AMP hook state: {amp_values}"
        )
    if (
        amp_values["epoch_successful_steps"]
        + amp_values["epoch_overflows"]
        != amp_values["epoch_optimizer_attempts"]
    ):
        raise ValueError("Parent checkpoint epoch AMP accounting is inconsistent")
    overflow_window = [int(value) for value in amp_state.get("overflow_window", [])]
    if any(value not in (0, 1) for value in overflow_window):
        raise ValueError("Parent checkpoint AMP overflow window is invalid")
    if sum(overflow_window) > overflows:
        raise ValueError("AMP overflow window exceeds the total overflow count")
    trailing_overflows = 0
    for value in reversed(overflow_window):
        if value == 0:
            break
        trailing_overflows += 1
    if trailing_overflows != amp_values["consecutive_overflows"]:
        raise ValueError(
            "AMP consecutive-overflow count does not match its window"
        )

    _validate_rng_state(checkpoint)
    _validate_grad_scaler_state(checkpoint)

    with _run_metadata_environment(expected_source_metadata):
        _validate_resume_checkpoint(source_checkpoint, "resume")

    target_metadata = {
        "run_id": args.target_run_id,
        "source_semantic_sha256": target_manifest[
            "semantic_combined_sha256"
        ],
        "config_sha256": target_config_sha256,
    }
    prepared_at = dt.datetime.now(dt.timezone.utc).isoformat()
    fork_provenance = {
        "schema_version": 1,
        "kind": "fork-resume",
        "prepared_at": prepared_at,
        "reason": args.reason,
        "source_run_id": args.source_run_id,
        "target_run_id": args.target_run_id,
        "resume_kind": args.resume_kind,
        "source_checkpoint_path": str(source_checkpoint),
        "source_checkpoint_sha256": source_sha256_before,
        "source_run_metadata": source_metadata,
        "target_run_metadata": target_metadata,
        "epoch": epoch,
        "global_step": global_step,
        "amp_state": {
            "total_optimizer_attempts": attempts,
            "successful_optimizer_steps": successful,
            "total_overflows": overflows,
        },
        "changed_semantic_paths": changed_paths,
    }
    checkpoint["audattn_run_metadata_v1"] = target_metadata

    try:
        _atomic_save_checkpoint(target_checkpoint, checkpoint)
        del checkpoint
        target_sha256 = _sha256(target_checkpoint)
        source_payload = _load_checkpoint(source_checkpoint)
        target_payload = _load_checkpoint(target_checkpoint)
        if source_payload.get("audattn_run_metadata_v1") != expected_source_metadata:
            raise RuntimeError("Parent checkpoint metadata changed during fork")
        _assert_checkpoint_equivalent(source_payload, target_payload)
        if target_payload.get("audattn_run_metadata_v1") != target_metadata:
            raise RuntimeError("Fork checkpoint run metadata did not persist")
        del source_payload
        del target_payload
        with _run_metadata_environment(target_metadata):
            _validate_resume_checkpoint(target_checkpoint, "resume")

        source_sha256_after = _sha256(source_checkpoint)
        source_stat_after = source_checkpoint.stat()
        if source_sha256_after != source_sha256_before:
            raise RuntimeError("Parent checkpoint content changed during fork")
        if source_stat_after.st_mtime_ns != source_stat_before.st_mtime_ns:
            raise RuntimeError("Parent checkpoint mtime changed during fork")

        lineage = dict(fork_provenance)
        lineage.update(
            {
                "target_checkpoint_path": str(logical_target_checkpoint),
                "target_checkpoint_staging_path": str(target_checkpoint),
                "target_checkpoint_sha256": target_sha256,
                "source_config_sha256": source_config_sha256,
                "target_config_sha256": target_config_sha256,
                "source_semantic_sha256": source_manifest[
                    "semantic_combined_sha256"
                ],
                "target_semantic_sha256": target_manifest[
                    "semantic_combined_sha256"
                ],
                "rolling_resume_warning": (
                    "Model, optimizer, GradScaler, RNG, and Lightning loop "
                    "state are preserved, but an ordinary DataLoader cursor "
                    "is not bitwise resumable."
                    if args.resume_kind == "best-effort-rolling"
                    else None
                ),
            }
        )
        _atomic_write_json(lineage_path, lineage)
        return lineage
    except BaseException:
        target_checkpoint.unlink(missing_ok=True)
        lineage_path.unlink(missing_ok=True)
        raise


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run-root", required=True)
    parser.add_argument("--target-run-root", required=True)
    parser.add_argument("--target-logical-run-root", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--target-run-id", required=True)
    parser.add_argument("--source-checkpoint", required=True)
    parser.add_argument("--target-checkpoint", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--target-manifest", required=True)
    parser.add_argument("--numerics-pass", required=True)
    parser.add_argument("--lineage", required=True)
    parser.add_argument(
        "--resume-kind",
        choices=("epoch", "best-effort-rolling"),
        required=True,
    )
    parser.add_argument("--expected-global-step", type=int, required=True)
    parser.add_argument("--expected-amp-overflows", type=int, default=0)
    parser.add_argument(
        "--allowed-semantic-change", action="append", default=[]
    )
    parser.add_argument(
        "--reason", default="continue after validated source-only bug fix"
    )
    return parser.parse_args()


def main() -> None:
    lineage = prepare_fork(_parse_args())
    print(json.dumps(lineage, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

"""Read-only primitives for the numerical-diagnostic evidence contract."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import pathlib
import pickle
import random
import stat
from collections.abc import Mapping
from typing import Any, Sequence


TRACE_SCHEMA_VERSION = 1
RELATIVE_DENOMINATOR_FLOOR = 1e-12
CANARY_REFERENCE_ABS = 0.0077362060546875
MAX_ARTIFACT_TOTAL_BYTES = 1 << 30


class TraceContractError(ValueError):
    """Raised when an input cannot meet the immutable trace contract."""


_IDENTITY_KEYS = (
    "relative_path",
    "mode",
    "size",
    "st_mtime_ns",
    "st_dev",
    "st_ino",
    "sha256",
)


def canonical_json_bytes(value: object) -> bytes:
    """Encode a JSON-compatible value in its sole permitted byte form."""
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def _raise_contract(message: str, error: OSError | None = None) -> None:
    if error is None:
        raise TraceContractError(message)
    raise TraceContractError(message) from error


def _canonical_root(allowed_root: pathlib.Path) -> pathlib.Path:
    try:
        root = pathlib.Path(allowed_root).resolve(strict=True)
        root_stat = os.stat(root)
    except OSError as error:
        _raise_contract("allowed root is unavailable", error)
    if not stat.S_ISDIR(root_stat.st_mode):
        _raise_contract("allowed root is not a directory")
    return root


def _canonical_contained_path(
    path: pathlib.Path, allowed_root: pathlib.Path
) -> tuple[pathlib.Path, pathlib.Path]:
    root = _canonical_root(allowed_root)
    candidate = pathlib.Path(path)
    if not candidate.is_absolute():
        candidate = pathlib.Path.cwd() / candidate
    try:
        resolved_parent = candidate.parent.resolve(strict=True)
    except OSError as error:
        _raise_contract("file parent is unavailable", error)
    canonical_path = resolved_parent / candidate.name
    try:
        canonical_path.relative_to(root)
    except ValueError:
        _raise_contract("file path escapes allowed root")
    return canonical_path, root


def _require_single_regular_file(observed: os.stat_result) -> None:
    if not stat.S_ISREG(observed.st_mode):
        _raise_contract("pinned path is not a regular file")
    if observed.st_nlink != 1:
        _raise_contract("pinned file must have exactly one hard link")


def _read_only_nofollow_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if not isinstance(nofollow, int) or nofollow == 0:
        _raise_contract("O_NOFOLLOW is unavailable; refusing a pathname read")
    return os.O_RDONLY | nofollow


def _same_pinned_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_mode,
        left.st_nlink,
        left.st_size,
        left.st_mtime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_mode,
        right.st_nlink,
        right.st_size,
        right.st_mtime_ns,
    )


def _record_for_stat(
    path: pathlib.Path, root: pathlib.Path, observed: os.stat_result, digest: str
) -> dict[str, object]:
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "mode": stat.S_IMODE(observed.st_mode),
        "size": observed.st_size,
        "st_mtime_ns": observed.st_mtime_ns,
        "st_dev": observed.st_dev,
        "st_ino": observed.st_ino,
        "sha256": digest,
    }


def read_stable_bytes(
    path: pathlib.Path, *, allowed_root: pathlib.Path
) -> tuple[bytes, dict[str, object]]:
    """Read one regular unaliased file while rejecting identity-changing races."""
    canonical_path, root = _canonical_contained_path(path, allowed_root)
    try:
        before_open = os.lstat(canonical_path)
    except OSError as error:
        _raise_contract("pinned path cannot be lstat'd", error)
    _require_single_regular_file(before_open)

    flags = _read_only_nofollow_flags()
    try:
        descriptor = os.open(canonical_path, flags)
    except OSError as error:
        _raise_contract("pinned path cannot be opened without following links", error)
    try:
        opened = os.fstat(descriptor)
        _require_single_regular_file(opened)
        if not _same_pinned_identity(before_open, opened):
            _raise_contract("pinned path changed before descriptor open")

        chunks: list[bytes] = []
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
            digest.update(chunk)
        after_read = os.fstat(descriptor)
        _require_single_regular_file(after_read)
        if not _same_pinned_identity(opened, after_read):
            _raise_contract("pinned descriptor changed while reading")
    except OSError as error:
        _raise_contract("pinned descriptor cannot be read", error)
    finally:
        os.close(descriptor)

    try:
        after_path = os.lstat(canonical_path)
    except OSError as error:
        _raise_contract("pinned path changed after descriptor read", error)
    _require_single_regular_file(after_path)
    if not _same_pinned_identity(after_read, after_path):
        _raise_contract("pinned path changed after descriptor read")
    payload = b"".join(chunks)
    return payload, _record_for_stat(
        canonical_path, root, after_read, digest.hexdigest()
    )


def stable_file_record(
    path: pathlib.Path, *, allowed_root: pathlib.Path
) -> dict[str, object]:
    """Return the immutable identity and SHA-256 record for one pinned file."""
    _, record = read_stable_bytes(path, allowed_root=allowed_root)
    return record


def verify_file_record(
    record: Mapping[str, object], *, allowed_root: pathlib.Path
) -> dict[str, object]:
    """Re-read a pinned file and require exact agreement with its prior record."""
    if not isinstance(record, Mapping) or set(record) != set(_IDENTITY_KEYS):
        _raise_contract("file record has an invalid schema")
    relative_path = record.get("relative_path")
    if (
        not isinstance(relative_path, str)
        or not relative_path
        or pathlib.PurePosixPath(relative_path).is_absolute()
    ):
        _raise_contract("file record has an invalid relative path")
    root = _canonical_root(allowed_root)
    actual = stable_file_record(
        root / pathlib.PurePosixPath(relative_path), allowed_root=root
    )
    if actual != dict(record):
        _raise_contract("file record no longer matches the pinned file")
    return actual


def _length_prefixed_utf8_fields(values: tuple[object, ...]) -> bytes:
    encoded_fields = []
    for value in values:
        encoded = str(value).encode("utf-8")
        encoded_fields.append(len(encoded).to_bytes(8, "big") + encoded)
    return b"".join(encoded_fields)


def _tree_file_sha256(
    name: str | pathlib.Path,
    expected: os.stat_result,
    *,
    dir_fd: int | None = None,
) -> str:
    flags = _read_only_nofollow_flags()
    open_kwargs = {} if dir_fd is None else {"dir_fd": dir_fd}
    try:
        descriptor = os.open(name, flags, **open_kwargs)
    except OSError as error:
        _raise_contract("tree file cannot be opened without following links", error)
    try:
        opened = os.fstat(descriptor)
        _require_single_regular_file(opened)
        if not _same_pinned_identity(expected, opened):
            _raise_contract("tree file changed before descriptor open")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                break
            digest.update(chunk)
        after_read = os.fstat(descriptor)
        _require_single_regular_file(after_read)
        if not _same_pinned_identity(opened, after_read):
            _raise_contract("tree descriptor changed while reading")
        return digest.hexdigest()
    except OSError as error:
        _raise_contract("tree file cannot be read", error)
    finally:
        os.close(descriptor)


def _open_tree_directory(
    name: str | pathlib.Path,
    expected: os.stat_result,
    *,
    dir_fd: int | None = None,
) -> int:
    flags = _read_only_nofollow_flags()
    open_kwargs = {} if dir_fd is None else {"dir_fd": dir_fd}
    try:
        descriptor = os.open(name, flags, **open_kwargs)
    except OSError as error:
        _raise_contract(
            "tree directory cannot be opened without following links", error
        )
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            _raise_contract("tree directory is no longer a directory")
        if not _same_pinned_identity(expected, opened):
            _raise_contract("tree directory changed before descriptor open")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def fingerprint_tree(root: pathlib.Path) -> dict[str, object]:
    """Fingerprint tree metadata and ordinary-file contents without following links."""
    root_path = pathlib.Path(root)
    try:
        root_stat = os.lstat(root_path)
    except OSError as error:
        _raise_contract("tree root cannot be lstat'd", error)
    if not stat.S_ISDIR(root_stat.st_mode):
        _raise_contract("tree root is not a directory")

    entries: list[dict[str, object]] = []
    content_records: list[tuple[str, int, str]] = []

    root_descriptor = _open_tree_directory(root_path, root_stat)

    def visit(directory_fd: int, relative_directory: pathlib.PurePath) -> None:
        try:
            scanner = os.scandir(directory_fd)
            try:
                children = list(scanner)
            finally:
                scanner.close()
        except OSError as error:
            _raise_contract("tree directory cannot be scanned", error)
        for child in children:
            relative_path = (relative_directory / child.name).as_posix()
            try:
                observed = os.stat(
                    child.name, dir_fd=directory_fd, follow_symlinks=False
                )
            except OSError as error:
                _raise_contract("tree entry cannot be lstat'd", error)
            if stat.S_ISREG(observed.st_mode):
                entry_type, symlink_target = "file", ""
                _require_single_regular_file(observed)
            elif stat.S_ISDIR(observed.st_mode):
                entry_type, symlink_target = "directory", ""
            elif stat.S_ISLNK(observed.st_mode):
                entry_type = "symlink"
                try:
                    symlink_target = os.readlink(child.name, dir_fd=directory_fd)
                except OSError as error:
                    _raise_contract("tree symlink target cannot be read", error)
            else:
                entry_type, symlink_target = "other", ""
            entries.append(
                {
                    "relative_path": relative_path,
                    "type": entry_type,
                    "mode": stat.S_IMODE(observed.st_mode),
                    "size": observed.st_size,
                    "st_mtime_ns": observed.st_mtime_ns,
                    "st_dev": observed.st_dev,
                    "st_ino": observed.st_ino,
                    "symlink_target": symlink_target,
                }
            )
            if entry_type == "file":
                content_records.append(
                    (
                        relative_path,
                        observed.st_size,
                        _tree_file_sha256(child.name, observed, dir_fd=directory_fd),
                    )
                )
            elif entry_type == "directory":
                child_descriptor = _open_tree_directory(
                    child.name, observed, dir_fd=directory_fd
                )
                try:
                    visit(child_descriptor, relative_directory / child.name)
                finally:
                    os.close(child_descriptor)

    try:
        visit(root_descriptor, pathlib.PurePath())
    finally:
        os.close(root_descriptor)
    entries.sort(key=lambda entry: str(entry["relative_path"]).encode("utf-8"))
    content_records.sort(key=lambda item: item[0].encode("utf-8"))
    tree_payload = b"".join(
        _length_prefixed_utf8_fields(
            (
                entry["relative_path"],
                entry["type"],
                entry["mode"],
                entry["size"],
                entry["st_mtime_ns"],
                entry["st_dev"],
                entry["st_ino"],
                entry["symlink_target"],
            )
        )
        for entry in entries
    )
    content_payload = b"".join(
        _length_prefixed_utf8_fields(content_record)
        for content_record in content_records
    )
    return {
        "entries": entries,
        "entry_count": len(entries),
        "tree_sha256": hashlib.sha256(tree_payload).hexdigest(),
        "content_sha256": hashlib.sha256(content_payload).hexdigest(),
    }


def _numeric_dependencies() -> tuple[Any, Any]:
    try:
        import numpy as np
        import torch
    except ImportError as error:
        _raise_contract("NumPy and Torch are required for numeric trace records", error)
    return np, torch


def _require_tensor(value: Any) -> tuple[str, Any]:
    np, torch = _numeric_dependencies()
    if isinstance(value, torch.Tensor):
        return "torch", value
    if isinstance(value, np.ndarray):
        return "numpy", value
    _raise_contract("tensor value must be a NumPy ndarray or Torch Tensor")


def _tensor_dtype(kind: str, value: Any) -> str:
    return str(value.dtype) if kind == "torch" else str(value.dtype)


def _tensor_device(kind: str, value: Any) -> str:
    return str(value.device) if kind == "torch" else "cpu"


def canonical_tensor_bytes(tensor: Any) -> bytes:
    """Return logical, contiguous CPU tensor bytes without changing their dtype."""
    np, torch = _numeric_dependencies()
    kind, value = _require_tensor(tensor)
    if kind == "torch":
        return value.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()
    return np.ascontiguousarray(value).view(np.uint8).tobytes()


def tensor_record(tensor: Any, *, boundary: str) -> dict[str, Any]:
    """Bind a tensor's byte content to its boundary, dtype, shape, and device."""
    if not isinstance(boundary, str) or not boundary:
        _raise_contract("tensor boundary must be a non-empty string")
    kind, value = _require_tensor(tensor)
    payload = canonical_tensor_bytes(value)
    return {
        "boundary": boundary,
        "dtype": _tensor_dtype(kind, value),
        "shape": [int(dimension) for dimension in value.shape],
        "device": _tensor_device(kind, value),
        "nbytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _trial_id_list(trial_ids: Sequence[int], expected_length: int) -> list[int]:
    if isinstance(trial_ids, (str, bytes)):
        _raise_contract("trial IDs must be an integer sequence")
    values = list(trial_ids)
    if len(values) != expected_length:
        _raise_contract("trial ID count does not match tensor batch axis")
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        _raise_contract("trial IDs must be integers")
    if len(set(values)) != len(values):
        _raise_contract("trial IDs must be unique")
    return values


def _normalized_axis(axis: int, ndim: int, *, name: str) -> int:
    if not isinstance(axis, int) or isinstance(axis, bool):
        _raise_contract(f"{name} must be an integer")
    normalized = axis + ndim if axis < 0 else axis
    if normalized < 0 or normalized >= ndim:
        _raise_contract(f"{name} is out of range")
    return normalized


def per_trial_tensor_records(
    tensor: Any, *, trial_ids: Sequence[int], boundary: str, batch_axis: int = 0
) -> list[dict[str, Any]]:
    """Return one independently hashed tensor record per uniquely identified trial."""
    _, value = _require_tensor(tensor)
    if value.ndim == 0:
        _raise_contract("per-trial tensor must have a batch axis")
    axis = _normalized_axis(batch_axis, value.ndim, name="batch axis")
    ids = _trial_id_list(trial_ids, int(value.shape[axis]))
    records: list[dict[str, Any]] = []
    for index, trial_id in enumerate(ids):
        slicer = [slice(None)] * value.ndim
        slicer[axis] = index
        record = tensor_record(value[tuple(slicer)], boundary=boundary)
        record["trial_id"] = trial_id
        record["batch_axis"] = axis
        records.append(record)
    return records


def _comparison_base(left: Any, right: Any, boundary: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "boundary": boundary,
        "left": None,
        "right": None,
        "schema_valid": False,
        "schema_errors": [],
        "finite_valid": False,
        "nonfinite_locations": [],
        "bitwise_equal": False,
        "classification": "SCHEMA_INVALID",
        "relative_denominator_floor": None,
        "mismatch_count": None,
        "max_abs": None,
        "max_rel": None,
        "quantile_method": "linear",
        "element_abs_quantiles": None,
        "trial_max_abs_quantiles": None,
        "worst": None,
    }
    try:
        result["left"] = tensor_record(left, boundary=boundary)
    except TraceContractError as error:
        result["schema_errors"].append(f"left: {error}")
    try:
        result["right"] = tensor_record(right, boundary=boundary)
    except TraceContractError as error:
        result["schema_errors"].append(f"right: {error}")
    return result


def _comparison_quantiles(values: Any) -> dict[str, float]:
    np, _ = _numeric_dependencies()
    return {
        name: float(np.quantile(values, quantile, method="linear"))
        for name, quantile in (("p50", 0.50), ("p95", 0.95), ("p99", 0.99))
    }


def compare_aligned_tensor(
    left: Any,
    right: Any,
    *,
    trial_ids: Sequence[int],
    boundary: str,
    class_axis: int | None = None,
    relative_floor: float = RELATIVE_DENOMINATOR_FLOOR,
) -> dict[str, Any]:
    """Compare identically aligned finite tensors and expose deterministic diagnostics."""
    np, torch = _numeric_dependencies()
    result = _comparison_base(left, right, boundary)
    if (
        not isinstance(relative_floor, (int, float))
        or isinstance(relative_floor, bool)
        or not math.isfinite(relative_floor)
        or relative_floor <= 0
    ):
        result["schema_errors"].append("relative floor must be positive and finite")
        return result
    result["relative_denominator_floor"] = float(relative_floor)
    try:
        left_kind, left_value = _require_tensor(left)
        right_kind, right_value = _require_tensor(right)
        if left_kind != right_kind:
            result["schema_errors"].append("tensor implementations differ")
        elif tuple(left_value.shape) != tuple(right_value.shape):
            result["schema_errors"].append("tensor shapes differ")
        elif _tensor_dtype(left_kind, left_value) != _tensor_dtype(
            right_kind, right_value
        ):
            result["schema_errors"].append("tensor dtypes differ")
        elif left_value.ndim == 0:
            result["schema_errors"].append("aligned tensor must have a trial axis")
        else:
            ids = _trial_id_list(trial_ids, int(left_value.shape[0]))
            normalized_class_axis = None
            if class_axis is not None:
                normalized_class_axis = _normalized_axis(
                    class_axis, left_value.ndim, name="class axis"
                )
                if normalized_class_axis == 0:
                    _raise_contract("class axis cannot be the trial axis")
    except TraceContractError as error:
        result["schema_errors"].append(str(error))
        return result
    if result["schema_errors"]:
        return result

    if left_kind == "torch":
        left64 = left_value.detach().cpu().to(torch.float64).numpy()
        right64 = right_value.detach().cpu().to(torch.float64).numpy()
    else:
        left64 = np.asarray(left_value, dtype=np.float64)
        right64 = np.asarray(right_value, dtype=np.float64)
    finite_mask = np.isfinite(left64) & np.isfinite(right64)
    result["bitwise_equal"] = canonical_tensor_bytes(
        left_value
    ) == canonical_tensor_bytes(right_value)
    if not bool(np.all(finite_mask)):
        result["classification"] = "NONFINITE"
        result["schema_errors"].append("tensor contains non-finite values")
        nonfinite_locations: list[dict[str, Any]] = []
        for location in np.argwhere(~finite_mask).tolist():
            index = tuple(int(value) for value in location)

            def nonfinite_label(value: float) -> str:
                if math.isnan(value):
                    return "NaN"
                if value == float("inf"):
                    return "+Inf"
                if value == float("-inf"):
                    return "-Inf"
                return "finite"

            nonfinite_locations.append(
                {
                    "index": list(index),
                    "left": nonfinite_label(float(left64[index])),
                    "right": nonfinite_label(float(right64[index])),
                }
            )
        result["nonfinite_locations"] = nonfinite_locations
        return result

    result["schema_valid"] = True
    result["finite_valid"] = True
    abs_diff = np.abs(left64 - right64)
    denominator = np.maximum(
        np.maximum(np.abs(left64), np.abs(right64)), float(relative_floor)
    )
    rel_diff = abs_diff / denominator
    flat_index = int(np.argmax(abs_diff.reshape(-1)))
    index = [int(value) for value in np.unravel_index(flat_index, abs_diff.shape)]
    trial_max = abs_diff.reshape(len(ids), -1).max(axis=1)
    worst: dict[str, Any] = {
        "flat_index": flat_index,
        "index": index,
        "trial_id": ids[index[0]],
        "left_value": float(left64[tuple(index)]),
        "right_value": float(right64[tuple(index)]),
    }
    if normalized_class_axis is not None:
        worst["class_index"] = index[normalized_class_axis]
    result.update(
        {
            "classification": "BITWISE_EQUAL" if result["bitwise_equal"] else "DIFF",
            "max_abs": float(abs_diff.reshape(-1)[flat_index]),
            "max_rel": float(np.max(rel_diff)),
            "mismatch_count": int(np.count_nonzero(abs_diff)),
            "element_abs_quantiles": _comparison_quantiles(abs_diff.reshape(-1)),
            "trial_max_abs_quantiles": _comparison_quantiles(trial_max),
            "worst": worst,
        }
    )
    return result


def snapshot_model_state(model: Any) -> dict[str, Any]:
    """Snapshot every named parameter and buffer including identity and mutation version."""
    if not hasattr(model, "named_parameters") or not hasattr(model, "named_buffers"):
        _raise_contract("model must provide named_parameters and named_buffers")
    entries: list[dict[str, Any]] = []
    for kind, named_values in (
        ("parameter", model.named_parameters()),
        ("buffer", model.named_buffers()),
    ):
        for name, value in named_values:
            if value is None:
                continue
            record = tensor_record(value, boundary=f"model_{kind}:{name}")
            entries.append(
                {
                    "kind": kind,
                    "name": name,
                    "identity": id(value),
                    "object_id": id(value),
                    "_version": int(value._version),
                    "version": int(value._version),
                    "shape": record["shape"],
                    "dtype": record["dtype"],
                    "device": record["device"],
                    "sha256": record["sha256"],
                }
            )
    entries.sort(key=lambda entry: (entry["kind"], entry["name"]))
    return {"entries": entries}


def _snapshot_entry_map(snapshot: Any) -> dict[tuple[str, str], Mapping[str, Any]]:
    if (
        not isinstance(snapshot, Mapping)
        or set(snapshot) != {"entries"}
        or not isinstance(snapshot["entries"], list)
    ):
        _raise_contract("model snapshot has an invalid schema")
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    required_keys = {
        "kind",
        "name",
        "identity",
        "object_id",
        "_version",
        "version",
        "shape",
        "dtype",
        "device",
        "sha256",
    }
    for entry in snapshot["entries"]:
        if not isinstance(entry, Mapping) or set(entry) != required_keys:
            _raise_contract("model snapshot entry has an invalid schema")
        if (
            entry["kind"] not in {"parameter", "buffer"}
            or not isinstance(entry["name"], str)
            or not entry["name"]
        ):
            _raise_contract("model snapshot entry has an invalid kind or name")
        if any(
            not isinstance(entry[key], int)
            or isinstance(entry[key], bool)
            or entry[key] < 0
            for key in ("identity", "object_id", "_version", "version")
        ):
            _raise_contract("model snapshot entry has invalid identity or version")
        if (
            entry["identity"] != entry["object_id"]
            or entry["_version"] != entry["version"]
        ):
            _raise_contract("model snapshot entry aliases disagree")
        if not isinstance(entry["shape"], list) or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in entry["shape"]
        ):
            _raise_contract("model snapshot entry has an invalid shape")
        if (
            not isinstance(entry["dtype"], str)
            or not entry["dtype"]
            or not isinstance(entry["device"], str)
            or not entry["device"]
        ):
            _raise_contract("model snapshot entry has an invalid dtype or device")
        if (
            not isinstance(entry["sha256"], str)
            or len(entry["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in entry["sha256"])
        ):
            _raise_contract("model snapshot entry has an invalid content SHA")
        key = (entry["kind"], entry["name"])
        if key in result:
            _raise_contract("model snapshot has duplicate entries")
        result[key] = entry
    return result


def _state_transition(left: Any, right: Any) -> dict[str, Any]:
    left_entries = _snapshot_entry_map(left)
    right_entries = _snapshot_entry_map(right)
    changed = [
        {"kind": kind, "name": name}
        for kind, name in sorted(set(left_entries) | set(right_entries))
        if left_entries.get((kind, name)) != right_entries.get((kind, name))
    ]
    return {"changed": changed, "unchanged": not changed}


def compare_model_snapshots(before: Any, between: Any, after: Any) -> dict[str, Any]:
    """Report any parameter or buffer identity/version/content change at either checkpoint."""
    first = _state_transition(before, between)
    second = _state_transition(between, after)
    return {
        "before_to_between": first,
        "between_to_after": second,
        "state_unchanged": first["unchanged"] and second["unchanged"],
    }


def _rng_record(family: str, payload: bytes, encoding: str) -> dict[str, str]:
    return {
        "family": family,
        "encoding": encoding,
        "state": base64.b64encode(payload).decode("ascii"),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def snapshot_rng_state() -> dict[str, Any]:
    """Capture the full Python, NumPy, Torch CPU, and available CUDA RNG states."""
    np, torch = _numeric_dependencies()
    families: dict[str, dict[str, str]] = {
        "python": _rng_record(
            "python", pickle.dumps(random.getstate(), protocol=4), "base64-pickle-v4"
        ),
        "numpy": _rng_record(
            "numpy", pickle.dumps(np.random.get_state(), protocol=4), "base64-pickle-v4"
        ),
        "torch_cpu": _rng_record(
            "torch_cpu",
            bytes(torch.random.get_rng_state().cpu().contiguous().numpy()),
            "base64-raw",
        ),
    }
    cuda_device_count = torch.cuda.device_count()
    for index in range(cuda_device_count):
        state = torch.cuda.get_rng_state(index)
        families[f"torch_cuda:{index}"] = _rng_record(
            f"torch_cuda:{index}", bytes(state.cpu().contiguous().numpy()), "base64-raw"
        )
    return {
        "cuda_device_count": cuda_device_count,
        "families": dict(sorted(families.items())),
    }


def _rng_family_map(snapshot: Any) -> Mapping[str, Any]:
    if (
        not isinstance(snapshot, Mapping)
        or set(snapshot) != {"cuda_device_count", "families"}
        or not isinstance(snapshot["cuda_device_count"], int)
        or isinstance(snapshot["cuda_device_count"], bool)
        or snapshot["cuda_device_count"] < 0
        or not isinstance(snapshot["families"], Mapping)
    ):
        _raise_contract("RNG snapshot has an invalid schema")
    families = snapshot["families"]
    core_families = {"python", "numpy", "torch_cpu"}
    cuda_device_count = snapshot["cuda_device_count"]
    if not core_families.issubset(families):
        _raise_contract("RNG snapshot has missing or unexpected families")
    cuda_family_names = set(families) - core_families
    if cuda_device_count != len(cuda_family_names):
        _raise_contract("RNG snapshot CUDA count does not match supplied families")
    cuda_indices: set[int] = set()
    for name in cuda_family_names:
        if not isinstance(name, str) or not name.startswith("torch_cuda:"):
            _raise_contract("RNG snapshot has missing or unexpected families")
        suffix = name.removeprefix("torch_cuda:")
        if not suffix.isdecimal() or str(int(suffix)) != suffix:
            _raise_contract("RNG snapshot has a non-canonical CUDA ordinal")
        cuda_indices.add(int(suffix))
    if cuda_indices != set(range(cuda_device_count)):
        _raise_contract("RNG snapshot CUDA ordinals are not contiguous")
    for name, record in families.items():
        if not isinstance(record, Mapping) or set(record) != {
            "family",
            "encoding",
            "state",
            "sha256",
        }:
            _raise_contract("RNG family record has an invalid schema")
        expected_encoding = (
            "base64-pickle-v4" if name in {"python", "numpy"} else "base64-raw"
        )
        if record["family"] != name or record["encoding"] != expected_encoding:
            _raise_contract("RNG family record has an invalid identity or encoding")
        if not isinstance(record["state"], str) or not isinstance(
            record["sha256"], str
        ):
            _raise_contract("RNG family record has invalid state or digest")
        try:
            payload = base64.b64decode(record["state"].encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError) as error:
            _raise_contract("RNG family record has invalid base64 state", error)
        digest = hashlib.sha256(payload).hexdigest()
        if record["sha256"] != digest:
            _raise_contract("RNG family record digest does not match state")
    return families


def _rng_transition(left: Any, right: Any) -> dict[str, Any]:
    left_families = _rng_family_map(left)
    right_families = _rng_family_map(right)
    changed = sorted(
        family
        for family in set(left_families) | set(right_families)
        if left_families.get(family) != right_families.get(family)
    )
    return {"changed": changed, "unchanged": not changed}


def compare_rng_snapshots(before: Any, between: Any, after: Any) -> dict[str, Any]:
    """Report RNG movement as context only; it never invalidates a numerical cell."""
    result: dict[str, Any] = {
        "schema_valid": False,
        "schema_errors": [],
        "before_to_between": None,
        "between_to_after": None,
        "rng_changed": False,
        "invalidates_cell": False,
    }
    try:
        first = _rng_transition(before, between)
        second = _rng_transition(between, after)
    except TraceContractError as error:
        result["schema_errors"].append(str(error))
        return result
    result.update(
        {
            "schema_valid": True,
            "before_to_between": first,
            "between_to_after": second,
            "rng_changed": not (first["unchanged"] and second["unchanged"]),
        }
    )
    return result


def runtime_record(
    *,
    device: Any,
    autocast_enabled: bool,
    pass_batch_sizes: tuple[int, int],
    cache_dirs: Mapping[str, str],
) -> dict[str, Any]:
    """Record the runtime choices that contextualize a paired numerical pass."""
    if not isinstance(autocast_enabled, bool):
        _raise_contract("autocast setting must be boolean")
    if (
        not isinstance(pass_batch_sizes, tuple)
        or len(pass_batch_sizes) != 2
        or any(
            not isinstance(size, int) or isinstance(size, bool) or size <= 0
            for size in pass_batch_sizes
        )
    ):
        _raise_contract("pass batch sizes must be two positive integers")
    if not isinstance(cache_dirs, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in cache_dirs.items()
    ):
        _raise_contract("cache directories must be a string mapping")
    return {
        "device": str(device),
        "autocast_enabled": autocast_enabled,
        "pass_batch_sizes": list(pass_batch_sizes),
        "cache_dirs": {key: cache_dirs[key] for key in sorted(cache_dirs)},
    }


def verify_artifact_inventory(
    root: pathlib.Path,
    *,
    expected: Sequence[Mapping[str, Any]],
    allowed_total_bytes: int = 1 << 30,
) -> dict[str, Any]:
    """Fail closed unless an artifact tree exactly matches its pinned regular-file records."""
    if (
        not isinstance(allowed_total_bytes, int)
        or isinstance(allowed_total_bytes, bool)
        or allowed_total_bytes < 0
        or allowed_total_bytes > MAX_ARTIFACT_TOTAL_BYTES
    ):
        _raise_contract(
            "artifact byte budget must be a non-negative integer no larger than 1 GiB"
        )
    canonical_root = _canonical_root(root)
    expected_records = list(expected)
    expected_paths: set[str] = set()
    for record in expected_records:
        if not isinstance(record, Mapping):
            _raise_contract("artifact inventory record has an invalid schema")
        relative_path = record.get("relative_path")
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or pathlib.PurePosixPath(relative_path).is_absolute()
        ):
            _raise_contract("artifact inventory record has an invalid relative path")
        if relative_path in expected_paths:
            _raise_contract("artifact inventory has duplicate expected paths")
        expected_paths.add(relative_path)

    tree = fingerprint_tree(canonical_root)
    actual_paths: set[str] = set()
    for entry in tree["entries"]:
        entry_type = entry["type"]
        if entry_type == "file":
            actual_paths.add(str(entry["relative_path"]))
        elif entry_type != "directory":
            _raise_contract("artifact inventory contains a non-regular entry")
    if actual_paths != expected_paths:
        _raise_contract(
            "artifact inventory paths do not exactly match expected records"
        )

    verified = [
        verify_file_record(record, allowed_root=canonical_root)
        for record in expected_records
    ]
    verified.sort(key=lambda record: str(record["relative_path"]).encode("utf-8"))
    total_bytes = sum(int(record["size"]) for record in verified)
    if total_bytes > allowed_total_bytes:
        _raise_contract("artifact inventory exceeds byte budget")
    return {
        "records": verified,
        "total_bytes": total_bytes,
        "allowed_total_bytes": allowed_total_bytes,
    }

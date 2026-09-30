#!/usr/bin/env python3
"""Locked three-model evaluation on the frozen 10k pilot bank.

This program is deliberately outside the training project and run tree.  It
never mutates either tree.  Its five commands form a fail-closed workflow:

* ``audit-inputs`` inventories and validates the intended immutable inputs;
* ``freeze-inputs`` atomically creates one input manifest;
* ``check-only`` revalidates that manifest and strictly loads all three models;
* ``smoke`` evaluates a deterministic small subset into a fresh attempt path;
* ``run-audit`` evaluates all 10,000 trials into a fresh attempt path.

The author's checkpoint is an external system-level reference.  It is loaded
with its native config and native single-example preprocessing.  It is not
treated as if it had been trained on the self-training task or distribution.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import fcntl
import gc
import hashlib
import inspect
import json
import math
import os
import pathlib
import pickle
import platform
import random
import re
import secrets
import stat
import sys
import types
import uuid
from collections.abc import Iterable, Mapping
from typing import Any


sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")


SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSION = 1
PROTOCOL_ID = "fullpilot4_same_bank_audit_20260829_v3_nfs_portable_identity_v1"
FILESYSTEM_IDENTITY_POLICY = (
    "cross_invocation_path_size_sha_exact__dev_inode_diagnostic"
)
LOCK_PURPOSE = "cross_node_evaluation_flock_identity"
RUN_ID = "fullpilot4_accum9_20260815_181000"
FINAL_JOB_ID = "628071"
PILOT_EVAL_JOB_ID = "584990"
EXPECTED_ROLE_CONFIRMATION = (
    "formal40-primary__valbest33-secondary__author-external"
)
EVALUATION_ROLE = "REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST"
MODEL_IDS = ("formal40", "valbest33", "author_external")
MODEL_ROLES = {
    "formal40": "primary_fixed_40_epoch",
    "valbest33": "validation_selected_secondary",
    "author_external": "external_system_reference",
}
CONTROL_CONDITIONS = ("shuffled", "silent", "distractor")
ROLE_NAMES = (
    "target",
    "correct_cue",
    "distractor_1",
    "distractor_2",
    "distractor_3",
    "distractor_4",
    "probe_distractor_cue",
    "shuffled_cue",
)
EXPECTED_HASHES = {
    "full_config": "3efe0f455d7c902c772f5d1a6fb30cf0a4f13e46f0b72024ff5bfa7b9f3229b4",
    "author_config": "9878adc94e8d3e7088948fe363067c14d5c5535c5d2404aa51746a1686955439",
    "label_map": "a7c30da14b78288806ebc2fb39fe7f8cfc77ee60dc3a743fecf18fcfe1f3b9e5",
    "bank": "d03404f2bca5aeb8a5d096b84f6ef758b6b07d0ee5efbd44ded59135bced0091",
    "historical_evaluator": "29414207e3fac53ff8805e61fcf4cee48fb155c4c60d0e736e35526c80dfae5b",
    "historical_results": "5046ed08c2adf006167e64bd987e2833d45a9c28163f37482bf2b25f5d07cf6d",
    "historical_summary": "7fc915c7bbf0e4774cc74ae01b0144e3d990c22fa8776ae23a454473cd3fc5eb",
    "source_semantic": "496cf41c8abedb4673a83a4ec148bc74ea92e6c059ea4bc998610a0db1ab9038",
    "formal40": "2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff",
    "valbest33": "853069b8a9c037bc11d373b1d76e63f3e5c9f7601fad724a6ce7e7d7840d5e14",
    "author_external": "6fb23dde8455ef353a00d9bf676bf00f337961ac7c6d45f35f2c45a15cd88ed0",
    "recovery_tool": "f7b682f61920d21d181a4721a32e87d4dc216d07df3d476392ee2de41f967959",
}
EXPECTED_BOUNDARIES = {
    "formal40": {"basename": "formal-final.ckpt", "epoch": 40, "global_step": 69440},
    "valbest33": {"basename": "epoch=33-step=59024.ckpt", "epoch": 33, "global_step": 59024},
    "author_external": {"basename": "epoch=1-step=24679-v1.ckpt", "epoch": 1, "global_step": 24679},
}
EXPECTED_FORMAL_SUCCESSFUL = 69414
EXPECTED_FORMAL_OVERFLOWS = 26
EXPECTED_ATTEMPTS_PER_EPOCH = 1736
EXPECTED_EPOCH_PROGRESS = {
    "formal40": {
        "total": {"ready": 40, "completed": 38, "started": 40, "processed": 40},
        "current": {"ready": 40, "completed": 40, "started": 40, "processed": 40},
    },
    "valbest33": {
        "total": {"ready": 34, "completed": 31, "started": 34, "processed": 34},
        "current": {"ready": 34, "completed": 33, "started": 34, "processed": 34},
    },
}
BOOTSTRAP_SEED = 20260829
BOOTSTRAP_REPETITIONS = 10_000
TOTAL_TRIALS = 10_000
MIXED_TRIALS = 9_000
CLEAN_TRIALS = 1_000
CONTROL_TRIALS = 2_000
SNR_IDENTITY_ATOL_DB = 1e-12


class EvaluationError(RuntimeError):
    """Fail-closed validation error."""


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def sha256_file(path: pathlib.Path) -> str:
    with open_pinned_file(path, f"SHA input {path}") as pinned:
        return pinned["sha256"]


def _is_relative_to(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _absolute_no_resolve(path: pathlib.Path | str) -> pathlib.Path:
    return pathlib.Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _reject_symlink_components(
    path: pathlib.Path | str,
    label: str,
    *,
    include_leaf: bool = True,
) -> pathlib.Path:
    """Return an absolute lexical path after rejecting every symlink component."""
    absolute = _absolute_no_resolve(path)
    parts = absolute.parts
    current = pathlib.Path(parts[0])
    stop = len(parts) if include_leaf else len(parts) - 1
    for part in parts[1:stop]:
        current /= part
        try:
            status = os.lstat(current)
        except FileNotFoundError as error:
            raise EvaluationError(f"{label} path component is missing: {current}") from error
        if stat.S_ISLNK(status.st_mode):
            raise EvaluationError(f"{label} has a symbolic-link component: {current}")
    return absolute


def safe_file(path: pathlib.Path | str, label: str) -> pathlib.Path:
    absolute = _reject_symlink_components(path, label)
    try:
        status = os.lstat(absolute)
    except FileNotFoundError as error:
        raise EvaluationError(f"{label} is missing: {absolute}") from error
    if not stat.S_ISREG(status.st_mode):
        raise EvaluationError(f"{label} is not a regular file: {absolute}")
    return absolute


def safe_directory(path: pathlib.Path | str, label: str) -> pathlib.Path:
    absolute = _reject_symlink_components(path, label)
    try:
        status = os.lstat(absolute)
    except FileNotFoundError as error:
        raise EvaluationError(f"{label} is missing: {absolute}") from error
    if not stat.S_ISDIR(status.st_mode):
        raise EvaluationError(f"{label} is not a directory: {absolute}")
    return absolute


@contextlib.contextmanager
def open_pinned_file(
    path: pathlib.Path | str,
    label: str,
    expected_sha256: str | None = None,
):
    """Open and hash one immutable regular file through the same descriptor.

    The yielded mapping contains a binary ``handle`` positioned at byte zero
    and its identity record.  Consumers must parse/load from that handle and
    must not reopen ``path``.  The final path-to-inode check catches namespace
    replacement while the descriptor was held; the descriptor itself makes
    such a replacement unable to change the consumed bytes.
    """
    absolute = safe_file(path, label)
    expected = (
        _require_sha(expected_sha256, f"Expected SHA for {label}")
        if expected_sha256 is not None
        else None
    )
    named_before = os.lstat(absolute)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(absolute, flags)
    except OSError as error:
        raise EvaluationError(f"Cannot safely open {label}: {absolute}: {error}") from error
    handle = os.fdopen(descriptor, "rb", closefd=True)
    try:
        opened_before = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened_before.st_mode):
            raise EvaluationError(f"{label} descriptor is not a regular file: {absolute}")
        if (opened_before.st_dev, opened_before.st_ino) != (
            named_before.st_dev,
            named_before.st_ino,
        ):
            raise EvaluationError(f"{label} changed while opening: {absolute}")
        digest = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        actual_sha = digest.hexdigest()
        if expected is not None and actual_sha != expected:
            raise EvaluationError(
                f"{label} SHA mismatch: expected={expected}, actual={actual_sha}, "
                f"path={absolute}"
            )
        opened_after_hash = os.fstat(handle.fileno())
        identity_before = (
            opened_before.st_dev,
            opened_before.st_ino,
            opened_before.st_size,
            opened_before.st_mtime_ns,
            opened_before.st_ctime_ns,
        )
        identity_after = (
            opened_after_hash.st_dev,
            opened_after_hash.st_ino,
            opened_after_hash.st_size,
            opened_after_hash.st_mtime_ns,
            opened_after_hash.st_ctime_ns,
        )
        if identity_before != identity_after:
            raise EvaluationError(f"{label} changed while hashing: {absolute}")
        handle.seek(0)
        record = {
            "path": str(absolute),
            "basename": absolute.name,
            "size": int(opened_before.st_size),
            "sha256": actual_sha,
            "device": int(opened_before.st_dev),
            "inode": int(opened_before.st_ino),
        }
        yield {**record, "handle": handle}
        opened_final = os.fstat(handle.fileno())
        named_final = os.lstat(absolute)
        if (
            opened_final.st_dev,
            opened_final.st_ino,
            opened_final.st_size,
            opened_final.st_mtime_ns,
            opened_final.st_ctime_ns,
        ) != identity_before or (
            named_final.st_dev,
            named_final.st_ino,
        ) != (opened_before.st_dev, opened_before.st_ino):
            raise EvaluationError(f"{label} changed while it was pinned: {absolute}")
    finally:
        handle.close()


def read_pinned_bytes(
    path: pathlib.Path | str,
    label: str,
    expected_sha256: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    with open_pinned_file(path, label, expected_sha256) as pinned:
        payload = pinned["handle"].read()
        record = {key: value for key, value in pinned.items() if key != "handle"}
    return payload, record


def read_json(
    path: pathlib.Path | str,
    label: str,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    payload, record = read_pinned_bytes(path, label, expected_sha256)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError(f"{label} is not valid JSON: {record['path']}") from error
    if not isinstance(value, dict):
        raise EvaluationError(f"{label} must contain a JSON object: {record['path']}")
    return value


def pinned_file(
    path: pathlib.Path | str,
    label: str,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    with open_pinned_file(path, label, expected_sha256) as pinned:
        return {key: value for key, value in pinned.items() if key != "handle"}


def validate_persistent_file_identity(
    frozen: Mapping[str, Any],
    current: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    """Validate one cross-invocation record without trusting client-local stat IDs.

    ``st_dev`` and ``st_ino`` remain valuable while a descriptor and pathname
    are observed by one process.  Across cluster nodes, however, they are only
    diagnostics.  Persistent identity is the canonical path/basename plus the
    exact byte size and SHA-256 digest; ``pinned_file`` has already enforced a
    regular, non-symlink file and consumed the bytes from one descriptor.
    """
    if not isinstance(frozen, Mapping) or not isinstance(current, Mapping):
        raise EvaluationError(f"{label} is not a persistent file record")
    required = {"path", "basename", "size", "sha256", "device", "inode"}
    if not required.issubset(frozen) or not required.issubset(current):
        raise EvaluationError(f"{label} lacks persistent identity fields")

    frozen_path_text = str(frozen["path"])
    current_path_text = str(current["path"])
    frozen_path = _absolute_no_resolve(frozen_path_text)
    current_path = _absolute_no_resolve(current_path_text)
    if frozen_path_text != str(frozen_path) or current_path_text != str(current_path):
        raise EvaluationError(f"{label} path is not canonical and absolute")
    if current_path != frozen_path:
        raise EvaluationError(f"{label} canonical path changed")

    frozen_basename = str(frozen["basename"])
    current_basename = str(current["basename"])
    if (
        not frozen_basename
        or frozen_basename != frozen_path.name
        or current_basename != current_path.name
        or current_basename != frozen_basename
    ):
        raise EvaluationError(f"{label} basename changed")
    try:
        frozen_size = int(frozen["size"])
        current_size = int(current["size"])
        frozen_device = int(frozen["device"])
        current_device = int(current["device"])
        frozen_inode = int(frozen["inode"])
        current_inode = int(current["inode"])
    except (TypeError, ValueError) as error:
        raise EvaluationError(f"{label} stat diagnostics are invalid") from error
    if frozen_size < 0 or current_size != frozen_size:
        raise EvaluationError(f"{label} size changed")
    if min(frozen_device, current_device, frozen_inode, current_inode) < 0:
        raise EvaluationError(f"{label} stat diagnostics are negative")
    frozen_sha = _require_sha(str(frozen["sha256"]), f"{label} frozen SHA")
    current_sha = _require_sha(str(current["sha256"]), f"{label} current SHA")
    if current_sha != frozen_sha:
        raise EvaluationError(f"{label} SHA changed")
    return {
        "frozen_device": frozen_device,
        "current_device": current_device,
        "device_match": current_device == frozen_device,
        "frozen_inode": frozen_inode,
        "current_inode": current_inode,
        "inode_match": current_inode == frozen_inode,
    }


def _new_lock_payload(external_root: pathlib.Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "filesystem_identity_policy": FILESYSTEM_IDENTITY_POLICY,
        "purpose": LOCK_PURPOSE,
        "lock_nonce": secrets.token_hex(32),
        "external_root": str(external_root),
    }


def _validate_lock_payload(
    value: Any,
    external_root: pathlib.Path,
) -> dict[str, Any]:
    expected_keys = {
        "schema_version",
        "protocol_id",
        "filesystem_identity_policy",
        "purpose",
        "lock_nonce",
        "external_root",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise EvaluationError("Evaluation lock payload fields are not exact")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("protocol_id") != PROTOCOL_ID
        or value.get("filesystem_identity_policy") != FILESYSTEM_IDENTITY_POLICY
        or value.get("purpose") != LOCK_PURPOSE
        or value.get("external_root") != str(external_root)
        or not re.fullmatch(r"[0-9a-f]{64}", str(value.get("lock_nonce", "")))
    ):
        raise EvaluationError("Evaluation lock payload boundary mismatch")
    return dict(value)


def read_lock_payload(
    path: pathlib.Path,
    expected_sha256: str,
    external_root: pathlib.Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, record = read_pinned_bytes(
        path,
        "Frozen evaluation lock",
        expected_sha256,
    )

    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        parsed = json.loads(payload.decode("utf-8"), parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise EvaluationError("Evaluation lock is not strict JSON") from error
    parsed = _validate_lock_payload(parsed, external_root)
    if canonical_json_bytes(parsed) != payload:
        raise EvaluationError("Evaluation lock bytes are not canonical JSON")
    return parsed, record


@contextlib.contextmanager
def open_pinned_directory(path: pathlib.Path | str, label: str):
    absolute = safe_directory(path, label)
    named = os.lstat(absolute)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(absolute, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
        ) != (named.st_dev, named.st_ino):
            raise EvaluationError(f"{label} changed while opening: {absolute}")
        yield absolute, descriptor, (opened.st_dev, opened.st_ino)
        final_named = os.lstat(absolute)
        final_opened = os.fstat(descriptor)
        if (
            final_opened.st_dev,
            final_opened.st_ino,
        ) != (opened.st_dev, opened.st_ino) or (
            final_named.st_dev,
            final_named.st_ino,
        ) != (opened.st_dev, opened.st_ino):
            raise EvaluationError(f"{label} changed while pinned: {absolute}")
    finally:
        os.close(descriptor)


def atomic_create_bytes(path: pathlib.Path, payload: bytes) -> None:
    path = _absolute_no_resolve(path)
    name = path.name
    if not name or name in {".", ".."}:
        raise EvaluationError(f"Unsafe output basename: {path}")
    temporary = f".{name}.partial.{os.getpid()}.{uuid.uuid4().hex}"
    temp_created = False
    published = False
    with open_pinned_directory(path.parent, f"Parent of {name}") as (
        parent,
        directory_fd,
        _,
    ):
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            descriptor = os.open(temporary, flags, 0o600, dir_fd=directory_fd)
            temp_created = True
            try:
                view = memoryview(payload)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            try:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileExistsError as error:
                raise FileExistsError(
                    f"Refusing to overwrite existing output: {path}"
                ) from error
            published = True
            destination = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            named_destination = os.lstat(path)
            if (
                destination.st_dev,
                destination.st_ino,
            ) != (named_destination.st_dev, named_destination.st_ino):
                raise EvaluationError(f"Output namespace changed during publish: {path}")
            os.unlink(temporary, dir_fd=directory_fd)
            temp_created = False
            with contextlib.suppress(OSError):
                os.fsync(directory_fd)
        except Exception:
            if published:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(name, dir_fd=directory_fd)
            raise
        finally:
            if temp_created:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=directory_fd)


def atomic_create_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    atomic_create_bytes(path, canonical_json_bytes(value))


def mkdir_exclusive(parent: pathlib.Path, name: str, mode: int = 0o700) -> pathlib.Path:
    if not name or name in {".", ".."} or "/" in name:
        raise EvaluationError(f"Unsafe directory basename: {name!r}")
    with open_pinned_directory(parent, f"Parent directory for {name}") as (
        parent_path,
        directory_fd,
        _,
    ):
        try:
            os.mkdir(name, mode=mode, dir_fd=directory_fd)
        except FileExistsError as error:
            raise FileExistsError(
                f"Refusing to reuse existing directory: {parent_path / name}"
            ) from error
        created = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        named = os.lstat(parent_path / name)
        if not stat.S_ISDIR(created.st_mode) or (
            created.st_dev,
            created.st_ino,
        ) != (named.st_dev, named.st_ino):
            with contextlib.suppress(OSError):
                os.rmdir(name, dir_fd=directory_fd)
            raise EvaluationError(
                f"Directory namespace changed during creation: {parent_path / name}"
            )
        with contextlib.suppress(OSError):
            os.fsync(directory_fd)
    return parent_path / name


def initialize_freeze_layout(
    external_root: pathlib.Path,
    manifest_path: pathlib.Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Create the one-shot external state tree; manifest is the commit record."""
    validate_protocol_boundary(manifest, "Manifest being frozen")
    external_root = safe_directory(external_root, "External evaluation root")
    manifest_path = _absolute_no_resolve(manifest_path)
    if manifest_path != external_root / "input_freeze.json":
        raise EvaluationError(
            "Frozen manifest must be exactly EXTERNAL_ROOT/input_freeze.json"
        )
    safe_directory(external_root / "tools", "External frozen tools directory")
    targets = [
        external_root / "logs",
        external_root / "state",
        external_root / "attempts",
        external_root / "submitted_runners",
        manifest_path,
    ]
    for target in targets:
        if os.path.lexists(target):
            raise FileExistsError(f"Refusing to reuse freeze target: {target}")
    logs = mkdir_exclusive(external_root, "logs")
    state_dir = mkdir_exclusive(external_root, "state")
    attempts = mkdir_exclusive(external_root, "attempts")
    submitted = mkdir_exclusive(external_root, "submitted_runners")
    smoke_attempts = mkdir_exclusive(attempts, "smoke")
    audit_attempts = mkdir_exclusive(attempts, "audit")
    lock_path = state_dir / "evaluation.lock"
    lock_payload = _new_lock_payload(external_root)
    lock_bytes = canonical_json_bytes(lock_payload)
    atomic_create_bytes(lock_path, lock_bytes)
    lock_record = pinned_file(
        lock_path,
        "Frozen evaluation lock",
        hashlib.sha256(lock_bytes).hexdigest(),
    )
    frozen_lock = {**lock_record, "payload": lock_payload}
    manifest["layout"] = {
        "logs": str(logs),
        "state": str(state_dir),
        "attempts": str(attempts),
        "smoke_attempts": str(smoke_attempts),
        "audit_attempts": str(audit_attempts),
        "submitted_runners": str(submitted),
        "evaluation_lock": frozen_lock,
    }
    atomic_create_json(manifest_path, manifest)
    return {
        "manifest": pinned_file(manifest_path, "Frozen input manifest"),
        "evaluation_lock": frozen_lock,
    }


def validate_frozen_layout(
    external_root: pathlib.Path,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    validate_protocol_boundary(manifest, "Frozen manifest")
    layout = manifest.get("layout")
    if not isinstance(layout, Mapping):
        raise EvaluationError("Frozen manifest has no layout binding")
    expected_dirs = {
        "logs": external_root / "logs",
        "state": external_root / "state",
        "attempts": external_root / "attempts",
        "smoke_attempts": external_root / "attempts/smoke",
        "audit_attempts": external_root / "attempts/audit",
        "submitted_runners": external_root / "submitted_runners",
    }
    for key, expected in expected_dirs.items():
        actual = safe_directory(str(layout.get(key, "")), f"Frozen layout {key}")
        if actual != expected:
            raise EvaluationError(f"Frozen layout path mismatch for {key}")
    lock = layout.get("evaluation_lock")
    if not isinstance(lock, Mapping):
        raise EvaluationError("Frozen layout has no evaluation lock record")
    canonical_lock = external_root / "state/evaluation.lock"
    if pathlib.Path(str(lock.get("path", ""))) != canonical_lock:
        raise EvaluationError("Frozen evaluation lock path is not canonical")
    lock_payload, lock_record = read_lock_payload(
        canonical_lock,
        str(lock.get("sha256", "")),
        external_root,
    )
    identity_diagnostics = validate_persistent_file_identity(
        lock,
        lock_record,
        "Frozen evaluation lock",
    )
    if lock_payload != lock.get("payload"):
        raise EvaluationError("Frozen evaluation lock payload differs from manifest")
    return {
        "directories": sorted(expected_dirs),
        "evaluation_lock": lock_record,
        "evaluation_lock_payload": lock_payload,
        "filesystem_identity_diagnostics": identity_diagnostics,
    }


@contextlib.contextmanager
def evaluation_lock(external_root: pathlib.Path):
    lock_path = external_root / "state/evaluation.lock"
    absolute = safe_file(lock_path, "Evaluation lock")
    flags = (
        os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(absolute, flags)
    handle = os.fdopen(descriptor, "r+b", closefd=True)
    locked = False

    def assert_named_lock_is_opened_inode() -> None:
        """Reject lock-file/parent namespace replacement while the lock is held."""
        opened_now = os.fstat(handle.fileno())
        try:
            named_now = os.lstat(absolute)
        except FileNotFoundError as error:
            raise EvaluationError("Evaluation lock disappeared while held") from error
        if not stat.S_ISREG(opened_now.st_mode) or not stat.S_ISREG(named_now.st_mode):
            raise EvaluationError("Evaluation lock is no longer a regular file")
        if (opened_now.st_dev, opened_now.st_ino) != (
            named_now.st_dev,
            named_now.st_ino,
        ):
            raise EvaluationError("Evaluation lock namespace changed while held")

    final_identity_error: Exception | None = None
    try:
        opened = os.fstat(handle.fileno())
        named = os.lstat(absolute)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
        ) != (named.st_dev, named.st_ino):
            raise EvaluationError("Evaluation lock changed while opening")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise EvaluationError("Another same-bank evaluation holds the lock") from error
        locked = True
        # A rename between open(2) and flock(2) could otherwise leave us holding
        # an obsolete inode while a second process locks the new path.
        assert_named_lock_is_opened_inode()
        yield handle
    finally:
        if locked:
            try:
                # Check again before unlocking so replacing the canonical name
                # never silently permits a concurrent second evaluator.
                assert_named_lock_is_opened_inode()
            except Exception as error:
                final_identity_error = error
        try:
            if locked:
                with contextlib.suppress(OSError):
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
        if final_identity_error is not None:
            raise final_identity_error


def _require_sha(value: str, label: str) -> str:
    normalized = str(value)
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise EvaluationError(f"{label} is not a lowercase SHA-256 digest")
    return normalized


def _require_attempt_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value):
        raise EvaluationError(f"Unsafe attempt ID: {value!r}")
    return value


def validate_protocol_boundary(value: Mapping[str, Any], label: str) -> None:
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("protocol_id") != PROTOCOL_ID
        or value.get("filesystem_identity_policy") != FILESYSTEM_IDENTITY_POLICY
    ):
        raise EvaluationError(f"{label} protocol/filesystem identity boundary mismatch")


def validate_role_manifest(manifest: Mapping[str, Any]) -> None:
    models = manifest.get("models")
    if not isinstance(models, dict) or set(models) != set(MODEL_IDS):
        raise EvaluationError("Manifest model IDs/roles are not the locked trio")
    for model_id in MODEL_IDS:
        record = models[model_id]
        if not isinstance(record, dict) or record.get("role") != MODEL_ROLES[model_id]:
            raise EvaluationError(f"Manifest role mismatch for {model_id}")
    if manifest.get("role_confirmation") != EXPECTED_ROLE_CONFIRMATION:
        raise EvaluationError("Manifest role-confirmation string is invalid")
    if manifest.get("evaluation_role") != EVALUATION_ROLE:
        raise EvaluationError("Manifest evaluation-role boundary is invalid")


def _load_torch_checkpoint(
    path: pathlib.Path,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    try:
        import torch
    except ImportError as error:
        raise EvaluationError("PyTorch is required to inspect checkpoints") from error
    with open_pinned_file(path, f"Checkpoint {path.name}", expected_sha256) as pinned:
        try:
            checkpoint = torch.load(
                pinned["handle"], map_location="cpu", weights_only=False
            )
        except TypeError:
            pinned["handle"].seek(0)
            checkpoint = torch.load(pinned["handle"], map_location="cpu")
    if not isinstance(checkpoint, dict):
        raise EvaluationError(f"Checkpoint is not a mapping: {path}")
    if not isinstance(checkpoint.get("state_dict"), Mapping):
        raise EvaluationError(f"Checkpoint has no state_dict mapping: {path}")
    return checkpoint


def _state_signature(state_dict: Mapping[str, Any]) -> dict[str, Any]:
    keys = list(state_dict)
    if any(not isinstance(key, str) for key in keys) or len(keys) != len(set(keys)):
        raise EvaluationError("Checkpoint state_dict has invalid/duplicate keys")
    total_numel = 0
    floating_numel = 0
    for key, value in state_dict.items():
        if not hasattr(value, "shape") or not hasattr(value, "dtype"):
            raise EvaluationError(f"state_dict value is not tensor-like: {key}")
        numel = int(value.numel())
        total_numel += numel
        if bool(value.is_floating_point()) or bool(value.is_complex()):
            floating_numel += numel
    return {
        "key_count": len(keys),
        "total_numel": total_numel,
        "floating_numel": floating_numel,
        "model_key_count": sum(key.startswith("model.") for key in keys),
        "cochleagram_key_count": sum(key.startswith("coch_gram.") for key in keys),
        "compiled_model_prefix": any(key.startswith("model._orig_mod.") for key in keys),
        "first_key": keys[0] if keys else None,
        "last_key": keys[-1] if keys else None,
    }


def _epoch_progress(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    value = (
        checkpoint.get("loops", {})
        .get("fit_loop", {})
        .get("epoch_progress", {})
    )
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _amp_audit(checkpoint: Mapping[str, Any], global_step: int) -> dict[str, int]:
    amp = checkpoint.get("audattn_amp_state_v1")
    if not isinstance(amp, dict):
        raise EvaluationError("Self-training checkpoint has no AMP state")
    attempts = int(amp.get("total_optimizer_attempts", -1))
    successful = int(amp.get("successful_optimizer_steps", -1))
    overflows = int(amp.get("total_overflows", -1))
    if attempts != global_step or successful + overflows != attempts:
        raise EvaluationError(
            "Checkpoint AMP accounting mismatch: "
            f"step={global_step}, attempts={attempts}, "
            f"successful={successful}, overflows={overflows}"
        )
    return {"attempts": attempts, "successful": successful, "overflows": overflows}


def inspect_checkpoint(
    file_record: Mapping[str, Any],
    model_id: str,
    source_semantic_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = pathlib.Path(str(file_record["path"]))
    checkpoint = _load_torch_checkpoint(path, str(file_record["sha256"]))
    boundary = EXPECTED_BOUNDARIES[model_id]
    epoch = int(checkpoint.get("epoch", -1))
    global_step = int(checkpoint.get("global_step", -1))
    if path.name != boundary["basename"]:
        raise EvaluationError(f"Unexpected {model_id} basename: {path.name}")
    if epoch != boundary["epoch"] or global_step != boundary["global_step"]:
        raise EvaluationError(
            f"{model_id} boundary mismatch: epoch={epoch}, step={global_step}, "
            f"expected={boundary}"
        )
    result: dict[str, Any] = {
        **dict(file_record),
        "pytorch_lightning_version": checkpoint.get("pytorch-lightning_version"),
        "epoch": epoch,
        "global_step": global_step,
        "epoch_progress": _epoch_progress(checkpoint),
        "state_dict": _state_signature(checkpoint["state_dict"]),
    }
    if model_id in {"formal40", "valbest33"}:
        expected_metadata = {
            "run_id": RUN_ID,
            "source_semantic_sha256": source_semantic_sha256,
            "config_sha256": EXPECTED_HASHES["full_config"],
        }
        if checkpoint.get("audattn_run_metadata_v1") != expected_metadata:
            raise EvaluationError(f"{model_id} run metadata mismatch")
        amp = _amp_audit(checkpoint, global_step)
        logical_completed = global_step // EXPECTED_ATTEMPTS_PER_EPOCH
        if global_step % EXPECTED_ATTEMPTS_PER_EPOCH:
            raise EvaluationError(f"{model_id} is not at an epoch boundary")
        expected_logical = 40 if model_id == "formal40" else 34
        if logical_completed != expected_logical:
            raise EvaluationError(f"{model_id} logical epoch count mismatch")
        if model_id == "formal40" and (
            amp["successful"] != EXPECTED_FORMAL_SUCCESSFUL
            or amp["overflows"] != EXPECTED_FORMAL_OVERFLOWS
        ):
            raise EvaluationError("Formal checkpoint final AMP totals mismatch")
        result.update(
            {
                "run_metadata": expected_metadata,
                "amp": amp,
                "logical_completed_epochs": logical_completed,
            }
        )
        if _epoch_progress(checkpoint) != EXPECTED_EPOCH_PROGRESS[model_id]:
            raise EvaluationError(
                f"{model_id} raw epoch-progress mismatch: "
                f"actual={_epoch_progress(checkpoint)}, "
                f"expected={EXPECTED_EPOCH_PROGRESS[model_id]}"
            )
    else:
        result["external_checkpoint_metadata_policy"] = (
            "exact_file_epoch_step_and_strict_state_only; no selftrain AMP/run metadata"
        )
    return result, checkpoint


def _load_pickle_mapping(
    path: pathlib.Path,
    label: str,
    expected_sha256: str,
) -> dict[Any, Any]:
    with open_pinned_file(path, label, expected_sha256) as pinned:
        mapping = pickle.load(pinned["handle"])
    if not isinstance(mapping, dict):
        raise EvaluationError(f"{label} is not a dictionary")
    return mapping


def _validate_label_map(path: pathlib.Path) -> dict[str, Any]:
    mapping = _load_pickle_mapping(
        path, "800-word label map", EXPECTED_HASHES["label_map"]
    )
    if not isinstance(mapping, dict) or len(mapping) != 800:
        raise EvaluationError("Word label map is not a dictionary of length 800")
    if any(not isinstance(word, str) or not isinstance(index, int) for word, index in mapping.items()):
        raise EvaluationError("Word label map has invalid key/value types")
    if set(mapping.values()) != set(range(800)):
        raise EvaluationError("Word label map is not a bijection onto 0..799")
    return {
        "entries": 800,
        "minimum_label": 0,
        "maximum_label": 799,
        "about": mapping.get("about"),
        "above": mapping.get("above"),
    }


def validate_bank_file(bank_path: pathlib.Path, label_map_path: pathlib.Path) -> dict[str, Any]:
    try:
        import numpy as np
        import pandas as pd
    except ImportError as error:
        raise EvaluationError("pandas and numpy are required to validate the bank") from error
    with open_pinned_file(
        bank_path, "Frozen 10k bank", EXPECTED_HASHES["bank"]
    ) as pinned:
        frame = pd.read_csv(
            pinned["handle"],
            sep="\t",
            dtype={f"{role}_speaker": str for role in ROLE_NAMES},
        )
    required = {
        "trial_id", "bank_seed", "scene_kind", "control_subset",
        "target_speaker", "target_gender", "target_norm", "target_label",
        "distractor_count", "snr_bin", "snr_db", "distractor_1_label",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise EvaluationError(f"Frozen bank is missing columns: {missing}")
    if len(frame) != TOTAL_TRIALS:
        raise EvaluationError(f"Frozen bank row count is not {TOTAL_TRIALS}")
    ids = frame["trial_id"].astype(int).to_numpy()
    if not np.array_equal(np.sort(ids), np.arange(TOTAL_TRIALS)) or len(np.unique(ids)) != TOTAL_TRIALS:
        raise EvaluationError("Frozen bank trial IDs are not unique/contiguous")
    mixed = frame["scene_kind"].astype(str) == "mixed"
    clean = frame["scene_kind"].astype(str) == "clean"
    controls = frame["control_subset"].astype(int) == 1
    if (int(mixed.sum()), int(clean.sum()), int(controls.sum())) != (
        MIXED_TRIALS, CLEAN_TRIALS, CONTROL_TRIALS
    ):
        raise EvaluationError("Frozen bank mixed/clean/control totals mismatch")
    cells = frame.loc[mixed].groupby(["distractor_count", "snr_bin"]).size()
    control_cells = frame.loc[controls].groupby(["distractor_count", "snr_bin"]).size()
    if len(cells) != 20 or set(cells.astype(int)) != {450}:
        raise EvaluationError("Frozen bank does not have 450 trials in each of 20 cells")
    if len(control_cells) != 20 or set(control_cells.astype(int)) != {100}:
        raise EvaluationError("Frozen bank does not have 100 controls in each cell")
    word_to_label = _load_pickle_mapping(
        label_map_path, "800-word label map", EXPECTED_HASHES["label_map"]
    )
    checked_roles = 0
    for role in ROLE_NAMES:
        norm_col = f"{role}_norm"
        label_col = f"{role}_label"
        index_col = f"{role}_index"
        if not {norm_col, label_col, index_col}.issubset(frame.columns):
            raise EvaluationError(f"Frozen bank lacks label-binding fields for {role}")
        active = frame[index_col].astype(int) >= 0
        for norm, label in zip(
            frame.loc[active, norm_col].astype(str),
            frame.loc[active, label_col].astype(int),
            strict=True,
        ):
            if word_to_label.get(norm) != int(label):
                raise EvaluationError(f"Frozen bank label-map mismatch for {role}: {norm}")
        checked_roles += int(active.sum())
    return {
        "trials": TOTAL_TRIALS,
        "mixed_trials": MIXED_TRIALS,
        "clean_trials": CLEAN_TRIALS,
        "control_trials": CONTROL_TRIALS,
        "cells": 20,
        "label_bound_role_rows": checked_roles,
        "target_speakers": int(frame["target_speaker"].nunique()),
        "target_labels": int(frame["target_label"].nunique()),
    }


def read_csv_pinned(
    path: pathlib.Path,
    label: str,
    expected_sha256: str,
    **kwargs: Any,
) -> tuple[Any, dict[str, Any]]:
    try:
        import pandas as pd
    except ImportError as error:
        raise EvaluationError("pandas is required to read frozen tables") from error
    with open_pinned_file(path, label, expected_sha256) as pinned:
        frame = pd.read_csv(pinned["handle"], **kwargs)
        record = {key: value for key, value in pinned.items() if key != "handle"}
    return frame, record


def validate_snr_identity(
    expected_values: Any,
    actual_values: Any,
    scene_kinds: Any,
    *,
    label: str,
    atol: float,
) -> dict[str, Any]:
    """Validate SNR metadata across an explicitly bounded CSV boundary.

    Mixed-trial SNR is finite and scientifically bounded, while clean trials
    use NaN to denote that SNR is not applicable.  ``atol`` is zero for an
    in-memory identity check and ``SNR_IDENTITY_ATOL_DB`` only where a frozen
    CSV serialization/parse boundary is known to exist.
    """
    import numpy as np

    try:
        expected = np.asarray(expected_values, dtype=np.float64)
        actual = np.asarray(actual_values, dtype=np.float64)
        kinds = np.asarray(scene_kinds, dtype=str)
    except (TypeError, ValueError) as error:
        raise EvaluationError(f"{label} SNR identity is not numeric") from error
    if (
        expected.ndim != 1
        or actual.ndim != 1
        or kinds.ndim != 1
        or len(expected) != len(actual)
        or len(expected) != len(kinds)
    ):
        raise EvaluationError(f"{label} SNR identity vectors are not aligned")
    if not math.isfinite(float(atol)) or float(atol) < 0.0:
        raise EvaluationError(f"{label} SNR identity tolerance is invalid")
    mixed = kinds == "mixed"
    clean = kinds == "clean"
    if not bool((mixed | clean).all()):
        raise EvaluationError(f"{label} contains an unknown scene kind")
    if not bool(np.isfinite(expected[mixed]).all()) or not bool(
        np.isfinite(actual[mixed]).all()
    ):
        raise EvaluationError(f"{label} mixed SNR values must both be finite")
    if (
        bool(((expected[mixed] < -10.0) | (expected[mixed] > 10.0)).any())
        or bool(((actual[mixed] < -10.0) | (actual[mixed] > 10.0)).any())
    ):
        raise EvaluationError(f"{label} mixed SNR values escaped [-10, 10] dB")
    if not bool((np.isnan(expected[clean]) & np.isnan(actual[clean])).all()):
        raise EvaluationError(f"{label} clean SNR values must both be NaN")
    differences = np.abs(actual[mixed] - expected[mixed])
    exact_mismatch_count = int(
        np.count_nonzero(actual[mixed] != expected[mixed])
    )
    max_abs = float(differences.max()) if len(differences) else 0.0
    if max_abs > float(atol):
        raise EvaluationError(
            f"{label} SNR identity mismatch: max_abs={max_abs}, atol={atol}"
        )
    report = {
        "mixed_rows": int(mixed.sum()),
        "clean_rows": int(clean.sum()),
        "exact_mismatch_count": exact_mismatch_count,
        "max_abs": max_abs,
        "rtol": 0.0,
        "atol": float(atol),
        "mixed_range_db": [-10.0, 10.0],
        "clean_policy": "both_nan",
    }
    report.update(
        {
            "exact_mismatches": report["exact_mismatch_count"],
            "max_abs_diff": report["max_abs"],
            "tolerance": {"rtol": report["rtol"], "atol": report["atol"]},
            "compared_rows": {
                "mixed": report["mixed_rows"],
                "clean": report["clean_rows"],
            },
        }
    )
    return report


def validate_historical_scene_binding(
    bank: Any,
    historical_results: Any,
) -> dict[str, Any]:
    """Bind current bank identity and raw scene bytes to frozen Job 584990."""
    import numpy as np

    if len(bank) != TOTAL_TRIALS or len(historical_results) != TOTAL_TRIALS:
        raise EvaluationError("Bank/Job584990 results must both contain 10,000 rows")
    required = {
        "trial_id",
        "scene_kind",
        "control_subset",
        "target_speaker",
        "target_gender",
        "target_label",
        "distractor_count",
        "snr_bin",
        "snr_db",
        "probe_distractor_label",
        "scene_sha256",
    }
    missing = sorted(required.difference(historical_results.columns))
    if missing:
        raise EvaluationError(f"Job584990 results lack binding fields: {missing}")
    historical = historical_results.sort_values("trial_id").reset_index(drop=True)
    expected_ids = np.arange(TOTAL_TRIALS)
    if not np.array_equal(historical["trial_id"].astype(int).to_numpy(), expected_ids):
        raise EvaluationError("Job584990 trial IDs are not exactly 0..9999")
    current = bank.sort_values("trial_id").reset_index(drop=True)
    bank_probe = np.where(
        current["scene_kind"].astype(str).to_numpy() == "mixed",
        current["distractor_1_label"].astype(int).to_numpy(),
        0,
    )
    pairs = {
        "scene_kind": current["scene_kind"].astype(str).to_numpy(),
        "control_subset": current["control_subset"].astype(int).to_numpy(),
        "target_speaker": current["target_speaker"].astype(str).to_numpy(),
        "target_gender": current["target_gender"].astype(str).to_numpy(),
        "target_label": current["target_label"].astype(int).to_numpy(),
        "distractor_count": current["distractor_count"].astype(int).to_numpy(),
        "snr_bin": current["snr_bin"].astype(int).to_numpy(),
        "probe_distractor_label": bank_probe,
    }
    for column, expected in pairs.items():
        if not np.array_equal(historical[column].to_numpy(dtype=expected.dtype), expected):
            raise EvaluationError(f"Job584990/bank identity mismatch: {column}")
    snr_identity = validate_snr_identity(
        current["snr_db"].to_numpy(dtype=float),
        historical["snr_db"].to_numpy(dtype=float),
        current["scene_kind"].astype(str).to_numpy(),
        label="Job584990/bank",
        atol=SNR_IDENTITY_ATOL_DB,
    )
    hashes = historical["scene_sha256"].astype(str)
    if not hashes.str.fullmatch(r"[0-9a-f]{64}").all():
        raise EvaluationError("Job584990 scene hashes are not canonical SHA-256")
    return {
        "trials": TOTAL_TRIALS,
        "identity_columns": sorted(pairs) + ["snr_db", "trial_id"],
        "snr_identity": snr_identity,
        "scene_hashes": TOTAL_TRIALS,
        "scene_hash_vector_sha256": hashlib.sha256(
            ("\n".join(hashes.tolist()) + "\n").encode("ascii")
        ).hexdigest(),
    }


def _derive_paths(args: argparse.Namespace) -> dict[str, pathlib.Path]:
    project_root = safe_directory(args.project_root, "Project root")
    run_root = safe_directory(args.run_root, "Run root")
    expected_run_root = (
        project_root / "selftrain" / "experiments" / "runs" / RUN_ID
    ).resolve()
    if run_root != expected_run_root or run_root.name != RUN_ID:
        raise EvaluationError(f"Run root is not the locked run: {run_root}")
    external_root = safe_directory(args.external_root, "External evaluation root")
    if _is_relative_to(external_root, project_root) or _is_relative_to(external_root, run_root):
        raise EvaluationError("External evaluation root must be outside project/run trees")
    snapshot_files = run_root / "snapshot" / "files"
    author_config = pathlib.Path(args.author_config).expanduser() if args.author_config else (
        project_root / "config/binaural_attn/word_task_v10_main_feature_gain_config.yaml"
    )
    author_checkpoint = pathlib.Path(args.author_checkpoint).expanduser() if args.author_checkpoint else (
        project_root
        / "attn_cue_models/word_task_v10_main_feature_gain_config/checkpoints/epoch=1-step=24679-v1.ckpt"
    )
    evaluation_root = run_root / "evaluation" / "pilot4"
    bank = evaluation_root / "frozen_bank.tsv"
    return {
        "project_root": project_root,
        "run_root": run_root,
        "external_root": external_root,
        "snapshot_files": safe_directory(snapshot_files, "Frozen snapshot files"),
        "clips_dir": safe_directory(
            project_root / "cv_train/clips", "Canonical CV clips directory"
        ),
        "source_manifest": run_root / "snapshot/manifest.json",
        "full_config": snapshot_files / "selftrain/configs/full.yaml",
        "label_map": snapshot_files / "cv_800_word_label_to_int_dict.pkl",
        "historical_evaluator": snapshot_files / "selftrain/scripts/eval_full_pilot.py",
        "bank": bank,
        "bank_sha_sidecar": bank.with_suffix(bank.suffix + ".sha256"),
        "bank_metadata": bank.with_suffix(bank.suffix + ".json"),
        "bank_freeze_state": run_root / "state/PILOT4_BANK_FROZEN.json",
        "historical_results": evaluation_root / f"jobs/{PILOT_EVAL_JOB_ID}/per_trial_results.csv",
        "historical_summary": evaluation_root / f"jobs/{PILOT_EVAL_JOB_ID}/PILOT4_EVAL.json",
        "completion": run_root / "state/COMPLETE",
        "completion_recovery": run_root / "state/COMPLETE_RECOVERY.json",
        "formal40": run_root / "full/checkpoints/formal-final.ckpt",
        "valbest33": run_root / "full/checkpoints/epoch=33-step=59024.ckpt",
        "author_config": author_config,
        "author_external": author_checkpoint,
        "recovery_tool": pathlib.Path(args.recovery_tool).expanduser(),
        "sbatch": pathlib.Path(args.sbatch).expanduser(),
        "evaluator": pathlib.Path(__file__).resolve(),
    }


def _validate_config_compatibility(full_config: pathlib.Path, author_config: pathlib.Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as error:
        raise EvaluationError("PyYAML is required to validate configs") from error
    full_bytes, _ = read_pinned_bytes(
        full_config, "Frozen full config", EXPECTED_HASHES["full_config"]
    )
    author_bytes, _ = read_pinned_bytes(
        author_config, "Author native config", EXPECTED_HASHES["author_config"]
    )
    full = yaml.safe_load(full_bytes.decode("utf-8"))
    author = yaml.safe_load(author_bytes.decode("utf-8"))
    if not isinstance(full, dict) or not isinstance(author, dict):
        raise EvaluationError("Model configs are not YAML mappings")
    if full.get("model") != author.get("model"):
        raise EvaluationError("Full and author model architecture configs differ")
    full_audio = copy.deepcopy(full.get("audio", {}))
    author_audio = copy.deepcopy(author.get("audio", {}))
    per_example = full_audio.pop("per_example_leveling", None)
    author_per_example = author_audio.pop("per_example_leveling", None)
    if per_example is not True or author_per_example is not None or full_audio != author_audio:
        raise EvaluationError("Unexpected full/author audio-config relationship")
    if full["model"].get("num_classes", {}).get("num_words") != 800:
        raise EvaluationError("Model output space is not 800 words")
    return {
        "architecture_equal": True,
        "num_words": 800,
        "only_audio_difference": "full enables per_example_leveling; author uses native global transform",
        "comparison_scope": "system_level_external_reference",
    }


def _module_from_verified_source(
    path: pathlib.Path,
    expected_sha256: str,
    module_name: str,
) -> tuple[types.ModuleType, dict[str, Any]]:
    source, record = read_pinned_bytes(path, module_name, expected_sha256)
    module = types.ModuleType(module_name)
    module.__file__ = record["path"]
    module.__package__ = ""
    code = compile(source, record["path"], "exec", dont_inherit=True)
    exec(code, module.__dict__)
    return module, record


def _validate_completion(
    paths: Mapping[str, pathlib.Path],
    formal: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Freshly rerun the exact recovery audit and validate published bytes."""
    recovery_module, tool_record = _module_from_verified_source(
        paths["recovery_tool"],
        EXPECTED_HASHES["recovery_tool"],
        "audattn_verified_completion_recovery",
    )
    required_api = ("audit", "validate_recovery_sidecar", "canonical_json")
    if any(not callable(getattr(recovery_module, name, None)) for name in required_api):
        raise EvaluationError("Verified recovery source does not expose the required API")
    log_dir = paths["project_root"] / "selftrain/hakusan/logs"
    try:
        audit_result = recovery_module.audit(
            paths["run_root"], paths["project_root"], log_dir, FINAL_JOB_ID
        )
    except Exception as error:
        raise EvaluationError(f"Fresh completion-recovery audit failed: {error}") from error
    sidecar_bytes, sidecar_record = read_pinned_bytes(
        paths["completion_recovery"], "Completion recovery sidecar"
    )
    try:
        sidecar = json.loads(sidecar_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError("Completion recovery sidecar is not valid JSON") from error
    if not isinstance(sidecar, dict):
        raise EvaluationError("Completion recovery sidecar is not a JSON object")
    try:
        planned, expected_complete_bytes = recovery_module.validate_recovery_sidecar(
            sidecar, audit_result, pathlib.Path(tool_record["path"])
        )
    except Exception as error:
        raise EvaluationError(f"Fresh recovery-sidecar validation failed: {error}") from error
    actual_complete_bytes, complete_record = read_pinned_bytes(
        paths["completion"], "Recovered COMPLETE"
    )
    if actual_complete_bytes != expected_complete_bytes:
        raise EvaluationError(
            "Recovered COMPLETE bytes differ from fresh validate_recovery_sidecar output"
        )
    if planned != json.loads(actual_complete_bytes.decode("utf-8")):
        raise EvaluationError("Fresh planned COMPLETE payload differs from published payload")
    tool_after = pinned_file(
        paths["recovery_tool"],
        "Recovery tool after fresh validation",
        tool_record["sha256"],
    )
    if tool_after != tool_record:
        raise EvaluationError("Recovery tool identity changed during fresh validation")
    fresh_checkpoint = audit_result.get("checkpoint", {})
    if (
        fresh_checkpoint.get("sha256") != formal["sha256"]
        or int(fresh_checkpoint.get("epoch", -1)) != 40
        or int(fresh_checkpoint.get("global_step", -1)) != 69440
        or fresh_checkpoint.get("epoch_progress") != EXPECTED_EPOCH_PROGRESS["formal40"]
    ):
        raise EvaluationError("Fresh recovery audit checkpoint differs from formal40")
    completion = {
        "complete": complete_record,
        "recovery": sidecar_record,
        "recovery_tool": tool_record,
        "fresh_audit_sha256": hashlib.sha256(
            recovery_module.canonical_json(audit_result)
        ).hexdigest(),
        "logical_completed_epochs": 40,
        "raw_total_completed": 38,
    }
    return completion, audit_result


def _validate_historical_bank_records(paths: Mapping[str, pathlib.Path]) -> dict[str, Any]:
    freeze_record = pinned_file(paths["bank_freeze_state"], "Pilot bank freeze state")
    bank_record = read_json(
        paths["bank_freeze_state"],
        "Pilot bank freeze state",
        freeze_record["sha256"],
    )
    expected_bank = {
        "schema_version": 1,
        "status": "FROZEN_BEFORE_PILOT_TRAINING",
        "bank": str(paths["bank"].resolve()),
        "bank_sha256": EXPECTED_HASHES["bank"],
        "bank_seed": 20260816,
        "config_sha256": EXPECTED_HASHES["full_config"],
        "source_semantic_sha256": EXPECTED_HASHES["source_semantic"],
        "evaluator_sha256": EXPECTED_HASHES["historical_evaluator"],
        "global_step_before_training": 0,
    }
    mismatches = {
        key: (bank_record.get(key), value)
        for key, value in expected_bank.items()
        if bank_record.get(key) != value
    }
    if mismatches:
        raise EvaluationError(f"Historical bank freeze-state mismatch: {mismatches}")
    summary = read_json(
        paths["historical_summary"],
        "Job 584990 summary",
        EXPECTED_HASHES["historical_summary"],
    )
    if summary.get("engineering_status") != "PASS" or summary.get("decision") != "GO":
        raise EvaluationError("Historical Job 584990 summary is not PASS/GO")
    if summary.get("frozen_inputs", {}).get("results_sha256") != EXPECTED_HASHES["historical_results"]:
        raise EvaluationError("Historical summary does not bind the expected results")
    return {
        "freeze_state": freeze_record,
        "job584990_results": pinned_file(
            paths["historical_results"],
            "Job 584990 results",
            EXPECTED_HASHES["historical_results"],
        ),
        "job584990_summary": pinned_file(
            paths["historical_summary"],
            "Job 584990 summary",
            EXPECTED_HASHES["historical_summary"],
        ),
    }


_EPOCH_METRIC_PATTERN = re.compile(
    rb"Epoch (?P<epoch>\d+): 100%[^\n]*?"
    rb"val_loss_epoch=(?P<val_loss>[0-9.]+), val_acc=(?P<val_acc>[0-9.]+), "
    rb"train_loss_epoch=(?P<train_loss>[0-9.]+), train_acc=(?P<train_acc>[0-9.]+)"
    rb"[^\n]*?AMP epoch summary: epoch=(?P=epoch), "
    rb"epoch_overflows=(?P<epoch_overflows>\d+), "
    rb"epoch_attempts=(?P<epoch_attempts>\d+), "
    rb"epoch_successful_steps=(?P<epoch_successful>\d+), "
    rb"total_overflows=(?P<total_overflows>\d+), "
    rb"total_attempts=(?P<total_attempts>\d+), "
    rb"total_successful_steps=(?P<total_successful>\d+)"
)


def _extract_epoch_metrics(
    path: pathlib.Path,
    expected_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open_pinned_file(path, f"Training log {path.name}", expected_sha256) as pinned:
        carry = b""
        while True:
            chunk = pinned["handle"].read(1024 * 1024)
            if not chunk:
                break
            normalized = (carry + chunk).replace(b"\r", b"\n")
            lines = normalized.split(b"\n")
            carry = lines.pop()
            for line in lines:
                match = _EPOCH_METRIC_PATTERN.search(line)
                if match:
                    values = match.groupdict()
                    rows.append(
                        {
                            "epoch": int(values["epoch"]),
                            "val_loss": float(values["val_loss"]),
                            "val_acc": float(values["val_acc"]),
                            "train_loss": float(values["train_loss"]),
                            "train_acc": float(values["train_acc"]),
                            **{
                                key: int(values[key])
                                for key in (
                                    "epoch_overflows",
                                    "epoch_attempts",
                                    "epoch_successful",
                                    "total_overflows",
                                    "total_attempts",
                                    "total_successful",
                                )
                            },
                        }
                    )
        match = _EPOCH_METRIC_PATTERN.search(carry.replace(b"\r", b"\n"))
        if match:
            values = match.groupdict()
            rows.append(
                {
                    "epoch": int(values["epoch"]),
                    "val_loss": float(values["val_loss"]),
                    "val_acc": float(values["val_acc"]),
                    "train_loss": float(values["train_loss"]),
                    "train_acc": float(values["train_acc"]),
                    **{
                        key: int(values[key])
                        for key in (
                            "epoch_overflows",
                            "epoch_attempts",
                            "epoch_successful",
                            "total_overflows",
                            "total_attempts",
                            "total_successful",
                        )
                    },
                }
            )
        record = {key: value for key, value in pinned.items() if key != "handle"}
    return rows, record


def _validate_valbest_selection(
    recovery_audit: Mapping[str, Any],
    valbest: Mapping[str, Any],
) -> dict[str, Any]:
    jobs = recovery_audit.get("lineage", {}).get("jobs", {})
    if not isinstance(jobs, dict) or set(jobs) != {"575142", "587802", "614647", "628071"}:
        raise EvaluationError("Fresh recovery lineage does not contain the four locked jobs")
    rows: list[dict[str, Any]] = []
    logs: dict[str, Any] = {}
    for job_id in ("575142", "587802", "614647", "628071"):
        log = jobs[job_id].get("log", {})
        if not isinstance(log, dict):
            raise EvaluationError(f"Fresh recovery lineage has no log for Job {job_id}")
        parsed, record = _extract_epoch_metrics(
            pathlib.Path(str(log.get("path", ""))), str(log.get("sha256", ""))
        )
        if int(log.get("size", -1)) != int(record["size"]):
            raise EvaluationError(f"Training log size mismatch for Job {job_id}")
        rows.extend(parsed)
        logs[job_id] = record
    if len(rows) != 40 or [row["epoch"] for row in rows] != list(range(40)):
        raise EvaluationError("Metric-bearing AMP summaries are not exactly epochs 0..39")
    best_accuracy = max(row["val_acc"] for row in rows)
    winners = [row for row in rows if row["val_acc"] == best_accuracy]
    if len(winners) != 1 or winners[0]["epoch"] != 33 or best_accuracy != 0.453:
        raise EvaluationError(
            f"Validation-selected checkpoint evidence changed: winners={winners}"
        )
    epoch33 = winners[0]
    amp = valbest.get("amp", {})
    if (
        epoch33["total_attempts"] != int(amp.get("attempts", -1))
        or epoch33["total_successful"] != int(amp.get("successful", -1))
        or epoch33["total_overflows"] != int(amp.get("overflows", -1))
    ):
        raise EvaluationError("Epoch33 checkpoint AMP totals differ from bound log")
    return {
        "selection_rule": "unique maximum logged val_acc over epochs 0..39",
        "selected_epoch": 33,
        "selected_val_acc": 0.453,
        "selected_val_loss": epoch33["val_loss"],
        "epoch33_amp": {
            "attempts": epoch33["total_attempts"],
            "successful": epoch33["total_successful"],
            "overflows": epoch33["total_overflows"],
        },
        "metric_rows": 40,
        "logs": logs,
    }


def _scalar_float(value: Any, label: str) -> float:
    if hasattr(value, "detach") and hasattr(value, "numel"):
        if int(value.numel()) != 1:
            raise EvaluationError(f"{label} is not scalar")
        value = value.detach().cpu().item()
    result = float(value)
    if not math.isfinite(result):
        raise EvaluationError(f"{label} is not finite")
    return result


def _validate_valbest_callback(
    formal_checkpoint: Mapping[str, Any],
    paths: Mapping[str, pathlib.Path],
    valbest: Mapping[str, Any],
) -> dict[str, Any]:
    callbacks = formal_checkpoint.get("callbacks")
    if not isinstance(callbacks, Mapping):
        raise EvaluationError("Formal checkpoint has no callback state")
    candidates: list[tuple[str, Mapping[str, Any]]] = []
    for key, state_value in callbacks.items():
        if "ModelCheckpoint" not in str(key) or not isinstance(state_value, Mapping):
            continue
        best_path = str(state_value.get("best_model_path", ""))
        best_score = state_value.get("best_model_score")
        if best_path.endswith("/epoch=33-step=59024.ckpt") and best_score is not None:
            candidates.append((str(key), state_value))
    if len(candidates) != 1:
        raise EvaluationError(
            "Formal checkpoint does not uniquely bind the epoch33 ModelCheckpoint state"
        )
    callback_key, state_value = candidates[0]
    if "'monitor': 'val_acc'" not in callback_key or "'mode': 'max'" not in callback_key:
        raise EvaluationError(
            f"Epoch33 checkpoint callback is not val_acc/max: {callback_key}"
        )
    best_path = _absolute_no_resolve(str(state_value["best_model_path"]))
    if best_path != paths["valbest33"]:
        raise EvaluationError(
            f"ModelCheckpoint best path mismatch: {best_path} != {paths['valbest33']}"
        )
    best_score = _scalar_float(state_value["best_model_score"], "best_model_score")
    if not math.isclose(best_score, 0.453, rel_tol=0.0, abs_tol=5e-4):
        raise EvaluationError(f"Unexpected epoch33 best val_acc: {best_score}")
    best_k = state_value.get("best_k_models")
    if not isinstance(best_k, Mapping) or str(paths["valbest33"]) not in {
        str(path) for path in best_k
    }:
        raise EvaluationError("ModelCheckpoint best_k_models does not contain epoch33")
    best_k_score = next(
        _scalar_float(score, "best_k_models epoch33 score")
        for path, score in best_k.items()
        if str(path) == str(paths["valbest33"])
    )
    if not math.isclose(best_k_score, best_score, rel_tol=0.0, abs_tol=1e-12):
        raise EvaluationError("ModelCheckpoint best score disagrees with best_k_models")
    if valbest.get("basename") != paths["valbest33"].name:
        raise EvaluationError("Validation-selected checkpoint basename mismatch")
    return {
        "selection_rule": "formal checkpoint ModelCheckpoint best val_acc (mode=max)",
        "callback_key": callback_key,
        "monitor": "val_acc",
        "mode": "max",
        "best_model_path": str(best_path),
        "best_model_score": best_score,
        "best_k_models": {str(best_path): best_k_score},
        "selected_checkpoint_sha256": valbest["sha256"],
        "selected_checkpoint_epoch": valbest["epoch"],
        "selected_checkpoint_global_step": valbest["global_step"],
        "selected_checkpoint_amp": valbest["amp"],
    }


def audit_inputs(args: argparse.Namespace) -> dict[str, Any]:
    paths = _derive_paths(args)
    expected_valbest = _require_sha(args.expected_valbest_sha256, "Expected valbest SHA")
    if expected_valbest != EXPECTED_HASHES["valbest33"]:
        raise EvaluationError(
            "Expected valbest SHA must equal the independently inventoried locked digest"
        )
    source_manifest_file = pinned_file(paths["source_manifest"], "Frozen source manifest")
    source_manifest = read_json(
        paths["source_manifest"],
        "Frozen source manifest",
        source_manifest_file["sha256"],
    )
    if source_manifest.get("semantic_combined_sha256") != EXPECTED_HASHES["source_semantic"]:
        raise EvaluationError("Frozen source semantic SHA mismatch")

    input_files = {
        "full_config": pinned_file(paths["full_config"], "Frozen full config", EXPECTED_HASHES["full_config"]),
        "author_config": pinned_file(paths["author_config"], "Author native config", EXPECTED_HASHES["author_config"]),
        "label_map": pinned_file(paths["label_map"], "800-word label map", EXPECTED_HASHES["label_map"]),
        "bank": pinned_file(paths["bank"], "Frozen 10k bank", EXPECTED_HASHES["bank"]),
        "bank_sha_sidecar": pinned_file(paths["bank_sha_sidecar"], "Bank SHA sidecar"),
        "bank_metadata": pinned_file(paths["bank_metadata"], "Bank metadata"),
        "historical_evaluator": pinned_file(
            paths["historical_evaluator"], "Historical frozen evaluator", EXPECTED_HASHES["historical_evaluator"]
        ),
        "source_manifest": source_manifest_file,
        "recovery_tool": pinned_file(paths["recovery_tool"], "Recovery tool", EXPECTED_HASHES["recovery_tool"]),
        "sbatch": pinned_file(paths["sbatch"], "Same-bank Slurm launcher"),
        "evaluator": pinned_file(paths["evaluator"], "Locked same-bank evaluator"),
    }
    label_audit = _validate_label_map(paths["label_map"])
    config_audit = _validate_config_compatibility(paths["full_config"], paths["author_config"])
    bank_audit = validate_bank_file(paths["bank"], paths["label_map"])
    sidecar_bytes, _ = read_pinned_bytes(
        paths["bank_sha_sidecar"],
        "Bank SHA sidecar",
        input_files["bank_sha_sidecar"]["sha256"],
    )
    recorded_bank_sha, recorded_bank_name = sidecar_bytes.decode("utf-8").split()
    if (recorded_bank_sha, recorded_bank_name) != (EXPECTED_HASHES["bank"], paths["bank"].name):
        raise EvaluationError("Frozen bank SHA sidecar is stale")
    bank_metadata = read_json(
        paths["bank_metadata"],
        "Frozen bank metadata",
        input_files["bank_metadata"]["sha256"],
    )
    if (
        bank_metadata.get("manifest_sha256") != EXPECTED_HASHES["bank"]
        or bank_metadata.get("config_sha256") != EXPECTED_HASHES["full_config"]
        or int(bank_metadata.get("trials", -1)) != TOTAL_TRIALS
    ):
        raise EvaluationError("Frozen bank metadata mismatch")

    checkpoint_files = {
        "formal40": pinned_file(paths["formal40"], "Formal final checkpoint", EXPECTED_HASHES["formal40"]),
        "valbest33": pinned_file(paths["valbest33"], "Validation-selected checkpoint", expected_valbest),
        "author_external": pinned_file(
            paths["author_external"], "Author external checkpoint", EXPECTED_HASHES["author_external"]
        ),
    }
    models: dict[str, Any] = {}
    formal_payload: dict[str, Any] | None = None
    try:
        for model_id in MODEL_IDS:
            record, payload = inspect_checkpoint(
                checkpoint_files[model_id], model_id, EXPECTED_HASHES["source_semantic"]
            )
            record["role"] = MODEL_ROLES[model_id]
            record["config_key"] = "author_config" if model_id == "author_external" else "full_config"
            models[model_id] = record
            if model_id == "formal40":
                formal_payload = payload
            else:
                del payload
                gc.collect()
        if formal_payload is None:
            raise EvaluationError("Formal checkpoint payload was not inspected")
        callback_selection = _validate_valbest_callback(
            formal_payload, paths, models["valbest33"]
        )
        completion, recovery_audit = _validate_completion(
            paths, models["formal40"]
        )
        log_selection = _validate_valbest_selection(
            recovery_audit, models["valbest33"]
        )
        selection = {
            "status": "DUAL_EVIDENCE_PASS",
            "callback": callback_selection,
            "training_logs": log_selection,
        }
    finally:
        formal_payload = None
        gc.collect()
    historical = _validate_historical_bank_records(paths)
    bank_frame, _ = read_csv_pinned(
        paths["bank"],
        "Frozen 10k bank",
        EXPECTED_HASHES["bank"],
        sep="\t",
        dtype={f"{role}_speaker": str for role in ROLE_NAMES},
    )
    historical_frame, _ = read_csv_pinned(
        paths["historical_results"],
        "Job584990 per-trial results",
        EXPECTED_HASHES["historical_results"],
        dtype={"target_speaker": str},
    )
    historical_scene_binding = validate_historical_scene_binding(
        bank_frame, historical_frame
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "filesystem_identity_policy": FILESYSTEM_IDENTITY_POLICY,
        "status": "AUDIT_PASS",
        "run_id": RUN_ID,
        "role_confirmation": EXPECTED_ROLE_CONFIRMATION,
        "evaluation_role": EVALUATION_ROLE,
        "comparison_scope": (
            "same frozen validation/pilot bank; author is a system-level external reference, not a task-matched ranking"
        ),
        "roots": {
            "project_root": str(paths["project_root"]),
            "run_root": str(paths["run_root"]),
            "external_root": str(paths["external_root"]),
            "snapshot_files": str(paths["snapshot_files"]),
            "clips_dir": str(paths["clips_dir"]),
        },
        "inputs": input_files,
        "models": models,
        "completion": completion,
        "historical_evidence": historical,
        "checkpoint_selection": selection,
        "audits": {
            "source_semantic_sha256": EXPECTED_HASHES["source_semantic"],
            "label_map": label_audit,
            "config_compatibility": config_audit,
            "bank": bank_audit,
            "job584990_scene_binding": historical_scene_binding,
            "fresh_recovery_status": recovery_audit.get("status"),
        },
    }
    validate_protocol_boundary(manifest, "Audited input manifest")
    validate_role_manifest(manifest)
    return manifest


def _validate_manifest_hash(path: pathlib.Path, expected_sha256: str) -> tuple[dict[str, Any], str]:
    expected = _require_sha(expected_sha256, "Expected manifest SHA")
    record = pinned_file(path, "Frozen same-bank input manifest", expected)
    manifest = read_json(path, "Frozen same-bank input manifest", expected)
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("status") != "FROZEN":
        raise EvaluationError("Input manifest is not a frozen schema-v1 manifest")
    validate_protocol_boundary(manifest, "Frozen input manifest")
    validate_role_manifest(manifest)
    return manifest, record["sha256"]


def verify_frozen_manifest(
    manifest: Mapping[str, Any],
    external_root: pathlib.Path,
) -> dict[str, Any]:
    validate_protocol_boundary(manifest, "Frozen input manifest")
    roots = manifest.get("roots")
    if not isinstance(roots, dict):
        raise EvaluationError("Manifest has no roots mapping")
    frozen_external = safe_directory(
        pathlib.Path(str(roots.get("external_root", ""))),
        "Frozen external root",
    )
    if frozen_external != external_root:
        raise EvaluationError("Requested external root differs from frozen root")
    verified: dict[str, Any] = {}
    identity_diagnostics: dict[str, Any] = {}

    def walk(value: Any, prefix: str) -> None:
        if isinstance(value, Mapping) and {"path", "size", "sha256"}.issubset(value):
            current = pinned_file(
                value["path"], f"Frozen {prefix}", str(value["sha256"])
            )
            identity_diagnostics[prefix] = validate_persistent_file_identity(
                value,
                current,
                f"Frozen {prefix}",
            )
            verified[prefix] = current
            return
        if isinstance(value, Mapping):
            for key, child in value.items():
                walk(child, f"{prefix}.{key}" if prefix else str(key))

    for group_name in (
        "inputs",
        "historical_evidence",
        "completion",
        "models",
        "checkpoint_selection",
    ):
        group = manifest.get(group_name)
        if not isinstance(group, Mapping):
            raise EvaluationError(f"Manifest has no {group_name}")
        walk(group, group_name)
    if not all(f"models.{model_id}" in verified for model_id in MODEL_IDS):
        raise EvaluationError("Manifest did not verify all three model files")
    live_evaluator = safe_file(__file__, "Running same-bank evaluator")
    if pathlib.Path(manifest["inputs"]["evaluator"]["path"]) != live_evaluator:
        raise EvaluationError("Running evaluator path differs from frozen evaluator path")
    if live_evaluator != external_root / "tools/locked_same_bank_eval.py":
        raise EvaluationError("Running evaluator is not at the canonical external tool path")
    if pathlib.Path(manifest["inputs"]["sbatch"]["path"]) != (
        external_root / "tools/run_locked_same_bank_eval.sbatch"
    ):
        raise EvaluationError("Frozen Slurm runner is not at its canonical external path")

    fresh_paths = {
        "project_root": safe_directory(roots["project_root"], "Frozen project root"),
        "run_root": safe_directory(roots["run_root"], "Frozen run root"),
        "recovery_tool": pathlib.Path(manifest["inputs"]["recovery_tool"]["path"]),
        "completion": pathlib.Path(manifest["completion"]["complete"]["path"]),
        "completion_recovery": pathlib.Path(manifest["completion"]["recovery"]["path"]),
    }
    fresh_completion, fresh_audit = _validate_completion(
        fresh_paths, manifest["models"]["formal40"]
    )
    for name in ("complete", "recovery", "recovery_tool"):
        if fresh_completion[name]["sha256"] != manifest["completion"][name]["sha256"]:
            raise EvaluationError(f"Fresh recovery evidence changed: completion.{name}")
    if fresh_completion["fresh_audit_sha256"] != manifest["completion"]["fresh_audit_sha256"]:
        raise EvaluationError("Fresh recovery audit digest differs from frozen manifest")
    return {
        "verified_files": len(verified),
        "files": verified,
        "filesystem_identity_policy": FILESYSTEM_IDENTITY_POLICY,
        "filesystem_identity_diagnostics": identity_diagnostics,
        "fresh_recovery_status": fresh_audit.get("status"),
        "fresh_recovery_audit_sha256": fresh_completion["fresh_audit_sha256"],
    }


def canonicalize_state_dict_keys(
    actual: Mapping[str, Any],
    expected_keys: Iterable[str],
    allow_compile_wrapper_rewrite: bool,
) -> tuple[dict[str, Any], str]:
    expected = set(expected_keys)
    if set(actual) == expected:
        return dict(actual), "exact"
    if not allow_compile_wrapper_rewrite:
        raise EvaluationError(
            "Strict state_dict key mismatch; wrapper rewrite is forbidden for selftrain models"
        )

    def remove_wrapper(key: str) -> str:
        prefix = "model._orig_mod."
        return "model." + key[len(prefix):] if key.startswith(prefix) else key

    def add_wrapper(key: str) -> str:
        prefix = "model."
        return "model._orig_mod." + key[len(prefix):] if key.startswith(prefix) and not key.startswith("model._orig_mod.") else key

    candidates: list[tuple[dict[str, Any], str]] = []
    for transform, name in (
        (remove_wrapper, "remove_model._orig_mod"),
        (add_wrapper, "add_model._orig_mod"),
    ):
        model_keys = [key for key in actual if key.startswith("model.")]
        if name.startswith("remove_") and (
            not model_keys
            or any(not key.startswith("model._orig_mod.") for key in model_keys)
        ):
            continue
        if name.startswith("add_") and (
            not model_keys
            or any(key.startswith("model._orig_mod.") for key in model_keys)
        ):
            continue
        mapped: dict[str, Any] = {}
        collision = False
        for key, value in actual.items():
            new_key = transform(key)
            if new_key in mapped:
                collision = True
                break
            mapped[new_key] = value
        if not collision and set(mapped) == expected:
            candidates.append((mapped, name))
    if len(candidates) != 1:
        raise EvaluationError(
            "Author state_dict cannot be mapped uniquely by the sole allowed compile-wrapper rewrite"
        )
    return candidates[0]


def audit_state_dict_compatibility(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
    allow_compile_wrapper_rewrite: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    mapped, rule = canonicalize_state_dict_keys(
        actual, expected.keys(), allow_compile_wrapper_rewrite
    )
    shape_mismatches: dict[str, Any] = {}
    dtype_mismatches: dict[str, Any] = {}
    for key in expected:
        actual_value = mapped[key]
        expected_value = expected[key]
        if tuple(actual_value.shape) != tuple(expected_value.shape):
            shape_mismatches[key] = [list(actual_value.shape), list(expected_value.shape)]
        if actual_value.dtype != expected_value.dtype:
            dtype_mismatches[key] = [str(actual_value.dtype), str(expected_value.dtype)]
    if shape_mismatches or dtype_mismatches:
        raise EvaluationError(
            f"state_dict incompatibility: shapes={shape_mismatches}, dtypes={dtype_mismatches}"
        )
    return mapped, {
        "key_count": len(mapped),
        "missing_keys": [],
        "unexpected_keys": [],
        "shape_mismatches": {},
        "dtype_mismatches": {},
        "prefix_rule": rule,
    }


@contextlib.contextmanager
def _frozen_import_context(snapshot_files: pathlib.Path):
    snapshot_files = safe_directory(snapshot_files, "Frozen snapshot import root")
    original_path = list(sys.path)
    original_cwd = pathlib.Path.cwd()
    protected_prefixes = ("src", "selftrain")
    saved_modules = {
        name: module
        for name, module in list(sys.modules.items())
        if name == protected_prefixes[0]
        or name.startswith("src.")
        or name == protected_prefixes[1]
        or name.startswith("selftrain.")
    }
    for name in saved_modules:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(snapshot_files))
    os.chdir(snapshot_files)
    try:
        yield
    finally:
        for name in list(sys.modules):
            if (
                name == "src"
                or name.startswith("src.")
                or name == "selftrain"
                or name.startswith("selftrain.")
            ):
                sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
        os.chdir(original_cwd)
        sys.path[:] = original_path


def _read_yaml(
    path: pathlib.Path,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    import yaml

    payload, _ = read_pinned_bytes(path, f"YAML config {path.name}", expected_sha256)
    value = yaml.safe_load(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise EvaluationError(f"YAML config is not a mapping: {path}")
    return value


def _all_state_finite(state_dict: Mapping[str, Any], model_id: str) -> None:
    import torch

    for key, value in state_dict.items():
        if (torch.is_floating_point(value) or torch.is_complex(value)) and not bool(torch.isfinite(value).all()):
            raise EvaluationError(f"Non-finite state tensor in {model_id}: {key}")


def strict_load_model(
    manifest: Mapping[str, Any],
    model_id: str,
    device: Any | None = None,
) -> tuple[Any, dict[str, Any]]:
    roots = manifest["roots"]
    snapshot_files = pathlib.Path(roots["snapshot_files"])
    config_key = manifest["models"][model_id]["config_key"]
    config_path = pathlib.Path(manifest["inputs"][config_key]["path"])
    checkpoint_path = pathlib.Path(manifest["models"][model_id]["path"])
    config = _read_yaml(config_path, manifest["inputs"][config_key]["sha256"])
    checkpoint = _load_torch_checkpoint(
        checkpoint_path, manifest["models"][model_id]["sha256"]
    )
    state_dict = checkpoint["state_dict"]
    _all_state_finite(state_dict, model_id)
    with _frozen_import_context(snapshot_files):
        import src.spatial_attn_lightning as model_module

        module_path = safe_file(
            inspect.getfile(model_module), "Imported frozen model module"
        )
        if not _is_relative_to(module_path, snapshot_files):
            raise EvaluationError(
                f"Model module escaped frozen snapshot: {module_path}"
            )
        BinauralAttentionModule = model_module.BinauralAttentionModule

        model = BinauralAttentionModule(config=config)
    expected_state = model.state_dict()
    mapped_state, report = audit_state_dict_compatibility(
        state_dict,
        expected_state,
        allow_compile_wrapper_rewrite=(model_id == "author_external"),
    )
    incompatible = model.load_state_dict(mapped_state, strict=True)
    if incompatible.missing_keys or incompatible.unexpected_keys:
        raise EvaluationError(f"Strict load returned incompatible keys for {model_id}")
    if model_id in {"formal40", "valbest33"}:
        model.on_load_checkpoint(checkpoint)
    trainable_keys = {name for name, _ in model.named_parameters()}
    loaded_trainable = trainable_keys.intersection(mapped_state)
    if loaded_trainable != trainable_keys:
        raise EvaluationError(f"Not every trainable parameter loaded for {model_id}")
    trainable_numel = sum(parameter.numel() for _, parameter in model.named_parameters())
    loaded_numel = sum(expected_state[key].numel() for key in loaded_trainable)
    report.update(
        {
            "loaded_trainable_numel": int(loaded_numel),
            "trainable_numel": int(trainable_numel),
            "loaded_trainable_numel_ratio": float(loaded_numel / trainable_numel),
            "native_preprocessing": (
                "author_singleton_native_global_rms"
                if model_id == "author_external"
                else "selftrain_singleton_per_example_leveling"
            ),
            "model_module": pinned_file(
                module_path, "Imported frozen model module"
            ),
        }
    )
    del checkpoint, state_dict, mapped_state, expected_state
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    if device is not None:
        model.to(device)
    return model, report


def check_only(args: argparse.Namespace) -> dict[str, Any]:
    external_root = safe_directory(args.external_root, "External evaluation root")
    manifest_path = safe_file(args.manifest, "Frozen input manifest")
    if not _is_relative_to(manifest_path, external_root):
        raise EvaluationError("Manifest must be inside the external evaluation root")
    manifest, manifest_sha = _validate_manifest_hash(
        manifest_path, args.expected_manifest_sha256
    )
    layout = validate_frozen_layout(external_root, manifest)
    verification = verify_frozen_manifest(manifest, external_root)
    load_reports: dict[str, Any] = {}
    for model_id in MODEL_IDS:
        model, report = strict_load_model(manifest, model_id)
        load_reports[model_id] = report
        del model
        gc.collect()
    publications: dict[str, Any] = {}
    for marker_name in ("SMOKE_PASS.json", "SAME_BANK_AUDIT_PUBLISHED.json"):
        marker_path = external_root / "state" / marker_name
        if os.path.lexists(marker_path):
            publications[marker_name] = verify_publication_marker(
                external_root, marker_name, manifest_sha
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "filesystem_identity_policy": FILESYSTEM_IDENTITY_POLICY,
        "status": "CHECK_PASS",
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "verification": verification,
        "layout": layout,
        "strict_loads": load_reports,
        "publications": publications,
    }


def singleton_native_preprocess(model: Any, raw_batch: Any) -> Any:
    """Apply a model's native waveform transform independently per trial."""
    import torch

    transformed = []
    for waveform in raw_batch:
        value, background = model.audio_transforms(waveform, None)
        if background is not None or value is None or value.ndim != 2:
            raise EvaluationError("Native singleton preprocessing returned an invalid shape")
        transformed.append(value)
    result = torch.stack(transformed, dim=0)
    if result.shape != raw_batch.shape or not bool(torch.isfinite(result).all()):
        raise EvaluationError("Native singleton preprocessing produced invalid output")
    return result


def predict_batch(
    model: Any,
    raw_scene: Any,
    raw_cue: Any,
    labels: Any,
    probe_labels: Any,
    device: Any,
) -> dict[str, Any]:
    import torch

    normalized_scene = singleton_native_preprocess(model, raw_scene)
    normalized_cue = singleton_native_preprocess(model, raw_cue)
    labels_device = labels.to(device, non_blocking=True)
    probes_device = probe_labels.to(device, non_blocking=True)
    with torch.inference_mode():
        with torch.autocast(
            device_type=device.type,
            dtype=torch.float16 if device.type == "cuda" else torch.bfloat16,
            enabled=device.type == "cuda",
        ):
            scene_features, _ = model.coch_gram.full_rep(
                normalized_scene.to(device, non_blocking=True), None
            )
            cue_features, _ = model.coch_gram.full_rep(
                normalized_cue.to(device, non_blocking=True), None
            )
            logits = model(cue_features, scene_features, None)
            if logits.ndim != 2 or int(logits.shape[1]) != 800:
                raise EvaluationError(
                    f"Model output is not [batch, 800]: shape={tuple(logits.shape)}"
                )
            log_probabilities = logits.float().log_softmax(dim=-1)
            probabilities = log_probabilities.exp()
            predicted = probabilities.argmax(dim=-1)
            nll = -log_probabilities.gather(1, labels_device[:, None]).squeeze(1)
            p_target = probabilities.gather(1, labels_device[:, None]).squeeze(1)
            p_probe = probabilities.gather(1, probes_device[:, None]).squeeze(1)
    tensors = (logits, nll, p_target, p_probe)
    if not all(bool(torch.isfinite(value).all()) for value in tensors):
        raise EvaluationError("Non-finite inference output")
    return {
        "pred_label": predicted.cpu().numpy(),
        "nll": nll.cpu().numpy(),
        "p_target": p_target.cpu().numpy(),
        "p_probe_distractor": p_probe.cpu().numpy(),
    }


def cluster_bootstrap_ci(
    values: Any,
    speakers: Any,
    seed: int,
    repetitions: int,
) -> tuple[float, float]:
    import numpy as np

    values = np.asarray(values, dtype=np.float64)
    raw_speakers = np.asarray(speakers, dtype=object)
    if (
        values.ndim != 1
        or raw_speakers.ndim != 1
        or len(values) != len(raw_speakers)
        or not len(values)
    ):
        raise EvaluationError("Cluster bootstrap inputs must be nonempty aligned vectors")
    if repetitions <= 0 or not np.isfinite(values).all():
        raise EvaluationError("Invalid cluster bootstrap input")
    normalized_speakers: list[str] = []
    for speaker in raw_speakers:
        if speaker is None or (
            isinstance(speaker, (float, np.floating)) and not np.isfinite(speaker)
        ):
            raise EvaluationError("Cluster bootstrap speaker IDs must not be missing")
        normalized = str(speaker)
        if not normalized.strip() or normalized.lower() in {"nan", "none"}:
            raise EvaluationError("Cluster bootstrap speaker IDs must not be empty")
        normalized_speakers.append(normalized)
    speakers = np.asarray(normalized_speakers, dtype=str)
    unique, inverse = np.unique(speakers, return_inverse=True)
    if len(unique) < 2:
        raise EvaluationError("Cluster bootstrap needs at least two speaker clusters")
    sums = np.bincount(inverse, weights=values)
    counts = np.bincount(inverse)
    rng = np.random.default_rng(seed)
    draws = np.empty(repetitions, dtype=np.float64)
    for index in range(repetitions):
        sampled = rng.integers(0, len(unique), size=len(unique))
        draws[index] = sums[sampled].sum() / counts[sampled].sum()
    low, high = np.quantile(draws, [0.025, 0.975], method="linear")
    return float(low), float(high)


def _paired_summary(
    values: Any,
    speakers: Any,
    seed: int,
    *,
    bootstrap: bool = True,
) -> dict[str, Any]:
    import numpy as np

    values = np.asarray(values, dtype=np.float64)
    speakers = np.asarray(speakers, dtype=object)
    if values.ndim != 1 or speakers.ndim != 1 or len(values) != len(speakers):
        raise EvaluationError("Paired summary requires aligned one-dimensional vectors")
    if not len(values) or not np.isfinite(values).all():
        raise EvaluationError("Paired summary requires finite nonempty values")
    normalized_speakers: list[str] = []
    for speaker in speakers:
        if speaker is None or (
            isinstance(speaker, (float, np.floating)) and not np.isfinite(speaker)
        ):
            raise EvaluationError("Paired summary speaker IDs must not be missing")
        normalized = str(speaker)
        if not normalized.strip() or normalized.lower() in {"nan", "none"}:
            raise EvaluationError("Paired summary speaker IDs must not be empty")
        normalized_speakers.append(normalized)
    result = {
        "mean": float(values.mean()),
        "trials": int(len(values)),
        "unique_target_speakers": int(len(np.unique(normalized_speakers))),
    }
    if bootstrap:
        low, high = cluster_bootstrap_ci(
            values, normalized_speakers, seed, BOOTSTRAP_REPETITIONS
        )
        result["target_speaker_cluster_bootstrap_95ci"] = [low, high]
        result["bootstrap_status"] = "PERFORMED"
    else:
        # Smoke is an engineering canary, not an inferential scientific result.
        # Sparse one-cell strata commonly contain one speaker, so no CI is
        # claimed or attempted for a smoke run.
        result["target_speaker_cluster_bootstrap_95ci"] = None
        result["bootstrap_status"] = "NOT_RUN_ENGINEERING_SMOKE"
    return result


def _strata_masks(results: Any) -> dict[str, Any]:
    import numpy as np

    mixed = results["scene_kind"].astype(str).to_numpy() == "mixed"
    masks: dict[str, Any] = {
        "overall": np.ones(len(results), dtype=bool),
        "mixed": mixed,
        "clean": ~mixed,
    }
    distractors = results["distractor_count"].astype(int).to_numpy()
    bins = results["snr_bin"].astype(int).to_numpy()
    genders = results["target_gender"].astype(str).to_numpy()
    for count in range(1, 5):
        masks[f"distractors_{count}"] = mixed & (distractors == count)
    for bin_index in range(5):
        masks[f"snr_bin_{bin_index}"] = mixed & (bins == bin_index)
    for count in range(1, 5):
        for bin_index in range(5):
            masks[f"distractors_{count}__snr_bin_{bin_index}"] = (
                mixed & (distractors == count) & (bins == bin_index)
            )
    for gender in ("female", "male"):
        masks[f"target_gender_{gender}"] = genders == gender
    return masks


def validate_results(results: Any, full_run: bool) -> None:
    import numpy as np

    required_identity = {
        "trial_id", "scene_kind", "control_subset", "target_speaker",
        "target_gender", "target_norm", "target_label", "distractor_count",
        "snr_bin", "snr_db", "probe_distractor_norm",
        "probe_distractor_label", "scene_sha256", "correct_cue_sha256",
    }
    missing = sorted(required_identity.difference(results.columns))
    if missing:
        raise EvaluationError(f"Results lack identity fields: {missing}")
    if full_run and len(results) != TOTAL_TRIALS:
        raise EvaluationError("Full results do not contain 10,000 rows")
    trial_ids = results["trial_id"].astype(int).to_numpy()
    if len(np.unique(trial_ids)) != len(trial_ids):
        raise EvaluationError("Result trial IDs are not unique")
    if full_run and not np.array_equal(trial_ids, np.arange(TOTAL_TRIALS)):
        raise EvaluationError("Full result trial IDs are not exactly ordered 0..9999")
    if ((trial_ids < 0) | (trial_ids >= TOTAL_TRIALS)).any():
        raise EvaluationError("Result trial ID is outside the frozen bank")
    for hash_column in ("scene_sha256", "correct_cue_sha256"):
        if not results[hash_column].map(
            lambda value: isinstance(value, str)
            and re.fullmatch(r"[0-9a-f]{64}", value) is not None
        ).all():
            raise EvaluationError(f"Result {hash_column} is not canonical SHA-256")
    labels = results["target_label"].astype(int).to_numpy()
    controls = results["control_subset"].astype(int).to_numpy() == 1
    for model_id in MODEL_IDS:
        core = [
            f"{model_id}_pred_label", f"{model_id}_correct",
            f"{model_id}_nll", f"{model_id}_p_target",
            f"{model_id}_p_probe_distractor",
        ]
        if any(column not in results for column in core):
            raise EvaluationError(f"Results lack core fields for {model_id}")
        prediction = results[core[0]].astype(int).to_numpy()
        if ((prediction < 0) | (prediction > 799)).any():
            raise EvaluationError(f"Prediction out of range for {model_id}")
        if not np.array_equal((prediction == labels).astype(int), results[core[1]].astype(int)):
            raise EvaluationError(f"Correctness is not derivable for {model_id}")
        numeric = results[core[2:]].to_numpy(dtype=float)
        if not np.isfinite(numeric).all() or (numeric[:, 0] < 0).any() or ((numeric[:, 1:] < 0) | (numeric[:, 1:] > 1)).any():
            raise EvaluationError(f"Invalid probability/NLL for {model_id}")
        probes = results.loc[controls, "probe_distractor_label"].astype(int).to_numpy()
        for condition in CONTROL_CONDITIONS:
            prefix = f"{model_id}_{condition}"
            columns = [
                f"{prefix}_pred_label", f"{prefix}_correct", f"{prefix}_nll",
                f"{prefix}_p_target", f"{prefix}_probe_intrusion",
                f"{prefix}_p_probe_distractor",
            ]
            if any(column not in results for column in columns):
                raise EvaluationError(f"Results lack {condition} fields for {model_id}")
            if results.loc[~controls, columns].notna().any().any():
                raise EvaluationError(f"Control metrics leaked outside subset: {model_id}/{condition}")
            pred = results.loc[controls, columns[0]].astype(int).to_numpy()
            if ((pred < 0) | (pred > 799)).any():
                raise EvaluationError(
                    f"Control prediction out of range: {model_id}/{condition}"
                )
            if not np.array_equal((pred == labels[controls]).astype(int), results.loc[controls, columns[1]].astype(int)):
                raise EvaluationError(f"Control correctness mismatch: {model_id}/{condition}")
            if not np.array_equal((pred == probes).astype(int), results.loc[controls, columns[4]].astype(int)):
                raise EvaluationError(f"Probe intrusion mismatch: {model_id}/{condition}")
            control_numeric = results.loc[
                controls,
                [columns[2], columns[3], columns[5]],
            ].to_numpy(dtype=float)
            if (
                not np.isfinite(control_numeric).all()
                or (control_numeric[:, 0] < 0).any()
                or ((control_numeric[:, 1:] < 0) | (control_numeric[:, 1:] > 1)).any()
            ):
                raise EvaluationError(
                    f"Invalid control probability/NLL: {model_id}/{condition}"
                )


def summarize_results(results: Any, full_run: bool) -> dict[str, Any]:
    import numpy as np

    validate_results(results, full_run=full_run)
    masks = _strata_masks(results)
    speakers = results["target_speaker"].astype(str).to_numpy()
    controls = results["control_subset"].astype(int).to_numpy() == 1
    summary: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "engineering_status": "PASS",
        "scientific_decision": "NOT_GATED_EXTERNAL_AUDIT",
        "comparison_scope": (
            "same frozen validation/pilot bank; author uses native preprocessing and is an external system reference"
        ),
        "bootstrap": {
            "performed": bool(full_run),
            "unit": "target_speaker",
            "seed": BOOTSTRAP_SEED,
            "repetitions": BOOTSTRAP_REPETITIONS,
            "numpy_version": np.__version__,
            "quantile_method": "linear",
            "draw_policy": "same seed/draws within every identical stratum speaker vector",
            "smoke_policy": "not run; smoke is a sparse engineering canary",
        },
        "models": {},
        "paired_model_differences": {},
    }
    for model_offset, model_id in enumerate(MODEL_IDS):
        strata: dict[str, Any] = {}
        for name, mask in masks.items():
            if not bool(mask.any()):
                continue
            strata[name] = {
                "trials": int(mask.sum()),
                "accuracy": float(results.loc[mask, f"{model_id}_correct"].mean()),
                "cross_entropy": float(results.loc[mask, f"{model_id}_nll"].mean()),
            }
        correct = results.loc[controls, f"{model_id}_correct"].to_numpy(dtype=float)
        cue_controls: dict[str, Any] = {
            "trials": int(controls.sum()),
            "correct_accuracy": float(correct.mean()),
        }
        for condition in CONTROL_CONDITIONS:
            control_correct = results.loc[
                controls, f"{model_id}_{condition}_correct"
            ].to_numpy(dtype=float)
            cue_controls[f"{condition}_accuracy"] = float(control_correct.mean())
            cue_controls[f"correct_minus_{condition}"] = _paired_summary(
                correct - control_correct,
                speakers[controls],
                BOOTSTRAP_SEED,
                bootstrap=full_run,
            )
        distractor_delta = (
            results.loc[
                controls, f"{model_id}_distractor_p_probe_distractor"
            ].to_numpy(dtype=float)
            - results.loc[
                controls, f"{model_id}_p_probe_distractor"
            ].to_numpy(dtype=float)
        )
        cue_controls["distractor_cue_p_probe_delta"] = _paired_summary(
            distractor_delta,
            speakers[controls],
            BOOTSTRAP_SEED,
            bootstrap=full_run,
        )
        summary["models"][model_id] = {
            "role": MODEL_ROLES[model_id],
            "strata": strata,
            "cue_controls": cue_controls,
        }
    pairs = (
        ("formal40", "valbest33"),
        ("formal40", "author_external"),
        ("valbest33", "author_external"),
    )
    for pair_offset, (model_a, model_b) in enumerate(pairs):
        pair_key = f"{model_a}_vs_{model_b}"
        pair_summary: dict[str, Any] = {}
        for stratum_offset, (name, mask) in enumerate(masks.items()):
            if not bool(mask.any()):
                continue
            accuracy = (
                results.loc[mask, f"{model_a}_correct"].to_numpy(dtype=float)
                - results.loc[mask, f"{model_b}_correct"].to_numpy(dtype=float)
            )
            ce_improvement = (
                results.loc[mask, f"{model_b}_nll"].to_numpy(dtype=float)
                - results.loc[mask, f"{model_a}_nll"].to_numpy(dtype=float)
            )
            pair_summary[name] = {
                "trials": int(mask.sum()),
                "accuracy_difference_a_minus_b_positive_favors_a": _paired_summary(
                    accuracy,
                    speakers[mask],
                    BOOTSTRAP_SEED + 1000 + stratum_offset,
                    bootstrap=full_run,
                ),
                "cross_entropy_improvement_b_minus_a_positive_favors_a": _paired_summary(
                    ce_improvement,
                    speakers[mask],
                    BOOTSTRAP_SEED + 1000 + stratum_offset,
                    bootstrap=full_run,
                ),
            }
        summary["paired_model_differences"][pair_key] = {
            "model_a": model_a,
            "model_b": model_b,
            "strata": pair_summary,
        }
    return summary


def _select_smoke_bank(bank: Any, trials: int) -> Any:
    import numpy as np

    if trials < 3 or trials > len(bank):
        raise EvaluationError("Smoke trial count is out of range")
    mandatory: list[int] = []
    for mask in (
        bank["scene_kind"].astype(str) == "clean",
        bank["scene_kind"].astype(str) == "mixed",
        bank["control_subset"].astype(int) == 1,
    ):
        matches = np.flatnonzero(mask.to_numpy())
        if not len(matches):
            raise EvaluationError("Smoke bank lacks a mandatory clean/mixed/control case")
        candidate = int(matches[0])
        if candidate not in mandatory:
            mandatory.append(candidate)
    if "target_speaker" in bank.columns:
        controls = bank.loc[bank["control_subset"].astype(int) == 1]
        distinct_controls = controls.drop_duplicates("target_speaker")
        if distinct_controls["target_speaker"].nunique() < 2:
            raise EvaluationError("Smoke bank needs at least two control speaker clusters")
        for index in distinct_controls.index[:2]:
            position = int(bank.index.get_loc(index))
            if position not in mandatory:
                mandatory.append(position)
    if len(mandatory) > trials:
        raise EvaluationError("Smoke trial count cannot cover mandatory cases")
    chosen = list(mandatory)
    for candidate in np.linspace(0, len(bank) - 1, num=max(trials * 2, 3), dtype=int):
        index = int(candidate)
        if index not in chosen:
            chosen.append(index)
        if len(chosen) == trials:
            break
    if len(chosen) < trials:
        for index in range(len(bank)):
            if index not in chosen:
                chosen.append(index)
            if len(chosen) == trials:
                break
    return bank.iloc[chosen].copy().reset_index(drop=True)


def _prepare_result_frame(bank: Any) -> Any:
    import numpy as np

    identity = bank[
        [
            "trial_id", "scene_kind", "control_subset", "target_speaker",
            "target_gender", "target_norm", "target_label", "distractor_count",
            "snr_bin", "snr_db", "distractor_1_norm", "distractor_1_label",
        ]
    ].copy()
    identity = identity.rename(
        columns={
            "distractor_1_norm": "probe_distractor_norm",
            "distractor_1_label": "probe_distractor_label",
        }
    )
    clean = identity["scene_kind"].astype(str) == "clean"
    identity.loc[clean, "probe_distractor_norm"] = ""
    identity.loc[clean, "probe_distractor_label"] = 0
    identity["scene_sha256"] = ""
    identity["correct_cue_sha256"] = ""
    for model_id in MODEL_IDS:
        for metric in ("pred_label", "correct", "nll", "p_target", "p_probe_distractor"):
            identity[f"{model_id}_{metric}"] = np.nan
        for condition in CONTROL_CONDITIONS:
            for metric in (
                "pred_label", "correct", "nll", "p_target",
                "probe_intrusion", "p_probe_distractor",
            ):
                identity[f"{model_id}_{condition}_{metric}"] = np.nan
    return identity


def _tensor_hashes(tensor: Any) -> list[str]:
    contiguous = tensor.detach().cpu().contiguous()
    return [hashlib.sha256(item.numpy().tobytes()).hexdigest() for item in contiguous]


def _create_attempt_directory(
    external_root: pathlib.Path,
    attempt_id: str,
    mode: str,
) -> pathlib.Path:
    attempt_id = _require_attempt_id(attempt_id)
    if mode not in {"smoke", "audit"}:
        raise EvaluationError(f"Invalid attempt mode: {mode}")
    parent = safe_directory(
        external_root / "attempts" / mode,
        f"Frozen {mode} attempt root",
    )
    return mkdir_exclusive(parent, attempt_id)


def _artifact_record_is_current(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not {
        "path",
        "basename",
        "size",
        "sha256",
        "device",
        "inode",
    }.issubset(value):
        raise EvaluationError(f"{label} is not a frozen artifact record")
    current = pinned_file(value["path"], label, str(value["sha256"]))
    diagnostics = validate_persistent_file_identity(value, current, label)
    return {**current, "filesystem_identity_diagnostics": diagnostics}


def read_environment_fingerprint(
    path: pathlib.Path,
    expected_sha256: str,
    job_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse one canonical, hash-bound environment evidence artifact."""
    payload, record = read_pinned_bytes(
        path,
        "Archived environment fingerprint",
        expected_sha256,
    )

    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        environment = json.loads(
            payload.decode("utf-8"),
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise EvaluationError("Environment fingerprint is not strict JSON") from error
    expected_keys = {
        "cuda_available",
        "cuda_runtime",
        "cudnn",
        "device",
        "hostname",
        "python",
        "slurm_job_id",
        "torch",
    }
    if not isinstance(environment, dict) or set(environment) != expected_keys:
        raise EvaluationError("Environment fingerprint fields are not canonical")
    canonical = (
        json.dumps(
            environment,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if canonical != payload:
        raise EvaluationError("Environment fingerprint bytes are not canonical JSON")
    if str(environment.get("slurm_job_id")) != str(job_id):
        raise EvaluationError("Environment fingerprint Slurm Job ID mismatch")
    if not isinstance(environment.get("cuda_available"), bool):
        raise EvaluationError("Environment fingerprint CUDA flag is not boolean")
    for field in ("hostname", "python", "torch"):
        if not isinstance(environment.get(field), str) or not environment[field]:
            raise EvaluationError(f"Environment fingerprint has invalid {field}")
    return environment, record


def verify_publication_marker(
    external_root: pathlib.Path,
    marker_name: str,
    manifest_sha256: str,
) -> dict[str, Any]:
    if marker_name not in {"SMOKE_PASS.json", "SAME_BANK_AUDIT_PUBLISHED.json"}:
        raise EvaluationError(f"Unknown publication marker: {marker_name}")
    marker_path = external_root / "state" / marker_name
    marker_record = pinned_file(marker_path, f"Publication marker {marker_name}")
    marker = read_json(
        marker_path, f"Publication marker {marker_name}", marker_record["sha256"]
    )
    validate_protocol_boundary(marker, f"Publication marker {marker_name}")
    expected_status = (
        "SMOKE_PASS"
        if marker_name == "SMOKE_PASS.json"
        else "SAME_BANK_AUDIT_PUBLISHED"
    )
    if (
        marker.get("schema_version") != RESULT_SCHEMA_VERSION
        or marker.get("status") != expected_status
        or marker.get("evaluation_role") != EVALUATION_ROLE
        or marker.get("role_confirmation") != EXPECTED_ROLE_CONFIRMATION
        or marker.get("manifest_sha256") != manifest_sha256
    ):
        raise EvaluationError(f"Publication marker boundary mismatch: {marker_name}")
    if pathlib.Path(str(marker.get("manifest", ""))) != external_root / "input_freeze.json":
        raise EvaluationError(f"Publication manifest path is not canonical: {marker_name}")
    runner_sha = _require_sha(
        str(marker.get("submitted_runner_sha256", "")),
        f"{marker_name} submitted runner SHA",
    )
    if runner_sha != marker.get("frozen_runner_sha256"):
        raise EvaluationError(f"Publication runner binding mismatch: {marker_name}")
    frozen_manifest = read_json(
        external_root / "input_freeze.json",
        f"{marker_name} frozen manifest",
        manifest_sha256,
    )
    validate_protocol_boundary(
        frozen_manifest,
        f"{marker_name} frozen manifest",
    )
    if frozen_manifest.get("inputs", {}).get("sbatch", {}).get("sha256") != runner_sha:
        raise EvaluationError(f"Publication runner is not manifest-bound: {marker_name}")
    slurm_job_id = str(marker.get("slurm_job_id", ""))
    if not re.fullmatch(r"[0-9]+", slurm_job_id):
        raise EvaluationError(f"Publication marker lacks a Slurm Job ID: {marker_name}")
    if marker.get("attempt_id") != f"slurm-{slurm_job_id}":
        raise EvaluationError(f"Publication attempt/job binding mismatch: {marker_name}")
    _require_sha(
        str(marker.get("environment_fingerprint_sha256", "")),
        f"{marker_name} environment fingerprint SHA",
    )
    artifacts = marker.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise EvaluationError(f"Publication marker lacks artifacts: {marker_name}")
    expected_artifacts = {
        "results",
        "long_results",
        "summary",
        "attempt_complete",
        "submitted_runner",
        "environment_fingerprint",
    }
    if marker_name == "SAME_BANK_AUDIT_PUBLISHED.json":
        expected_artifacts.add("smoke_parent")
    if set(artifacts) != expected_artifacts:
        raise EvaluationError(
            f"Publication artifact set mismatch: {marker_name}: {sorted(artifacts)}"
        )
    verified = {
        name: _artifact_record_is_current(value, f"{marker_name} artifact {name}")
        for name, value in artifacts.items()
    }
    attempt_root = (
        external_root
        / "attempts"
        / ("smoke" if marker_name == "SMOKE_PASS.json" else "audit")
        / f"slurm-{slurm_job_id}"
    )
    canonical_artifacts = {
        "results": attempt_root / "per_trial_results.csv",
        "long_results": attempt_root / "per_model_results_long.csv",
        "summary": attempt_root
        / ("SMOKE_AUDIT.json" if marker_name == "SMOKE_PASS.json" else "SAME_BANK_AUDIT.json"),
        "attempt_complete": attempt_root / "COMPLETE.json",
        "submitted_runner": external_root / "submitted_runners" / f"{slurm_job_id}.sbatch",
        "environment_fingerprint": (
            external_root
            / "submitted_runners"
            / f"{slurm_job_id}.environment.json"
        ),
    }
    if marker_name == "SAME_BANK_AUDIT_PUBLISHED.json":
        canonical_artifacts["smoke_parent"] = external_root / "state/SMOKE_PASS.json"
    for name, expected_path in canonical_artifacts.items():
        if pathlib.Path(verified[name]["path"]) != expected_path:
            raise EvaluationError(
                f"Publication artifact path is not canonical: {marker_name}/{name}"
            )
    if (
        verified["submitted_runner"]["sha256"] != runner_sha
        or pathlib.Path(verified["submitted_runner"]["path"])
        != external_root / "submitted_runners" / f"{slurm_job_id}.sbatch"
    ):
        raise EvaluationError(f"Submitted runner artifact mismatch: {marker_name}")
    environment_sha = _require_sha(
        str(marker.get("environment_fingerprint_sha256", "")),
        f"{marker_name} environment fingerprint SHA",
    )
    if verified["environment_fingerprint"]["sha256"] != environment_sha:
        raise EvaluationError(
            f"Environment fingerprint artifact mismatch: {marker_name}"
        )
    environment, _ = read_environment_fingerprint(
        pathlib.Path(verified["environment_fingerprint"]["path"]),
        environment_sha,
        slurm_job_id,
    )
    complete_payload = read_json(
        pathlib.Path(verified["attempt_complete"]["path"]),
        f"{marker_name} attempt COMPLETE",
        verified["attempt_complete"]["sha256"],
    )
    validate_protocol_boundary(
        complete_payload,
        f"{marker_name} attempt COMPLETE",
    )
    expected_attempt_status = (
        "SMOKE_PASS" if marker_name == "SMOKE_PASS.json" else "RUN_AUDIT_PASS"
    )
    if (
        complete_payload.get("schema_version") != RESULT_SCHEMA_VERSION
        or complete_payload.get("status") != expected_attempt_status
        or complete_payload.get("attempt_id") != marker["attempt_id"]
        or str(complete_payload.get("job_id")) != slurm_job_id
        or complete_payload.get("manifest_sha256") != manifest_sha256
        or complete_payload.get("evaluation_role") != EVALUATION_ROLE
        or complete_payload.get("role_confirmation")
        != EXPECTED_ROLE_CONFIRMATION
        or complete_payload.get("environment_fingerprint_sha256")
        != environment_sha
        or complete_payload.get("environment") != environment
    ):
        raise EvaluationError(f"Attempt COMPLETE boundary mismatch: {marker_name}")
    for artifact_name in (
        "results",
        "long_results",
        "summary",
        "submitted_runner",
        "environment_fingerprint",
    ):
        if (
            complete_payload.get(artifact_name, {}).get("sha256")
            != verified[artifact_name]["sha256"]
        ):
            raise EvaluationError(
                f"Attempt COMPLETE artifact mismatch: {marker_name}/{artifact_name}"
            )
    if marker_name == "SAME_BANK_AUDIT_PUBLISHED.json":
        smoke = verify_publication_marker(
            external_root, "SMOKE_PASS.json", manifest_sha256
        )
        if smoke["marker_record"]["sha256"] != verified["smoke_parent"]["sha256"]:
            raise EvaluationError("Full publication smoke-parent lineage mismatch")
        smoke_complete = read_json(
            pathlib.Path(
                smoke["verified_artifacts"]["attempt_complete"]["path"]
            ),
            "Smoke attempt COMPLETE for environment lineage",
            smoke["verified_artifacts"]["attempt_complete"]["sha256"],
        )
        stable_environment_fields = (
            "cuda_available",
            "cuda_runtime",
            "cudnn",
            "device",
            "python",
            "torch",
        )
        if any(
            complete_payload.get("environment", {}).get(field)
            != smoke_complete.get("environment", {}).get(field)
            for field in stable_environment_fields
        ):
            raise EvaluationError(
                "Full evaluation environment is incompatible with the smoke environment"
            )
    return {
        "marker": marker,
        "marker_record": marker_record,
        "verified_artifacts": verified,
    }


def publish_canonical_marker(
    external_root: pathlib.Path,
    *,
    smoke: bool,
    completion: Mapping[str, Any],
    manifest_path: pathlib.Path,
    manifest_sha256: str,
    submitted_runner_sha256: str,
    frozen_runner_sha256: str,
    slurm_job_id: str,
    environment_fingerprint_sha256: str,
    smoke_parent: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    marker_name = "SMOKE_PASS.json" if smoke else "SAME_BANK_AUDIT_PUBLISHED.json"
    marker = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "filesystem_identity_policy": FILESYSTEM_IDENTITY_POLICY,
        "status": "SMOKE_PASS" if smoke else "SAME_BANK_AUDIT_PUBLISHED",
        "evaluation_role": EVALUATION_ROLE,
        "role_confirmation": EXPECTED_ROLE_CONFIRMATION,
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "attempt_id": completion["attempt_id"],
        "slurm_job_id": slurm_job_id,
        "submitted_runner_sha256": submitted_runner_sha256,
        "frozen_runner_sha256": frozen_runner_sha256,
        "environment_fingerprint_sha256": environment_fingerprint_sha256,
        "published_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "artifacts": {
            "results": completion["results"],
            "long_results": completion["long_results"],
            "summary": completion["summary"],
            "attempt_complete": completion["attempt_complete"],
            "submitted_runner": completion["submitted_runner"],
            "environment_fingerprint": completion["environment_fingerprint"],
        },
    }
    if smoke:
        if smoke_parent is not None:
            raise EvaluationError("Smoke publication cannot have a smoke parent")
    else:
        if not isinstance(smoke_parent, Mapping):
            raise EvaluationError("Full publication requires the verified smoke marker")
        marker["artifacts"]["smoke_parent"] = dict(smoke_parent)
    path = external_root / "state" / marker_name
    atomic_create_json(path, marker)
    return verify_publication_marker(external_root, marker_name, manifest_sha256)


def _configure_runtime(allow_cpu: bool) -> Any:
    import torch

    random.seed(BOOTSTRAP_SEED)
    try:
        import numpy as np

        np.random.seed(BOOTSTRAP_SEED)
    except ImportError:
        pass
    torch.manual_seed(BOOTSTRAP_SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(BOOTSTRAP_SEED)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.set_float32_matmul_precision("medium")
    if hasattr(torch.backends, "cuda"):
        torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    if not torch.cuda.is_available() and not allow_cpu:
        raise EvaluationError("CUDA is required unless --allow-cpu is explicitly set")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def validate_runtime_provenance(
    args: argparse.Namespace,
    manifest: Mapping[str, Any],
    external_root: pathlib.Path,
) -> dict[str, Any]:
    import torch

    validate_protocol_boundary(manifest, "Runtime frozen manifest")
    job_id = str(args.job_id)
    if not re.fullmatch(r"[0-9]+", job_id):
        raise EvaluationError("--job-id must be a numeric Slurm Job ID")
    if args.attempt_id != f"slurm-{job_id}":
        raise EvaluationError("--attempt-id must be exactly slurm-<job-id>")
    submitted_sha = _require_sha(
        args.submitted_runner_sha256, "Submitted runner SHA"
    )
    environment_sha = _require_sha(
        args.environment_fingerprint_sha256, "Environment fingerprint SHA"
    )
    frozen_runner_sha = str(manifest["inputs"]["sbatch"]["sha256"])
    if submitted_sha != frozen_runner_sha:
        raise EvaluationError(
            "Submitted Slurm spool SHA differs from frozen runner SHA"
        )
    submitted_path = safe_file(args.submitted_runner, "Archived submitted runner")
    canonical = external_root / "submitted_runners" / f"{job_id}.sbatch"
    if submitted_path != canonical:
        raise EvaluationError(
            f"Archived submitted runner path is not canonical: {submitted_path}"
        )
    submitted_record = pinned_file(
        submitted_path, "Archived submitted runner", submitted_sha
    )
    environment_path = safe_file(
        args.environment_fingerprint, "Archived environment fingerprint"
    )
    canonical_environment = (
        external_root / "submitted_runners" / f"{job_id}.environment.json"
    )
    if environment_path != canonical_environment:
        raise EvaluationError(
            f"Archived environment fingerprint path is not canonical: {environment_path}"
        )
    environment, environment_record = read_environment_fingerprint(
        environment_path,
        environment_sha,
        job_id,
    )
    actual_environment = {
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_runtime": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "device": (
            torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
        ),
        "hostname": platform.node(),
        "python": platform.python_version(),
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "torch": torch.__version__,
    }
    if environment != actual_environment or str(environment["slurm_job_id"]) != job_id:
        raise EvaluationError(
            "Archived environment fingerprint differs from the active process"
        )
    return {
        "job_id": job_id,
        "attempt_id": args.attempt_id,
        "submitted_runner": submitted_record,
        "submitted_runner_sha256": submitted_sha,
        "frozen_runner_sha256": frozen_runner_sha,
        "environment_fingerprint": environment_record,
        "environment": environment,
        "environment_fingerprint_sha256": environment_sha,
    }


def snapshot_model_tensor_versions(model: Any) -> tuple[tuple[Any, ...], ...]:
    """Snapshot every registered parameter and buffer, including persistence metadata."""
    entries: list[tuple[Any, ...]] = []
    for kind, tensors in (
        ("parameter", model.named_parameters(recurse=True)),
        ("buffer", model.named_buffers(recurse=True)),
    ):
        for name, tensor in tensors:
            entries.append(
                (
                    kind,
                    str(name),
                    id(tensor),
                    int(tensor._version),
                    tuple(int(value) for value in tensor.shape),
                    str(tensor.dtype),
                    str(tensor.device),
                )
            )
    entries.sort(key=lambda value: (value[0], value[1]))
    return tuple(entries)


def _evaluate_prediction_pass(
    *,
    bank: Any,
    historical_scene_hashes: Mapping[int, str],
    models: Mapping[str, Any],
    device: Any,
    clips_dir: pathlib.Path,
    batch_size: int,
    cache_items: int,
    waveform_cache_class: Any,
    raw_scene_batch: Any,
    correct_cue_batch: Any,
    role_batch: Any,
) -> tuple[Any, list[float]]:
    """Evaluate one pass; every batch's raw tensors are shared by all models."""
    import numpy as np
    import torch

    results = _prepare_result_frame(bank)
    cache = waveform_cache_class(max_items=cache_items)
    snr_errors: list[float] = []
    for start in range(0, len(bank), batch_size):
        stop = min(start + batch_size, len(bank))
        frame = bank.iloc[start:stop]
        positions = np.arange(start, stop)
        raw_scene = raw_scene_batch(frame, cache, clips_dir, snr_errors=snr_errors)
        raw_correct = correct_cue_batch(frame, cache, clips_dir)
        scene_hashes = np.asarray(_tensor_hashes(raw_scene), dtype=str)
        cue_hashes = np.asarray(_tensor_hashes(raw_correct), dtype=str)
        trial_ids = frame["trial_id"].astype(int).to_numpy()
        expected_scene = np.asarray(
            [historical_scene_hashes[int(trial_id)] for trial_id in trial_ids],
            dtype=str,
        )
        if not np.array_equal(scene_hashes, expected_scene):
            bad = trial_ids[scene_hashes != expected_scene][:10].tolist()
            raise EvaluationError(
                f"Regenerated scene bytes differ from frozen Job584990: trials={bad}"
            )
        results.loc[positions, "scene_sha256"] = scene_hashes
        results.loc[positions, "correct_cue_sha256"] = cue_hashes
        labels = torch.as_tensor(
            frame["target_label"].to_numpy(dtype=np.int64), dtype=torch.long
        )
        probes = torch.as_tensor(
            np.where(
                frame["scene_kind"].astype(str).to_numpy() == "mixed",
                frame["distractor_1_label"].to_numpy(dtype=np.int64),
                0,
            ),
            dtype=torch.long,
        )
        selected = frame["control_subset"].astype(int).to_numpy() == 1
        control_payload: dict[str, Any] | None = None
        if selected.any():
            control_frame = frame.iloc[np.flatnonzero(selected)]
            control_correct = raw_correct[selected]
            control_payload = {
                "scene": raw_scene[selected],
                "labels": labels[selected],
                "probes": probes[selected],
                "positions": positions[selected],
                "cues": {
                    "shuffled": role_batch(
                        control_frame, "shuffled_cue", cache, clips_dir
                    ),
                    "silent": torch.zeros_like(control_correct),
                    "distractor": role_batch(
                        control_frame, "probe_distractor_cue", cache, clips_dir
                    ),
                },
            }
        raw_versions = (raw_scene._version, raw_correct._version)
        for model_id in MODEL_IDS:
            model = models[model_id]
            prediction = predict_batch(
                model, raw_scene, raw_correct, labels, probes, device
            )
            predicted = prediction["pred_label"].astype(int)
            results.loc[positions, f"{model_id}_pred_label"] = predicted
            results.loc[positions, f"{model_id}_correct"] = (
                predicted == labels.numpy()
            ).astype(int)
            for metric in ("nll", "p_target", "p_probe_distractor"):
                results.loc[positions, f"{model_id}_{metric}"] = prediction[metric]
            if control_payload is not None:
                for condition, cue in control_payload["cues"].items():
                    values = predict_batch(
                        model,
                        control_payload["scene"],
                        cue,
                        control_payload["labels"],
                        control_payload["probes"],
                        device,
                    )
                    condition_pred = values["pred_label"].astype(int)
                    prefix = f"{model_id}_{condition}"
                    control_positions = control_payload["positions"]
                    results.loc[control_positions, f"{prefix}_pred_label"] = condition_pred
                    results.loc[control_positions, f"{prefix}_correct"] = (
                        condition_pred == control_payload["labels"].numpy()
                    ).astype(int)
                    results.loc[control_positions, f"{prefix}_probe_intrusion"] = (
                        condition_pred == control_payload["probes"].numpy()
                    ).astype(int)
                    for metric in ("nll", "p_target", "p_probe_distractor"):
                        results.loc[control_positions, f"{prefix}_{metric}"] = values[metric]
        if raw_versions != (raw_scene._version, raw_correct._version):
            raise EvaluationError("A model mutated the shared raw batch tensor")
        if not np.array_equal(np.asarray(_tensor_hashes(raw_scene)), scene_hashes):
            raise EvaluationError("Shared raw scene bytes changed during inference")
        print(f"same-bank shared-raw batch: {stop}/{len(bank)}", flush=True)
    for model_id in MODEL_IDS:
        results[f"{model_id}_pred_label"] = results[f"{model_id}_pred_label"].astype(int)
        results[f"{model_id}_correct"] = results[f"{model_id}_correct"].astype(int)
    return results, snr_errors


def compare_smoke_passes(first: Any, second: Any) -> dict[str, Any]:
    import numpy as np

    if list(first.columns) != list(second.columns) or len(first) != len(second):
        raise EvaluationError("Smoke canary passes have different schemas")
    max_abs = 0.0
    for column in first.columns:
        if first[column].dtype.kind in "biufc" and second[column].dtype.kind in "biufc":
            left = first[column].to_numpy(dtype=float)
            right = second[column].to_numpy(dtype=float)
            finite = np.isfinite(left) & np.isfinite(right)
            if not np.array_equal(np.isnan(left), np.isnan(right)):
                raise EvaluationError(f"Smoke canary NaN pattern differs: {column}")
            if finite.any():
                error = float(np.max(np.abs(left[finite] - right[finite])))
                max_abs = max(max_abs, error)
                if error > 1e-6:
                    raise EvaluationError(
                        f"Smoke batch-size canary differs: {column}, max_abs={error}"
                    )
        elif not np.array_equal(first[column].astype(str), second[column].astype(str)):
            raise EvaluationError(f"Smoke canary identity differs: {column}")
    return {
        "status": "PASS",
        "passes": 2,
        "batch_sizes": [1, "requested"],
        "maximum_absolute_numeric_difference": max_abs,
    }


def to_model_long_results(results: Any, manifest: Mapping[str, Any]) -> Any:
    import pandas as pd

    identity = [
        "trial_id", "scene_kind", "control_subset", "target_speaker",
        "target_gender", "target_norm", "target_label", "distractor_count",
        "snr_bin", "snr_db", "probe_distractor_norm",
        "probe_distractor_label", "scene_sha256", "correct_cue_sha256",
    ]
    frames = []
    for model_id in MODEL_IDS:
        frame = results[identity].copy()
        frame.insert(len(identity), "model_id", model_id)
        frame.insert(len(identity) + 1, "model_role", MODEL_ROLES[model_id])
        frame.insert(
            len(identity) + 2,
            "checkpoint_sha256",
            manifest["models"][model_id]["sha256"],
        )
        rename = {
            column: column[len(model_id) + 1 :]
            for column in results.columns
            if column.startswith(f"{model_id}_")
        }
        for source, destination in rename.items():
            frame[destination] = results[source].to_numpy()
        frames.append(frame)
    long_results = pd.concat(frames, ignore_index=True)
    if len(long_results) != len(results) * len(MODEL_IDS):
        raise EvaluationError("Long result row count is not trials times three models")
    return long_results


def validate_result_identity(
    results: Any,
    bank: Any,
    *,
    expected_generated: Any | None = None,
) -> dict[str, Any]:
    import numpy as np

    if len(results) != len(bank):
        raise EvaluationError("Result/bank row counts differ")
    expected = bank.reset_index(drop=True)
    actual = results.reset_index(drop=True)
    mixed = expected["scene_kind"].astype(str).to_numpy() == "mixed"
    expected_probe_norm = np.where(
        mixed,
        expected["distractor_1_norm"].astype(str).to_numpy(),
        "",
    )
    expected_probe_label = np.where(
        mixed,
        expected["distractor_1_label"].astype(int).to_numpy(),
        0,
    )
    pairs = {
        "trial_id": expected["trial_id"].astype(int).to_numpy(),
        "scene_kind": expected["scene_kind"].astype(str).to_numpy(),
        "control_subset": expected["control_subset"].astype(int).to_numpy(),
        "target_speaker": expected["target_speaker"].astype(str).to_numpy(),
        "target_gender": expected["target_gender"].astype(str).to_numpy(),
        "target_norm": expected["target_norm"].astype(str).to_numpy(),
        "target_label": expected["target_label"].astype(int).to_numpy(),
        "distractor_count": expected["distractor_count"].astype(int).to_numpy(),
        "snr_bin": expected["snr_bin"].astype(int).to_numpy(),
        "probe_distractor_norm": expected_probe_norm,
        "probe_distractor_label": expected_probe_label,
    }
    for column, values in pairs.items():
        if not np.array_equal(actual[column].to_numpy(dtype=values.dtype), values):
            raise EvaluationError(f"Result identity differs from frozen bank: {column}")
    snr_identity = validate_snr_identity(
        expected["snr_db"].to_numpy(dtype=float),
        actual["snr_db"].to_numpy(dtype=float),
        expected["scene_kind"].astype(str).to_numpy(),
        label="Result/bank",
        atol=(SNR_IDENTITY_ATOL_DB if expected_generated is not None else 0.0),
    )
    if expected_generated is not None:
        expected_generated = expected_generated.reset_index(drop=True)
        if len(expected_generated) != len(actual):
            raise EvaluationError("Generated identity row counts differ after serialization")
        for column in ("scene_sha256", "correct_cue_sha256"):
            if not np.array_equal(
                actual[column].astype(str).to_numpy(),
                expected_generated[column].astype(str).to_numpy(),
            ):
                raise EvaluationError(
                    f"Generated identity changed during serialization: {column}"
                )
    return {
        "snr_identity": snr_identity,
        "generated_hash_binding": (
            "scene_and_correct_cue_sha256_exact"
            if expected_generated is not None
            else "not_applicable_before_serialization"
        ),
    }


def run_evaluation(args: argparse.Namespace, *, smoke: bool) -> dict[str, Any]:
    import torch

    if args.confirm_role != EXPECTED_ROLE_CONFIRMATION:
        raise EvaluationError("Role confirmation does not match the locked comparison")
    external_root = safe_directory(args.external_root, "External evaluation root")
    with evaluation_lock(external_root):
        manifest_path = safe_file(args.manifest, "Frozen input manifest")
        if manifest_path != external_root / "input_freeze.json":
            raise EvaluationError("Manifest path is not the canonical frozen path")
        manifest, manifest_sha = _validate_manifest_hash(
            manifest_path, args.expected_manifest_sha256
        )
        layout_verification = validate_frozen_layout(external_root, manifest)
        frozen_verification = verify_frozen_manifest(manifest, external_root)
        provenance = validate_runtime_provenance(args, manifest, external_root)
        marker_name = "SMOKE_PASS.json" if smoke else "SAME_BANK_AUDIT_PUBLISHED.json"
        if os.path.lexists(external_root / "state" / marker_name):
            raise FileExistsError(f"Canonical publication already exists: {marker_name}")
        smoke_gate: dict[str, Any] | None = None
        if not smoke:
            smoke_gate = verify_publication_marker(
                external_root, "SMOKE_PASS.json", manifest_sha
            )
        device = _configure_runtime(args.allow_cpu)
        mode = "smoke" if smoke else "audit"
        output_dir = _create_attempt_directory(
            external_root, args.attempt_id, mode
        )
        running = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "filesystem_identity_policy": FILESYSTEM_IDENTITY_POLICY,
            "status": "RUNNING",
            "mode": mode,
            "evaluation_role": EVALUATION_ROLE,
            "role_confirmation": EXPECTED_ROLE_CONFIRMATION,
            "manifest_sha256": manifest_sha,
            "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "provenance": provenance,
        }
        atomic_create_json(output_dir / "RUNNING.json", running)
        try:
            bank, _ = read_csv_pinned(
                pathlib.Path(manifest["inputs"]["bank"]["path"]),
                "Frozen 10k bank",
                manifest["inputs"]["bank"]["sha256"],
                sep="\t",
                dtype={f"{role}_speaker": str for role in ROLE_NAMES},
            )
            historical, _ = read_csv_pinned(
                pathlib.Path(
                    manifest["historical_evidence"]["job584990_results"]["path"]
                ),
                "Job584990 per-trial results",
                manifest["historical_evidence"]["job584990_results"]["sha256"],
                dtype={"target_speaker": str},
            )
            historical_binding = validate_historical_scene_binding(bank, historical)
            historical_scene_hashes = {
                int(row.trial_id): str(row.scene_sha256)
                for row in historical[["trial_id", "scene_sha256"]].itertuples(index=False)
            }
            if smoke:
                bank = _select_smoke_bank(bank, args.trials)
            bank = bank.reset_index(drop=True)
            snapshot_files = pathlib.Path(manifest["roots"]["snapshot_files"])
            clips_dir = safe_directory(
                manifest["roots"]["clips_dir"], "Frozen canonical CV clips directory"
            )
            with _frozen_import_context(snapshot_files):
                import selftrain.data.diotic_attention as data_module
                import selftrain.scripts.eval_full_pilot as historical_evaluator_module

                for imported in (data_module, historical_evaluator_module):
                    imported_path = safe_file(
                        inspect.getfile(imported), "Imported frozen evaluation module"
                    )
                    if not _is_relative_to(imported_path, snapshot_files):
                        raise EvaluationError(
                            f"Evaluation import escaped frozen snapshot: {imported_path}"
                        )
                WaveformCache = data_module.WaveformCache
                _raw_scene_batch = historical_evaluator_module._raw_scene_batch
                _correct_cue_batch = historical_evaluator_module._correct_cue_batch
                _role_batch = historical_evaluator_module._role_batch
            models: dict[str, Any] = {}
            load_reports: dict[str, Any] = {}
            versions: dict[str, tuple[tuple[Any, ...], ...]] = {}
            try:
                for model_id in MODEL_IDS:
                    model, report = strict_load_model(
                        manifest, model_id, device=device
                    )
                    models[model_id] = model
                    load_reports[model_id] = report
                    versions[model_id] = snapshot_model_tensor_versions(model)
                results, snr_errors = _evaluate_prediction_pass(
                    bank=bank,
                    historical_scene_hashes=historical_scene_hashes,
                    models=models,
                    device=device,
                    clips_dir=clips_dir,
                    batch_size=args.batch_size,
                    cache_items=args.cache_items,
                    waveform_cache_class=WaveformCache,
                    raw_scene_batch=_raw_scene_batch,
                    correct_cue_batch=_correct_cue_batch,
                    role_batch=_role_batch,
                )
                canary = None
                if smoke:
                    second, second_snr_errors = _evaluate_prediction_pass(
                        bank=bank,
                        historical_scene_hashes=historical_scene_hashes,
                        models=models,
                        device=device,
                        clips_dir=clips_dir,
                        batch_size=1,
                        cache_items=args.cache_items,
                        waveform_cache_class=WaveformCache,
                        raw_scene_batch=_raw_scene_batch,
                        correct_cue_batch=_correct_cue_batch,
                        role_batch=_role_batch,
                    )
                    canary = compare_smoke_passes(results, second)
                    snr_errors.extend(second_snr_errors)
                for model_id, model in models.items():
                    if versions[model_id] != snapshot_model_tensor_versions(model):
                        raise EvaluationError(
                            f"Model parameters/buffers changed during inference: {model_id}"
                        )
            finally:
                models.clear()
                gc.collect()
                if device.type == "cuda":
                    torch.cuda.empty_cache()
            validate_results(results, full_run=not smoke)
            in_memory_identity = validate_result_identity(results, bank)
            results_path = output_dir / "per_trial_results.csv"
            atomic_create_bytes(
                results_path, results.to_csv(index=False).encode("utf-8")
            )
            reloaded, _ = read_csv_pinned(
                results_path,
                "Evaluation results",
                sha256_file(results_path),
                dtype={"target_speaker": str},
                keep_default_na=True,
            )
            validate_results(reloaded, full_run=not smoke)
            csv_reload_identity = validate_result_identity(
                reloaded,
                bank,
                expected_generated=results,
            )
            long_results = to_model_long_results(reloaded, manifest)
            long_path = output_dir / "per_model_results_long.csv"
            atomic_create_bytes(
                long_path, long_results.to_csv(index=False).encode("utf-8")
            )
            summary = summarize_results(reloaded, full_run=not smoke)
            summary.update(
                {
                    "mode": mode,
                    "protocol_id": PROTOCOL_ID,
                    "filesystem_identity_policy": FILESYSTEM_IDENTITY_POLICY,
                    "attempt_id": args.attempt_id,
                    "run_id": RUN_ID,
                    "evaluation_role": EVALUATION_ROLE,
                    "role_confirmation": EXPECTED_ROLE_CONFIRMATION,
                    "manifest": str(manifest_path),
                    "manifest_sha256": manifest_sha,
                    "trials": len(reloaded),
                    "long_rows": len(long_results),
                    "historical_scene_binding": historical_binding,
                    "filesystem_identity_diagnostics": {
                        "layout": layout_verification[
                            "filesystem_identity_diagnostics"
                        ],
                        "frozen_files": frozen_verification[
                            "filesystem_identity_diagnostics"
                        ],
                    },
                    "result_identity": {
                        "in_memory": in_memory_identity,
                        "csv_reload": csv_reload_identity,
                    },
                    "correct_cue_historical_binding": (
                        "UNAVAILABLE_IN_JOB584990; regenerated once per batch and shared across all three models"
                    ),
                    "smoke_batch_size_canary": canary,
                    "smoke_gate": (
                        smoke_gate["marker_record"] if smoke_gate is not None else None
                    ),
                    "load_audits": load_reports,
                    "provenance": provenance,
                    "runtime": {
                        "python": platform.python_version(),
                        "torch": torch.__version__,
                        "device": str(device),
                        "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
                        "batch_size": args.batch_size,
                        "cache_items": args.cache_items,
                        "max_abs_measured_snr_error_db": (
                            max(snr_errors) if snr_errors else 0.0
                        ),
                    },
                }
            )
            summary_path = output_dir / (
                "SMOKE_AUDIT.json" if smoke else "SAME_BANK_AUDIT.json"
            )
            atomic_create_json(summary_path, summary)
            completion_path = output_dir / "COMPLETE.json"
            completion = {
                "schema_version": RESULT_SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "filesystem_identity_policy": FILESYSTEM_IDENTITY_POLICY,
                "status": "SMOKE_PASS" if smoke else "RUN_AUDIT_PASS",
                "evaluation_role": EVALUATION_ROLE,
                "role_confirmation": EXPECTED_ROLE_CONFIRMATION,
                "attempt_id": args.attempt_id,
                "job_id": provenance["job_id"],
                "manifest_sha256": manifest_sha,
                "environment_fingerprint_sha256": provenance[
                    "environment_fingerprint_sha256"
                ],
                "environment_fingerprint": provenance["environment_fingerprint"],
                "environment": provenance["environment"],
                "submitted_runner": provenance["submitted_runner"],
                "results": pinned_file(results_path, "Evaluation results"),
                "long_results": pinned_file(long_path, "Long evaluation results"),
                "summary": pinned_file(summary_path, "Evaluation summary"),
            }
            atomic_create_json(completion_path, completion)
            completion["attempt_complete"] = pinned_file(
                completion_path, "Attempt completion record"
            )
            publication = publish_canonical_marker(
                external_root,
                smoke=smoke,
                completion=completion,
                manifest_path=manifest_path,
                manifest_sha256=manifest_sha,
                submitted_runner_sha256=provenance["submitted_runner_sha256"],
                frozen_runner_sha256=provenance["frozen_runner_sha256"],
                slurm_job_id=provenance["job_id"],
                environment_fingerprint_sha256=provenance[
                    "environment_fingerprint_sha256"
                ],
                smoke_parent=(
                    smoke_gate["marker_record"] if smoke_gate is not None else None
                ),
            )
            return {**completion, "publication": publication["marker_record"]}
        except Exception as error:
            with contextlib.suppress(Exception):
                atomic_create_json(
                    output_dir / "FAILED.json",
                    {
                        "schema_version": RESULT_SCHEMA_VERSION,
                        "protocol_id": PROTOCOL_ID,
                        "filesystem_identity_policy": FILESYSTEM_IDENTITY_POLICY,
                        "status": "FAILED",
                        "evaluation_role": EVALUATION_ROLE,
                        "attempt_id": args.attempt_id,
                        "job_id": str(args.job_id),
                        "failed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "error_type": type(error).__name__,
                        "error": str(error),
                    },
                )
            raise


def _add_inventory_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", required=True, type=pathlib.Path)
    parser.add_argument("--run-root", required=True, type=pathlib.Path)
    parser.add_argument("--external-root", required=True, type=pathlib.Path)
    parser.add_argument("--recovery-tool", required=True, type=pathlib.Path)
    parser.add_argument("--sbatch", required=True, type=pathlib.Path)
    parser.add_argument("--expected-valbest-sha256", required=True)
    parser.add_argument("--author-config", type=pathlib.Path)
    parser.add_argument("--author-checkpoint", type=pathlib.Path)


def _add_frozen_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--external-root", required=True, type=pathlib.Path)
    parser.add_argument("--manifest", required=True, type=pathlib.Path)
    parser.add_argument("--expected-manifest-sha256", required=True)


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    _add_frozen_arguments(parser)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--confirm-role", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--submitted-runner", required=True, type=pathlib.Path)
    parser.add_argument("--submitted-runner-sha256", required=True)
    parser.add_argument(
        "--environment-fingerprint", required=True, type=pathlib.Path
    )
    parser.add_argument("--environment-fingerprint-sha256", required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--cache-items", type=int, default=512)
    parser.add_argument("--allow-cpu", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Locked three-model same-bank final evaluation"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit_parser = subparsers.add_parser("audit-inputs")
    _add_inventory_arguments(audit_parser)
    freeze_parser = subparsers.add_parser("freeze-inputs")
    _add_inventory_arguments(freeze_parser)
    freeze_parser.add_argument("--manifest", required=True, type=pathlib.Path)
    check_parser = subparsers.add_parser("check-only")
    _add_frozen_arguments(check_parser)
    smoke_parser = subparsers.add_parser("smoke")
    _add_run_arguments(smoke_parser)
    smoke_parser.add_argument("--trials", type=int, default=32)
    run_parser = subparsers.add_parser("run-audit")
    _add_run_arguments(run_parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "audit-inputs":
            result = audit_inputs(args)
        elif args.command == "freeze-inputs":
            result = audit_inputs(args)
            result["status"] = "FROZEN"
            result["frozen_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            manifest = _absolute_no_resolve(args.manifest)
            external_root = safe_directory(args.external_root, "External evaluation root")
            layout = initialize_freeze_layout(external_root, manifest, result)
            result = {
                "status": "FROZEN",
                "manifest": str(manifest),
                "manifest_sha256": layout["manifest"]["sha256"],
                "evaluation_lock": layout["evaluation_lock"],
            }
        elif args.command == "check-only":
            result = check_only(args)
        elif args.command == "smoke":
            if args.batch_size <= 0 or args.cache_items <= 0:
                raise EvaluationError("batch-size/cache-items must be positive")
            result = run_evaluation(args, smoke=True)
        elif args.command == "run-audit":
            if args.batch_size <= 0 or args.cache_items <= 0:
                raise EvaluationError("batch-size/cache-items must be positive")
            result = run_evaluation(args, smoke=False)
        else:
            raise AssertionError(args.command)
    except (EvaluationError, FileExistsError, OSError, ValueError, KeyError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

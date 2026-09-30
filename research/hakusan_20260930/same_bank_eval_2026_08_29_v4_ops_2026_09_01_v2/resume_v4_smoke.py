#!/usr/bin/env python3
"""Fail-closed, one-process recovery of the frozen v4 smoke submission.

This program is an operations wrapper only.  It does not implement or alter
scientific evaluation logic.  It re-runs the frozen evaluator's read-only
checks, proves that the compute-node check made no change to the frozen v4
tree, and then calls ``sbatch`` at most once.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import fcntl
import getpass
import hashlib
import json
import os
import pathlib
import pwd
import re
import secrets
import stat
import subprocess
import sys
from typing import Any, Iterator, Mapping, Sequence


PROTOCOL_ID = "fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1"
FILESYSTEM_IDENTITY_POLICY = (
    "cross_invocation_path_size_sha_exact__dev_inode_diagnostic"
)
ANALYSIS_STATUS = "REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST"
EXPECTED_MANIFEST_SHA256 = (
    "1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5"
)
EXPECTED_LOCK_SHA256 = (
    "63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710"
)
EXPECTED_EVALUATOR_SHA256 = (
    "31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4"
)
EXPECTED_RUNNER_SHA256 = (
    "b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495"
)
EXPECTED_RECOVERY_SHA256 = (
    "f7b682f61920d21d181a4721a32e87d4dc216d07df3d476392ee2de41f967959"
)
EXPECTED_VALBEST_SHA256 = (
    "853069b8a9c037bc11d373b1d76e63f3e5c9f7601fad724a6ce7e7d7840d5e14"
)
EXPECTED_LEGACY_HELPER_SHA256 = (
    "245e272a6c6b953ae3a8007f6a042b7b6aa906fef173d5deed906ec542b943c4"
)
EXPECTED_LOCK_NONCE = "6f7488407ef4b2193ae48efffa29a2dc40990318004a7219af2a80a2ef265546"
MAX_CHECK_OUTPUT_BYTES = 8 * 1024 * 1024
SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
JOB_OUTPUT_PATTERN = re.compile(r"([0-9]+)(?:;[A-Za-z0-9_.-]+)?\Z")


class GateError(RuntimeError):
    """A prerequisite failed before a trustworthy smoke submission."""


class AmbiguousSubmissionError(GateError):
    """An sbatch call may have happened, so automatic retry is forbidden."""


@dataclasses.dataclass(frozen=True)
class CommandOutcome:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclasses.dataclass(frozen=True)
class Fingerprint:
    tree_sha256: str
    content_sha256: str

    def validate(self) -> None:
        if not SHA_PATTERN.fullmatch(self.tree_sha256):
            raise GateError("invalid tree fingerprint")
        if not SHA_PATTERN.fullmatch(self.content_sha256):
            raise GateError("invalid content fingerprint")


@dataclasses.dataclass(frozen=True)
class WorkflowResult:
    status: str
    job_id: str


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise GateError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_nonfinite(value: str) -> None:
    raise GateError(f"non-finite JSON number: {value}")


def _strict_json_loads(raw: bytes, *, label: str) -> Any:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise GateError(f"{label} is not strict UTF-8") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except GateError:
        raise
    except json.JSONDecodeError as exc:
        raise GateError(f"{label} is not valid JSON") from exc


def parse_check_output(raw: bytes, expected_manifest_sha256: str) -> dict[str, Any]:
    """Return the one final CHECK_PASS object from evaluator stdout.

    Diagnostic lines before the object are allowed.  A second valid top-level
    JSON object, trailing non-whitespace, duplicate keys, non-finite values,
    invalid UTF-8, or any semantic mismatch is rejected.
    """

    if not SHA_PATTERN.fullmatch(expected_manifest_sha256):
        raise GateError("expected manifest SHA-256 is invalid")
    if not raw:
        raise GateError("check-only stdout is empty")
    if len(raw) > MAX_CHECK_OUTPUT_BYTES:
        raise GateError("check-only stdout exceeds the reviewed size limit")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise GateError("check-only stdout is not strict UTF-8") from exc

    decoder = json.JSONDecoder(
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_nonfinite,
    )
    documents: list[tuple[int, int, Any]] = []
    for match in re.finditer(r"(?m)^[ \t]*(?P<brace>\{)", text):
        start = match.start("brace")
        try:
            value, relative_end = decoder.raw_decode(text[start:])
        except GateError:
            raise
        except json.JSONDecodeError:
            continue
        end = start + relative_end
        documents.append((start, end, value))

    trailing = [document for document in documents if not text[document[1] :].strip()]
    if len(trailing) != 1:
        raise GateError(
            "expected exactly one trailing JSON object in check-only stdout"
        )
    final_start, final_end, value = trailing[0]
    for start, end, _ in documents:
        if (start, end) == (final_start, final_end):
            continue
        if final_start < start and end <= final_end:
            continue
        raise GateError("multiple top-level JSON objects in check-only stdout")
    if not isinstance(value, dict):
        raise GateError("check-only JSON must be an object")
    if value.get("status") != "CHECK_PASS":
        raise GateError("check-only status is not CHECK_PASS")
    if value.get("protocol_id") != PROTOCOL_ID:
        raise GateError("check-only protocol mismatch")
    if value.get("filesystem_identity_policy") != FILESYSTEM_IDENTITY_POLICY:
        raise GateError("check-only top-level filesystem policy mismatch")
    if value.get("manifest_sha256") != expected_manifest_sha256:
        raise GateError("check-only manifest SHA-256 mismatch")
    verification = value.get("verification")
    if not isinstance(verification, dict):
        raise GateError("check-only verification object is missing")
    if verification.get("filesystem_identity_policy") != FILESYSTEM_IDENTITY_POLICY:
        raise GateError("check-only verification filesystem policy mismatch")
    verified_files = verification.get("verified_files")
    if type(verified_files) is not int or verified_files != 24:
        raise GateError("check-only did not verify exactly 24 files")
    if verification.get("fresh_recovery_status") != "CHECK_PASS":
        raise GateError("fresh recovery verification did not pass")
    return value


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _atomic_create(path: pathlib.Path, payload: Mapping[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        data = _canonical_json_bytes(payload)
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written <= 0:
                raise OSError("short write while creating durable operations state")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class SubmissionJournal:
    """Durable at-most-once state outside the frozen evaluation root."""

    def __init__(self, state_root: pathlib.Path) -> None:
        self.state_root = pathlib.Path(state_root)
        if os.path.lexists(self.state_root):
            info = os.lstat(self.state_root)
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise GateError("operations state root is not a real directory")
        else:
            self.state_root.mkdir(mode=0o700)
            parent_descriptor = os.open(
                self.state_root.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(parent_descriptor)
            finally:
                os.close(parent_descriptor)
        self.lock_path = self.state_root / "workflow.lock"
        self.intent_path = self.state_root / "intent.json"
        self.receipt_path = self.state_root / "receipt.json"

    @contextlib.contextmanager
    def exclusive(self) -> Iterator[None]:
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.lock_path, flags, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise GateError("another v4 recovery process is active") from exc
            yield
        finally:
            os.close(descriptor)

    def _read_record(self, path: pathlib.Path, label: str) -> dict[str, Any] | None:
        if not os.path.lexists(path):
            return None
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise GateError(f"{label} is not a regular non-symlink file")
        value = _strict_json_loads(
            _stable_small_bytes(path, maximum_size=64 * 1024), label=label
        )
        if not isinstance(value, dict):
            raise GateError(f"{label} is not a JSON object")
        return value

    def receipt(self) -> dict[str, Any] | None:
        value = self._read_record(self.receipt_path, "submission receipt")
        if value is None:
            return None
        job_id = value.get("job_id")
        nonce = value.get("intent_nonce")
        raw_stdout = value.get("sbatch_stdout")
        stdout_match = (
            JOB_OUTPUT_PATTERN.fullmatch(raw_stdout)
            if isinstance(raw_stdout, str)
            else None
        )
        if (
            value.get("status") != "SMOKE_SUBMITTED"
            or not isinstance(job_id, str)
            or not job_id.isdigit()
            or not isinstance(nonce, str)
            or not SHA_PATTERN.fullmatch(nonce)
            or value.get("protocol_id") != PROTOCOL_ID
            or value.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
            or stdout_match is None
            or stdout_match.group(1) != job_id
        ):
            raise GateError("submission receipt is invalid")
        return value

    def intent(self) -> dict[str, Any] | None:
        value = self._read_record(self.intent_path, "submission intent")
        if value is None:
            return None
        nonce = value.get("intent_nonce")
        if (
            value.get("status") != "SUBMISSION_INTENT"
            or not isinstance(nonce, str)
            or not SHA_PATTERN.fullmatch(nonce)
            or value.get("protocol_id") != PROTOCOL_ID
            or value.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        ):
            raise GateError("submission intent is invalid")
        return value

    def begin(self, nonce: str) -> None:
        if not SHA_PATTERN.fullmatch(nonce):
            raise GateError("submission intent nonce is invalid")
        _atomic_create(
            self.intent_path,
            {
                "created_utc": _utc_now(),
                "intent_nonce": nonce,
                "manifest_sha256": EXPECTED_MANIFEST_SHA256,
                "protocol_id": PROTOCOL_ID,
                "status": "SUBMISSION_INTENT",
            },
        )

    def record_receipt(self, nonce: str, job_id: str, raw_stdout: str) -> None:
        if not SHA_PATTERN.fullmatch(nonce) or not job_id.isdigit():
            raise GateError("cannot record an invalid submission receipt")
        intent = self.intent()
        if intent is None or intent.get("intent_nonce") != nonce:
            raise GateError("cannot record receipt without the matching intent")
        _atomic_create(
            self.receipt_path,
            {
                "created_utc": _utc_now(),
                "intent_nonce": nonce,
                "job_id": job_id,
                "manifest_sha256": EXPECTED_MANIFEST_SHA256,
                "protocol_id": PROTOCOL_ID,
                "sbatch_stdout": raw_stdout,
                "status": "SMOKE_SUBMITTED",
            },
        )


class SmokeWorkflow:
    def __init__(
        self,
        *,
        gateway: Any,
        journal: SubmissionJournal,
        expected_manifest_sha256: str,
    ) -> None:
        if expected_manifest_sha256 != EXPECTED_MANIFEST_SHA256:
            raise GateError("workflow manifest SHA-256 is not the reviewed v4 value")
        self.gateway = gateway
        self.journal = journal
        self.expected_manifest_sha256 = expected_manifest_sha256

    @staticmethod
    def _require_command_pass(outcome: CommandOutcome, label: str) -> None:
        if outcome.returncode != 0:
            stderr = outcome.stderr.decode("utf-8", errors="replace").strip()
            raise GateError(
                f"{label} exited with {outcome.returncode}: {stderr[-1000:]}"
            )

    def execute(self) -> WorkflowResult:
        with self.journal.exclusive():
            receipt = self.journal.receipt()
            intent = self.journal.intent()
            if receipt is not None:
                if intent is None or receipt.get("intent_nonce") != intent.get(
                    "intent_nonce"
                ):
                    raise GateError("submission receipt has no matching durable intent")
                return WorkflowResult("ALREADY_SUBMITTED", str(receipt["job_id"]))
            if intent is not None:
                raise AmbiguousSubmissionError(
                    "an unresolved submission intent exists; inspect Slurm and do not retry"
                )

            self.gateway.verify_trust()
            login = self.gateway.run_login_check()
            self._require_command_pass(login, "login-node check-only")
            parse_check_output(login.stdout, self.expected_manifest_sha256)

            self.gateway.verify_trust()
            before = self.gateway.fingerprint()
            before.validate()

            compute_error: GateError | None = None
            try:
                compute = self.gateway.run_compute_check()
                self._require_command_pass(compute, "compute-node check-only")
                parse_check_output(compute.stdout, self.expected_manifest_sha256)
            except GateError as exc:
                compute_error = exc
            finally:
                after = self.gateway.fingerprint()
                after.validate()

            if before != after:
                raise GateError("compute check-only changed the frozen v4 tree")
            if compute_error is not None:
                raise compute_error

            self.gateway.verify_trust()
            evidence = self.gateway.smoke_evidence()
            if evidence:
                raise GateError(
                    "pre-existing smoke evidence blocks submission: "
                    + ", ".join(evidence)
                )
            active = self.gateway.query_active_jobs()
            self._require_command_pass(active, "active-job query")
            try:
                active_text = active.stdout.decode("utf-8", errors="strict").strip()
            except UnicodeDecodeError as exc:
                raise GateError("active-job query output is not UTF-8") from exc
            if active_text:
                raise GateError(
                    "an audattn_samebank_v4 job is already active: " + active_text
                )

            nonce = secrets.token_hex(32)
            self.journal.begin(nonce)
            try:
                submitted = self.gateway.submit_smoke(nonce)
            except BaseException as exc:
                raise AmbiguousSubmissionError(
                    "sbatch raised after durable intent; submission state is unknown"
                ) from exc
            if submitted.returncode != 0:
                raise AmbiguousSubmissionError(
                    "sbatch returned nonzero after durable intent; submission state is unknown"
                )
            try:
                raw_stdout = submitted.stdout.decode("utf-8", errors="strict").strip()
            except UnicodeDecodeError as exc:
                raise AmbiguousSubmissionError(
                    "sbatch output was not UTF-8; submission state is unknown"
                ) from exc
            match = JOB_OUTPUT_PATTERN.fullmatch(raw_stdout)
            if match is None:
                raise AmbiguousSubmissionError(
                    "sbatch returned an invalid Job ID; submission state is unknown"
                )
            job_id = match.group(1)
            try:
                self.journal.record_receipt(nonce, job_id, raw_stdout)
            except BaseException as exc:
                raise AmbiguousSubmissionError(
                    "sbatch succeeded but durable receipt failed; do not retry"
                ) from exc
            return WorkflowResult("SMOKE_SUBMITTED", job_id)


@dataclasses.dataclass(frozen=True)
class ReviewedContract:
    home: pathlib.Path
    user: str
    project_root: pathlib.Path
    run_root: pathlib.Path
    external_root: pathlib.Path
    tool: pathlib.Path
    runner: pathlib.Path
    python: pathlib.Path
    recovery_tool: pathlib.Path
    valbest: pathlib.Path
    manifest: pathlib.Path
    lock: pathlib.Path
    operations_root: pathlib.Path
    operations_script: pathlib.Path

    @classmethod
    def production(cls) -> "ReviewedContract":
        home = pathlib.Path("/home/s2510040")
        project = home / "selective_listening_repro/code/auditory_attention"
        run = project / ("selftrain/experiments/runs/fullpilot4_accum9_20260815_181000")
        external = home / "audattn_external_eval/same_bank_2026-08-29_v4"
        operations_root = home / (
            "audattn_external_eval_ops/same_bank_v4_2026-09-01_v2"
        )
        return cls(
            home=home,
            user="s2510040",
            project_root=project,
            run_root=run,
            external_root=external,
            tool=external / "tools/locked_same_bank_eval.py",
            runner=external / "tools/run_locked_same_bank_eval.sbatch",
            python=home / "miniconda3/envs/attn/bin/python",
            recovery_tool=home
            / "audattn_recovery/2026-08-28/recover_full_completion_2026_08_28.py",
            valbest=run / "full/checkpoints/epoch=33-step=59024.ckpt",
            manifest=external / "input_freeze.json",
            lock=external / "state/evaluation.lock",
            operations_root=operations_root,
            operations_script=operations_root / "resume_v4_smoke.py",
        )

    def clean_environment(self) -> dict[str, str]:
        return {
            "HOME": str(self.home),
            "PATH": f"{self.home}/miniconda3/envs/attn/bin:/usr/local/bin:/usr/bin:/bin",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "CV_CLIPS": str(self.project_root / "cv_train/clips"),
        }

    def scheduler_client_environment(self) -> dict[str, str]:
        return {
            "HOME": str(self.home),
            "LC_ALL": "C",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "USER": self.user,
        }

    def check_argv(self) -> tuple[str, ...]:
        return (
            str(self.python),
            "-I",
            str(self.tool),
            "check-only",
            "--external-root",
            str(self.external_root),
            "--manifest",
            str(self.manifest),
            "--expected-manifest-sha256",
            EXPECTED_MANIFEST_SHA256,
        )

    def srun_argv(self) -> tuple[str, ...]:
        env = self.clean_environment()
        assignments = tuple(f"{key}={value}" for key, value in env.items())
        return (
            "/usr/bin/srun",
            "-p",
            "GPU-1A",
            "-N",
            "1",
            "-G",
            "1",
            "--ntasks=1",
            "--cpus-per-task=8",
            "-t",
            "01:00:00",
            "/usr/bin/env",
            "-i",
            *assignments,
            *self.check_argv(),
        )

    def sbatch_argv(self, nonce: str) -> tuple[str, ...]:
        if not SHA_PATTERN.fullmatch(nonce):
            raise GateError("submission nonce is invalid")
        exports = (
            "EVAL_ACTION=smoke,"
            f"EXTERNAL_ROOT={self.external_root},"
            f"INPUT_MANIFEST={self.manifest},"
            f"EXPECTED_MANIFEST_SHA256={EXPECTED_MANIFEST_SHA256}"
        )
        return (
            "/usr/bin/sbatch",
            "--parsable",
            f"--comment=audattn-v4-smoke-resume-{nonce[:12]}",
            f"--export={exports}",
            str(self.runner),
        )


def _stable_sha256(path: pathlib.Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened_before = os.fstat(descriptor)
        named_before = os.lstat(path)
        if not stat.S_ISREG(opened_before.st_mode) or stat.S_ISLNK(
            named_before.st_mode
        ):
            raise GateError(f"not a regular non-symlink file: {path}")
        if (opened_before.st_dev, opened_before.st_ino) != (
            named_before.st_dev,
            named_before.st_ino,
        ):
            raise GateError(f"file identity changed while opening: {path}")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        opened_after = os.fstat(descriptor)
        named_after = os.lstat(path)
        before = (
            opened_before.st_dev,
            opened_before.st_ino,
            opened_before.st_size,
            opened_before.st_mtime_ns,
        )
        after = (
            opened_after.st_dev,
            opened_after.st_ino,
            opened_after.st_size,
            opened_after.st_mtime_ns,
        )
        named = (
            named_after.st_dev,
            named_after.st_ino,
            named_after.st_size,
            named_after.st_mtime_ns,
        )
        if before != after or after != named:
            raise GateError(f"file changed while hashing: {path}")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _stable_small_bytes(path: pathlib.Path, *, maximum_size: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened_before = os.fstat(descriptor)
        named_before = os.lstat(path)
        if not stat.S_ISREG(opened_before.st_mode) or stat.S_ISLNK(
            named_before.st_mode
        ):
            raise GateError(f"not a regular non-symlink file: {path}")
        if opened_before.st_size > maximum_size:
            raise GateError(f"reviewed JSON file is unexpectedly large: {path}")
        if (opened_before.st_dev, opened_before.st_ino) != (
            named_before.st_dev,
            named_before.st_ino,
        ):
            raise GateError(f"file identity changed while opening: {path}")

        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum_size:
                raise GateError(f"reviewed JSON grew while reading: {path}")
            chunks.append(chunk)

        opened_after = os.fstat(descriptor)
        named_after = os.lstat(path)
        before = (
            opened_before.st_dev,
            opened_before.st_ino,
            opened_before.st_size,
            opened_before.st_mtime_ns,
        )
        after = (
            opened_after.st_dev,
            opened_after.st_ino,
            opened_after.st_size,
            opened_after.st_mtime_ns,
        )
        named = (
            named_after.st_dev,
            named_after.st_ino,
            named_after.st_size,
            named_after.st_mtime_ns,
        )
        if before != after or after != named:
            raise GateError(f"file changed while reading: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _assert_no_symlink_components(path: pathlib.Path) -> None:
    current = pathlib.Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode):
            raise GateError(f"symlink path component is forbidden: {current}")


def validate_legacy_attempt_state(
    legacy_root: pathlib.Path,
    expected_helper_sha256: str,
) -> None:
    """Prove that the reviewed legacy helper failed before any submission state."""

    if not SHA_PATTERN.fullmatch(expected_helper_sha256):
        raise GateError("legacy helper SHA-256 is invalid")
    _assert_no_symlink_components(legacy_root)
    root_info = os.lstat(legacy_root)
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise GateError("legacy operations root is not a regular directory")

    expected_root_entries = {"resume_state", "resume_v4_smoke.py"}
    if {entry.name for entry in os.scandir(legacy_root)} != expected_root_entries:
        raise GateError("legacy operations root layout changed")

    helper = legacy_root / "resume_v4_smoke.py"
    helper_info = os.lstat(helper)
    if not stat.S_ISREG(helper_info.st_mode) or stat.S_ISLNK(helper_info.st_mode):
        raise GateError("legacy helper is not a regular non-symlink file")
    if _stable_sha256(helper) != expected_helper_sha256:
        raise GateError("legacy helper SHA-256 changed")

    state_root = legacy_root / "resume_state"
    state_info = os.lstat(state_root)
    if not stat.S_ISDIR(state_info.st_mode) or stat.S_ISLNK(state_info.st_mode):
        raise GateError("legacy resume state is not a regular directory")
    if {entry.name for entry in os.scandir(state_root)} != {"workflow.lock"}:
        raise GateError("legacy submission state is not provably empty")

    workflow_lock = state_root / "workflow.lock"
    lock_info = os.lstat(workflow_lock)
    if (
        not stat.S_ISREG(lock_info.st_mode)
        or stat.S_ISLNK(lock_info.st_mode)
        or lock_info.st_size != 0
    ):
        raise GateError("legacy workflow lock is invalid or nonempty")


def validate_operations_location(
    script_path: pathlib.Path,
    operations_root: pathlib.Path,
    external_root: pathlib.Path,
) -> None:
    reviewed = pathlib.Path(
        "/home/s2510040/audattn_external_eval_ops/same_bank_v4_2026-09-01_v2"
    )
    expected_script = reviewed / "resume_v4_smoke.py"
    if operations_root != reviewed or script_path != expected_script:
        raise GateError("operations helper is not at the reviewed external ops path")
    try:
        common = pathlib.Path(os.path.commonpath((operations_root, external_root)))
    except ValueError as exc:
        raise GateError("cannot compare operations and frozen roots") from exc
    if common in (operations_root, external_root):
        raise GateError("operations state must be disjoint from the frozen v4 root")


class ProductionGateway:
    def __init__(self, contract: ReviewedContract) -> None:
        self.contract = contract

    @staticmethod
    def _run(
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: pathlib.Path | None = None,
        input_bytes: bytes | None = None,
        timeout: float | None = None,
    ) -> CommandOutcome:
        completed = subprocess.run(
            tuple(argv),
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            check=False,
            env=None if env is None else dict(env),
            cwd=None if cwd is None else str(cwd),
            timeout=timeout,
        )
        return CommandOutcome(completed.returncode, completed.stdout, completed.stderr)

    @staticmethod
    def _require_pipeline(outcome: CommandOutcome, label: str) -> bytes:
        if outcome.returncode != 0:
            stderr = outcome.stderr.decode("utf-8", errors="replace").strip()
            raise GateError(f"{label} failed: {stderr[-1000:]}")
        return outcome.stdout

    def verify_trust(self) -> None:
        current_pw = pwd.getpwuid(os.getuid())
        if current_pw.pw_name != self.contract.user or current_pw.pw_dir != str(
            self.contract.home
        ):
            raise GateError(
                f"must run as reviewed account {self.contract.user}; got {getpass.getuser()}"
            )
        if self.contract.external_root != pathlib.Path(
            "/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4"
        ):
            raise GateError("external root is not the reviewed v4 path")

        validate_operations_location(
            self.contract.operations_script,
            self.contract.operations_root,
            self.contract.external_root,
        )
        validate_legacy_attempt_state(
            pathlib.Path(
                "/home/s2510040/audattn_external_eval_ops/same_bank_v4_2026-09-01"
            ),
            EXPECTED_LEGACY_HELPER_SHA256,
        )

        for executable in (
            pathlib.Path("/usr/bin/env"),
            pathlib.Path("/usr/bin/find"),
            pathlib.Path("/usr/bin/sbatch"),
            pathlib.Path("/usr/bin/sha256sum"),
            pathlib.Path("/usr/bin/sort"),
            pathlib.Path("/usr/bin/squeue"),
            pathlib.Path("/usr/bin/srun"),
            pathlib.Path("/usr/bin/xargs"),
        ):
            _assert_no_symlink_components(executable)
            info = os.lstat(executable)
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or not os.access(executable, os.X_OK)
            ):
                raise GateError(f"required executable is invalid: {executable}")
        _assert_no_symlink_components(self.contract.python.parent)
        python_info = os.stat(self.contract.python, follow_symlinks=True)
        if not stat.S_ISREG(python_info.st_mode) or not os.access(
            self.contract.python, os.X_OK
        ):
            raise GateError(f"reviewed Python is invalid: {self.contract.python}")

        required_dirs = (
            self.contract.external_root,
            self.contract.external_root / "logs",
            self.contract.external_root / "state",
            self.contract.external_root / "attempts",
            self.contract.external_root / "attempts/smoke",
            self.contract.external_root / "attempts/audit",
            self.contract.external_root / "submitted_runners",
            self.contract.external_root / "tools",
        )
        for directory in required_dirs:
            _assert_no_symlink_components(directory)
            info = os.lstat(directory)
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise GateError(f"required directory is invalid: {directory}")

        expected_files = {
            self.contract.tool: EXPECTED_EVALUATOR_SHA256,
            self.contract.runner: EXPECTED_RUNNER_SHA256,
            self.contract.recovery_tool: EXPECTED_RECOVERY_SHA256,
            self.contract.valbest: EXPECTED_VALBEST_SHA256,
            self.contract.manifest: EXPECTED_MANIFEST_SHA256,
            self.contract.lock: EXPECTED_LOCK_SHA256,
        }
        for path, expected in expected_files.items():
            _assert_no_symlink_components(path)
            if _stable_sha256(path) != expected:
                raise GateError(f"reviewed SHA-256 mismatch: {path}")

        manifest_bytes = _stable_small_bytes(
            self.contract.manifest, maximum_size=1024 * 1024
        )
        if hashlib.sha256(manifest_bytes).hexdigest() != EXPECTED_MANIFEST_SHA256:
            raise GateError("frozen manifest changed before parsing")
        manifest = _strict_json_loads(manifest_bytes, label="frozen manifest")
        if not isinstance(manifest, dict):
            raise GateError("frozen manifest is not an object")
        if manifest.get("schema_version") != 1 or manifest.get("status") != "FROZEN":
            raise GateError("frozen manifest status/schema mismatch")
        if manifest.get("protocol_id") != PROTOCOL_ID:
            raise GateError("frozen manifest protocol mismatch")
        if manifest.get("filesystem_identity_policy") != FILESYSTEM_IDENTITY_POLICY:
            raise GateError("frozen manifest filesystem policy mismatch")
        if manifest.get("evaluation_role") != ANALYSIS_STATUS:
            raise GateError("frozen manifest analysis boundary mismatch")
        roots = manifest.get("roots")
        if not isinstance(roots, dict) or roots.get("external_root") != str(
            self.contract.external_root
        ):
            raise GateError("frozen manifest external root mismatch")

        lock_bytes = _stable_small_bytes(self.contract.lock, maximum_size=64 * 1024)
        if hashlib.sha256(lock_bytes).hexdigest() != EXPECTED_LOCK_SHA256:
            raise GateError("evaluation lock changed before parsing")
        lock = _strict_json_loads(lock_bytes, label="evaluation lock")
        expected_lock = {
            "schema_version": 1,
            "protocol_id": PROTOCOL_ID,
            "filesystem_identity_policy": FILESYSTEM_IDENTITY_POLICY,
            "purpose": "cross_node_evaluation_flock_identity",
            "external_root": str(self.contract.external_root),
            "lock_nonce": EXPECTED_LOCK_NONCE,
        }
        if lock != expected_lock:
            raise GateError("evaluation lock payload mismatch")

    def run_login_check(self) -> CommandOutcome:
        self.verify_trust()
        return self._run(
            self.contract.check_argv(),
            env=self.contract.clean_environment(),
            timeout=1800,
        )

    def fingerprint(self) -> Fingerprint:
        locale_env = {"LC_ALL": "C", "PATH": "/usr/bin:/bin"}
        tree_find = self._run(
            (
                "/usr/bin/find",
                ".",
                "-xdev",
                "-printf",
                "%P\t%y\t%m\t%s\t%T@\t%D\t%i\t%l\\0",
            ),
            env=locale_env,
            cwd=self.contract.external_root,
        )
        tree_raw = self._require_pipeline(tree_find, "tree find")
        tree_sort = self._run(
            ("/usr/bin/sort", "-z"), env=locale_env, input_bytes=tree_raw
        )
        tree_sorted = self._require_pipeline(tree_sort, "tree sort")
        tree_sum = self._run(
            ("/usr/bin/sha256sum",), env=locale_env, input_bytes=tree_sorted
        )
        tree_digest = self._parse_sha_output(
            self._require_pipeline(tree_sum, "tree sha256sum"), "tree"
        )

        content_find = self._run(
            ("/usr/bin/find", ".", "-xdev", "-type", "f", "-print0"),
            env=locale_env,
            cwd=self.contract.external_root,
        )
        content_raw = self._require_pipeline(content_find, "content find")
        content_sort = self._run(
            ("/usr/bin/sort", "-z"), env=locale_env, input_bytes=content_raw
        )
        content_sorted = self._require_pipeline(content_sort, "content sort")
        file_sums = self._run(
            ("/usr/bin/xargs", "-0", "-r", "/usr/bin/sha256sum"),
            env=locale_env,
            cwd=self.contract.external_root,
            input_bytes=content_sorted,
        )
        file_sum_bytes = self._require_pipeline(file_sums, "content file hashing")
        content_sum = self._run(
            ("/usr/bin/sha256sum",), env=locale_env, input_bytes=file_sum_bytes
        )
        content_digest = self._parse_sha_output(
            self._require_pipeline(content_sum, "content aggregate hashing"), "content"
        )
        return Fingerprint(tree_digest, content_digest)

    @staticmethod
    def _parse_sha_output(raw: bytes, label: str) -> str:
        try:
            text = raw.decode("ascii", errors="strict").strip()
        except UnicodeDecodeError as exc:
            raise GateError(f"{label} SHA output is not ASCII") from exc
        digest = text.split(maxsplit=1)[0] if text else ""
        if not SHA_PATTERN.fullmatch(digest):
            raise GateError(f"{label} SHA output is invalid")
        return digest

    def run_compute_check(self) -> CommandOutcome:
        self.verify_trust()
        return self._run(
            self.contract.srun_argv(),
            env=self.contract.scheduler_client_environment(),
            timeout=24 * 60 * 60,
        )

    def query_active_jobs(self) -> CommandOutcome:
        return self._run(
            (
                "/usr/bin/squeue",
                "-h",
                "-u",
                self.contract.user,
                "-n",
                "audattn_samebank_v4",
                "-o",
                "%A|%T|%j",
            ),
            env=self.contract.scheduler_client_environment(),
            timeout=120,
        )

    def smoke_evidence(self) -> tuple[str, ...]:
        paths: list[pathlib.Path] = []
        for directory in (
            self.contract.external_root / "logs",
            self.contract.external_root / "submitted_runners",
            self.contract.external_root / "attempts/smoke",
            self.contract.external_root / "attempts/audit",
        ):
            paths.extend(directory.iterdir())
        for marker in (
            self.contract.external_root / "state/SMOKE_PASS.json",
            self.contract.external_root / "state/SAME_BANK_AUDIT_PUBLISHED.json",
        ):
            if os.path.lexists(marker):
                paths.append(marker)
        state = self.contract.external_root / "state"
        for path in state.iterdir():
            if path.name != "evaluation.lock":
                paths.append(path)
        return tuple(
            sorted(
                {str(path.relative_to(self.contract.external_root)) for path in paths}
            )
        )

    def submit_smoke(self, intent_nonce: str) -> CommandOutcome:
        return self._run(
            self.contract.sbatch_argv(intent_nonce),
            env=self.contract.scheduler_client_environment(),
            timeout=120,
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Re-close the frozen v4 login/compute zero-write gates and submit one smoke."
        )
    )
    parser.add_argument(
        "--confirm-action",
        required=True,
        choices=("RESUME_V4_SMOKE",),
        help="Explicit confirmation for the one permitted operation.",
    )
    parser.add_argument(
        "--confirm-manifest-sha256",
        required=True,
        help="Must equal the human-reviewed frozen v4 manifest SHA-256.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.confirm_manifest_sha256 != EXPECTED_MANIFEST_SHA256:
        print(
            "STOP: manifest confirmation does not match the reviewed value",
            file=sys.stderr,
        )
        return 2
    contract = ReviewedContract.production()
    script_path = pathlib.Path(__file__).absolute()
    state_root = contract.operations_root / "resume_state"
    try:
        validate_operations_location(
            script_path, contract.operations_root, contract.external_root
        )
        _assert_no_symlink_components(contract.operations_root)
        script_info = os.lstat(script_path)
        if not stat.S_ISREG(script_info.st_mode) or stat.S_ISLNK(script_info.st_mode):
            raise GateError("operations helper must be a regular non-symlink file")
        result = SmokeWorkflow(
            gateway=ProductionGateway(contract),
            journal=SubmissionJournal(state_root),
            expected_manifest_sha256=args.confirm_manifest_sha256,
        ).execute()
    except AmbiguousSubmissionError as exc:
        print(f"STOP_AMBIGUOUS: {exc}", file=sys.stderr)
        print(f"OPS_STATE={state_root}", file=sys.stderr)
        return 3
    except (GateError, OSError, subprocess.SubprocessError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "analysis_status": ANALYSIS_STATUS,
                "job_id": result.job_id,
                "manifest_sha256": EXPECTED_MANIFEST_SHA256,
                "next": "wait_for_smoke_then_verify_SMOKE_PASS",
                "protocol_id": PROTOCOL_ID,
                "status": result.status,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

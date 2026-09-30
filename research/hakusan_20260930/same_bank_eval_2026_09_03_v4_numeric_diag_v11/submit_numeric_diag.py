"""Fixed-contract submission, durable journal and read-only scheduler status."""

from __future__ import annotations

import base64
import argparse
import contextlib
import dataclasses
import fcntl
import hashlib
import json
import os
import pathlib
import re
import stat
import sys
import subprocess
import uuid
from collections.abc import Iterator


class SubmissionError(RuntimeError):
    """Definite refusal before a safe submission can be established."""


class AmbiguousSubmissionError(SubmissionError):
    """Intent exists; never automatically submit again."""


@dataclasses.dataclass(frozen=True)
class CommandOutcome:
    argv: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclasses.dataclass(frozen=True)
class SubmissionContract:
    root: pathlib.Path
    v4_root: pathlib.Path
    python: pathlib.Path
    sbatch: pathlib.Path = pathlib.Path("/usr/bin/sbatch")
    squeue: pathlib.Path = pathlib.Path("/usr/bin/squeue")
    sacct: pathlib.Path = pathlib.Path("/usr/bin/sacct")
    user: str = "s2510040"
    job_names: tuple[str, str] = ("audattn_samebank_v4", "audattn_v4_numdiag")
    confirm_action: str = "SUBMIT_V4_FORMAL40_NUMERIC_DIAGNOSTIC"
    confirm_v4_job_id: str = "646900"
    protocol: str = "formal40_batch_invariance_diag_20260903_v11"
    v4_manifest_sha256: str = (
        "1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5"
    )


PRODUCTION_CONTRACT = SubmissionContract(
    root=pathlib.Path(
        "/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v11"
    ),
    v4_root=pathlib.Path(
        "/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4"
    ),
    python=pathlib.Path("/home/s2510040/miniconda3/envs/attn/bin/python"),
)


def canonical(value) -> bytes:
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


def _hex(value, length):
    if type(value) is not str or not re.fullmatch(
        "[0-9a-f]{" + str(length) + "}", value
    ):
        raise SubmissionError("invalid hexadecimal submission identity")
    return value


def submission_argv(contract, sha, nonce):
    _hex(sha, 64)
    _hex(nonce, 32)
    return [
        str(contract.sbatch),
        "--parsable",
        "--export=NONE",
        f"--comment=audattn-v4-numdiag-{nonce[:12]}",
        str(contract.root / "tools/run_numeric_diag.sbatch"),
        sha,
        nonce,
    ]


def _directory_path(path):
    path = pathlib.Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise SubmissionError("journal path is not canonical absolute")
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise SubmissionError("journal parent is not a real directory")
    return path


def _dir_identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid


@contextlib.contextmanager
def directory(path) -> Iterator[int]:
    path = _directory_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        if opened.st_uid != os.getuid() or stat.S_IMODE(opened.st_mode) != 0o700:
            raise SubmissionError("journal directory must be private and user-owned")
        if _dir_identity(opened) != _dir_identity(path.lstat()):
            raise SubmissionError("journal parent changed while opening")
        yield fd
        _directory_path(path)
        if _dir_identity(opened) != _dir_identity(path.lstat()):
            raise SubmissionError("journal parent changed during operation")
    finally:
        os.close(fd)


def _file_identity(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _private_file(info):
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise SubmissionError("journal file must be private, owned and single-link")


def read_json(path):
    path = pathlib.Path(path)
    with directory(path.parent) as parent:
        fd = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
        )
        try:
            before = os.fstat(fd)
            _private_file(before)
            if not 0 < before.st_size <= 4 * 1024 * 1024:
                raise SubmissionError("journal record size is invalid")
            chunks = []
            remaining = before.st_size + 1
            while remaining:
                data = os.read(fd, min(remaining, 65536))
                if not data:
                    break
                chunks.append(data)
                remaining -= len(data)
            raw = b"".join(chunks)
            if (
                len(raw) != before.st_size
                or _file_identity(before) != _file_identity(os.fstat(fd))
                or _file_identity(before)
                != _file_identity(
                    os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                )
            ):
                raise SubmissionError("journal record changed while reading")
        finally:
            os.close(fd)
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or canonical(value) != raw:
            raise ValueError("noncanonical JSON")
    except (ValueError, UnicodeError) as error:
        raise SubmissionError("invalid canonical journal JSON") from error
    return value, raw


def atomic_create_json(path, value):
    """Publish once; fsync data then parent, reject any existing target."""
    path = pathlib.Path(path)
    raw = canonical(value)
    if len(raw) > 4 * 1024 * 1024:
        raise SubmissionError("journal record too large")
    with directory(path.parent) as parent:
        if os.path.lexists(path):
            raise FileExistsError(str(path))
        temporary = f".{path.name}.{uuid.uuid4().hex}.partial"
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
        try:
            view = memoryview(raw)
            while view:
                count = os.write(fd, view)
                if count <= 0:
                    raise SubmissionError("short journal write")
                view = view[count:]
            os.fsync(fd)
            info = os.fstat(fd)
            _private_file(info)
            if _file_identity(info) != _file_identity(
                os.stat(temporary, dir_fd=parent, follow_symlinks=False)
            ):
                raise SubmissionError("temporary journal identity changed")
            os.link(
                temporary,
                path.name,
                src_dir_fd=parent,
                dst_dir_fd=parent,
                follow_symlinks=False,
            )
        finally:
            os.close(fd)
            os.unlink(temporary, dir_fd=parent)
        os.fsync(parent)
    if read_json(path)[1] != raw:
        raise SubmissionError("published journal verification failed")


class SubmissionJournal:
    def __init__(self, contract):
        self.contract = contract
        self.state = contract.root / "state"
        self.fd = None
        self.lock_identity = None
        self.namespace = None

    def _boundary(self):
        result = {}
        for path in (self.contract.root, self.state):
            with directory(path) as fd:
                result[path] = _dir_identity(os.fstat(fd))
        return result

    def _guard(self):
        if self.fd is None:
            raise SubmissionError("journal mutation requires exclusive lock")
        if self._boundary() != self.namespace:
            raise SubmissionError("journal directory identity changed")
        opened = os.fstat(self.fd)
        _private_file(opened)
        if (
            opened.st_size != 0
            or _file_identity(opened) != self.lock_identity
            or _file_identity((self.state / "submission.lock").lstat())
            != self.lock_identity
        ):
            raise SubmissionError("submission lock identity changed")

    @contextlib.contextmanager
    def lock(self):
        if self.fd is not None:
            raise SubmissionError("submission lock is not reentrant")
        self.namespace = self._boundary()
        with directory(self.state) as parent:
            fd = None
            try:
                try:
                    fd = os.open(
                        "submission.lock",
                        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=parent,
                    )
                    os.fsync(fd)
                    os.fsync(parent)
                except FileExistsError:
                    fd = os.open(
                        "submission.lock",
                        os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                        dir_fd=parent,
                    )
                _private_file(os.fstat(fd))
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise SubmissionError("another submitter owns the lock") from error
                self.fd = fd
                self.lock_identity = _file_identity(os.fstat(fd))
                self._guard()
                yield self
            finally:
                self.fd = None
                self.lock_identity = None
                self.namespace = None
                if fd is not None:
                    os.close(fd)

    def _common(self, sha, runner_sha, nonce):
        return dict(
            schema_version=1,
            diagnostic_protocol=self.contract.protocol,
            input_freeze_sha256=_hex(sha, 64),
            runner_sha256=_hex(runner_sha, 64),
            intent_nonce=_hex(nonce, 32),
        )

    def _read_intent(self, sha=None, runner_sha=None):
        intent, raw = read_json(self.state / "INTENT.json")
        common = self._common(
            intent.get("input_freeze_sha256"),
            intent.get("runner_sha256"),
            intent.get("intent_nonce"),
        )
        if intent != dict(
            common,
            status="SUBMISSION_INTENT",
            argv=submission_argv(
                self.contract, common["input_freeze_sha256"], common["intent_nonce"]
            ),
        ):
            raise AmbiguousSubmissionError("intent schema or argv differs")
        if sha is not None and (
            common["input_freeze_sha256"] != sha
            or common["runner_sha256"] != runner_sha
        ):
            raise AmbiguousSubmissionError("intent is bound to other inputs")
        return intent, raw, common

    def classify(self, sha, runner_sha):
        """Read-only journal decision. Scheduler/terminal monitoring is separate."""
        _hex(sha, 64)
        _hex(runner_sha, 64)
        try:
            self._boundary()
            for name in ("attempts", "submitted_runners"):
                with directory(self.contract.root / name) as fd:
                    if os.listdir(fd):
                        raise AmbiguousSubmissionError(
                            "execution evidence exists; use status, never resubmit"
                        )
            with directory(self.state) as fd:
                names = set(os.listdir(fd))
            allowed = {
                "submission.lock",
                "INTENT.json",
                "SBATCH_RESPONSE.json",
                "SUBMISSION_RECEIPT.json",
            }
            if names - allowed:
                raise AmbiguousSubmissionError(
                    "terminal/partial/unrecognized submission evidence exists"
                )
            if "INTENT.json" not in names:
                if names - {"submission.lock"}:
                    raise AmbiguousSubmissionError("orphan response or receipt")
                return {"status": "NOT_SUBMITTED"}
            intent, intent_raw, common = self._read_intent(sha, runner_sha)
            if not {"SBATCH_RESPONSE.json", "SUBMISSION_RECEIPT.json"} <= names:
                raise AmbiguousSubmissionError(
                    "intent lacks a confirmed response and receipt"
                )
            response, response_raw = read_json(self.state / "SBATCH_RESPONSE.json")
            receipt, receipt_raw = read_json(self.state / "SUBMISSION_RECEIPT.json")
            job = self._response_job(response, common, intent["argv"])
            expected = dict(
                common,
                status="SUBMITTED",
                job_id=job,
                intent_record_sha256=hashlib.sha256(intent_raw).hexdigest(),
                response_record_sha256=hashlib.sha256(response_raw).hexdigest(),
            )
            if receipt != expected:
                raise AmbiguousSubmissionError(
                    "receipt does not bind response and intent"
                )
            # Re-read to avoid trusting mixed records across a concurrent change.
            if (
                read_json(self.state / "INTENT.json")[1] != intent_raw
                or read_json(self.state / "SBATCH_RESPONSE.json")[1] != response_raw
                or read_json(self.state / "SUBMISSION_RECEIPT.json")[1] != receipt_raw
            ):
                raise AmbiguousSubmissionError("journal changed during classification")
            return dict(status="ALREADY_SUBMITTED", receipt=receipt, job_id=job)
        except (OSError, ValueError, TypeError, KeyError, SubmissionError) as error:
            return dict(status="STOP_AMBIGUOUS", reason=str(error))

    def begin(self, sha, runner_sha, nonce):
        self._guard()
        if self.classify(sha, runner_sha)["status"] != "NOT_SUBMITTED":
            raise AmbiguousSubmissionError(
                "journal is not fresh; automatic submission is forbidden"
            )
        common = self._common(sha, runner_sha, nonce)
        value = dict(
            common,
            status="SUBMISSION_INTENT",
            argv=submission_argv(self.contract, sha, nonce),
        )
        atomic_create_json(self.state / "INTENT.json", value)
        self._guard()
        return value

    @staticmethod
    def _response_job(response, common, argv):
        try:
            stdout = base64.b64decode(response["stdout_b64"], validate=True)
            stderr = base64.b64decode(response["stderr_b64"], validate=True)
        except (ValueError, TypeError, KeyError) as error:
            raise AmbiguousSubmissionError("invalid raw scheduler response") from error
        expected = dict(
            common,
            status="SBATCH_RESPONSE",
            argv=argv,
            returncode=0,
            stdout_b64=base64.b64encode(stdout).decode("ascii"),
            stderr_b64="",
        )
        if (
            type(response.get("returncode")) is not int
            or response != expected
            or stderr
            or not re.fullmatch(rb"[1-9][0-9]{0,19}\n?", stdout)
        ):
            raise AmbiguousSubmissionError(
                "scheduler response is not unambiguous success"
            )
        return stdout.rstrip(b"\n").decode("ascii")

    def record_response(self, outcome):
        self._guard()
        intent, intent_raw, common = self._read_intent()
        if (
            not isinstance(outcome, CommandOutcome)
            or type(outcome.returncode) is not int
            or type(outcome.stdout) is not bytes
            or type(outcome.stderr) is not bytes
            or type(outcome.argv) is not tuple
            or any(type(x) is not str for x in outcome.argv)
        ):
            raise AmbiguousSubmissionError(
                "invalid scheduler outcome; intent remains unresolved"
            )
        response = dict(
            common,
            status="SBATCH_RESPONSE",
            argv=list(outcome.argv),
            returncode=outcome.returncode,
            stdout_b64=base64.b64encode(outcome.stdout).decode("ascii"),
            stderr_b64=base64.b64encode(outcome.stderr).decode("ascii"),
        )
        try:
            atomic_create_json(self.state / "SBATCH_RESPONSE.json", response)
            self._guard()
            job = self._response_job(response, common, intent["argv"])
            if read_json(self.state / "INTENT.json")[1] != intent_raw:
                raise AmbiguousSubmissionError("intent changed after external call")
            receipt = dict(
                common,
                status="SUBMITTED",
                job_id=job,
                intent_record_sha256=hashlib.sha256(intent_raw).hexdigest(),
                response_record_sha256=hashlib.sha256(canonical(response)).hexdigest(),
            )
            atomic_create_json(self.state / "SUBMISSION_RECEIPT.json", receipt)
            self._guard()
            return receipt
        except (OSError, ValueError, SubmissionError) as error:
            raise AmbiguousSubmissionError(
                "response/receipt incomplete; never automatically resubmit: "
                + str(error)
            ) from error

    def record_exception(self, error):
        self._guard()
        intent, _, common = self._read_intent()

        def raw(value):
            return (
                value
                if isinstance(value, bytes)
                else str(value).encode("utf-8")
                if value is not None
                else b""
            )

        response = dict(
            common,
            status="SBATCH_RESPONSE",
            argv=intent["argv"],
            returncode=None,
            stdout_b64=base64.b64encode(raw(getattr(error, "stdout", None))).decode(
                "ascii"
            ),
            stderr_b64=base64.b64encode(raw(getattr(error, "stderr", None))).decode(
                "ascii"
            ),
            exception_type=type(error).__name__,
            exception_message=str(error),
        )
        try:
            atomic_create_json(self.state / "SBATCH_RESPONSE.json", response)
        except (OSError, ValueError, SubmissionError) as persistence_error:
            raise AmbiguousSubmissionError(
                "external outcome unknown and response persistence failed"
            ) from persistence_error
        raise AmbiguousSubmissionError(
            "external outcome unknown; intent permanently blocks automatic retry"
        ) from error


PRODUCTION_FILES = (
    "diagnose_batch_invariance.py",
    "numeric_trace.py",
    "submit_numeric_diag.py",
    "run_numeric_diag.sbatch",
)
EVALUATION_ROLE = "REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST"
ACTIVE_STATES = frozenset(
    (
        "PENDING",
        "RUNNING",
        "CONFIGURING",
        "COMPLETING",
        "SUSPENDED",
        "RESIZING",
        "REQUEUED",
        "REQUEUE_FED",
        "REQUEUE_HOLD",
        "SIGNALING",
        "STAGE_OUT",
        "STOPPED",
        "SPECIAL_EXIT",
    )
)
TERMINAL_STATES = frozenset(
    (
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "TIMEOUT",
        "NODE_FAIL",
        "OUT_OF_MEMORY",
        "PREEMPTED",
        "BOOT_FAIL",
        "DEADLINE",
        "REVOKED",
    )
)


class SchedulerGateway:
    """Only fixed executables, raw bytes, clean environment and shell-free calls."""

    def __init__(self, contract):
        self.contract = contract

    def run(self, argv, *, timeout=60):
        argv = tuple(argv)
        c = self.contract
        if not argv or argv[0] not in {
            str(c.sbatch),
            str(c.squeue),
            str(c.sacct),
            str(c.python),
        }:
            raise SubmissionError("command is outside the fixed gateway")
        environment = dict(
            HOME=f"/home/{c.user}",
            PATH=f"{c.python.parent}:/usr/local/bin:/usr/bin:/bin",
            PYTHONNOUSERSITE="1",
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONHASHSEED="0",
            LC_ALL="C",
        )
        result = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=False,
            timeout=timeout,
            check=False,
            cwd=c.root,
            env=environment,
        )
        return CommandOutcome(argv, result.returncode, result.stdout, result.stderr)


def _source_digest(path):
    path = pathlib.Path(path)
    _directory_path(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise SubmissionError("frozen source is not a single-link regular file")
        digest, size = hashlib.sha256(), 0
        while True:
            raw = os.read(fd, 1024 * 1024)
            if not raw:
                break
            digest.update(raw)
            size += len(raw)
            if size > before.st_size:
                raise SubmissionError("frozen source grew during reading")
        if (
            size != before.st_size
            or _file_identity(before) != _file_identity(os.fstat(fd))
            or _file_identity(before) != _file_identity(path.lstat())
        ):
            raise SubmissionError("frozen source changed during reading")
        _directory_path(path.parent)
        return size, digest.hexdigest(), stat.S_IMODE(before.st_mode)
    finally:
        os.close(fd)


def _load_freeze(contract, expected_sha=None):
    """Stdlib trust bootstrap; full semantic/live input audit follows before submit."""
    root = contract.root
    with directory(root) as fd:
        if set(os.listdir(fd)) != {
            "tools",
            "state",
            "logs",
            "attempts",
            "submitted_runners",
            "input_freeze.json",
        }:
            raise SubmissionError("diagnostic root layout differs")
    for name in ("tools", "state", "logs", "attempts", "submitted_runners"):
        with directory(root / name):
            pass
    freeze, raw = read_json(root / "input_freeze.json")
    sha = hashlib.sha256(raw).hexdigest()
    if expected_sha is not None and sha != _hex(expected_sha, 64):
        raise SubmissionError("input freeze hash differs")
    if (
        type(freeze.get("schema_version")) is not int
        or freeze["schema_version"] != 1
        or freeze.get("status") != "INPUTS_FROZEN"
        or freeze.get("diagnostic_protocol") != contract.protocol
        or not isinstance(freeze.get("roots"), dict)
        or freeze["roots"].get("diagnostic_root") != str(root)
        or freeze["roots"].get("v4_root") != str(contract.v4_root)
    ):
        raise SubmissionError("input freeze contract differs")
    records = freeze.get("production_files")
    if (
        not isinstance(records, list)
        or len(records) != 4
        or any(not isinstance(r, dict) for r in records)
        or {r.get("relative_path") for r in records} != set(PRODUCTION_FILES)
    ):
        raise SubmissionError("production inventory differs")
    runner_sha = None
    for record in records:
        path = root / "tools" / record["relative_path"]
        size, digest, mode = _source_digest(path)
        if (
            type(record.get("size")) is not int
            or type(record.get("mode")) is not int
            or (size, digest, mode)
            != (record["size"], record.get("sha256"), record["mode"])
        ):
            raise SubmissionError("frozen production file differs: " + path.name)
        if path.name == "run_numeric_diag.sbatch":
            runner_sha = digest
    if (
        _source_digest(contract.v4_root / "input_freeze.json")[1]
        != contract.v4_manifest_sha256
    ):
        raise SubmissionError("fixed v4 manifest changed")
    return freeze, sha, runner_sha


def _checked_call(gateway, argv, *, timeout=60, permit_stderr=False):
    try:
        result = gateway.run(argv, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        raise SubmissionError("read-only gateway call failed: " + str(error)) from error
    if (
        not isinstance(result, CommandOutcome)
        or result.argv != tuple(argv)
        or type(result.returncode) is not int
        or result.returncode != 0
        or type(result.stdout) is not bytes
        or type(result.stderr) is not bytes
        or len(result.stdout) > 4 * 1024 * 1024
        or len(result.stderr) > 4 * 1024 * 1024
        or (result.stderr and not permit_stderr)
    ):
        raise SubmissionError("read-only gateway response is invalid")
    return result


def _rows(raw, fields):
    try:
        text = raw.decode("ascii")
    except UnicodeError as error:
        raise SubmissionError("non-ASCII scheduler response") from error
    if not text:
        return []
    rows = []
    seen = set()
    for line in text.splitlines():
        row = line.split("|")
        if (
            len(row) != fields
            or any(not x or x.strip() != x for x in row)
            or not re.fullmatch(r"[1-9][0-9]{0,19}", row[0])
            or row[0] in seen
        ):
            raise SubmissionError("malformed or duplicate scheduler rows")
        seen.add(row[0])
        rows.append(row)
    return rows


def _queue(contract, gateway):
    argv = [
        str(contract.squeue),
        "--noheader",
        "--user",
        contract.user,
        "--name",
        ",".join(contract.job_names),
        "--format=%i|%T|%j",
    ]
    rows = _rows(_checked_call(gateway, argv).stdout, 3)
    for _, state, name in rows:
        if (
            state not in ACTIVE_STATES | TERMINAL_STATES
            or name not in contract.job_names
        ):
            raise SubmissionError("unexpected queue state or job name")
    return rows


def _require_empty_outputs(contract):
    for name in ("logs", "attempts", "submitted_runners"):
        with directory(contract.root / name) as fd:
            if os.listdir(fd):
                raise AmbiguousSubmissionError(
                    "prior output exists; no automatic submission"
                )


def _full_check(contract, gateway, sha):
    argv = [
        str(contract.python),
        "-I",
        "-B",
        str(contract.root / "tools/diagnose_batch_invariance.py"),
        "check-only",
        "--expected-input-freeze-sha256",
        sha,
    ]
    outcome = _checked_call(gateway, argv, timeout=1800, permit_stderr=True)
    raw = outcome.stdout
    banner = b"Using explicit dim specification for demeaning in audio transforms\n"
    while raw.startswith(banner):
        raw = raw[len(banner) :]
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise SubmissionError("check-only did not return one JSON document") from error
    if (
        not isinstance(result, dict)
        or type(result.get("schema_version")) is not int
        or result["schema_version"] != 1
        or result.get("status") != "CHECK_PASS"
        or result.get("diagnostic_protocol") != contract.protocol
        or result.get("input_freeze_sha256") != sha
    ):
        raise SubmissionError("full live input check failed")


def submit(
    confirm_action,
    confirm_v4_job_id,
    expected_input_freeze_sha256,
    *,
    contract,
    gateway,
):
    if (
        confirm_action != contract.confirm_action
        or confirm_v4_job_id != contract.confirm_v4_job_id
    ):
        raise SubmissionError("explicit submission confirmation differs")
    sha = _hex(expected_input_freeze_sha256, 64)
    try:
        freeze, _, runner_sha = _load_freeze(contract, sha)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise SubmissionError("input bootstrap refused: " + str(error)) from error
    journal = SubmissionJournal(contract)
    with journal.lock():
        decision = journal.classify(sha, runner_sha)
        if decision["status"] == "ALREADY_SUBMITTED":
            return decision
        if decision["status"] != "NOT_SUBMITTED":
            raise AmbiguousSubmissionError(
                decision.get("reason", "submission identity unresolved")
            )
        _require_empty_outputs(contract)
        if _queue(contract, gateway):
            raise SubmissionError("active v4 or numerical diagnostic job exists")
        _full_check(contract, gateway, sha)
        if _load_freeze(contract, sha) != (freeze, sha, runner_sha):
            raise SubmissionError("inputs changed during preflight")
        if _queue(contract, gateway):
            raise SubmissionError("job appeared during preflight")
        _require_empty_outputs(contract)
        nonce = uuid.uuid4().hex
        intent = journal.begin(sha, runner_sha, nonce)
        # This is the sole external write call. Intent is durable first; never loop.
        try:
            outcome = gateway.run(intent["argv"], timeout=60)
        except BaseException as error:
            journal.record_exception(error)
            raise AssertionError("record_exception must stop")
        receipt = journal.record_response(outcome)
        return dict(
            status="SUBMITTED",
            job_id=receipt["job_id"],
            receipt=receipt,
            next="wait_then_status_and_verify_results",
        )


def _confirmed_receipt(journal, sha, runner_sha):
    intent, intent_raw, common = journal._read_intent(sha, runner_sha)
    response, response_raw = read_json(journal.state / "SBATCH_RESPONSE.json")
    receipt, receipt_raw = read_json(journal.state / "SUBMISSION_RECEIPT.json")
    job = journal._response_job(response, common, intent["argv"])
    expected = dict(
        common,
        status="SUBMITTED",
        job_id=job,
        intent_record_sha256=hashlib.sha256(intent_raw).hexdigest(),
        response_record_sha256=hashlib.sha256(response_raw).hexdigest(),
    )
    if receipt != expected:
        raise AmbiguousSubmissionError("receipt differs from confirmed intent/response")
    evidence = {
        "INTENT.json": intent_raw,
        "SBATCH_RESPONSE.json": response_raw,
        "SUBMISSION_RECEIPT.json": receipt_raw,
    }
    return receipt, evidence


def status(*, contract, gateway):
    """Observe only: no lock creation, artifact writes, inference, or submission."""
    try:
        _, sha, runner_sha = _load_freeze(contract)
        journal = SubmissionJournal(contract)
        if not os.path.lexists(journal.state / "INTENT.json"):
            decision = journal.classify(sha, runner_sha)
            if decision["status"] == "NOT_SUBMITTED":
                _require_empty_outputs(contract)
            return decision
        receipt, evidence = _confirmed_receipt(journal, sha, runner_sha)
        job = receipt["job_id"]

        def terminal_names():
            return [
                name
                for name in ("DIAGNOSTIC_COMPLETE", "DIAGNOSTIC_FAILED")
                if os.path.lexists(journal.state / (name + ".json"))
            ]

        markers = terminal_names()

        def finish(report):
            if terminal_names() != markers:
                raise AmbiguousSubmissionError(
                    "terminal set changed during status; query again"
                )
            _load_freeze(contract, sha)
            for name, raw in evidence.items():
                if read_json(journal.state / name)[1] != raw:
                    raise AmbiguousSubmissionError("journal changed during status")
            if terminal_names() != markers:
                raise AmbiguousSubmissionError(
                    "terminal set changed during status; query again"
                )
            return dict(
                report, job_id=job, input_freeze_sha256=sha, results_verified=False
            )

        if len(markers) > 1:
            raise AmbiguousSubmissionError("conflicting diagnostic terminal markers")
        if markers:
            name = markers[0]
            marker, raw = read_json(journal.state / (name + ".json"))
            expected = dict(
                schema_version=1,
                status=name,
                diagnostic_protocol=contract.protocol,
                evaluation_role=EVALUATION_ROLE,
                job_id=job,
                input_freeze_sha256=sha,
            )
            if type(marker.get("schema_version")) is not int or any(
                marker.get(k) != v for k, v in expected.items()
            ):
                raise AmbiguousSubmissionError("terminal marker binding differs")
            evidence[name + ".json"] = raw
            return finish(
                dict(status=name, source="terminal_marker", next="verify-results")
            )
        rows = _queue(contract, gateway)
        own = [row for row in rows if row[0] == job]
        if own:
            if own[0][2] != contract.job_names[1] or own[0][1] not in ACTIVE_STATES:
                raise AmbiguousSubmissionError("unexpected live job identity/state")
            return finish(dict(status=own[0][1], source="squeue"))
        argv = [
            str(contract.sacct),
            "-j",
            job,
            "-X",
            "--noheader",
            "--parsable2",
            "--format=JobIDRaw,JobName%64,State%64,ExitCode",
        ]
        rows = _rows(_checked_call(gateway, argv).stdout, 4)
        if not rows:
            return finish(
                dict(
                    status="ACCOUNTING_PENDING",
                    source="sacct",
                    next="query_status_later",
                )
            )
        if len(rows) != 1 or rows[0][0] != job or rows[0][1] != contract.job_names[1]:
            raise AmbiguousSubmissionError("accounting job identity differs")
        state, exit_code = rows[0][2:]
        if re.fullmatch(r"CANCELLED by [0-9]+", state):
            state = "CANCELLED"
        if state not in ACTIVE_STATES | TERMINAL_STATES or not re.fullmatch(
            r"[0-9]+:[0-9]+", exit_code
        ):
            raise AmbiguousSubmissionError("unknown accounting state/exit code")
        result = state if state in ACTIVE_STATES else "INCOMPLETE_UNTRAPPED_TERMINATION"
        return finish(
            dict(
                status=result,
                scheduler_state=state,
                exit_code=exit_code,
                source="sacct",
            )
        )
    except (SubmissionError, OSError, ValueError, TypeError, KeyError) as error:
        return dict(status="STOP_AMBIGUOUS", reason=str(error), results_verified=False)


def run_cli(argv, *, contract, gateway):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    commands = parser.add_subparsers(dest="action", required=True)
    command = commands.add_parser("submit", allow_abbrev=False)
    command.add_argument("--confirm-action", required=True)
    command.add_argument("--confirm-v4-job-id", required=True)
    command.add_argument("--expected-input-freeze-sha256", required=True)
    commands.add_parser("status", allow_abbrev=False)
    args = parser.parse_args(argv)
    try:
        if args.action == "submit":
            result = submit(
                args.confirm_action,
                args.confirm_v4_job_id,
                args.expected_input_freeze_sha256,
                contract=contract,
                gateway=gateway,
            )
        else:
            result = status(contract=contract, gateway=gateway)
    except (SubmissionError, OSError, ValueError, TypeError, KeyError) as error:
        result = dict(
            status="STOP_AMBIGUOUS"
            if isinstance(error, AmbiguousSubmissionError)
            else "STOP",
            reason=str(error),
        )
    sys.stdout.write(canonical(result).decode("ascii"))
    return 2 if result["status"] in ("STOP", "STOP_AMBIGUOUS") else 0


def main(argv=None):
    return run_cli(
        argv,
        contract=PRODUCTION_CONTRACT,
        gateway=SchedulerGateway(PRODUCTION_CONTRACT),
    )


if __name__ == "__main__":
    sys.exit(main())

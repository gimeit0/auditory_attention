"""Local runner contract tests; no scheduler or GPU is invoked."""

import hashlib
import ast
import dataclasses
import base64
import contextlib
import io
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
RUNNER = HERE / "run_numeric_diag.sbatch"


def load_diag():
    spec = importlib.util.spec_from_file_location(
        "runner_test_diag", HERE / "diagnose_batch_invariance.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_submitter():
    spec = importlib.util.spec_from_file_location(
        "journal_test_submitter", HERE / "submit_numeric_diag.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def bootstrap():
    source = RUNNER.read_text()
    body = source.split("# BEGIN STDLIB BOOTSTRAP\n", 1)[1]
    body = body.split("# END STDLIB BOOTSTRAP", 1)[0]
    module = types.ModuleType("runner_bootstrap_test")
    exec(compile(body, str(RUNNER), "exec"), module.__dict__)
    return module


class RunnerContractTests(unittest.TestCase):
    def setUp(self):
        self.b = bootstrap()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name).resolve()
        for name in ("tools", "state", "attempts", "submitted_runners"):
            (self.root / name).mkdir()
        self.sha = "a" * 64
        self.nonce = "b" * 32

    def fixture(self, diagnostic_code=None):
        records = []
        for name in self.b.FILES:
            data = name.encode()
            if name == "diagnose_batch_invariance.py" and diagnostic_code is not None:
                data = diagnostic_code
            (self.root / "tools" / name).write_bytes(data)
            records.append(
                dict(
                    relative_path=name,
                    size=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                )
            )
        self.spool = self.root / "spool"
        self.spool.write_bytes(b"run_numeric_diag.sbatch")
        freeze = dict(production_files=records)
        raw = self.b.canonical(freeze)
        (self.root / "input_freeze.json").write_bytes(raw)
        self.sha = hashlib.sha256(raw).hexdigest()
        runner_sha = hashlib.sha256(self.spool.read_bytes()).hexdigest()
        intent = self.b.expected_intent(self.root, self.sha, self.nonce, runner_sha)
        (self.root / "state/INTENT.json").write_bytes(self.b.canonical(intent))
        return freeze

    def validate(self):
        return self.b.validate_inputs(
            self.root, self.spool, "123", self.sha, self.nonce
        )

    def test_directives_and_bash_syntax(self):
        source = RUNNER.read_text()
        self.assertEqual(
            subprocess.run(
                ["/bin/bash", "-n", str(RUNNER)], capture_output=True
            ).returncode,
            0,
        )
        expected = [
            "--job-name=audattn_v4_numdiag",
            "--partition=GPU-1A",
            "--nodes=1",
            "--gpus=1",
            "--ntasks=1",
            "--cpus-per-task=8",
            "--time=01:00:00",
            "--no-requeue",
        ]
        for item in expected:
            self.assertIn("#SBATCH " + item + "\n", source)
        for option, suffix in (
            ("chdir", ""),
            ("output", "/logs/audattn_v4_numdiag_%j.log"),
            ("error", "/logs/audattn_v4_numdiag_%j.log"),
        ):
            self.assertIn(f"#SBATCH --{option}={self.b.ROOT}{suffix}\n", source)
        self.assertIn('[[ "$#" -eq 2 ]]', source)
        self.assertIn("umask 077", source)
        self.assertIn("exec /usr/bin/env -i", source)
        self.assertIn('"$PYTHON" -I -B - "$0" "$1" "$2"', source)
        self.assertNotIn("#SBATCH --export=ALL", source)

    def test_valid_input_binding_is_read_only_and_does_not_wait_for_receipt(self):
        freeze = self.fixture()
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        actual, code = self.validate()
        self.assertEqual(actual, freeze)
        self.assertEqual(code, b"diagnose_batch_invariance.py")
        self.assertEqual(
            before,
            {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()},
        )

    def test_live_spool_and_freeze_changes_are_rejected(self):
        self.fixture()
        for path in (
            self.spool,
            self.root / "input_freeze.json",
            *(self.root / "tools" / n for n in self.b.FILES),
        ):
            old = path.read_bytes()
            path.write_bytes(old + b"changed")
            with self.assertRaises((ValueError, OSError)):
                self.validate()
            path.write_bytes(old)

    def test_existing_archive_attempt_or_terminal_is_rejected(self):
        self.fixture()
        for path in (
            self.root / "submitted_runners/123.sbatch",
            self.root / "attempts/old",
            self.root / "state/DIAGNOSTIC_FAILED.json",
        ):
            path.touch()
            with self.assertRaises(ValueError):
                self.validate()
            path.unlink()

    def test_wrong_nonce_or_symlink_is_rejected(self):
        self.fixture()
        with self.assertRaises(ValueError):
            self.b.validate_inputs(self.root, self.spool, "123", self.sha, "c" * 32)
        original = self.root / "tools/numeric_trace.py"
        moved = self.root / "trace"
        original.rename(moved)
        original.symlink_to(moved)
        with self.assertRaises((ValueError, OSError)):
            self.validate()

    def test_duplicate_production_and_noncanonical_json_are_rejected(self):
        freeze = self.fixture()
        freeze["production_files"][-1] = freeze["production_files"][0]
        raw = self.b.canonical(freeze)
        (self.root / "input_freeze.json").write_bytes(raw)
        self.sha = hashlib.sha256(raw).hexdigest()
        with self.assertRaises(ValueError):
            self.validate()
        raw = json.dumps(freeze, indent=2).encode()
        (self.root / "input_freeze.json").write_bytes(raw)
        self.sha = hashlib.sha256(raw).hexdigest()
        with self.assertRaises(ValueError):
            self.validate()

    def test_parent_symlink_and_noncanonical_spool_are_rejected(self):
        self.fixture()
        alias = self.root / "alias"
        alias.symlink_to(self.root / "tools", target_is_directory=True)
        with self.assertRaises(ValueError):
            self.b.read_file(alias / "numeric_trace.py")
        with self.assertRaises(ValueError):
            self.b.validate_inputs(self.root, "spool", "123", self.sha, self.nonce)

    def test_bounded_sources_and_special_files(self):
        path = self.root / "source"
        path.write_bytes(b"12345")
        with self.assertRaises(ValueError):
            self.b.read_file(path, limit=4)
        path.unlink()
        os.mkfifo(path)
        with self.assertRaises(ValueError):
            self.b.read_file(path)

    def test_runner_rejects_bad_arguments_before_production_python(self):
        for args, job in (
            ([], "123"),
            (["a" * 64, "b" * 32], "01"),
            (["bad", "b" * 32], "123"),
        ):
            run = subprocess.run(
                ["/bin/bash", str(RUNNER), *args],
                env={"SLURM_JOB_ID": job, "CUDA_VISIBLE_DEVICES": "0"},
                capture_output=True,
            )
            self.assertEqual(run.returncode, 2)
            self.assertNotIn(b"No such file", run.stderr)

    def test_scheduler_allowlist_matches_coordinator_and_drops_injection(self):
        diag = load_diag()
        self.assertEqual(
            set(self.b.SCHEDULER_KEYS),
            set(diag._CHILD_SLURM_ENV_KEYS) | {"CUDA_VISIBLE_DEVICES"},
        )
        env = dict(
            SLURM_JOB_ID="123",
            CUDA_VISIBLE_DEVICES="0",
            PYTHONPATH="/bad",
            LD_PRELOAD="/bad",
            CONDA_PREFIX="/bad",
            DIAG_ROOT="/bad",
        )
        final = diag.coordinator_environment("123", "/tmp/audattn_v4_numdiag_123", env)
        for key in ("PYTHONPATH", "LD_PRELOAD", "CONDA_PREFIX", "DIAG_ROOT"):
            self.assertNotIn(key, final)
        args = types.SimpleNamespace(
            job_id="123",
            intent_nonce=self.nonce,
            expected_input_freeze_sha256=self.sha,
            spool_runner="/tmp/spool",
        )
        self.assertEqual(
            diag.coordinator_command(args)[4:],
            [
                "run-coordinator",
                "--job-id",
                "123",
                "--intent-nonce",
                self.nonce,
                "--expected-input-freeze-sha256",
                self.sha,
                "--spool-runner",
                "/tmp/spool",
            ],
        )

    def test_scratch_writes_are_fd_relative_and_only_under_new_job_directory(self):
        diag = load_diag()
        parent = self.root / "local"
        parent.mkdir(mode=0o700)
        writes = []
        real_mkdir = os.mkdir

        def audited_mkdir(path, mode=0o777, *, dir_fd=None):
            self.assertIsNotNone(dir_fd)
            self.assertNotIn("/", path)
            self.assertEqual(mode, 0o700)
            writes.append(path)
            return real_mkdir(path, mode, dir_fd=dir_fd)

        before = {p for p in self.root.rglob("*")}
        with (
            mock.patch.object(diag, "_require_local_scratch_mount", return_value={}),
            mock.patch.object(self.b.os, "mkdir", side_effect=audited_mkdir),
        ):
            scratch = self.b.create_scratch(diag, "123", {"SLURM_TMPDIR": str(parent)})
        additions = {p for p in self.root.rglob("*")} - before
        self.assertEqual(
            additions,
            {scratch, *(scratch / n for n in diag._COORDINATOR_WRITE_PATHS.values())},
        )
        self.assertEqual(
            len(writes), 1 + len(set(diag._COORDINATOR_WRITE_PATHS.values()))
        )

    def test_supplied_scratch_owner_mode_and_empty_value_are_rejected(self):
        for uid, mode in ((os.getuid() + 1, 0o40700), (os.getuid(), 0o40777)):
            with self.assertRaises(ValueError):
                self.b.validate_parent_policy(
                    self.root,
                    types.SimpleNamespace(st_uid=uid, st_mode=mode),
                    supplied=True,
                )
        with self.assertRaises(ValueError):
            self.b.create_scratch(load_diag(), "123", {"SLURM_TMPDIR": ""})

    def test_bootstrap_main_exec_boundary_with_real_environment_and_scratch_helpers(
        self,
    ):
        # Pure fixture loader substitutes only the verified source body and mount/
        # full-freeze Linux checks. No production CLI root override is introduced.
        diag = load_diag()
        code = b"import runner_test_diag; globals().update(vars(runner_test_diag))\n"
        freeze = self.fixture(code)
        with tempfile.TemporaryDirectory() as scratch_parent:
            parent = pathlib.Path(scratch_parent).resolve()
            scheduler = {
                "SLURM_JOB_ID": "123",
                "CUDA_VISIBLE_DEVICES": "0",
                "SLURM_TMPDIR": str(parent),
            }
            with (
                mock.patch.object(self.b, "ROOT", self.root),
                mock.patch.object(self.b, "PYTHON", pathlib.Path(sys.executable)),
                mock.patch.object(diag, "DIAGNOSTIC_ROOT", self.root),
                mock.patch.object(
                    diag, "PRODUCTION_PYTHON", pathlib.Path(sys.executable)
                ),
                mock.patch.object(diag, "_validate_freeze_value") as schema,
                mock.patch.object(
                    diag, "_require_local_scratch_mount", return_value={}
                ),
                mock.patch.object(sys, "platform", "linux"),
                mock.patch.object(
                    sys, "argv", ["-", str(self.spool), self.sha, self.nonce]
                ),
                mock.patch.dict(os.environ, scheduler, clear=True),
                mock.patch.object(os, "execve") as execute,
            ):
                self.b.main()
                schema.assert_called_once()
                self.assertEqual(schema.call_args.args[0], freeze)
                execute.assert_called_once()
                executable, argv, environment = execute.call_args.args
                self.assertEqual(executable, str(pathlib.Path(sys.executable)))
                self.assertEqual(
                    argv[1:4],
                    ["-I", "-B", str(self.root / "tools/diagnose_batch_invariance.py")],
                )
                self.assertEqual(argv[-2:], ["--spool-runner", str(self.spool)])
                self.assertEqual(environment, dict(os.environ))
                self.assertEqual(
                    environment["DIAG_SCRATCH_ROOT"],
                    str(parent / "audattn_v4_numdiag_123"),
                )
                self.assertEqual(set((self.root / "attempts").iterdir()), set())
                self.assertFalse((self.root / "state/SUBMISSION_RECEIPT.json").exists())

    def test_canonical_id_and_positional_values(self):
        for job in ("", "0", "01", "1;echo", "１２３"):
            with self.assertRaises(ValueError):
                self.b.validate_identity(job, self.sha, self.nonce)
        for sha, nonce in (("A" * 64, self.nonce), (self.sha, "b" * 31)):
            with self.assertRaises(ValueError):
                self.b.validate_identity("123", sha, nonce)

    def test_scratch_creation_and_write_locations_match_coordinator(self):
        diag = load_diag()
        parent = self.root / "local"
        parent.mkdir(mode=0o700)
        env = {
            "SLURM_JOB_ID": "123",
            "CUDA_VISIBLE_DEVICES": "0",
            "SLURM_TMPDIR": str(parent),
        }
        with mock.patch.object(
            diag, "_require_local_scratch_mount", return_value={"filesystem": "tmpfs"}
        ):
            scratch = self.b.create_scratch(diag, "123", env)
        expected = diag.coordinator_environment("123", str(scratch), env)
        self.assertEqual(
            set(p.name for p in scratch.iterdir()),
            set(diag._COORDINATOR_WRITE_PATHS.values()),
        )
        for key in diag._COORDINATOR_WRITE_PATHS:
            self.assertTrue(pathlib.Path(expected[key]).is_relative_to(scratch))
        for path in (scratch, *scratch.iterdir()):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
        with mock.patch.object(diag, "_require_local_scratch_mount", return_value={}):
            with self.assertRaises(FileExistsError):
                self.b.create_scratch(diag, "123", env)
        self.assertEqual(
            set(self.root.iterdir()),
            {
                self.root / n
                for n in ("tools", "state", "attempts", "submitted_runners", "local")
            },
        )

    def test_scratch_invalid_supplied_parent_never_falls_back(self):
        diag = load_diag()
        with mock.patch.object(
            diag, "_require_local_scratch_mount", side_effect=ValueError("network")
        ):
            with self.assertRaises(ValueError):
                self.b.create_scratch(diag, "123", {"SLURM_TMPDIR": str(self.root)})
        self.assertFalse((self.root / "audattn_v4_numdiag_123").exists())

    def test_fallback_policy_is_exact(self):
        good = types.SimpleNamespace(st_uid=0, st_mode=0o41777)
        self.b.validate_parent_policy(pathlib.Path("/tmp"), good, supplied=False)
        for path, info in (
            (pathlib.Path("/var/tmp"), good),
            (pathlib.Path("/tmp"), types.SimpleNamespace(st_uid=0, st_mode=0o40777)),
        ):
            with self.assertRaises(ValueError):
                self.b.validate_parent_policy(path, info, supplied=False)

    def test_bootstrap_has_no_science_imports_and_uses_fixed_exec_contract(self):
        source = RUNNER.read_text()
        self.assertNotIn("import torch", source)
        self.assertNotIn("import numpy", source)
        self.assertIn("os.execve", source)
        self.assertIn("diag.coordinator_command(args)", source)
        self.assertIn("diag.coordinator_environment", source)
        self.assertIn("BOOTSTRAP_ENVIRONMENT_SHA256=", source)


class SubmissionJournalTests(unittest.TestCase):
    def setUp(self):
        self.s = load_submitter()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name).resolve()
        for name in ("state", "tools", "attempts", "submitted_runners"):
            (self.root / name).mkdir(mode=0o700)
        self.contract = dataclasses.replace(self.s.PRODUCTION_CONTRACT, root=self.root)
        self.j = self.s.SubmissionJournal(self.contract)
        self.sha, self.runner_sha, self.nonce = "a" * 64, "b" * 64, "c" * 32

    def begin(self):
        return self.j.begin(self.sha, self.runner_sha, self.nonce)

    def outcome(self, stdout=b"123\n", stderr=b"", returncode=0):
        return self.s.CommandOutcome(
            tuple(self.s.submission_argv(self.contract, self.sha, self.nonce)),
            returncode,
            stdout,
            stderr,
        )

    def test_durable_intent_matches_coordinator_wire_contract(self):
        with self.j.lock():
            record = self.begin()
            self.assertEqual(
                self.s.read_json(self.root / "state/INTENT.json")[0], record
            )
        self.assertEqual(
            record,
            bootstrap().expected_intent(
                self.root, self.sha, self.nonce, self.runner_sha
            ),
        )
        self.assertEqual(
            (self.root / "state/INTENT.json").stat().st_mode & 0o777, 0o600
        )

    def test_lock_is_exclusive_nonblocking_and_single_link(self):
        with self.j.lock():
            with self.assertRaises(self.s.SubmissionError):
                with self.s.SubmissionJournal(self.contract).lock():
                    self.fail("duplicate lock accepted")
        os.link(self.root / "state/submission.lock", self.root / "lock-alias")
        with self.assertRaises(self.s.SubmissionError):
            with self.j.lock():
                self.fail("linked lock accepted")

    def test_journal_writes_require_lock(self):
        with self.assertRaises(self.s.SubmissionError):
            self.begin()

    def test_success_response_and_receipt_bind_exact_raw_bytes(self):
        with self.j.lock():
            self.begin()
            receipt = self.j.record_response(self.outcome())
            self.assertEqual(receipt["job_id"], "123")
            self.assertEqual(
                self.j.classify(self.sha, self.runner_sha)["status"],
                "ALREADY_SUBMITTED",
            )
        response, raw = self.s.read_json(self.root / "state/SBATCH_RESPONSE.json")
        self.assertEqual(base64.b64decode(response["stdout_b64"]), b"123\n")
        self.assertEqual(
            receipt["response_record_sha256"], hashlib.sha256(raw).hexdigest()
        )
        diag = load_diag()
        args = types.SimpleNamespace(
            job_id="123", intent_nonce=self.nonce, expected_input_freeze_sha256=self.sha
        )
        with mock.patch.object(diag, "DIAGNOSTIC_ROOT", self.root):
            binding = diag._wait_submission_binding(
                args, self.runner_sha, wait_for_receipt=False
            )
        self.assertEqual(binding["job_id"], "123")

    def test_ambiguous_response_preserved_and_never_reusable(self):
        cases = [
            (b"", b"", 0),
            (b"123;cluster\n", b"", 0),
            (b" 123\n", b"", 0),
            (b"123\n\n", b"", 0),
            (b"123", b"warning", 0),
            (b"123", b"", 1),
            (b"123", b"", -15),
            (b"01\n", b"", 0),
            (b"0", b"", 0),
            (b"\xff", b"", 0),
        ]
        for index, (out, err, rc) in enumerate(cases):
            root = self.root / str(index)
            root.mkdir(mode=0o700)
            for name in ("state", "tools", "attempts", "submitted_runners"):
                (root / name).mkdir(mode=0o700)
            contract = dataclasses.replace(self.contract, root=root)
            j = self.s.SubmissionJournal(contract)
            with j.lock():
                j.begin(self.sha, self.runner_sha, self.nonce)
                outcome = self.s.CommandOutcome(
                    tuple(self.s.submission_argv(contract, self.sha, self.nonce)),
                    rc,
                    out,
                    err,
                )
                with self.assertRaises(self.s.AmbiguousSubmissionError):
                    j.record_response(outcome)
                self.assertEqual(
                    j.classify(self.sha, self.runner_sha)["status"], "STOP_AMBIGUOUS"
                )
                with self.assertRaises(self.s.AmbiguousSubmissionError):
                    j.begin(self.sha, self.runner_sha, self.nonce)
            value, _ = self.s.read_json(root / "state/SBATCH_RESPONSE.json")
            self.assertEqual(base64.b64decode(value["stdout_b64"]), out)
            self.assertEqual(base64.b64decode(value["stderr_b64"]), err)
            self.assertFalse((root / "state/SUBMISSION_RECEIPT.json").exists())

    def test_timeout_exception_preserves_partial_output_and_unresolved_intent(self):
        with self.j.lock():
            self.begin()
            error = subprocess.TimeoutExpired(
                ["sbatch"], 30, output=b"123", stderr=b"late"
            )
            with self.assertRaises(self.s.AmbiguousSubmissionError):
                self.j.record_exception(error)
            self.assertEqual(
                self.j.classify(self.sha, self.runner_sha)["status"], "STOP_AMBIGUOUS"
            )
        value, _ = self.s.read_json(self.root / "state/SBATCH_RESPONSE.json")
        self.assertIsNone(value["returncode"])
        self.assertEqual(value["exception_type"], "TimeoutExpired")
        self.assertEqual(base64.b64decode(value["stdout_b64"]), b"123")

    def test_receipt_failure_keeps_intent_and_raw_response(self):
        original = self.s.atomic_create_json

        def failing(path, value):
            if path.name == "SUBMISSION_RECEIPT.json":
                raise OSError("disk full")
            return original(path, value)

        with self.j.lock():
            self.begin()
            with mock.patch.object(self.s, "atomic_create_json", side_effect=failing):
                with self.assertRaises(self.s.AmbiguousSubmissionError):
                    self.j.record_response(self.outcome())
            self.assertEqual(
                self.j.classify(self.sha, self.runner_sha)["status"], "STOP_AMBIGUOUS"
            )
        self.assertTrue((self.root / "state/INTENT.json").exists())
        self.assertTrue((self.root / "state/SBATCH_RESPONSE.json").exists())

    def test_mismatched_receipt_and_preexisting_evidence_are_ambiguous(self):
        with self.j.lock():
            self.begin()
            self.j.record_response(self.outcome())
            self.assertEqual(
                self.j.classify("d" * 64, self.runner_sha)["status"], "STOP_AMBIGUOUS"
            )
            (self.root / "attempts/slurm-123").mkdir()
            self.assertEqual(
                self.j.classify(self.sha, self.runner_sha)["status"], "STOP_AMBIGUOUS"
            )

    def test_readonly_classification_does_not_create_lock_or_files(self):
        before = {str(p): p.stat().st_mtime_ns for p in self.root.rglob("*")}
        self.assertEqual(
            self.j.classify(self.sha, self.runner_sha)["status"], "NOT_SUBMITTED"
        )
        self.assertEqual(
            before, {str(p): p.stat().st_mtime_ns for p in self.root.rglob("*")}
        )

    def test_create_once_refuses_overwrite_symlink_and_hardlink(self):
        target = self.root / "state/data.json"
        self.s.atomic_create_json(target, {"value": 1})
        with self.assertRaises((OSError, self.s.SubmissionError)):
            self.s.atomic_create_json(target, {"value": 2})
        self.assertEqual(self.s.read_json(target)[0], {"value": 1})
        alias = self.root / "state/alias.json"
        alias.symlink_to(target)
        with self.assertRaises((OSError, self.s.SubmissionError)):
            self.s.atomic_create_json(alias, {})
        with self.assertRaises((OSError, self.s.SubmissionError)):
            self.s.read_json(alias)
        os.link(target, self.root / "state/hard.json")
        with self.assertRaises(self.s.SubmissionError):
            self.s.read_json(target)

    def test_writer_fsyncs_file_and_directory_and_has_no_partial_files(self):
        real = os.fsync
        with mock.patch.object(self.s.os, "fsync", wraps=real) as sync:
            self.s.atomic_create_json(self.root / "state/test.json", {"x": 1})
        self.assertGreaterEqual(sync.call_count, 2)
        self.assertEqual(
            {p.name for p in (self.root / "state").iterdir()}, {"test.json"}
        )

    def test_parent_symlink_and_mutated_lock_are_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root / "state", target_is_directory=True)
        with self.assertRaises(self.s.SubmissionError):
            self.s.atomic_create_json(alias / "test.json", {})
        with self.j.lock():
            (self.root / "state/submission.lock").rename(self.root / "old-lock")
            (self.root / "state/submission.lock").touch(mode=0o600)
            with self.assertRaises(self.s.SubmissionError):
                self.begin()

    def test_insecure_journal_directory_is_rejected(self):
        (self.root / "state").chmod(0o777)
        with self.assertRaises(self.s.SubmissionError):
            with self.j.lock():
                self.fail("unsafe state directory accepted")
        self.assertEqual(
            self.j.classify(self.sha, self.runner_sha)["status"], "STOP_AMBIGUOUS"
        )

    def test_wrong_argv_is_preserved_but_cannot_publish_receipt(self):
        with self.j.lock():
            self.begin()
            outcome = dataclasses.replace(
                self.outcome(), argv=("/usr/bin/sbatch", "other.sbatch")
            )
            with self.assertRaises(self.s.AmbiguousSubmissionError):
                self.j.record_response(outcome)
            response, _ = self.s.read_json(self.root / "state/SBATCH_RESPONSE.json")
            self.assertEqual(response["argv"], list(outcome.argv))
            self.assertFalse((self.root / "state/SUBMISSION_RECEIPT.json").exists())

    def test_response_and_receipt_cannot_be_replaced(self):
        with self.j.lock():
            self.begin()
            self.j.record_response(self.outcome())
            before = {p.name: p.read_bytes() for p in (self.root / "state").iterdir()}
            with self.assertRaises(self.s.AmbiguousSubmissionError):
                self.j.record_response(self.outcome(b"456"))
            self.assertEqual(
                before,
                {p.name: p.read_bytes() for p in (self.root / "state").iterdir()},
            )

    def test_raw_response_without_receipt_blocks_retry_even_if_successful(self):
        with self.j.lock():
            intent = self.begin()
            common = {k: v for k, v in intent.items() if k not in ("status", "argv")}
            response = dict(
                common,
                status="SBATCH_RESPONSE",
                argv=intent["argv"],
                returncode=0,
                stdout_b64="MTIzCg==",
                stderr_b64="",
            )
            self.s.atomic_create_json(
                self.root / "state/SBATCH_RESPONSE.json", response
            )
            self.assertEqual(
                self.j.classify(self.sha, self.runner_sha)["status"], "STOP_AMBIGUOUS"
            )

    def test_short_write_loop_and_fsync_failure(self):
        real_write = os.write
        with mock.patch.object(
            self.s.os, "write", side_effect=lambda fd, data: real_write(fd, data[:2])
        ):
            self.s.atomic_create_json(
                self.root / "state/small.json", {"value": "longer than two bytes"}
            )
        self.assertEqual(
            self.s.read_json(self.root / "state/small.json")[0]["value"],
            "longer than two bytes",
        )
        with mock.patch.object(self.s.os, "fsync", side_effect=OSError("fsync failed")):
            with self.assertRaises(OSError):
                self.s.atomic_create_json(self.root / "state/failed.json", {})
        self.assertFalse((self.root / "state/failed.json").exists())
        self.assertFalse(list((self.root / "state").glob("*.partial")))

    def test_receipt_mutation_is_not_trusted(self):
        with self.j.lock():
            self.begin()
            receipt = self.j.record_response(self.outcome())
            receipt["job_id"] = "456"
            (self.root / "state/SUBMISSION_RECEIPT.json").write_bytes(
                self.s.canonical(receipt)
            )
            self.assertEqual(
                self.j.classify(self.sha, self.runner_sha)["status"], "STOP_AMBIGUOUS"
            )

    def test_command_outcome_is_frozen_and_incomplete_cli_cannot_submit(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.outcome().returncode = 1
        run = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(HERE / "submit_numeric_diag.py"),
                "submit",
            ],
            capture_output=True,
        )
        self.assertEqual(run.returncode, 2)
        self.assertIn(b"required", run.stderr)


class GatewayFixture(unittest.TestCase):
    def setUp(self):
        self.s = load_submitter()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = pathlib.Path(self.tmp.name).resolve()
        self.root, self.v4 = base / "diag", base / "v4"
        self.root.mkdir(mode=0o700)
        self.v4.mkdir(mode=0o700)
        for name in ("tools", "state", "logs", "attempts", "submitted_runners"):
            (self.root / name).mkdir(mode=0o700)
        (self.v4 / "input_freeze.json").write_bytes(b"{}\n")
        self.contract = dataclasses.replace(
            self.s.PRODUCTION_CONTRACT,
            root=self.root,
            v4_root=self.v4,
            v4_manifest_sha256=hashlib.sha256(b"{}\n").hexdigest(),
        )
        records = []
        for name in bootstrap().FILES:
            raw = (HERE / name).read_bytes()
            path = self.root / "tools" / name
            path.write_bytes(raw)
            path.chmod(0o600)
            records.append(
                dict(
                    relative_path=name,
                    size=len(raw),
                    mode=0o600,
                    sha256=hashlib.sha256(raw).hexdigest(),
                )
            )
        self.freeze = dict(
            schema_version=1,
            status="INPUTS_FROZEN",
            diagnostic_protocol=self.contract.protocol,
            roots={"diagnostic_root": str(self.root), "v4_root": str(self.v4)},
            production_files=records,
        )
        self.s.atomic_create_json(self.root / "input_freeze.json", self.freeze)
        self.sha = hashlib.sha256(self.s.canonical(self.freeze)).hexdigest()
        self.runner_sha = next(
            r["sha256"]
            for r in records
            if r["relative_path"] == "run_numeric_diag.sbatch"
        )
        owner = self

        class FakeGateway:
            def __init__(self):
                self.calls = []
                self.queue = b""
                self.accounting = b"123|audattn_v4_numdiag|COMPLETED|0:0\n"
                self.batch = (0, b"123\n", b"")
                self.check = None
                self.submissions = 0

            def run(self, argv, *, timeout=60):
                argv = tuple(argv)
                self.calls.append(argv)
                if argv[0] == str(owner.contract.squeue):
                    value = (
                        self.queue.pop(0)
                        if isinstance(self.queue, list)
                        else self.queue
                    )
                    if isinstance(value, BaseException):
                        raise value
                    if isinstance(value, tuple):
                        return owner.s.CommandOutcome(argv, *value)
                    return owner.s.CommandOutcome(argv, 0, value, b"")
                if argv[0] == str(owner.contract.sacct):
                    return owner.s.CommandOutcome(argv, 0, self.accounting, b"")
                if argv[0] == str(owner.contract.sbatch):
                    self.submissions += 1
                    intent, _ = owner.s.read_json(owner.root / "state/INTENT.json")
                    owner.assertEqual(argv, tuple(intent["argv"]))
                    # Actual runner bootstrap accepts the journal even before receipt exists.
                    bootstrap().validate_inputs(
                        owner.root,
                        owner.root / "tools/run_numeric_diag.sbatch",
                        "123",
                        owner.sha,
                        intent["intent_nonce"],
                    )
                    if isinstance(self.batch, BaseException):
                        raise self.batch
                    return owner.s.CommandOutcome(argv, *self.batch)
                owner.assertIn("check-only", argv)
                value = (
                    self.check
                    if self.check is not None
                    else dict(
                        schema_version=1,
                        status="CHECK_PASS",
                        diagnostic_protocol=owner.contract.protocol,
                        input_freeze_sha256=owner.sha,
                    )
                )
                return owner.s.CommandOutcome(argv, 0, owner.s.canonical(value), b"")

        self.g = FakeGateway()

    def submit(self):
        return self.s.submit(
            self.contract.confirm_action,
            "646900",
            self.sha,
            contract=self.contract,
            gateway=self.g,
        )


class SubmissionGatewayTests(GatewayFixture):
    def test_exactly_one_submit_then_idempotent_receipt(self):
        result = self.submit()
        self.assertEqual(result["status"], "SUBMITTED")
        self.assertEqual(result["job_id"], "123")
        self.assertEqual(self.g.submissions, 1)
        self.assertEqual(self.submit()["status"], "ALREADY_SUBMITTED")
        self.assertEqual(self.g.submissions, 1)
        intent, _ = self.s.read_json(self.root / "state/INTENT.json")
        diag = load_diag()
        with mock.patch.object(diag, "DIAGNOSTIC_ROOT", self.root):
            self.assertEqual(
                intent["argv"], diag._submission_argv(intent["intent_nonce"], self.sha)
            )

    def test_active_jobs_and_bad_queue_never_create_intent(self):
        for value in (
            b"9|RUNNING|audattn_samebank_v4\n",
            b"10|PENDING|audattn_v4_numdiag\n",
            b"garbage\n",
            b"1|UNKNOWN|audattn_v4_numdiag\n",
            (1, b"", b"error"),
            (0, b"", b"warning"),
            subprocess.TimeoutExpired(["squeue"], 60),
        ):
            self.g.queue = value
            with self.assertRaises(self.s.SubmissionError):
                self.submit()
            self.assertEqual(self.g.submissions, 0)
            self.assertFalse((self.root / "state/INTENT.json").exists())

    def test_queue_race_after_full_check_blocks_submit(self):
        self.g.queue = [b"", b"9|RUNNING|audattn_samebank_v4\n"]
        with self.assertRaises(self.s.SubmissionError):
            self.submit()
        self.assertEqual(self.g.submissions, 0)

    def test_bad_confirmation_and_hash_before_any_external_call(self):
        for action, job, sha in (
            ("wrong", "646900", self.sha),
            (self.contract.confirm_action, "1", self.sha),
            (self.contract.confirm_action, "646900", "d" * 64),
        ):
            with self.assertRaises(self.s.SubmissionError):
                self.s.submit(action, job, sha, contract=self.contract, gateway=self.g)
        self.assertEqual(self.g.calls, [])

    def test_altered_source_v4_manifest_and_check_verdict_block(self):
        for path in (
            self.root / "tools/diagnose_batch_invariance.py",
            self.v4 / "input_freeze.json",
        ):
            raw = path.read_bytes()
            path.write_bytes(raw + b"changed")
            with self.assertRaises(self.s.SubmissionError):
                self.submit()
            path.write_bytes(raw)
        self.g.check = dict(
            status="CHECK_PASS",
            input_freeze_sha256="d" * 64,
            schema_version=1,
            diagnostic_protocol=self.contract.protocol,
        )
        with self.assertRaises(self.s.SubmissionError):
            self.submit()
        self.assertEqual(self.g.submissions, 0)

    def test_any_previous_output_prevents_new_submission(self):
        for directory in ("logs", "attempts", "submitted_runners"):
            path = self.root / directory / "old"
            path.touch()
            with self.assertRaises(self.s.SubmissionError):
                self.submit()
            path.unlink()
        self.assertEqual(self.g.submissions, 0)

    def test_uncertain_external_call_never_retries(self):
        self.g.batch = subprocess.TimeoutExpired(["sbatch"], 60, output=b"123")
        with self.assertRaises(self.s.AmbiguousSubmissionError):
            self.submit()
        with self.assertRaises(self.s.AmbiguousSubmissionError):
            self.submit()
        self.assertEqual(self.g.submissions, 1)
        self.assertTrue((self.root / "state/SBATCH_RESPONSE.json").exists())

    def test_nonzero_and_stderr_are_ambiguous(self):
        self.g.batch = (0, b"123\n", b"warning")
        with self.assertRaises(self.s.AmbiguousSubmissionError):
            self.submit()
        self.assertEqual(self.g.submissions, 1)
        self.assertFalse((self.root / "state/SUBMISSION_RECEIPT.json").exists())

    def test_real_gateway_is_shell_free_and_cleans_environment(self):
        gateway = self.s.SchedulerGateway(self.contract)
        completed = subprocess.CompletedProcess(["x"], 0, b"123\n", b"")
        with (
            mock.patch.dict(os.environ, {"PYTHONPATH": "/bad", "LD_PRELOAD": "/bad"}),
            mock.patch.object(self.s.subprocess, "run", return_value=completed) as call,
        ):
            outcome = gateway.run([str(self.contract.squeue), "-h"])
        self.assertFalse(call.call_args.kwargs["shell"])
        self.assertEqual(call.call_args.kwargs["timeout"], 60)
        self.assertNotIn("PYTHONPATH", call.call_args.kwargs["env"])
        self.assertNotIn("LD_PRELOAD", call.call_args.kwargs["env"])
        self.assertEqual(outcome.stdout, b"123\n")

    def test_cli_fixed_contract_and_no_root_override(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            rc = self.s.run_cli(
                [
                    "submit",
                    "--confirm-action",
                    self.contract.confirm_action,
                    "--confirm-v4-job-id",
                    "646900",
                    "--expected-input-freeze-sha256",
                    self.sha,
                ],
                contract=self.contract,
                gateway=self.g,
            )
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(output.getvalue())["job_id"], "123")
        with (
            mock.patch.object(self.s, "run_cli", return_value=0) as run,
            mock.patch.object(self.s, "SchedulerGateway") as gateway,
        ):
            self.s.main(["status"])
        self.assertIs(run.call_args.kwargs["contract"], self.s.PRODUCTION_CONTRACT)
        gateway.assert_called_once_with(self.s.PRODUCTION_CONTRACT)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.s.run_cli(
                ["status", "--root", "/tmp"], contract=self.contract, gateway=self.g
            )

    def test_receipt_failure_after_external_success_still_calls_sbatch_once(self):
        original = self.s.atomic_create_json

        def publish(path, value):
            if path.name == "SUBMISSION_RECEIPT.json":
                raise OSError("disk full")
            return original(path, value)

        with mock.patch.object(self.s, "atomic_create_json", side_effect=publish):
            with self.assertRaises(self.s.AmbiguousSubmissionError):
                self.submit()
        with self.assertRaises(self.s.AmbiguousSubmissionError):
            self.submit()
        self.assertEqual(self.g.submissions, 1)
        self.assertTrue((self.root / "state/SBATCH_RESPONSE.json").exists())

    def test_check_only_known_banner_is_parsed_but_unknown_text_is_not(self):
        original = self.g.run
        prefix = [
            b"Using explicit dim specification for demeaning in audio transforms\n"
        ]

        def run(argv, *, timeout=60):
            result = original(argv, timeout=timeout)
            if "check-only" in argv:
                return dataclasses.replace(result, stdout=prefix[0] + result.stdout)
            return result

        with mock.patch.object(self.g, "run", side_effect=run):
            self.s._full_check(self.contract, self.g, self.sha)
            prefix[0] = b"unexpected status text\n"
            with self.assertRaises(self.s.SubmissionError):
                self.s._full_check(self.contract, self.g, self.sha)
        self.assertFalse((self.root / "state/INTENT.json").exists())

    def test_queue_duplicate_rows_and_wrong_name_are_rejected(self):
        for raw in (
            b"1|RUNNING|audattn_v4_numdiag\n1|RUNNING|audattn_v4_numdiag\n",
            b"1|RUNNING|unrelated\n",
            b"\xff\n",
            b"\n",
        ):
            self.g.queue = raw
            with self.assertRaises(self.s.SubmissionError):
                self.submit()
        self.assertEqual(self.g.submissions, 0)

    def test_sbatch_signal_is_saved_once_and_does_not_enable_retry(self):
        self.g.batch = KeyboardInterrupt("operator interrupt")
        with self.assertRaises(self.s.AmbiguousSubmissionError):
            self.submit()
        response, _ = self.s.read_json(self.root / "state/SBATCH_RESPONSE.json")
        self.assertEqual(response["exception_type"], "KeyboardInterrupt")
        with self.assertRaises(self.s.AmbiguousSubmissionError):
            self.submit()
        self.assertEqual(self.g.submissions, 1)

    def test_actual_gateway_submit_boundary_has_one_shell_free_sbatch_and_no_v4_writes(
        self,
    ):
        gateway = self.s.SchedulerGateway(self.contract)
        before = {
            str(p): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
            for p in (self.v4, *self.v4.rglob("*"))
        }

        def subprocess_fixture(argv, **kwargs):
            self.assertFalse(kwargs["shell"])
            result = self.g.run(argv, timeout=kwargs["timeout"])
            return subprocess.CompletedProcess(
                argv, result.returncode, result.stdout, result.stderr
            )

        with mock.patch.object(
            self.s.subprocess, "run", side_effect=subprocess_fixture
        ) as calls:
            result = self.s.submit(
                self.contract.confirm_action,
                "646900",
                self.sha,
                contract=self.contract,
                gateway=gateway,
            )
            again = self.s.submit(
                self.contract.confirm_action,
                "646900",
                self.sha,
                contract=self.contract,
                gateway=gateway,
            )
        self.assertEqual(result["status"], "SUBMITTED")
        self.assertEqual(again["status"], "ALREADY_SUBMITTED")
        submits = [
            c for c in calls.call_args_list if c.args[0][0] == str(self.contract.sbatch)
        ]
        self.assertEqual(len(submits), 1)
        self.assertEqual(
            before,
            {
                str(p): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                for p in (self.v4, *self.v4.rglob("*"))
            },
        )


class StatusTests(GatewayFixture):
    def observe(self):
        return self.s.status(contract=self.contract, gateway=self.g)

    def test_fresh_status_is_readonly(self):
        before = {
            str(p): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
            for p in self.root.rglob("*")
        }
        self.assertEqual(self.observe()["status"], "NOT_SUBMITTED")
        self.assertEqual(
            before,
            {
                str(p): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                for p in self.root.rglob("*")
            },
        )
        self.assertEqual(self.g.submissions, 0)

    def test_pending_running_and_accounting_delay(self):
        self.submit()
        for state in ("PENDING", "RUNNING"):
            self.g.queue = f"123|{state}|audattn_v4_numdiag\n".encode()
            self.assertEqual(self.observe()["status"], state)
        self.g.queue, self.g.accounting = b"", b""
        self.assertEqual(self.observe()["status"], "ACCOUNTING_PENDING")
        self.assertEqual(self.g.submissions, 1)

    def test_terminal_without_marker_is_incomplete_not_success(self):
        self.submit()
        for state, exit_code in (
            ("COMPLETED", "0:0"),
            ("FAILED", "2:0"),
            ("CANCELLED by 42", "0:15"),
        ):
            self.g.accounting = f"123|audattn_v4_numdiag|{state}|{exit_code}\n".encode()
            self.assertEqual(
                self.observe()["status"], "INCOMPLETE_UNTRAPPED_TERMINATION"
            )

    def test_marker_bound_to_receipt_is_reported_not_scientifically_verified(self):
        self.submit()
        for state in ("DIAGNOSTIC_COMPLETE", "DIAGNOSTIC_FAILED"):
            path = self.root / "state" / (state + ".json")
            marker = dict(
                schema_version=1,
                status=state,
                diagnostic_protocol=self.contract.protocol,
                evaluation_role="REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST",
                job_id="123",
                input_freeze_sha256=self.sha,
            )
            self.s.atomic_create_json(path, marker)
            before = {str(p): p.stat().st_mtime_ns for p in self.root.rglob("*")}
            report = self.observe()
            self.assertEqual(report["status"], state)
            self.assertFalse(report["results_verified"])
            self.assertEqual(
                before, {str(p): p.stat().st_mtime_ns for p in self.root.rglob("*")}
            )
            path.unlink()

    def test_wrong_marker_or_unresolved_intent_stops(self):
        with self.s.SubmissionJournal(self.contract).lock() as journal:
            journal.begin(self.sha, self.runner_sha, "c" * 32)
        self.assertEqual(self.observe()["status"], "STOP_AMBIGUOUS")
        self.assertEqual(self.g.calls, [])

    def test_malformed_accounting_is_not_success(self):
        self.submit()
        self.g.accounting = b"wrong\n"
        self.assertEqual(self.observe()["status"], "STOP_AMBIGUOUS")

    def test_wrong_terminal_binding_and_conflicting_markers_stop(self):
        self.submit()
        marker = dict(
            schema_version=1,
            status="DIAGNOSTIC_COMPLETE",
            diagnostic_protocol=self.contract.protocol,
            evaluation_role="REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST",
            job_id="456",
            input_freeze_sha256=self.sha,
        )
        path = self.root / "state/DIAGNOSTIC_COMPLETE.json"
        self.s.atomic_create_json(path, marker)
        self.assertEqual(self.observe()["status"], "STOP_AMBIGUOUS")
        self.s.atomic_create_json(self.root / "state/DIAGNOSTIC_FAILED.json", marker)
        self.assertEqual(self.observe()["status"], "STOP_AMBIGUOUS")

    def test_new_terminal_during_accounting_query_requires_requery(self):
        self.submit()
        original = self.g.run

        def run(argv, *, timeout=60):
            if argv[0] == str(self.contract.sacct):
                self.s.atomic_create_json(
                    self.root / "state/DIAGNOSTIC_COMPLETE.json",
                    dict(
                        schema_version=1,
                        status="DIAGNOSTIC_COMPLETE",
                        diagnostic_protocol=self.contract.protocol,
                        evaluation_role="REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST",
                        job_id="123",
                        input_freeze_sha256=self.sha,
                    ),
                )
            return original(argv, timeout=timeout)

        with mock.patch.object(self.g, "run", side_effect=run):
            report = self.observe()
        self.assertEqual(report["status"], "STOP_AMBIGUOUS")
        self.assertIn("changed", report["reason"])
        self.assertEqual(self.observe()["status"], "DIAGNOSTIC_COMPLETE")

    def test_changed_freeze_during_query_is_not_reported_as_running(self):
        self.submit()
        self.g.queue = b"123|RUNNING|audattn_v4_numdiag\n"
        original = self.g.run

        def run(argv, *, timeout=60):
            if argv[0] == str(self.contract.squeue):
                (self.root / "input_freeze.json").write_bytes(b"{}\n")
            return original(argv, timeout=timeout)

        with mock.patch.object(self.g, "run", side_effect=run):
            self.assertEqual(self.observe()["status"], "STOP_AMBIGUOUS")

    def test_status_cli_does_not_submit_or_write(self):
        self.submit()
        before = {
            str(p): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
            for p in self.root.rglob("*")
        }
        self.g.queue = b"123|RUNNING|audattn_v4_numdiag\n"
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = self.s.run_cli(["status"], contract=self.contract, gateway=self.g)
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue())["status"], "RUNNING")
        self.assertEqual(self.g.submissions, 1)
        self.assertEqual(
            before,
            {
                str(p): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                for p in self.root.rglob("*")
            },
        )


def load_numeric_test_fixtures():
    if "integration_numeric_fixtures" in sys.modules:
        return sys.modules["integration_numeric_fixtures"]
    spec = importlib.util.spec_from_file_location(
        "integration_numeric_fixtures", HERE / "test_numeric_diag.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def cpu_integration_child(config_json):
    """Test-only transport peer: real process, synthetic CPU data, never a GPU."""
    config = json.loads(config_json)
    with contextlib.redirect_stdout(sys.stderr):
        n = load_numeric_test_fixtures()
        d = n.diagnose
        d.DIAGNOSTIC_ROOT = pathlib.Path(config["attempt"]).parent.parent
        original_create = d.atomic_create_bytes

        def bounded_create(path, payload):
            if not pathlib.Path(path).is_relative_to(d.DIAGNOSTIC_ROOT):
                raise AssertionError(
                    "CPU child attempted publication outside diagnostic root"
                )
            return original_create(path, payload)

        d.atomic_create_bytes = bounded_create
        matrix = n.PersistedMatrixTests()
        matrix.scratch = pathlib.Path(config["scratch"])
        matrix.sources = config["sources"]
        matrix.env = dict(os.environ)
        cell = config["cell"]
        result = matrix.data(
            cell, delta=0.0077362060546875 if cell in (None, "A2") else 0.0
        )
        result["input_freeze_sha256"] = config["sha"]
        result["trials"] = tuple(
            dataclasses.replace(t, identity=config["trials"][t.ordinal]["identity"])
            for t in result["trials"]
        )
        for item in result["passes"]:
            meta = item.boundary_records["metadata"]
            meta["worker_pid"] = os.getpid()
            meta["attestation"]["worker_pid"] = os.getpid()
            meta["worker_environment"]["software"]["worker_pid"] = os.getpid()
            d._bind_pass_commitment(item)
        path = pathlib.Path(config["attempt"])
        path /= f"cells/{cell}" if cell else "reference_cold"
        writer = d.write_cell_artifacts if cell else d.write_reference_artifacts
        receipt = writer(path, result)
        completion = dict(
            schema_version=1,
            diagnostic_protocol=d.DIAGNOSTIC_PROTOCOL,
            evaluation_role=d.EVALUATION_ROLE,
            status="CHILD_ARTIFACTS_READY",
            job_id="123",
            input_freeze_sha256=config["sha"],
            worker_pid=os.getpid() + int(config.get("corrupt_pid", False)),
            mode="_child-cell" if cell else "_child-reference",
            cell=cell,
            marker_record=receipt["marker_record"],
        )
    sys.stdout.write(n.trace.canonical_json_bytes(completion).decode("ascii"))


class HermeticFakeSlurmIntegrationTests(GatewayFixture):
    """Real journals/owner/five processes/verifier; fake scheduler and CPU evidence."""

    def setUp(self):
        super().setUp()
        self.n = load_numeric_test_fixtures()
        self.fixture = self.n.ResultVerifierTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.v4 = self.fixture.files.v4
        self.d = self.n.diagnose
        self.contract = dataclasses.replace(
            self.s.PRODUCTION_CONTRACT,
            root=self.root,
            v4_root=self.v4,
            v4_manifest_sha256=self.fixture.files.contract.manifest_sha256,
        )
        records = []
        for name in self.d.PRODUCTION_FILES:
            path = self.root / "tools" / name
            path.write_bytes((HERE / name).read_bytes())
            path.chmod(0o600)
            records.append(
                self.n.trace.stable_file_record(path, allowed_root=self.root / "tools")
            )
        self.fixture.files.freeze["production_files"] = records
        raw = self.s.canonical(self.fixture.files.freeze)
        freeze_path = self.root / "input_freeze.json"
        freeze_path.write_bytes(raw)
        freeze_path.chmod(0o600)
        self.sha = hashlib.sha256(raw).hexdigest()
        self.fixture.matrix.sha = self.sha
        self.fixture.args.expected_input_freeze_sha256 = self.sha
        for name in ("INTENT.json", "SBATCH_RESPONSE.json", "SUBMISSION_RECEIPT.json"):
            (self.root / "state" / name).unlink()
        self.runner_sha = hashlib.sha256(RUNNER.read_bytes()).hexdigest()

    def run_pipeline(self, *, corrupt_pid=False):
        before = self.n.trace.fingerprint_tree(self.v4)
        args = [
            "submit",
            "--confirm-action",
            self.contract.confirm_action,
            "--confirm-v4-job-id",
            "646900",
            "--expected-input-freeze-sha256",
            self.sha,
        ]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = self.s.run_cli(args, contract=self.contract, gateway=self.g)
        self.assertEqual(rc, 0, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["status"], "SUBMITTED")
        self.assertEqual(self.g.submissions, 1)
        intent, _ = self.s.read_json(self.root / "state/INTENT.json")
        self.fixture.args.intent_nonce = intent["intent_nonce"]
        real_popen = subprocess.Popen
        launches = []

        def spawn(argv, **kwargs):
            cell = argv[argv.index("--cell") + 1] if "--cell" in argv else None
            expected = self.d.child_command(
                "_child-cell" if cell else "_child-reference",
                "123",
                self.sha,
                cell,
                self.fixture.matrix.scratch,
            )
            self.assertEqual(argv, expected)
            config = dict(
                scratch=str(self.fixture.matrix.scratch),
                sources=self.fixture.matrix.sources,
                trials=self.fixture.matrix.trials,
                attempt=str(self.fixture.matrix.attempt),
                sha=self.sha,
                cell=cell,
                corrupt_pid=corrupt_pid,
            )
            source = (
                "import importlib.util,sys;"
                "s=importlib.util.spec_from_file_location('cpu_peer',sys.argv[1]);"
                "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
                "m.cpu_integration_child(sys.argv[2])"
            )
            process = real_popen(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-c",
                    source,
                    __file__,
                    json.dumps(config),
                ],
                **kwargs,
            )
            launches.append((cell, process.pid))
            return process

        writes = []
        original_create = self.d.atomic_create_bytes

        def bounded_create(path, payload):
            self.assertTrue(pathlib.Path(path).is_relative_to(self.root))
            self.assertFalse(pathlib.Path(path).is_relative_to(self.v4))
            writes.append(str(path))
            return original_create(path, payload)

        with (
            mock.patch.object(self.d.subprocess, "Popen", side_effect=spawn),
            mock.patch.object(
                self.d, "atomic_create_bytes", side_effect=bounded_create
            ),
        ):
            report = self.d._coordinate(self.fixture.args, self.fixture.files.owner())
        self.assertTrue(writes)
        self.assertEqual(self.n.trace.fingerprint_tree(self.v4), before)
        self.assertEqual(self.g.submissions, 1)
        if corrupt_pid:
            self.assertEqual(report["status"], "DIAGNOSTIC_FAILED")
            self.assertEqual(len(launches), 1)
            self.assertFalse((self.root / "state/DIAGNOSTIC_COMPLETE.json").exists())
            failure = self.fixture.verify()
            self.assertEqual(failure["status"], "DIAGNOSTIC_FAILURE_RECORDED")
            self.assertFalse(failure["numeric_results_interpretable"])
            return
        self.assertEqual(
            report["status"], "DIAGNOSTIC_COMPLETE", report["primary_error"]
        )
        self.assertEqual([cell for cell, _ in launches], [None, "A2", "A1", "B1", "B2"])
        self.assertEqual(len({pid for _, pid in launches}), 5)
        diagnostic_before = self.n.trace.fingerprint_tree(self.root)
        with mock.patch.object(
            self.d.subprocess,
            "Popen",
            side_effect=AssertionError("verifier must not launch"),
        ):
            result = self.fixture.verify()
        self.assertEqual(self.n.trace.fingerprint_tree(self.root), diagnostic_before)
        self.assertEqual(result["status"], "DIAGNOSTIC_RESULTS_VERIFIED")
        self.assertEqual(result["matrix"]["a2_replay_classification"], "REPRODUCED")
        self.assertEqual(self.n.trace.fingerprint_tree(self.v4), before)
        self.assertEqual(self.g.submissions, 1)
        repeated = io.StringIO()
        with contextlib.redirect_stdout(repeated):
            rc = self.s.run_cli(args, contract=self.contract, gateway=self.g)
        self.assertEqual(rc, 2, repeated.getvalue())
        self.assertEqual(json.loads(repeated.getvalue())["status"], "STOP_AMBIGUOUS")
        self.assertEqual(self.g.submissions, 1)

    def test_cli_to_five_cold_processes_and_verified_finite_diff(self):
        self.run_pipeline()

    def test_wrong_child_pid_stops_pipeline_without_complete_marker(self):
        self.run_pipeline(corrupt_pid=True)


class ReleaseCallableSurfaceTests(unittest.TestCase):
    def test_production_ast_has_no_v4_evaluation_or_publication_calls(self):
        forbidden = {
            "run_evaluation",
            "_create_attempt_directory",
            "publish_smoke",
            "publish_audit",
        }
        for name in (
            "diagnose_batch_invariance.py",
            "numeric_trace.py",
            "submit_numeric_diag.py",
        ):
            tree = ast.parse((HERE / name).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    called = getattr(node.func, "attr", getattr(node.func, "id", None))
                    self.assertNotIn(called, forbidden, (name, node.lineno))

    def test_evaluator_whitelist_is_exact_read_inference_surface(self):
        self.assertEqual(
            set(load_diag().V4_EVALUATOR_WHITELIST),
            {
                "_frozen_import_context",
                "strict_load_model",
                "singleton_native_preprocess",
                "predict_batch",
                "_select_smoke_bank",
                "_configure_runtime",
                "_tensor_hashes",
            },
        )


if __name__ == "__main__":
    unittest.main()

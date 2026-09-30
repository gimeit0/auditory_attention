"""Synthetic subprocess/scheduler-double checks; no SSH or actual allocation."""
import ast
import builtins
import contextlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
import types
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coordinator  # noqa: E402
import job_contract as contract  # noqa: E402
import process_runner as runner  # noqa: E402


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gpu-job-control-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def child(self, code, seconds=2, cap=8192):
        return runner.run_process([sys.executable, "-I", "-B", "-c", code], dict(os.environ),
                                  self.root / "child.log", seconds=seconds, max_log_bytes=cap)

    def pair(self, reference="print('reference')", observed="print('observed')", verify=None, final=None):
        return runner.run_pair(self.root / "pair", {
            role: [sys.executable, "-I", "-B", "-c", code]
            for role, code in (("reference", reference), ("observed", observed))},
            {r: dict(os.environ) for r in ("reference", "observed")}, child_seconds=1, total_seconds=3,
            verify_child=verify or (lambda role, record: (role, record["pid"])),
            verify_pair=final or (lambda a, b: {"verified": a[1] != b[1]}))

    def test_child_success_and_log_recheck(self):
        value = self.child("print('hello')")
        self.assertEqual(value["returncode"], 0)
        self.assertIsNone(value["error"])
        self.assertEqual(value["log"]["sha256"], runner.file_record(self.root / "child.log")["sha256"])

    def test_child_nonzero_not_retried(self):
        self.assertEqual(self.child("raise SystemExit(7)")["returncode"], 7)

    def test_child_missing_executable_recorded(self):
        value = runner.run_process([str(self.root / "missing")], dict(os.environ), self.root / "missing.log", seconds=1)
        self.assertEqual(value["error"]["type"], "FileNotFoundError")
        self.assertIsNone(value["pid"])

    def test_silent_child_timeout(self):
        value = self.child("import time; time.sleep(5)", seconds=0.2)
        self.assertEqual(value["error"]["type"], "TimeoutError")
        self.assertEqual(value["returncode"], -signal.SIGKILL)

    def test_exited_leader_descendant_pipe_is_bounded(self):
        value = self.child("import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(5)'])", seconds=0.3)
        self.assertEqual(value["error"]["type"], "TimeoutError")
        self.assertLess(value["elapsed_seconds"], 2)

    def test_log_overflow_prefix_preserved(self):
        value = self.child("print('x'*100000)", cap=1024)
        self.assertIn("log budget", value["error"]["message"])
        self.assertEqual((self.root / "child.log").stat().st_size, 1024)

    def test_pair_success_distinct_processes(self):
        value = self.pair()
        self.assertEqual(value["status"], "PAIR_VERIFIED")
        self.assertEqual(len({c["pid"] for c in value["children"]}), 2)
        self.assertEqual(json.loads((self.root / "pair/TERMINAL.json").read_bytes()), value)

    def test_reference_failure_does_not_start_observed(self):
        value = self.pair(reference="raise SystemExit(2)")
        self.assertEqual(value["status"], "PAIR_FAILED")
        self.assertEqual(len(value["children"]), 1)
        self.assertFalse((self.root / "pair/observed.log").exists())

    def test_observed_failure_retains_reference(self):
        value = self.pair(observed="raise SystemExit(2)")
        self.assertEqual(value["status"], "PAIR_FAILED")
        self.assertEqual(len(value["children"]), 2)
        self.assertTrue((self.root / "pair/reference-process.json").exists())

    def test_zero_rc_does_not_override_artifact_failure(self):
        def reject(*_):
            raise RuntimeError("damaged evidence")
        value = self.pair(verify=reject)
        self.assertEqual(value["status"], "PAIR_FAILED")
        self.assertEqual(len(value["children"]), 1)

    def test_failed_final_verifier_not_accepted(self):
        self.assertEqual(self.pair(final=lambda *_: {"verified": False})["status"], "PAIR_FAILED")

    def test_existing_pair_root_never_overwritten(self):
        self.pair()
        with self.assertRaises(FileExistsError):
            self.pair()

    def test_verifier_deadline_restores_handler(self):
        before = signal.getsignal(signal.SIGALRM)
        with self.assertRaises(TimeoutError):
            with runner.verification_deadline(0.05):
                time.sleep(0.2)
        self.assertEqual(signal.getsignal(signal.SIGALRM), before)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))

    def test_verifier_exception_restores_handler(self):
        before = signal.getsignal(signal.SIGALRM)
        with self.assertRaises(ValueError):
            with runner.verification_deadline(1):
                raise ValueError("fixture")
        self.assertEqual(signal.getsignal(signal.SIGALRM), before)

    def test_write_once_preserves_original(self):
        runner.write_once(self.root / "record", {"first": True})
        with self.assertRaises(FileExistsError):
            runner.write_once(self.root / "record", {"first": False})
        self.assertEqual(json.loads((self.root / "record").read_bytes()), {"first": True})

    def test_hash_rejects_symlink_and_hardlink(self):
        runner.write_once(self.root / "record", {})
        (self.root / "alias").symlink_to(self.root / "record")
        with self.assertRaises(OSError):
            runner.file_record(self.root / "alias")
        os.link(self.root / "record", self.root / "hard")
        with self.assertRaises(RuntimeError):
            runner.file_record(self.root / "record")

    def test_submit_requires_new_explicit_authorization(self):
        call = mock.Mock(return_value={"job_id": "123"})
        with self.assertRaises(RuntimeError):
            runner.submit_once(self.root, {"approved": False}, call)
        call.assert_not_called()
        self.assertFalse((self.root / "SUBMIT_INTENT.json").exists())

    def test_submit_journal_before_exactly_one_call(self):
        def submit():
            self.assertTrue((self.root / "SUBMIT_INTENT.json").exists())
            return {"job_id": "123"}
        call = mock.Mock(side_effect=submit)
        runner.submit_once(self.root, {"approved": True}, call)
        with self.assertRaises(FileExistsError):
            runner.submit_once(self.root, {"approved": True}, call)
        call.assert_called_once()

    def test_uncertain_submit_never_retries(self):
        call = mock.Mock(side_effect=TimeoutError("lost scheduler response"))
        with self.assertRaises(TimeoutError):
            runner.submit_once(self.root, {"approved": True}, call)
        with self.assertRaises(FileExistsError):
            runner.submit_once(self.root, {"approved": True}, call)
        call.assert_called_once()
        self.assertFalse(json.loads((self.root / "SUBMIT_UNCERTAIN.json").read_bytes())["retry_allowed"])

    def test_invalid_scheduler_response_is_uncertain(self):
        with self.assertRaises(RuntimeError):
            runner.submit_once(self.root, {"approved": True}, lambda: {"job_id": "123;124"})
        self.assertTrue((self.root / "SUBMIT_UNCERTAIN.json").exists())

    def test_gpu_zero_is_an_index(self):
        env = {"SLURM_JOB_ID": "123", "SLURM_CPUS_PER_TASK": "8", "SLURM_NTASKS": "1", "SLURM_NNODES": "1",
               "SLURM_MEM_PER_NODE": "65536", "SLURM_JOB_PARTITION": "GPU-1A", "SLURM_JOB_GPUS": "0", "CUDA_VISIBLE_DEVICES": "0"}
        contract.allocation(env, host="spcc-a100g04")
        for key, bad in (("SLURM_JOB_GPUS", "0,1"), ("CUDA_VISIBLE_DEVICES", ""), ("SLURM_CPUS_PER_TASK", "4"),
                         ("SLURM_MEM_PER_NODE", "4096"), ("SLURM_JOB_ID", "0"), ("SLURM_JOB_PARTITION", "CPU")):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                contract.allocation({**env, key: bad}, host="spcc-a100g04")
        with self.assertRaises(RuntimeError):
            contract.allocation(env, host="hakusan1")

    def test_home_preserved_and_child_environment_sanitized(self):
        original = dict(os.environ)
        parent = {**original, "UNRELATED_SECRET": "synthetic", "SLURM_JOB_ID": "123", "CUDA_VISIBLE_DEVICES": "0"}
        env = coordinator.child_environment(parent, self.root, "reference")
        self.assertEqual(env["HOME"], original["HOME"])
        self.assertNotIn("UNRELATED_SECRET", env)
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "0")
        self.assertTrue(env["TMPDIR"].endswith("reference_cold/tmp"))
        self.assertEqual(dict(os.environ), original)
        with self.assertRaises(RuntimeError):
            coordinator.child_environment(parent, self.root, "invalid")

    def test_verifier_cache_environment_restored(self):
        original = dict(os.environ)
        with coordinator.verifier_environment(self.root / "cache"):
            self.assertEqual(os.environ["HOME"], original["HOME"])
            self.assertTrue(Path(os.environ["TORCH_HOME"]).is_dir())
        self.assertEqual(dict(os.environ), original)

    def test_candidate_entry_gates_precede_numeric_imports(self):
        tree = ast.parse((HERE / "gpu_child.py").read_bytes())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run")
        attempt = next(n for n in function.body if isinstance(n, ast.Try))
        first_numeric = next(i for i, n in enumerate(attempt.body) if isinstance(n, ast.Import)
                             and any(a.name == "cuda_registration" for a in n.names))
        prefix = ast.unparse(ast.Module(body=function.body[:function.body.index(attempt)] +
                                       attempt.body[:first_numeric], type_ignores=[]))
        self.assertIn("_startup.open_scratch", ast.unparse(attempt.body[0]))
        self.assertIn("startup_stack", ast.unparse(attempt.finalbody))
        self.assertIn("contract.child_cold_gate", prefix)
        self.assertIn("contract.check_sources", prefix)
        self.assertIn("contract.check_authorization", prefix)
        self.assertNotIn("allow_cpu=True", ast.unparse(tree))

    def test_deployed_entry_matches_reviewed_startup_derivation(self):
        sys.path.insert(0, str(HERE.parent / "targeted_gpu_startup_20260914"))
        import entry_adapter
        expected, audit = entry_adapter.derive()
        source = ast.parse((HERE / "gpu_child.py").read_bytes())
        actual = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "run")
        self.assertEqual(ast.dump(actual), ast.dump(expected.body[0]))
        previous = ast.parse(entry_adapter.OLD_ENTRY.read_bytes())
        lifetime = lambda t: next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == "lifetime")
        self.assertEqual(ast.dump(lifetime(source)), ast.dump(lifetime(previous)))
        self.assertTrue(audit["original_run_ast_restored_exactly"])

    def test_new_typed_a100_runner_and_root_not_old_attempt(self):
        script = (HERE / "run_gpu.sbatch").read_text()
        self.assertEqual(script.count("#SBATCH --gres=gpu:nvidia_a100:1\n"), 1)
        self.assertNotIn("#SBATCH --gpus", script)
        self.assertIn("#SBATCH --nodes=1\n", script)
        self.assertIn("gpu_pair_2026-09-14_v3", script)
        self.assertNotIn("gpu_pair_2026-09-13_v1", script)
        self.assertEqual(contract.REMOTE.name, "gpu_pair_2026-09-14_v3")
        self.assertEqual(contract.LIMITS, {"jobs": 1, "gpus": 1, "cpus": 8, "memory_mib": 65536,
            "wall_seconds": 7200, "child_seconds": 3000, "pair_seconds": 6600, "partition": "GPU-1A"})

    def test_real_v2_entry_opens_scratch_before_import_and_records_failure(self):
        import gpu_child
        events = []
        @contextlib.contextmanager
        def scope(*_):
            events.append("scratch_enter")
            try:
                yield object()
            finally:
                events.append("scratch_exit")
        (self.root / "artifacts").mkdir()
        candidate = types.SimpleNamespace(child_cold_gate=lambda _: events.append("cold_gate"),
            require=contract.require, check_sources=lambda _: None, check_authorization=lambda *_: None,
            REMOTE=self.root, FREEZE_SHA=contract.FREEZE_SHA)
        original_import = builtins.__import__
        def importing(name, *args, **kwargs):
            if name == "cuda_registration":
                events.append("numeric_import")
                raise ImportError("synthetic cold import failure")
            return original_import(name, *args, **kwargs)
        with mock.patch.object(gpu_child, "contract", candidate), \
                mock.patch.object(gpu_child, "_startup", types.SimpleNamespace(open_scratch=scope)), \
                mock.patch.dict(os.environ, {"SLURM_JOB_ID": "7770001"}), \
                mock.patch("builtins.__import__", importing):
            self.assertEqual(gpu_child.run("reference", "a" * 64, "b" * 32), 2)
        record = json.loads((self.root / "artifacts/reference/CHILD.json").read_bytes())
        self.assertEqual(events, ["cold_gate", "scratch_enter", "numeric_import", "scratch_exit"])
        self.assertEqual(record["status"], "GPU_CHILD_FAILED")
        self.assertEqual(record["error"]["type"], "ImportError")
        self.assertEqual(record["cleanup_errors"], [])


if __name__ == "__main__":
    unittest.main()

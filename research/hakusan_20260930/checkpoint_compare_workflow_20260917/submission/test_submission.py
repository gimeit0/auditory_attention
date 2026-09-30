"""Synthetic scheduler/process tests; no remote calls and no GPU qualification."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "small_test_control", HERE / "remote_control.py"
)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def held(job="123"):
    return (
        f"JobId={job} JobName={c.JOB_NAME} UserId=s2510040(1) Comment=eager-s1-"
        + "a" * 32
        + f" Partition=GPU-1A Account=student NumCPUs=8 NumNodes=1 NumTasks=1 CPUs/Task=8 TimeLimit=00:30:00 Requeue=0 Restarts=0 WorkDir={c.ROOT} Command={c.ROOT}/tools/run_small.sbatch ReqTRES=cpu=8,mem=64G,node=1,billing=8,gres/gpu=1,gres/gpu:nvidia_a100=1 TresPerNode=gres/gpu:nvidia_a100:1 JobState=PENDING Reason=JobHeldUser Priority=0"
    )


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "run"
        self.root.mkdir(mode=0o700)
        for name in ("state", "attempts", "tools", "logs"):
            (self.root / name).mkdir(mode=0o700)
        self.patch = patch.object(c, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.release = {"nonce": "a" * 32, "limits": c.LIMITS}
        c.write(
            self.root / "state/TEST_ONLY.json",
            c.wire({"release_sha256": "sha", "result": {"rc": 0}}),
        )

    def fake(self, argv):
        if argv[0] == "/usr/bin/sbatch":
            return {"rc": 0, "stdout": "123\n", "stderr": ""}
        return {"rc": 0, "stdout": held(), "stderr": ""}

    def test_valid_held_and_runtime_allocation(self):
        c.validate_job(held(), self.release, "123", True)
        raw = (
            held().replace("JobState=PENDING", "JobState=RUNNING")
            + " AllocTRES=cpu=8,mem=64G,node=1,gres/gpu=1,gres/gpu:nvidia_a100=1"
        )
        c.validate_job(raw, self.release, "123", False)

    def test_wrong_gpu_blocks(self):
        for raw in (
            held().replace("nvidia_a100", "h100-20c"),
            held().replace("gres/gpu:nvidia_a100:1", "gres/gpu:1"),
        ):
            with self.assertRaises(RuntimeError):
                c.validate_job(raw, self.release, "123", True)

    def test_other_resource_and_identity_changes_block(self):
        for key, old, new in (
            ("NumCPUs", "8", "16"),
            ("NumNodes", "1", "2"),
            ("TimeLimit", "00:30:00", "03:00:00"),
            ("Requeue", "0", "1"),
            ("Account", "student", "other"),
            ("JobId", "123", "456"),
        ):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                c.validate_job(
                    held().replace(key + "=" + old, key + "=" + new),
                    self.release,
                    "123",
                    True,
                )

    def test_runtime_rejects_wrong_allocated_gpu(self):
        raw = (
            held().replace("JobState=PENDING", "JobState=RUNNING")
            + " AllocTRES=cpu=8,mem=64G,node=1,gres/gpu=1,gres/gpu:h100-20c=1"
        )
        with self.assertRaises(RuntimeError):
            c.validate_job(raw, self.release, "123", False)

    def test_submit_once_never_releases(self):
        calls = []

        def execute(argv):
            calls.append(argv)
            return self.fake(argv)

        with patch.object(c, "preflight", return_value={}):
            out = c.submit(self.release, "sha", execute)
            self.assertEqual(out["status"], "SUBMITTED_HELD")
            with self.assertRaises(RuntimeError):
                c.submit(self.release, "sha", execute)
        self.assertEqual(sum(a[0] == "/usr/bin/sbatch" for a in calls), 1)
        self.assertFalse(any("release" in a for a in calls))

    def test_timeout_consumes_intent(self):
        with patch.object(c, "preflight", return_value={}):
            with self.assertRaisesRegex(RuntimeError, "SUBMISSION_UNKNOWN"):
                c.submit(
                    self.release,
                    "sha",
                    lambda a: {"rc": 124, "stdout": "", "stderr": "timeout"},
                )
            with self.assertRaisesRegex(RuntimeError, "already attempted"):
                c.submit(self.release, "sha", self.fake)

    def test_wrong_resource_submission_retains_job(self):
        def execute(argv):
            out = self.fake(argv)
            return dict(out, stdout=out["stdout"].replace("nvidia_a100", "h100-20c"))

        with patch.object(c, "preflight", return_value={}):
            out = c.submit(self.release, "sha", execute)
        self.assertEqual(out["job_id"], "123")
        self.assertEqual(out["status"], "HELD_RESOURCE_MISMATCH")

    def test_release_once_and_no_repeat(self):
        c.write(
            self.root / "state/SUBMISSION.json",
            c.wire(
                {
                    "job_id": "123",
                    "nonce": self.release["nonce"],
                    "release_sha256": "sha",
                }
            ),
        )
        calls = []

        def execute(argv):
            calls.append(argv)
            return self.fake(argv)

        with patch.object(c, "checked", return_value=self.release):
            c.release_job(self.release, "sha", execute)
            with self.assertRaises(FileExistsError):
                c.release_job(self.release, "sha", execute)
        self.assertEqual(sum("release" in a for a in calls), 1)

    def test_failed_test_prevents_submit(self):
        with self.assertRaisesRegex(RuntimeError, "Matching"):
            c.submit(self.release, "wrong", self.fake)

    def test_exact_argv_budget_testonly(self):
        args = c.batch_argv(self.release, "sha", True)
        self.assertIn("--test-only", args)
        self.assertNotIn("--hold", args)
        self.assertIn("--time=00:30:00", args)
        self.assertIn("--gres=gpu:nvidia_a100:1", args)
        self.assertEqual(args[-1], "sha")
        self.assertFalse(any("\x00" in a for a in args))

    def test_exclusive_write_and_symlink_rejection(self):
        p = self.root / "record"
        c.write(p, b"original")
        with self.assertRaises(FileExistsError):
            c.write(p, b"replacement")
        alias = self.root / "alias"
        alias.symlink_to(p)
        with self.assertRaises(RuntimeError):
            c.read(alias)

    def test_real_process_error_and_timeout(self):
        result = c.command(["/bin/sh", "-c", "echo failure >&2; exit 7"])
        self.assertEqual(result["rc"], 7)
        self.assertIn("failure", result["stderr"])
        result = c.command(["/bin/sleep", "1"], timeout=0.01)
        self.assertEqual(result["rc"], 124)

    def test_runner_rejects_missing_arg_before_python(self):
        result = subprocess.run(
            ["/bin/bash", str(HERE / "run_small.sbatch")],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("No such file", result.stderr)

    def test_launch_fails_locally_without_model(self):
        import sys

        result = subprocess.run(
            [sys.executable, "-I", "-B", str(HERE / "launch_small.py"), "sha"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Use native Python", result.stderr)


if __name__ == "__main__":
    unittest.main()

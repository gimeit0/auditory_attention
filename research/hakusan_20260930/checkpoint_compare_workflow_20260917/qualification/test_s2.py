"""Local-only real subprocess/filesystem tests and simulated scheduler RPCs."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = load("s2_test_control", HERE / "control_s2.py")
launcher = load("s2_test_launcher", HERE / "launch_s2.py")
s = load("s2_test_ship", HERE / "ship_s2.py")
c = m.c


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def argv(self, stage):
        return [
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import os;print('SYNTHETIC_PID='+str(os.getpid()))",
        ]

    def test_two_distinct_real_processes_and_durable_records(self):
        records = launcher.run_children(
            self.root, self.argv, lambda stage, batch, identity: identity, timeout=5
        )
        self.assertEqual([r["batch_size"] for r in records], [16, 1])
        self.assertEqual(len({r["pid"] for r in records}), 2)
        self.assertNotIn(os.getpid(), {r["pid"] for r in records})
        self.assertEqual(len(list(self.root.glob("*.json"))), 6)

    def test_first_failure_prevents_second(self):
        with self.assertRaisesRegex(RuntimeError, "rc=7"):
            launcher.run_children(
                self.root,
                lambda stage: [sys.executable, "-c", "raise SystemExit(7)"],
                lambda *args: None,
                timeout=5,
            )
        self.assertFalse((self.root / "batch1_INTENT.json").exists())

    def test_first_verification_failure_prevents_second(self):
        def reject(*args):
            raise RuntimeError("bad receipt")

        with self.assertRaisesRegex(RuntimeError, "bad receipt"):
            launcher.run_children(self.root, self.argv, reject, timeout=5)
        self.assertFalse((self.root / "batch1_INTENT.json").exists())

    def test_repeat_is_rejected_before_spawn(self):
        launcher.run_children(self.root, self.argv, lambda *args: None, timeout=5)
        with patch.object(launcher.subprocess, "Popen") as spawn:
            with self.assertRaises(FileExistsError):
                launcher.run_children(
                    self.root, self.argv, lambda *args: None, timeout=5
                )
            spawn.assert_not_called()

    def test_total_timeout_terminates_owned_child_and_stops(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            launcher.run_children(
                self.root,
                lambda stage: [sys.executable, "-c", "import time;time.sleep(5)"],
                lambda *args: None,
                timeout=0.05,
            )
        record = json.loads((self.root / "repeat16_PROCESS.json").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(record["pid"], 0)
        self.assertFalse((self.root / "batch1_INTENT.json").exists())


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "new_root"
        self.root.mkdir()
        for name in ("state", "tools", "attempts", "logs"):
            (self.root / name).mkdir()
        p = patch.object(m, "ROOT", self.root)
        p.start()
        self.addCleanup(p.stop)
        self.files = {
            name: (HERE / name).read_bytes()
            for name in ("control_s2.py", "launch_s2.py", "run_s2.sbatch")
        }
        self.files["s1_control.py"] = (
            HERE.parent / "submission/remote_control.py"
        ).read_bytes()
        self.files["eager_compare.py"] = (
            PROJECT / "same_bank_compare_2026_09_17_eager_v1/eager_compare.py"
        ).read_bytes()
        self.files["AUTHORIZATION.json"] = c.wire(
            {
                "limits": m.LIMITS,
                "status": "USER_APPROVED",
                "conditional_release": True,
                "resource_repair_authorized": False,
            }
        )
        self.release = {
            "protocol": m.PROTOCOL,
            "nonce": "a" * 32,
            "limits": m.LIMITS,
            "baseline_receipt_sha256": m.BASELINE_SHA,
            "files": {n: c.sha(b) for n, b in self.files.items()},
        }
        self.raw_release = c.wire(self.release)
        self.digest = c.sha(self.raw_release)
        c.write(self.root / "RELEASE.json", self.raw_release)
        for name, raw in self.files.items():
            c.write(self.root / "tools" / name, raw)
        native = json.loads(
            (
                PROJECT
                / "docs/superpowers/evidence/eager-small-production-20260917/repair-inspect-6ty1jjww/RESULT.json"
            ).read_text()
        )["result"]["result"]["snapshot"]["job"]["stdout"]
        self.raw_job = (
            native.replace(str(c.ROOT), str(self.root))
            .replace("JobId=724808", "JobId=123")
            .replace("JobName=audattn_eager_s1", "JobName=" + m.JOB_NAME)
            .replace(
                "eager-s1-d43522ea059d47688fd05235f8adeccf", "eager-s2a-" + "a" * 32
            )
            .replace("run_small.sbatch", "run_s2.sbatch")
        )
        self.calls = []
        for name, value in (("preflight", {}), ("baseline", {})):
            p = patch.object(m, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        c.write(
            self.root / "state/TEST_ONLY.json",
            c.wire(
                {
                    "release_sha256": self.digest,
                    "result": {
                        "rc": 0,
                        "argv": m.batch_argv(self.release, self.digest, True),
                    },
                }
            ),
        )

    def execute(self, argv):
        self.calls.append(argv)
        if argv[0] == "/usr/bin/sbatch":
            out = "123\n"
        elif argv[0] == "/usr/bin/sacct":
            out = "123|PENDING|" + c.fields(self.raw_job)["ReqTRES"] + "||00:00:00\n"
        elif argv[1:3] == ["write", "batch_script"]:
            out = self.files["run_s2.sbatch"].decode()
        elif argv[1:2] == ["release"]:
            out = ""
        else:
            out = self.raw_job
        return {"argv": argv, "rc": 0, "stdout": out, "stderr": ""}

    def action(self, name, execute=None):
        return m.remote(
            {"action": name, "release_sha256": self.digest}, execute or self.execute
        )

    def test_native_format_and_exact_total_node_gpu_args(self):
        m.validate_job(self.raw_job, self.release, "123", True)
        argv = m.batch_argv(self.release, self.digest)
        self.assertIn("--gpus=nvidia_a100:1", argv)
        self.assertIn("--gpus-per-node=nvidia_a100:1", argv)
        self.assertFalse(any(x.startswith("--gres") for x in argv))
        self.assertIn("--hold", argv)

    def test_wrong_allocation_or_budget_blocked(self):
        for old, new in [
            ("nvidia_a100", "h100-20c"),
            ("NumCPUs=8", "NumCPUs=16"),
            ("NumNodes=1-1", "NumNodes=1-2"),
            ("RunTime=00:00:00", "RunTime=00:00:01"),
        ]:
            with self.subTest(old=old), self.assertRaises(RuntimeError):
                m.validate_job(
                    self.raw_job.replace(old, new), self.release, "123", True
                )

    def test_submit_then_release_once(self):
        self.assertEqual(self.action("submit")["status"], "SUBMITTED_HELD")
        with self.assertRaisesRegex(RuntimeError, "already attempted"):
            self.action("submit")
        self.assertEqual(self.action("release")["status"], "RELEASED_ONCE")
        with self.assertRaisesRegex(RuntimeError, "already attempted"):
            self.action("release")
        self.assertEqual(sum(a[0] == "/usr/bin/sbatch" for a in self.calls), 1)
        self.assertEqual(sum(a[1:2] == ["release"] for a in self.calls), 1)

    def test_mismatch_stays_held_and_release_rejected(self):
        self.raw_job = self.raw_job.replace("nvidia_a100", "h100-20c")
        self.assertEqual(self.action("submit")["status"], "HELD_RESOURCE_MISMATCH")
        with self.assertRaises(RuntimeError):
            self.action("release")
        self.assertFalse(any(a[1:2] == ["release"] for a in self.calls))

    def test_uncertain_submission_never_retried(self):
        def timeout(argv):
            if argv[0] == "/usr/bin/sbatch":
                self.calls.append(argv)
                return {"argv": argv, "rc": 124, "stdout": "", "stderr": "timeout"}
            return self.execute(argv)

        with self.assertRaisesRegex(RuntimeError, "SUBMISSION_UNKNOWN"):
            self.action("submit", timeout)
        with self.assertRaisesRegex(RuntimeError, "already attempted"):
            self.action("submit")
        self.assertEqual(sum(a[0] == "/usr/bin/sbatch" for a in self.calls), 1)

    def test_uncertain_release_never_retried(self):
        self.action("submit")

        def timeout(argv):
            if argv[1:2] == ["release"]:
                self.calls.append(argv)
                return {"argv": argv, "rc": 124, "stdout": "", "stderr": "timeout"}
            return self.execute(argv)

        with self.assertRaisesRegex(RuntimeError, "Command failed"):
            self.action("release", timeout)
        with self.assertRaisesRegex(RuntimeError, "already attempted"):
            self.action("release")
        self.assertEqual(sum(a[1:2] == ["release"] for a in self.calls), 1)

    def test_changed_candidate_rejected(self):
        (self.root / "tools/eager_compare.py").write_text("changed")
        with self.assertRaisesRegex(RuntimeError, "Package changed"):
            self.action("submit")
        self.assertEqual(self.calls, [])

    def test_missing_or_different_test_only_blocks_submit(self):
        path = self.root / "state/TEST_ONLY.json"
        value = json.loads(path.read_text())
        value["result"]["argv"] += ["--gpus=2"]
        path.write_bytes(c.wire(value))
        with self.assertRaisesRegex(RuntimeError, "matching test-only"):
            self.action("submit")
        self.assertEqual(self.calls, [])

    def test_saved_spool_change_blocks_release(self):
        self.action("submit")

        def changed(argv):
            record = self.execute(argv)
            if argv[1:3] == ["write", "batch_script"]:
                record["stdout"] += "# changed\n"
            return record

        with self.assertRaisesRegex(RuntimeError, "Submitted script differs"):
            self.action("release", changed)
        self.assertFalse(any(a[1:2] == ["release"] for a in self.calls))

    def test_payload_compiles_without_filesystem_module_import(self):
        request = s.payload("status", self.raw_release, self.files, self.digest)
        compile(request, "<tested-payload>", "exec")
        self.assertIn(b"m.common=common", request)


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.parent = (
            PROJECT
            / "docs/superpowers/evidence/eager-small-production-20260917/collect-724808-8lr7w3yd/archive/attempts"
        )
        self.stage = "slurm-724808"
        self.run = json.loads((self.parent / self.stage / "RUN.json").read_text())

    def test_verified_real_s1_receipt_readonly_path(self):
        with patch.object(
            launcher.platform, "node", return_value=self.run["environment"]["hostname"]
        ):
            out = launcher.verify_child(
                self.parent,
                self.stage,
                16,
                {"pid": self.run["pid"]},
                self.run,
                "724808",
            )
        self.assertEqual(out["receipt_sha256"], m.BASELINE_SHA)

    def test_wrong_child_pid_or_batch_is_rejected(self):
        with patch.object(
            launcher.platform, "node", return_value=self.run["environment"]["hostname"]
        ):
            for batch, pid in ((1, self.run["pid"]), (16, self.run["pid"] + 1)):
                with (
                    self.subTest(batch=batch),
                    self.assertRaisesRegex(RuntimeError, "process/batch identity"),
                ):
                    launcher.verify_child(
                        self.parent, self.stage, batch, {"pid": pid}, self.run, "724808"
                    )

    def test_child_cannot_start_production_from_local_mac(self):
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(HERE / "launch_s2.py"),
                "unused",
                "--child",
                "repeat16",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Native Python -I -B required", result.stderr)


if __name__ == "__main__":
    unittest.main()

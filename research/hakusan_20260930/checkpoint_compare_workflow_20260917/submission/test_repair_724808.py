"""Local filesystem integration + simulated scheduler; never contacts HAKUSAN."""

import base64
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parents[1] / "docs/superpowers/evidence/eager-small-production-20260917"
spec = importlib.util.spec_from_file_location(
    "tested_repair", HERE / "repair_724808.py"
)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "run"
        self.root.mkdir(mode=0o700)
        for name in ("state", "attempts", "tools"):
            (self.root / name).mkdir(mode=0o700)
        self.source = (HERE / "remote_control.py").read_bytes()
        self.c = r.loaded(
            self.source, "tested_live_control", HERE / "remote_control.py"
        )
        self.c.ROOT = self.root
        self.release = json.loads((EVIDENCE / "package/RELEASE.json").read_text())
        for name in self.release["files"]:
            self.c.write(
                self.root / "tools" / name, (EVIDENCE / "package" / name).read_bytes()
            )
        self.c.write(
            self.root / "RELEASE.json", (EVIDENCE / "package/RELEASE.json").read_bytes()
        )
        # Synthetic submit journals have real fixed identity, never saved outside temp.
        argv = self.c.batch_argv(self.release, r.BASE_SHA)
        records = {
            "SUBMISSION.json": {
                "automatic_retry": False,
                "job_id": r.JOB,
                "nonce": self.release["nonce"],
                "release_sha256": r.BASE_SHA,
                "status": "SUBMITTED_HELD",
            },
            "SUBMIT_INTENT.json": {
                "release_sha256": r.BASE_SHA,
                "nonce": self.release["nonce"],
                "argv": argv,
            },
            "SBATCH_RESPONSE.json": {"rc": 0, "stdout": r.JOB + "\n", "argv": argv},
            "TEST_ONLY.json": {
                "release_sha256": r.BASE_SHA,
                "result": {
                    "rc": 0,
                    "argv": self.c.batch_argv(self.release, r.BASE_SHA, test=True),
                },
            },
        }
        for name, value in records.items():
            self.c.write(self.root / "state" / name, self.c.wire(value))
        status = json.loads((EVIDENCE / "status-yyum1i2c/RESULT.json").read_text())[
            "result"
        ]["result"]
        self.raw = status["job"]["stdout"].replace(
            "/home/s2510040/audattn_external_eval_ops/eager_small_20260917_v1",
            str(self.root),
        )
        self.batch = (EVIDENCE / "package/run_small.sbatch").read_text()
        self.calls = []
        self.spec = {
            "controller": base64.b64encode(self.source).decode(),
            "controller_sha256": self.c.sha(self.source),
            "repair_sha256": self.c.sha((HERE / "repair_724808.py").read_bytes()),
        }
        original_loaded = r.loaded

        def redirect(raw, name, path):
            module = original_loaded(raw, name, path)
            module.ROOT = self.root
            return module

        p = patch.object(r, "loaded", side_effect=redirect)
        p.start()
        self.addCleanup(p.stop)

    def execute(self, argv):
        self.calls.append(argv)
        if argv == r.UPDATE:
            self.raw = (
                self.raw.replace(
                    "gres/gpu:h100-20c=1", "gres/gpu:nvidia_a100=1"
                ).replace("TresPerNode=gres/gpu:1", "TresPerNode=" + r.GPU)
                + " TresPerJob="
                + r.GPU
            )
            output = ""
        elif argv[0] == "/usr/bin/sacct":
            req = self.c.fields(self.raw)["ReqTRES"]
            output = r.JOB + "|PENDING|" + req + "||00:00:00\n"
        elif argv[0] == "/usr/bin/squeue":
            output = (
                r.JOB
                + "|PENDING|"
                + self.c.JOB_NAME
                + "|eager-s1-"
                + self.release["nonce"]
                + "\n"
            )
        elif argv[1:3] == ["write", "batch_script"]:
            output = self.batch
        elif argv[1:] == ["--version"]:
            output = "slurm 25.05.5\n"
        else:
            output = self.raw
        return {"argv": argv, "rc": 0, "stdout": output, "stderr": ""}

    def install(self):
        return r.install(self.c, self.spec, self.release, self.execute)

    def test_archive_replace_verify_end_to_end(self):
        result = self.install()
        self.assertEqual(result["status"], "CONTROL_REPAIRED_STILL_HELD")
        self.c.checked(r.BASE_SHA)
        self.assertEqual(
            (self.root / "tools/remote_control.py").read_bytes(), self.source
        )
        for name, digest in self.release["files"].items():
            self.assertEqual(
                self.c.sha(
                    (self.root / "repairs/job724808/original" / name).read_bytes()
                ),
                digest,
            )
            if name != "remote_control.py":
                self.assertEqual(
                    self.c.sha((self.root / "tools" / name).read_bytes()), digest
                )
        self.assertFalse(
            any(
                a == r.UPDATE or "release" in a or a[0].endswith("sbatch")
                for a in self.calls
            )
        )

    def test_install_cannot_run_twice(self):
        self.install()
        with self.assertRaises(RuntimeError):
            self.install()

    def test_changed_scientific_candidate_blocks_install(self):
        (self.root / "tools/eager_compare.py").write_text("changed")
        with self.assertRaisesRegex(RuntimeError, "drift"):
            self.install()
        self.assertFalse((self.root / "repairs").exists())

    def test_running_job_blocks_install(self):
        self.raw = self.raw.replace("JobState=PENDING", "JobState=RUNNING")
        with self.assertRaises(RuntimeError):
            self.install()

    def test_saved_slurm_batch_body_changed_blocks_install(self):
        self.batch += "# changed\n"
        with self.assertRaisesRegex(RuntimeError, "batch script differs"):
            self.install()

    def test_replace_failure_leaves_archive_and_fail_closed(self):
        with patch.object(r.os, "replace", side_effect=OSError("injected failure")):
            with self.assertRaises(OSError):
                self.install()
        original = self.root / "repairs/job724808/original/remote_control.py"
        self.assertEqual(self.c.sha(original.read_bytes()), r.OLD_SHA)
        self.assertEqual(
            self.c.sha((self.root / "tools/remote_control.py").read_bytes()), r.OLD_SHA
        )
        with self.assertRaisesRegex(RuntimeError, "Package changed"):
            self.c.checked(r.BASE_SHA)

    def test_archive_damage_blocks_later_use(self):
        self.install()
        (self.root / "repairs/job724808/original/eager_compare.py").write_text(
            "damaged"
        )
        with self.assertRaisesRegex(RuntimeError, "archive differs"):
            self.c.checked(r.BASE_SHA)

    def test_amendment_cannot_modify_other_files_or_authorize_release(self):
        self.install()
        path = self.root / "state/CONTROL_REPAIR.json"
        original = json.loads(path.read_text())
        for changes in (
            {"changed_files": ["eager_compare.py"]},
            {"release_authorized": True},
            {"job_id": "123"},
        ):
            with self.subTest(changes=changes):
                path.write_bytes(self.c.wire(dict(original, **changes)))
                with self.assertRaises(RuntimeError):
                    self.c.checked(r.BASE_SHA)
        path.write_bytes(self.c.wire(original))
        self.c.checked(r.BASE_SHA)

    def test_original_submit_journal_change_rejected(self):
        self.install()
        (self.root / "state/SBATCH_RESPONSE.json").write_text("{}")
        with self.assertRaisesRegex(RuntimeError, "journal changed"):
            self.c.checked(r.BASE_SHA)

    def test_runtime_amendment_rejects_other_job(self):
        self.install()
        with patch.dict(os.environ, {"SLURM_JOB_ID": "123"}):
            with self.assertRaisesRegex(RuntimeError, "only for Job724808"):
                self.c.checked(r.BASE_SHA)

    def test_exact_update_once_does_not_release(self):
        self.install()
        result = r.update_gpu(self.c, self.spec, self.release, self.execute)
        self.assertEqual(result["status"], "A100_CORRECTED_STILL_HELD")
        self.assertEqual(sum(a == r.UPDATE for a in self.calls), 1)
        self.assertFalse(
            any("release" in a or a[0].endswith("sbatch") for a in self.calls)
        )
        with self.assertRaises(RuntimeError):
            r.update_gpu(self.c, self.spec, self.release, self.execute)
        self.assertEqual(sum(a == r.UPDATE for a in self.calls), 1)

    def test_uncertain_rpc_keeps_intent_and_cannot_retry(self):
        self.install()

        def timeout(argv):
            if argv == r.UPDATE:
                self.calls.append(argv)
                return {"argv": argv, "rc": 124, "stdout": "", "stderr": "timeout"}
            return self.execute(argv)

        with self.assertRaises(RuntimeError):
            r.update_gpu(self.c, self.spec, self.release, timeout)
        with self.assertRaises(FileExistsError):
            r.update_gpu(self.c, self.spec, self.release, self.execute)
        self.assertEqual(sum(a == r.UPDATE for a in self.calls), 1)

    def test_old_release_entry_disabled_after_repair(self):
        self.install()
        with self.assertRaisesRegex(RuntimeError, "does not authorize release"):
            self.c.release_job(self.release, r.BASE_SHA, self.execute)


if __name__ == "__main__":
    unittest.main()

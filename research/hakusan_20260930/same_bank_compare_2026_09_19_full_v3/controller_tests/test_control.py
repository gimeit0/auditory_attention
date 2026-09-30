"""Synthetic scheduler only. Never SSH/sbatch or read production inputs."""

import base64
import copy
import importlib.util
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("control_test", HERE / "control.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "remote"
        self.addCleanup(patch.stopall)
        patch.object(M, "ROOT", self.root).start()
        self.files = {n: (M.S.PROJECT / n).read_bytes() for n in M.FILES}
        self.r = dict(
            protocol=M.PROTOCOL,
            status="EXPLICITLY_APPROVED",
            limits=M.S.LIMITS,
            stages=list(M.S.STAGES),
            nonce="a" * 32,
            baseline_receipts={k: v[1] for k, v in M.S.BASELINES.items()},
            files={n: M.digest(b) for n, b in self.files.items()},
            authorization=dict(
                single_held_submission=True,
                conditional_release=True,
                resource_repair=False,
                automatic_retry=False,
                user_approval_record="SYNTHETIC TEST ONLY",
            ),
        )
        self.raw = M.S.wire(self.r)
        self.sha = M.digest(self.raw)
        M.publish(
            self.raw,
            self.sha,
            {n: base64.b64encode(b).decode() for n, b in self.files.items()},
        )
        patch.object(M, "inputs").start()
        self.calls = []

    def execute(self, argv):
        self.calls.append(argv)
        out = ""
        if argv[0].endswith("sbatch") and "--hold" in argv:
            out = "12345\n"
        if argv[1:4] == ["-o", "show", "job"]:
            out = self.job()
        if argv[1:3] == ["write", "batch_script"]:
            out = self.files[M.PREFIX + "run_layouts.sbatch"].decode()
        if argv[0].endswith("sacct"):
            out = "12345|PENDING|0:0|00:00:00|Unknown|Unknown\n"
        return dict(argv=argv, rc=0, stdout=out, stderr="")

    def job(self):
        fields = dict(
            JobId="12345",
            JobName="audattn_eager_p08full",
            Partition="GPU-1A",
            Account="student",
            NumCPUs="8",
            NumTasks="1",
            **{"CPUs/Task": "8"},
            TimeLimit="03:00:00",
            Requeue="0",
            Restarts="0",
            WorkDir=str(self.root),
            Command=str(self.root / "package" / M.PREFIX / "run_layouts.sbatch"),
            Comment="p08full-" + self.r["nonce"],
            JobState="PENDING",
            Reason="JobHeldUser",
            Priority="0",
            RunTime="00:00:00",
            UserId="s2510040(123)",
            NumNodes="1",
            NodeList="(null)",
            ReqTRES="cpu=8,mem=64G,node=1,billing=8,gres/gpu:nvidia_a100=1",
        )
        return " ".join(f"{k}={v}" for k, v in fields.items())

    def submitted(self):
        M.test_only(self.sha, self.execute)
        return M.submit(self.sha, self.execute)

    def test_publish_exact_exclusive(self):
        self.assertEqual(M.checked(self.sha), self.r)
        with self.assertRaises(ValueError):
            M.publish(
                self.raw,
                self.sha,
                {n: base64.b64encode(b).decode() for n, b in self.files.items()},
            )

    def test_no_implicit_approval_budget_or_repair(self):
        for key, value in (("status", "CANDIDATE"), ("stages", ["full10k"])):
            r = copy.deepcopy(self.r)
            r[key] = value
            raw = M.S.wire(r)
            with self.assertRaises(ValueError):
                M.decode(raw, M.digest(raw))
        r = copy.deepcopy(self.r)
        r["authorization"]["resource_repair"] = True
        raw = M.S.wire(r)
        with self.assertRaises(ValueError):
            M.decode(raw, M.digest(raw))

    def test_mutated_package_rejected(self):
        (self.root / "package" / M.PREFIX / "control.py").write_text("changed")
        with self.assertRaises(ValueError):
            M.submit(self.sha, self.execute)
        self.assertFalse(self.calls)

    def test_no_test_only_no_submit(self):
        with self.assertRaises(FileNotFoundError):
            M.submit(self.sha, self.execute)
        self.assertFalse(self.calls)

    def test_held_submit_exactly_once(self):
        self.assertEqual(self.submitted()["job_id"], "12345")
        with self.assertRaises(FileExistsError):
            M.submit(self.sha, self.execute)
        self.assertEqual(sum("--hold" in a for a in self.calls), 1)
        self.assertFalse((self.root / "state/CONTRACT.json").exists())

    def test_lost_submit_response_blocks_retry(self):
        M.test_only(self.sha, self.execute)

        def lost(argv):
            if "--hold" in argv:
                self.calls.append(argv)
                raise TimeoutError("uncertain")
            return self.execute(argv)

        with self.assertRaises(TimeoutError):
            M.submit(self.sha, lost)
        with self.assertRaises(FileExistsError):
            M.submit(self.sha, self.execute)
        self.assertEqual(sum("--hold" in a for a in self.calls), 1)

    def test_invalid_submit_response_blocks_retry(self):
        M.test_only(self.sha, self.execute)

        def bad(argv):
            r = self.execute(argv)
            if "--hold" in argv:
                r["stdout"] = "unknown"
            return r

        with self.assertRaisesRegex(ValueError, "SUBMISSION_UNKNOWN"):
            M.submit(self.sha, bad)
        with self.assertRaises(FileExistsError):
            M.submit(self.sha, self.execute)

    def test_nonempty_queue_blocks_submission(self):
        M.test_only(self.sha, self.execute)

        def busy(argv):
            r = self.execute(argv)
            if argv[0].endswith("squeue"):
                r["stdout"] = "999|RUNNING|other|"
            return r

        with self.assertRaises(ValueError):
            M.submit(self.sha, busy)
        self.assertFalse((self.root / "state/SUBMIT_INTENT.json").exists())

    def test_release_contract_binds_actual_job(self):
        self.submitted()
        M.release(self.sha, self.execute)
        path, sha = M.launch_contract(self.sha, "12345")
        self.assertEqual(M.S.read(path), M.contract(self.r, "12345"))
        self.assertEqual(M.S.sha(path), sha)
        with self.assertRaises(ValueError):
            M.launch_contract(self.sha, "999")
        with self.assertRaises(ValueError):
            M.release(self.sha, self.execute)
        self.assertEqual(sum(a[1:2] == ["release"] for a in self.calls), 1)

    def test_gpu_rewrite_stays_held(self):
        self.submitted()
        with patch.object(
            self, "job", return_value=self.job().replace("nvidia_a100", "h100-20c")
        ):
            with self.assertRaises(RuntimeError):
                M.release(self.sha, self.execute)
        self.assertFalse(any(a[1] in ("release", "update") for a in self.calls))
        self.assertFalse((self.root / "state/CONTRACT.json").exists())

    def test_spool_mismatch_no_release(self):
        self.submitted()

        def wrong(argv):
            r = self.execute(argv)
            if argv[1:3] == ["write", "batch_script"]:
                r["stdout"] = "wrong script"
            return r

        with self.assertRaises(ValueError):
            M.release(self.sha, wrong)
        self.assertFalse(any(a[1] == "release" for a in self.calls))

    def test_lost_release_no_retry(self):
        self.submitted()

        def lost(argv):
            if argv[1] == "release":
                self.calls.append(argv)
                raise TimeoutError("uncertain")
            return self.execute(argv)

        with self.assertRaises(TimeoutError):
            M.release(self.sha, lost)
        with self.assertRaises(ValueError):
            M.release(self.sha, self.execute)
        self.assertEqual(sum(a[1] == "release" for a in self.calls), 1)

    def attempt(self, failed=False):
        self.submitted()
        M.release(self.sha, self.execute)
        parent = self.root / "attempts/slurm-12345"
        parent.mkdir()
        M.S.write(parent / "synthetic.json", {"fake": True})
        marker = parent / ("FAILED.json" if failed else "COMPLETE.json")
        M.S.write(
            marker,
            dict(
                protocol=M.S.PROTOCOL,
                status="EXECUTION_FAILED"
                if failed
                else "EXECUTION_COMPLETE_NOT_QUALIFIED",
                provenance={
                    "job_id": "12345",
                    "contract_sha256": M.S.sha(self.root / "state/CONTRACT.json"),
                },
                full_run_authorized=False,
                inventory=M.S.inventory(parent),
            ),
        )
        return M.S.sha(marker)

    def test_export_import_and_readonly_source(self):
        terminal = self.attempt()
        before = M.S.inventory(self.root)
        payload = M.export_attempt(self.sha, terminal)
        result = M.import_attempt(
            payload, self.sha, "12345", terminal, self.root.parent / "collected"
        )
        self.assertEqual(result["status"], "COLLECTED_NOT_QUALIFIED")
        self.assertEqual(before, M.S.inventory(self.root))

    def test_failed_collection_stays_failed(self):
        terminal = self.attempt(failed=True)
        p = M.export_attempt(self.sha, terminal)
        result = M.import_attempt(
            p, self.sha, "12345", terminal, self.root.parent / "failed-copy"
        )
        self.assertEqual(result["terminal_status"], "EXECUTION_FAILED")

    def test_transfer_identity_hash_and_traversal_rejected(self):
        terminal = self.attempt()
        p = M.export_attempt(self.sha, terminal)
        for key, value in (("job_id", "999"), ("terminal_sha256", "a" * 64)):
            bad = copy.deepcopy(p)
            bad[key] = value
            with self.assertRaises(ValueError):
                M.import_attempt(
                    bad, self.sha, "12345", terminal, self.root.parent / "bad"
                )
        bad = copy.deepcopy(p)
        bad["inventory"]["directories"] = ["../escape"]
        with self.assertRaises(ValueError):
            M.import_attempt(bad, self.sha, "12345", terminal, self.root.parent / "bad")
        p["files"]["synthetic.json"]["base64"] = base64.b64encode(b"tampered").decode()
        with self.assertRaises(ValueError):
            M.import_attempt(p, self.sha, "12345", terminal, self.root.parent / "bad")


if __name__ == "__main__":
    unittest.main()

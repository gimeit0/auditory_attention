"""No network: replay the real held record and test mutation/release barriers."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import remote_ops as ops
import repair_713897 as repair

RECORD = HERE.parents[3] / "docs/superpowers/evidence/gpu-control-20260914-v3/status-20260914T023611Z-jod13kgb/receipt.json"
RECEIPT = json.loads(RECORD.read_text())
import hashlib
assert hashlib.sha256((RECORD.parent / "output.log").read_bytes()).hexdigest() == RECEIPT["output"]["sha256"] == "575f1a6862ea540b4681bbb59c07a910ef49cf142dfcade84ffb9a3bb8471f1d"
assert RECEIPT["remote"]["ok"]
RAW = RECEIPT["remote"]["result"]["journals"]["HELD_ALLOCATION.json"]["stdout"]


def corrected(text=RAW):
    return text.replace("gres/gpu:h100-20c=1", "gres/gpu=1,gres/gpu:nvidia_a100=1").replace("gres/gpu:1", repair.GPU) + " TresPerJob=" + repair.GPU


def output(value, rc=0):
    return {"stdout": value, "stderr": "", "returncode": rc, "timed_out": False, "truncated": False}


class ValidationTests(unittest.TestCase):
    def test_real_held_record_is_known_before_not_after(self):
        repair.validate_job(RAW, ops.REMOTE, corrected=False)
        with self.assertRaises(RuntimeError):
            repair.validate_job(RAW, ops.REMOTE, corrected=True)

    def test_unreviewed_before_per_job_field_rejected(self):
        with self.assertRaises(RuntimeError):
            repair.validate_job(RAW + " TresPerJob=gres/gpu:1", ops.REMOTE, corrected=False)

    def test_explicit_a100_required(self):
        repair.validate_job(corrected(), ops.REMOTE, corrected=True)
        repair.validate_job(corrected().replace("gres/gpu=1,", ""), ops.REMOTE, corrected=True)
        for old, new in (("nvidia_a100", "h100-20c"), ("gres/gpu=1", "gres/gpu=2"),
                         ("nvidia_a100=1", "nvidia_a100=2"), ("nvidia_a100:1", "nvidia_a100:2")):
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                repair.validate_job(corrected().replace(old, new), ops.REMOTE, corrected=True)

    def test_non_gpu_and_identity_changes_rejected(self):
        for old, new in (("JobId=713897", "JobId=713898"), ("NumCPUs=8", "NumCPUs=16"),
                         ("mem=64G", "mem=128G"), ("02:00:00", "04:00:00"),
                         ("Priority=0", "Priority=1"), ("JobHeldUser", "Resources"),
                         ("RunTime=00:00:00", "RunTime=00:00:01"), ("Requeue=0", "Requeue=1"),
                         ("AllocTRES=(null)", "AllocTRES=cpu=8"),
                         ("audattn-b2-" + repair.NONCE, "other-comment")):
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                repair.validate_job(corrected().replace(old, new), ops.REMOTE, corrected=True)

    def test_duplicate_or_extra_resources_rejected(self):
        for extra in (" JobId=713897", " TresPerSocket=gres/gpu:1"):
            with self.assertRaises(RuntimeError):
                repair.validate_job(corrected() + extra, ops.REMOTE, corrected=True)
        for extra in (",gres/gpu=1", ",gres/nic=1", ",gres/gpu:h100-20c=1"):
            with self.assertRaises(RuntimeError):
                repair.validate_job(corrected().replace("billing=8", "billing=8" + extra), ops.REMOTE, corrected=True)

    def test_accounting_must_agree(self):
        req = repair.validate_job(corrected(), ops.REMOTE, corrected=True)
        tres = ",".join(k + "=" + v for k, v in req.items())
        text = "713897|PENDING|" + tres + "||00:00:00\n"
        repair.validate_accounting(text, req)
        for bad in (text.replace("nvidia_a100", "h100-20c"), text * 2, text.replace("PENDING", "RUNNING")):
            with self.assertRaises(RuntimeError):
                repair.validate_accounting(bad, req)

    def test_fixed_update_is_only_one_job_two_gpu_fields(self):
        self.assertEqual(repair.UPDATE, ["/usr/bin/scontrol", "update", "JobId=713897",
                                         "TresPerJob=gres/gpu:nvidia_a100:1", "TresPerNode=gres/gpu:nvidia_a100:1"])
        self.assertEqual(repair.RELEASE, ["/usr/bin/scontrol", "release", "713897"])


class MutationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        os.chmod(self.root, 0o700)
        self.raw = RAW.replace(str(ops.REMOTE), str(self.root))
        self.current = self.raw
        self.calls = []
        self.bad_update = False
        self.bad_post = False
        self.fake = types.SimpleNamespace(REMOTE=self.root, read=ops.read, sha=ops.sha,
                    wire=ops.wire, success=ops.success, command=self.invoke,
                    Operations=lambda: ops.Operations(root=self.root))
        self.context = patch.object(repair, "checked_context", return_value={"original": "unchanged"})
        self.context.start()
        self.addCleanup(self.context.stop)
        self.spec = {"request_id": "a" * 32, "repair_source_sha256": "b" * 64}

    def invoke(self, command):
        self.calls.append(command)
        if command == repair.UPDATE:
            self.assertTrue((self.root / "GPU_TYPE_UPDATE_INTENT.json").is_file())
            if self.bad_update:
                return output("", 1)
            self.current = corrected(self.raw)
            if self.bad_post:
                self.current = self.current.replace("nvidia_a100=1", "h100-20c=1")
            return output("")
        if command == repair.RELEASE:
            self.assertTrue((self.root / "RELEASE_INTENT.json").is_file())
            self.current = self.current.replace("Priority=0", "Priority=200").replace("JobHeldUser", "Priority")
            return output("")
        if command == repair.SCONTROL:
            return output(self.current)
        if command == repair.ACCOUNTING:
            return output("713897|PENDING|" + repair.fields(self.current)["ReqTRES"] + "||00:00:00\n")
        if command == ["/usr/bin/scontrol", "--version"]:
            return output("slurm 25.05.5\n")
        if command[0] == "/usr/bin/sinfo":
            return output("\n".join("spcc-a100g%02d|gpu:nvidia_a100:2(S:0-1)|mix" % i for i in range(1, 11)))
        if command[0] == "/usr/bin/squeue":
            return output("713897|PENDING|audattn_b2_coldpair\n")
        self.fail("unexpected command: " + repr(command))

    def test_update_never_releases(self):
        result = repair.mutate("update", self.fake, self.spec)
        self.assertEqual(result["status"], "GPU_TYPE_CORRECTED_STILL_HELD")
        self.assertEqual(self.calls.count(repair.UPDATE), 1)
        self.assertNotIn(repair.RELEASE, self.calls)

    def test_failed_rpc_is_recorded_not_retried(self):
        self.bad_update = True
        with self.assertRaises(RuntimeError):
            repair.mutate("update", self.fake, self.spec)
        with self.assertRaises(FileExistsError):
            repair.mutate("update", self.fake, self.spec)
        self.assertEqual(self.calls.count(repair.UPDATE), 1)
        self.assertNotIn(repair.RELEASE, self.calls)
        self.assertTrue((self.root / "GPU_TYPE_UPDATE_READBACK.json").is_file())

    def test_inconsistent_postcheck_never_releases(self):
        self.bad_post = True
        with self.assertRaises(RuntimeError):
            repair.mutate("update", self.fake, self.spec)
        with self.assertRaises(RuntimeError):
            repair.mutate("release", self.fake, self.spec)
        self.assertNotIn(repair.RELEASE, self.calls)

    def test_good_same_job_releases_once(self):
        repair.mutate("update", self.fake, self.spec)
        result = repair.mutate("release", self.fake, self.spec)
        self.assertEqual(result["status"], "SAME_JOB_RELEASED")
        with self.assertRaises(RuntimeError):
            repair.mutate("release", self.fake, self.spec)
        self.assertEqual(self.calls.count(repair.RELEASE), 1)
        self.assertEqual(self.calls.count(repair.UPDATE), 1)

    def test_release_without_successful_update_rejected(self):
        self.current = corrected(self.raw)
        with self.assertRaises(FileNotFoundError):
            repair.mutate("release", self.fake, self.spec)
        self.assertNotIn(repair.RELEASE, self.calls)

    def test_unverified_update_cannot_release(self):
        self.current = corrected(self.raw)
        ops.Operations(root=self.root).save("GPU_TYPE_UPDATE_RESPONSE.json", output(""))
        ops.Operations(root=self.root).save("GPU_TYPE_UPDATE_INTENT.json", {
            "command": repair.UPDATE, "job_id": repair.JOB, "pair_nonce": repair.NONCE,
            "repair_source_sha256": self.spec["repair_source_sha256"]})
        with self.assertRaises(FileNotFoundError):
            repair.mutate("release", self.fake, self.spec)
        self.assertNotIn(repair.RELEASE, self.calls)

    def test_recovery_source_change_cannot_release(self):
        repair.mutate("update", self.fake, self.spec)
        with self.assertRaises(RuntimeError):
            repair.mutate("release", self.fake, {**self.spec, "repair_source_sha256": "c" * 64})
        self.assertNotIn(repair.RELEASE, self.calls)

    def test_context_failure_precedes_all_commands(self):
        with patch.object(repair, "checked_context", side_effect=RuntimeError("changed sources")):
            with self.assertRaises(RuntimeError):
                repair.mutate("update", self.fake, self.spec)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

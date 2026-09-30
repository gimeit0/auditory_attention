"""Regression for real Job724808 output; proposed fixes execute in memory only.

Does not edit published sources, contact Slurm, release or submit any job.
"""

import hashlib
import json
from pathlib import Path
import types
import unittest

PROJECT = Path(__file__).resolve().parents[2]
EVIDENCE = PROJECT / "docs/superpowers/evidence/eager-small-production-20260917"
SOURCE_SHA = "fc8617224ba852e3d57fc68ee9ac07b64e38a46289a1fd00018cbbfc2f66d037"
STATUS_SHA = "afc6a2dac5f33d9b4a4c3e2dca99277c4a9883ed230db5a9424b34aa16a6917a"
REPLACEMENTS = (
    ("[A-Za-z][A-Za-z0-9_/]*", "[A-Za-z][A-Za-z0-9_/:]*"),
    ('f.get("NumNodes") == "1"', 'f.get("NumNodes") in ("1", "1-1")'),
    ('not f.get("AllocTRES")', 'f.get("AllocTRES") in (None, "", "(null)")'),
)


def load_corrected_for_test():
    source = (EVIDENCE / "package/remote_control.py").read_bytes()
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise RuntimeError("Frozen controller changed")
    text = source.decode()
    for old, new in REPLACEMENTS:
        if text.count(old) != 1:
            raise RuntimeError("Correction no longer applies exactly once")
        text = text.replace(old, new)
    module = types.ModuleType("in_memory_scheduler_compatibility_test")
    exec(compile(text, "<local-compatibility-proposal-only>", "exec"), vars(module))
    return module


class NativeSchedulerTests(unittest.TestCase):
    def setUp(self):
        raw = (EVIDENCE / "status-yyum1i2c/RESULT.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), STATUS_SHA)
        self.saved = json.loads(raw)["result"]["result"]
        self.raw = self.saved["job"]["stdout"]
        self.release = json.loads((EVIDENCE / "package/RELEASE.json").read_text())
        self.c = load_corrected_for_test()

    def corrected_gpu_fixture(self):
        # Counterfactual fixture only, never save as actual remote evidence.
        return self.raw.replace(
            "gres/gpu:h100-20c=1", "gres/gpu:nvidia_a100=1"
        ).replace("TresPerNode=gres/gpu:1", "TresPerNode=gres/gpu:nvidia_a100:1")

    def test_real_slurm_colon_fields_are_separate(self):
        f = self.c.fields(self.raw)
        self.assertEqual(f["Partition"], "GPU-1A")
        self.assertEqual(f["AllocNode:Sid"], "hakusan1:3576707")
        self.assertEqual(f["CPUs/Task"], "8")
        self.assertEqual(f["ReqB:S:C:T"], "0:0:*:1")

    def test_actual_job_still_rejected_for_h100(self):
        with self.assertRaisesRegex(RuntimeError, "typed A100"):
            self.c.validate_job(self.raw, self.release, "724808", held=True)

    def test_exact_one_node_range_and_null_allocation_accepted(self):
        self.c.validate_job(
            self.corrected_gpu_fixture(), self.release, "724808", held=True
        )

    def test_two_node_range_rejected(self):
        raw = self.corrected_gpu_fixture().replace("NumNodes=1-1", "NumNodes=1-2")
        with self.assertRaisesRegex(RuntimeError, "node count"):
            self.c.validate_job(raw, self.release, "724808", held=True)

    def test_held_allocation_rejected(self):
        raw = self.corrected_gpu_fixture().replace(
            "AllocTRES=(null)", "AllocTRES=cpu=8"
        )
        with self.assertRaisesRegex(RuntimeError, "unexpectedly allocated"):
            self.c.validate_job(raw, self.release, "724808", held=True)

    def test_bad_gpu_not_excused_by_parser_correction(self):
        for old, new in (
            ("gres/gpu:nvidia_a100=1", "gres/gpu:nvidia_a100=2"),
            ("TresPerNode=gres/gpu:nvidia_a100:1", "TresPerNode=gres/gpu:1"),
        ):
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                self.c.validate_job(
                    self.corrected_gpu_fixture().replace(old, new),
                    self.release,
                    "724808",
                    held=True,
                )

    def test_running_allocation_remains_required(self):
        raw = (
            self.corrected_gpu_fixture()
            .replace("JobState=PENDING", "JobState=RUNNING")
            .replace("NumNodes=1-1", "NumNodes=1")
        )
        with self.assertRaises(RuntimeError):
            self.c.validate_job(raw, self.release, "724808", held=False)
        raw = raw.replace(
            "AllocTRES=(null)", "AllocTRES=cpu=8,mem=64G,node=1,gres/gpu:nvidia_a100=1"
        )
        self.c.validate_job(raw, self.release, "724808", held=False)

    def test_native_accounting_confirms_no_execution_and_h100_request(self):
        line = self.saved["accounting"]["stdout"].strip().split("|")
        self.assertEqual(line[:4], ["724808", "PENDING", "0:0", "00:00:00"])
        self.assertIn("gres/gpu:h100-20c=1", line[6])
        self.assertEqual(line[7], "")


if __name__ == "__main__":
    unittest.main()

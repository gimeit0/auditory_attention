"""Static evidence-binding tests; not a real-model forward or loader test."""

import hashlib
from pathlib import Path
import tempfile
import unittest

from check_formal_plan import build_report, pinned


class StaticPlanTests(unittest.TestCase):
    def test_first_layer_shape_and_bytes(self):
        report = build_report()
        stage = report["post_hook_stages"][3]
        self.assertEqual(stage["module"], "model_dict.conv_block_0")
        self.assertEqual(stage["per_trial_shape"], [32, 39, 19967])
        self.assertEqual(stage["float32_bytes"], 99675264)

    def test_complete_stage_order_and_budget(self):
        report = build_report()
        self.assertEqual(report["stage_count"], 42)
        self.assertEqual(report["float32_capture_bytes_per_cell"], 1495537152)
        self.assertTrue(report["fits_2GiB_per_cell_capture_store"])
        self.assertTrue(report["fits_128MiB_per_tensor_limit"])
        self.assertEqual(report["post_hook_stages"][-1]["per_trial_shape"], [800])
        self.assertEqual(report["post_hook_stages"][-5]["per_trial_shape"], [512, 5, 12])
        self.assertFalse(report["ready_for_gpu"])
        self.assertFalse(report["actual_live_module_binding_verified"])

    def test_bad_pin_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "evidence"
            p.write_bytes(b"actual")
            with self.assertRaisesRegex(RuntimeError, "changed pinned"):
                pinned(p, hashlib.sha256(b"other").hexdigest())

    def test_symlink_pin_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "evidence"
            p.write_bytes(b"actual")
            alias = Path(temp) / "alias"
            alias.symlink_to(p)
            with self.assertRaisesRegex(RuntimeError, "nonregular"):
                pinned(alias, hashlib.sha256(b"actual").hexdigest())


if __name__ == "__main__":
    unittest.main(verbosity=2)

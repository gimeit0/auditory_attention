"""Offline checker regression tests; no network or GPU."""

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np


SOURCE = Path(__file__).with_name("2026-09-11-job685198-offline-analysis.py")
SPEC = importlib.util.spec_from_file_location("offline_analysis", SOURCE)
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


class OfflineChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "sub").mkdir(mode=0o700)
        data = b"bound artifact\n"
        self.path = self.root / "sub" / "artifact"
        self.path.write_bytes(data)
        self.path.chmod(0o600)
        self.inventory = {
            "schema_version": 1,
            "directories": [{"relative_path": "sub", "mode": 0o700}],
            "files": [{"relative_path": "sub/artifact", "mode": 0o600,
                       "type": "file", "size": len(data),
                       "sha256": hashlib.sha256(data).hexdigest()}],
        }
        self.refresh()

    def refresh(self):
        self.inventory["sha256"] = analysis.wire_sha(
            {k: v for k, v in self.inventory.items() if k != "sha256"})

    def verify(self):
        return analysis.verify_inventory(self.root, self.inventory)

    def test_valid_inventory(self):
        self.assertEqual(self.verify()["files"], 1)

    def test_changed_bytes_same_size(self):
        self.path.write_bytes(b"BOUND ARTIFACT\n")
        with self.assertRaisesRegex(ValueError, "SHA differs"):
            self.verify()

    def test_changed_size(self):
        self.path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "size differs"):
            self.verify()

    def test_missing_file(self):
        self.path.unlink()
        with self.assertRaisesRegex(ValueError, "missing artifacts"):
            self.verify()

    def test_extra_file(self):
        (self.root / "extra").write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "unexpected artifact"):
            self.verify()

    def test_file_symlink(self):
        self.path.unlink()
        self.path.symlink_to("absent")
        with self.assertRaisesRegex(ValueError, "wrong type/link"):
            self.verify()

    def test_permissions(self):
        self.path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "permissions differ"):
            self.verify()

    def test_duplicate_path(self):
        self.inventory["files"].append(dict(self.inventory["files"][0]))
        self.refresh()
        with self.assertRaisesRegex(ValueError, "duplicate inventory path"):
            self.verify()

    def test_inventory_digest(self):
        self.inventory["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "inventory digest differs"):
            self.verify()

    def test_unsafe_relative_paths(self):
        for path in ("", "/tmp/a", "../a", "a/../b", ".", "a//b", "a/./b"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                analysis.safe_relative(path)

    def test_constant_shift_leaves_nll_unchanged(self):
        logits = np.array([[1000., 1001., 999.], [-1000., -1001., -1002.]])
        targets = np.array([1, 0])
        np.testing.assert_allclose(analysis.nll64(logits, targets),
                                   analysis.nll64(logits + 128., targets), atol=1e-12, rtol=0)

    def test_uniform_logits(self):
        np.testing.assert_allclose(analysis.nll64(np.zeros((2, 800)), np.array([0, 799])),
                                   np.log(800), atol=1e-12, rtol=0)

    def test_invalid_logits(self):
        for logits in (np.zeros(2), np.zeros((0, 3)), np.zeros((2, 1)),
                       np.array([[np.nan, 0]]), np.array([[np.inf, 0]])):
            with self.subTest(shape=logits.shape), self.assertRaises(ValueError):
                analysis.logsumexp64(logits)

    def test_invalid_targets(self):
        for targets in (np.array([0.]), np.array([2]), np.array([-1]), np.array([0, 1])):
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                analysis.nll64(np.zeros((1, 2)), targets)


if __name__ == "__main__":
    unittest.main(verbosity=2)

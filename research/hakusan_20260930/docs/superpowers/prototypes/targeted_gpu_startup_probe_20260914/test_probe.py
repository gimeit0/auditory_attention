"""Synthetic verifier rejection checks; never remote evidence or execution."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_probe
import probe_parent

class ProbeTests(unittest.TestCase):
    def setUp(self):
        data = run_probe.ROOT / "docs/superpowers/evidence/startup-probe-local-20260913T172959Z-xjqc2wya/receipt.json"
        self.value = json.loads(data.read_bytes())["result"]
        # Fixture upgrade for the newly required field; not a re-verification
        # claim about the historical result's absent package field.
        for case in self.value["cases"]:
            case["result"]["package_sha256"] = run_probe.PACKAGE_SHA

    def test_complete_local_shape(self):
        run_probe.verify(self.value, True)

    def test_local_cannot_claim_native(self):
        with self.assertRaises(RuntimeError):
            run_probe.verify(self.value, False)

    def test_duplicate_or_missing_case(self):
        for cases in (self.value["cases"][:2], [self.value["cases"][0]] * 3):
            value = {**self.value, "cases": cases}
            with self.assertRaises(RuntimeError):
                run_probe.verify(value, True)

    def test_role_relabel_rejected(self):
        self.value["cases"][1]["result"]["role"] = "observed"
        with self.assertRaisesRegex(RuntimeError, "identity"):
            run_probe.verify(self.value, True)

    def test_nonzero_or_error_rejected(self):
        for change in ({"returncode": 2}, {"error": {"message": "timeout"}}):
            value = copy.deepcopy(self.value)
            value["cases"][0]["process"].update(change)
            with self.assertRaises(RuntimeError):
                run_probe.verify(value, True)

    def test_changed_log_or_pid_rejected(self):
        for kind in ("log", "pid"):
            value = copy.deepcopy(self.value)
            if kind == "log":
                value["cases"][1]["log_base64"] = "YQ=="
            else:
                value["cases"][1]["result"]["pid"] += 1
            with self.assertRaises(RuntimeError):
                run_probe.verify(value, True)

    def test_cuda_model_forward_job_claim_rejected(self):
        for field, bad in (("cuda_initialized", True), ("production_model_loaded", True),
                           ("forward_calls", 1), ("jobs_submitted", 1), ("allocation_claimed", True)):
            value = copy.deepcopy(self.value)
            value["cases"][1]["result"][field] = bad
            with self.assertRaises(RuntimeError):
                run_probe.verify(value, True)

    def test_startup_gate_missing_rejected(self):
        for field in ("torch_absent_before_scratch", "caches_initially_empty", "anchors_closed", "original_loader_binding_checked"):
            value = copy.deepcopy(self.value)
            value["cases"][2]["result"][field] = False
            with self.assertRaises(RuntimeError):
                run_probe.verify(value, True)

    def test_package_scope_and_cleanup_rejected(self):
        for key, bad in (("temporary_directory_removed", False), ("sources_unchanged", False),
                         ("package_sha256", "0" * 64), ("error", {"message": "failure"})):
            with self.assertRaises(RuntimeError):
                run_probe.verify({**self.value, key: bad}, True)

    def test_bad_child_package_rejected(self):
        self.value["cases"][2]["result"]["package_sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "identity"):
            run_probe.verify(self.value, True)

    def test_payload_rejects_missing_extra_and_traversal(self):
        value = run_probe.package(True)
        for change in ("missing", "extra", "traversal"):
            spec = copy.deepcopy(value)
            name = next(iter(spec["files"]))
            if change == "missing":
                spec["files"].pop(name)
            elif change == "extra":
                spec["files"]["docs/extra.py"] = spec["files"][name]
            else:
                spec["files"]["docs/../../escape.py"] = spec["files"].pop(name)
            with tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(RuntimeError):
                    probe_parent.install(spec, Path(temp) / "package")
                self.assertFalse((Path(temp) / "escape.py").exists())

    def test_corrupt_payload_rejected(self):
        value = run_probe.package(True)
        value["files"][next(iter(value["files"]))]["base64"] = "YQ=="
        with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(RuntimeError, "bytes"):
            probe_parent.install(value, Path(temp) / "package")


if __name__ == "__main__":
    unittest.main(verbosity=2)

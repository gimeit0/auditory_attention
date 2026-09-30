"""Lifecycle checks for the experimental policy, not production acceptance."""
import hashlib
import importlib.util
import pathlib
import sys
import tempfile
import types
import unittest

spec = importlib.util.spec_from_file_location(
    "policy_lifecycle_fixture", pathlib.Path(__file__).with_name("candidate_policy.py")
)
policy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = policy
spec.loader.exec_module(policy)
diag = policy.diag


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name).resolve()
        files = {
            "selftrain/__init__.py": b"",
            "selftrain/data/__init__.py": b"",
            "selftrain/data/diotic_attention.py": b"class WaveformCache: pass\n",
            "selftrain/scripts/__init__.py": b"",
            "selftrain/scripts/eval_full_pilot.py": (
                b"def _raw_scene_batch(): return 'raw'\n"
                b"def _correct_cue_batch(): return 'cue'\n"
            ),
        }
        self.records = {}
        for relative, payload in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            self.records[relative] = {
                "path": relative, "type": "file", "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }

    def test_context_restores_registry_and_revokes_callback(self):
        before = {n: m for n, m in sys.modules.items() if n.partition('.')[0] == 'selftrain'}
        with diag.frozen_scene_context(self.root, self.records) as api:
            self.assertEqual(api.raw_scene_batch(), "raw")
        after = {n: m for n, m in sys.modules.items() if n.partition('.')[0] == 'selftrain'}
        self.assertEqual(before, after)
        with self.assertRaisesRegex(diag.DiagnosticError, "after context exit"):
            api.raw_scene_batch()

    def test_tampered_source_rejected_at_import(self):
        (self.root / "selftrain/data/diotic_attention.py").write_text("class Changed: pass\n")
        with self.assertRaisesRegex(ImportError, "identity mismatch"):
            with diag.frozen_scene_context(self.root, self.records):
                self.fail("tampered source entered context")

    def test_protected_module_replacement_changes_active_graph(self):
        with diag.frozen_scene_context(self.root, self.records):
            baseline = policy.graph()
            name = "selftrain.data.diotic_attention"
            original = sys.modules[name]
            try:
                sys.modules[name] = types.ModuleType(name)
                self.assertNotEqual(policy.graph(), baseline)
            finally:
                sys.modules[name] = original

    def test_legitimate_context_entry_keeps_evaluator_seal_valid(self):
        # Required positive behavior. Expected RED for the current prototype:
        # it still treats authorized protected-module imports as arbitrary changes.
        before = policy.graph()
        with diag.frozen_scene_context(self.root, self.records):
            self.assertTrue(policy.graph() == before,
                            "authorized frozen scope still invalidates evaluator graph")


if __name__ == "__main__":
    unittest.main(verbosity=2)

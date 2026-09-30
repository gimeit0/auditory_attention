"""Local regression only; does not modify or publish the reviewed v2 package."""

import hashlib
import importlib.util
import pathlib
import sys
import tempfile
import unittest


WORKSPACE = pathlib.Path(__file__).resolve().parents[2]
PACKAGE = WORKSPACE / "same_bank_eval_2026_09_03_v4_numeric_diag_v2"
SPEC = importlib.util.spec_from_file_location(
    "v2_loader_regression", PACKAGE / "diagnose_batch_invariance.py"
)
diag = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diag
SPEC.loader.exec_module(diag)


class LoaderRecordRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()
        (self.root / "tools").mkdir()
        self.path = self.root / "tools" / "locked_same_bank_eval.py"
        source = "\n".join(
            f"def {name}(*args, **kwargs): return None"
            for name in diag.V4_EVALUATOR_WHITELIST
        ) + "\n"
        self.path.write_text(source)
        self.trace = diag._get_trace()
        # Exactly the two read roots used by read_frozen_context and its loader.
        self.payload, self.outer = self.trace.read_stable_bytes(
            self.path, allowed_root=self.root
        )
        self.facade = diag.load_verified_v4_evaluator(
            self.trace, self.path, len(self.payload),
            hashlib.sha256(self.payload).hexdigest(),
        )
        self.addCleanup(
            diag._VERIFIED_PRODUCTION_EVALUATORS.pop, id(self.facade), None
        )
        self.inner = diag._VERIFIED_PRODUCTION_EVALUATORS[id(self.facade)][1]

    def test_actual_reads_differ_only_in_relative_path(self):
        self.assertEqual(self.outer["relative_path"], "tools/locked_same_bank_eval.py")
        self.assertEqual(self.inner["relative_path"], "locked_same_bank_eval.py")
        self.assertEqual(
            {k: v for k, v in self.outer.items() if k != "relative_path"},
            {k: v for k, v in self.inner.items() if k != "relative_path"},
        )

    def test_same_verified_file_can_register_production_capability(self):
        # Desired behavior: a genuinely loaded unchanged file must register.
        # No fake evaluator registry entry and no bypass of capability validation.
        manifest = {"fixture": True}
        manifest_path = self.root / "input_freeze.json"
        manifest_path.write_text('{"fixture": true}\n')
        _, manifest_record = self.trace.read_stable_bytes(
            manifest_path, allowed_root=self.root
        )
        source_path = self.root / "source.py"
        source_path.write_text("VALUE = 1\n")
        _, source_record = self.trace.read_stable_bytes(
            source_path, allowed_root=self.root
        )
        diag._VERIFIED_PRODUCTION_MANIFESTS[id(manifest)] = (
            manifest, manifest_record
        )
        diag._VERIFIED_PRODUCTION_INVENTORIES[id(manifest)] = (
            manifest, (self.outer,), (source_record,), self.root
        )
        self.addCleanup(diag._VERIFIED_PRODUCTION_MANIFESTS.pop, id(manifest), None)
        self.addCleanup(diag._VERIFIED_PRODUCTION_INVENTORIES.pop, id(manifest), None)
        capability = diag._register_frozen_context_capability(
            evaluator=self.facade,
            manifest=manifest,
            evaluator_record=self.outer,
            manifest_record=manifest_record,
            pinned_records=[self.outer],
            source_records=[source_record],
            root=self.root,
            source_root=self.root,
            trust_domain="production",
        )
        self.assertEqual(capability.trust_domain, "production")


if __name__ == "__main__":
    unittest.main(verbosity=2)

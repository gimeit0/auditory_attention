"""New-source identity and unchanged inference boundaries; synthetic/local only."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

import build_release as recipe

ROOT, PROTO, NEW, OLD = recipe.ROOT, recipe.PROTO, recipe.NEW, recipe.OLD


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(PROTO / "targeted_production_preparation_20260915_scan"))
        import cuda_registration
        cls.cuda = cuda_registration
        cls.bridge = cls.cuda.bridge
        cls.diag = cls.bridge.load_v19(NEW / "diagnose_batch_invariance.py")
        cls.old_bridge = load(PROTO / "targeted_worker_20260912/baseline_bridge.py", "old_loader_cross_version_test")
        cls.old_diag = cls.old_bridge.load_v18(OLD / "diagnose_batch_invariance.py")

    def test_frozen_parent_and_new_recipe_sources_exact(self):
        files, manifest = recipe.recipe()
        self.assertEqual(len(files), 44)
        for path, raw in files.items():
            with self.subTest(path=str(path)):
                self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(json.loads((recipe.HERE / "SOURCE_MANIFEST.json").read_bytes()), manifest)

    def test_only_scanner_and_two_identity_constants_changed_in_diagnostic(self):
        original = recipe.version((OLD / "diagnose_batch_invariance.py").read_text())
        self.assertEqual((NEW / "diagnose_batch_invariance.py").read_text(), recipe.scanner_delta(original))
        old, new = ast.parse(original), ast.parse((NEW / "diagnose_batch_invariance.py").read_bytes())
        changed = []
        self.assertEqual(len(old.body), len(new.body))
        for before, after in zip(old.body, new.body):
            if ast.dump(before) != ast.dump(after):
                changed.append(before.name)
        self.assertEqual(changed, [recipe.TARGET])

    def test_new_loader_uses_new_physical_file_and_own_identity(self):
        self.assertEqual(Path(self.diag.__file__), NEW / "diagnose_batch_invariance.py")
        self.assertEqual(recipe.sha(Path(self.diag.__file__).read_bytes()), self.bridge.V19_SHA)
        self.assertNotEqual(self.bridge.V19_SHA, self.old_bridge.V18_SHA)
        self.assertEqual(self.diag.DIAGNOSTIC_PROTOCOL, "formal40_batch_invariance_diag_20260903_v19")
        self.assertEqual(self.diag.DIAGNOSTIC_ROOT.name, "same_bank_v4_job646900_2026-09-03_v19")
        self.bridge._require_module(self.diag)

    def test_new_loader_rejects_old_source(self):
        with self.assertRaisesRegex(self.bridge.BridgeError, "SHA"):
            self.bridge.load_v19(OLD / "diagnose_batch_invariance.py")

    def test_old_loader_rejects_new_source(self):
        with self.assertRaisesRegex(self.old_bridge.BridgeError, "SHA"):
            self.old_bridge.load_v18(NEW / "diagnose_batch_invariance.py")

    def test_loaded_modules_are_not_interchangeable(self):
        with self.assertRaisesRegex(self.bridge.BridgeError, "pinned loader"):
            self.bridge._require_module(self.old_diag)
        with self.assertRaisesRegex(self.old_bridge.BridgeError, "pinned loader"):
            self.old_bridge._require_module(self.diag)

    def test_equal_source_independent_module_cannot_borrow_issuance(self):
        impostor = load(NEW / "diagnose_batch_invariance.py", "non_loader_v19_test")
        with self.assertRaisesRegex(self.bridge.BridgeError, "pinned loader"):
            self.bridge._require_module(impostor)

    def test_postload_scanner_replacement_is_rejected(self):
        with mock.patch.object(self.diag, recipe.TARGET, lambda _: {}):
            with self.assertRaisesRegex(self.bridge.BridgeError, "function replaced"):
                self.bridge._require_module(self.diag)
        self.bridge._require_module(self.diag)

    def test_entire_observer_chain_uses_same_new_bridge(self):
        chain = (self.cuda, self.cuda.admission, self.cuda.compiled, self.cuda.prep, self.cuda.life)
        for part in chain:
            with self.subTest(module=part.__name__):
                self.assertIs(part.bridge, self.bridge)
                self.assertIn("20260915_scan", str(Path(part.__file__).parent))
        self.cuda.source_check()

    def test_old_freeze_is_rejected_by_new_validator(self):
        path = ROOT / "docs/superpowers/evidence/v18-deployment-artifacts/input_freeze.json"
        raw = path.read_bytes()
        self.assertEqual(recipe.sha(raw), self.bridge.replay.FREEZE_SHA)
        with self.assertRaisesRegex(self.diag.DiagnosticError, "freeze protocol/contract"):
            self.diag._validate_freeze_value(json.loads(raw), self.diag.production_contract(),
                                            status="INPUTS_FROZEN", diagnostic_root=self.diag.DIAGNOSTIC_ROOT)

    def test_plan_and_historical_replay_stay_explicit_parent_data(self):
        self.assertEqual(self.bridge.PARENT_SHA, self.old_bridge.PARENT_SHA)
        self.assertEqual(self.bridge.REPLAY_SHA, self.old_bridge.REPLAY_SHA)
        self.assertEqual(self.cuda.admission.prior.FREEZE_SHA, self.old_bridge.replay.FREEZE_SHA)
        raw = (ROOT / "docs/superpowers/evidence/v18-deployment-artifacts/input_freeze.json").read_bytes()
        plan = self.cuda.admission.plan_documents(self.cuda.admission.PLAN_PATH.read_bytes(), raw, "B2")
        self.assertEqual(plan.batch_sizes, (16, 1))
        self.assertEqual(len(plan.schedule()), 34)
        self.assertEqual(len(plan.stages), 42)

    def test_preparation_derivation_still_restores_all_original_statements(self):
        raw = Path(self.diag.__file__).read_bytes()
        tree = self.cuda.prep.build_candidate(raw)
        audit = self.cuda.prep.verify_delta(raw, tree.body[0])
        self.assertTrue(audit["original_ast_restored_exactly"])
        self.assertEqual(audit["added_calls"], [self.cuda.prep.INSTALL, self.cuda.prep.BEFORE_ISSUE])
        before = next(n for n in ast.parse(Path(self.old_diag.__file__).read_bytes()).body
                      if isinstance(n, ast.FunctionDef) and n.name == "prepare_formal40_worker")
        after = next(n for n in ast.parse(raw).body
                     if isinstance(n, ast.FunctionDef) and n.name == "prepare_formal40_worker")
        self.assertEqual(ast.dump(before), ast.dump(after))

    def test_historical_runtime_and_science_contracts_unchanged(self):
        for name in ("V4_MANIFEST_SHA256", "V4_EVALUATOR_SHA256", "V4_LOCK_SHA256", "FORMAL40_SHA256",
                     "NUMERIC_TRACE_SHA256", "EVALUATION_ROLE"):
            self.assertEqual(getattr(self.diag, name), getattr(self.old_diag, name))
        old = {n.name: ast.dump(n) for n in ast.parse(Path(self.old_diag.__file__).read_bytes()).body
               if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        new = {n.name: ast.dump(n) for n in ast.parse(Path(self.diag.__file__).read_bytes()).body
               if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        self.assertEqual({k: v for k, v in old.items() if k != recipe.TARGET},
                         {k: v for k, v in new.items() if k != recipe.TARGET})

    def test_no_new_freeze_or_gpu_authorization_claim(self):
        manifest = json.loads((recipe.HERE / "SOURCE_MANIFEST.json").read_bytes())
        self.assertIsNone(manifest["candidate_input_freeze_sha256"])
        for flag in ("ready_for_gpu", "gpu_job_entry_integrated", "submission_authorized"):
            self.assertIs(manifest[flag], False)
        self.assertFalse((NEW / "input_freeze.json").exists())
        self.assertFalse((recipe.HERE / "submit_once.py").exists())

    def test_old_remote_cpu_entry_is_closed_not_redirected_silently(self):
        probe = load(PROTO / "targeted_real_registration_20260915_scan/probe_cpu.py", "closed_v19_cpu_entry_test")
        with self.assertRaisesRegex(RuntimeError, "local-only; new freeze"):
            probe.main()


if __name__ == "__main__":
    unittest.main()

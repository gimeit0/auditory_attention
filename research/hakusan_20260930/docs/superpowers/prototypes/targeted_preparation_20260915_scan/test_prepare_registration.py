"""The loader creates the model now; no preconstructed model is injected."""

import ast
import contextlib
import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import prepare_registration as prep

life = prep.life
bridge = prep.bridge
PROTOTYPES = Path(__file__).resolve().parent.parent
prior = bridge._load(PROTOTYPES / "targeted_lifecycle_20260915_scan/test_observer_lifecycle.py",
                     "1550f5797d6f978ae16c4679af55b612f80633ce1906ae032837efc62fc34e79",
                     "preparation_prior_fixtures")
diag, fixtures = prior.diag, prior.fixtures


class LazyEvaluator(fixtures._Task4Evaluator):
    def __init__(self, scene, *, bad_report=False, bad_postload_sources=False):
        super().__init__()
        self.scene = scene
        self.bad_report = bad_report
        self.bad_postload_sources = bad_postload_sources

    def strict_load_model(self, manifest, model_id, device=None):
        if self.model_to_load is not None or self.strict_load_hook is not None:
            raise AssertionError("preconstructed fixture injection must not be used")
        self.load_calls.append((manifest, model_id, device))
        model = prior.Toy(self.calls)
        model.to(device)
        if self.bad_postload_sources:
            object.__setattr__(self.scene, "imported_source_records", ())
        report = {"key_count": 1, "missing_keys": [], "unexpected_keys": [],
                  "shape_mismatches": {}, "dtype_mismatches": {}, "prefix_rule": "exact",
                  "loaded_trainable_numel": 1, "trainable_numel": 1,
                  "loaded_trainable_numel_ratio": 0.5 if self.bad_report else 1.0,
                  "native_preprocessing": "selftrain_singleton_per_example_leveling",
                  "model_module": {"path": "/frozen/src/spatial_attn_lightning.py"}}
        return model, report


@contextlib.contextmanager
def request_context(cell="B2", **kwargs):
    scene = fixtures._Task4SceneAPI()
    evaluator = LazyEvaluator(scene, **kwargs)
    bank = fixtures._task4_bank(32)
    trials = fixtures._task4_trials(bank)
    with tempfile.TemporaryDirectory(prefix="preseal-registration-test-") as temporary:
        with life.capture.CaptureStore(Path(temporary) / "captures", total_bytes=1024**2) as store:
            with fixtures._task4_hermetic_worker_context(evaluator, scene) as context:
                run = {**context, "bank": bank, "clips_dir": Path("/clips"), "cell_id": cell,
                       "historical_scene_hashes": fixtures._task4_scene_hashes(bank),
                       "scratch_root": temporary, "cache_roots": {}}
                request = prep.RegistrationRequest(diag, run, prior.plan(trials), store, hermetic_test=True)
                try:
                    yield request, trials, evaluator, scene
                finally:
                    request.close()


class PreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        life.torch.set_num_threads(1)
        cls.contract = prior.expected_contract()
        cls.complete_runs = []

    def test_lazy_load_registration_original_guards_and_full_passes(self):
        for cell in ("A2", "B2"):
            with self.subTest(cell=cell), request_context(cell) as (request, trials, evaluator, scene):
                old_function = diag.prepare_formal40_worker
                self.assertIsNone(request.model)
                self.assertEqual(evaluator.load_calls, [])
                prepared, lease, receipt = prep.prepare_registered(request, allow_cpu=True)
                self.assertIs(diag.prepare_formal40_worker, old_function)
                self.assertNotIn(prep.CANDIDATE_NAME, vars(diag))
                self.assertTrue(receipt["ast_audit"]["original_ast_restored_exactly"])
                self.assertEqual(receipt["install_count"], 1)
                self.assertEqual(receipt["pre_issue_check_count"], 1)
                self.assertTrue(receipt["preparation_state_rng_runtime_unchanged"])
                self.assertIsNone(evaluator.model_to_load)
                self.assertIsNone(evaluator.strict_load_hook)
                run = {**request.context, **prepared}
                wire = bridge.replay.canonical(self.contract)
                gate = bridge.BaselineBridge(diag, run, trials, wire, bridge.digest(wire), cell, hermetic_test=True)
                result = life.run_observed(gate, lease)
                self.assertEqual(result["batches"], 34)
                self.assertEqual(result["capture_records"], 16)
                self.assertEqual(evaluator.calls.count("model"), 34)
                self.assertEqual(len(evaluator.load_calls), 1)
                self.assertEqual(sum(type(c) is tuple and c[0] == "configure_runtime" for c in evaluator.calls), 1)
                self.assertEqual([len(c[0]) for c in scene.raw_calls], [16, 16] + [1] * 32)
                self.assertEqual([len(c[0]) for c in scene.cue_calls], [16, 16] + [1] * 32)
                self.assertTrue(lease.closed)
                self.complete_runs.append({"cell": cell, "preparation": receipt, "observed": result,
                                           "load_calls": len(evaluator.load_calls), "forward_calls": 34,
                                           "hooks_removed": not any(m._forward_hooks or m._forward_pre_hooks
                                                                    for m in gate.model.modules())})

    def test_exact_ast_delta(self):
        raw = Path(diag.__file__).read_bytes()
        tree = prep.build_candidate(raw)
        report = prep.verify_delta(raw, tree.body[0])
        self.assertEqual(report["added_calls"], [prep.INSTALL, prep.BEFORE_ISSUE])
        self.assertTrue(report["original_ast_restored_exactly"])

    def test_modified_parent_source_rejected(self):
        raw = Path(diag.__file__).read_bytes() + b"\n"
        with self.assertRaisesRegex(prep.PreparationError, "SHA differs"):
            prep.build_candidate(raw)

    def test_removing_original_guard_rejected(self):
        raw = Path(diag.__file__).read_bytes()
        node = prep.build_candidate(raw).body[0]
        index = next(i for i, n in enumerate(node.body) if isinstance(n, ast.If))
        node.body.pop(index)
        with self.assertRaisesRegex(prep.PreparationError, "logic was changed"):
            prep.verify_delta(raw, node)

    def test_changed_runtime_call_rejected(self):
        raw = Path(diag.__file__).read_bytes()
        node = prep.build_candidate(raw).body[0]
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "_configure_runtime":
                call.args[0] = ast.Constant(value=True)
        with self.assertRaisesRegex(prep.PreparationError, "logic was changed"):
            prep.verify_delta(raw, node)

    def test_late_install_rejected(self):
        raw = Path(diag.__file__).read_bytes()
        node = prep.build_candidate(raw).body[0]
        index = next(i for i, n in enumerate(node.body) if ast.unparse(n) == prep.INSTALL)
        install = node.body.pop(index)
        node.body.insert(index + 1, install)
        with self.assertRaisesRegex(prep.PreparationError, "immediately after"):
            prep.verify_delta(raw, node)

    def test_duplicate_install_rejected(self):
        raw = Path(diag.__file__).read_bytes()
        node = prep.build_candidate(raw).body[0]
        node.body.insert(0, ast.parse(prep.INSTALL).body[0])
        with self.assertRaisesRegex(prep.PreparationError, "call count"):
            prep.verify_delta(raw, node)

    def test_arbitrary_registration_callback_rejected(self):
        with self.assertRaisesRegex(prep.PreparationError, "exact reviewed"):
            prep.prepare_registered(object(), allow_cpu=True)

    def test_production_mode_rejected_before_runtime_and_load(self):
        with request_context() as (request, trials, evaluator, scene):
            candidate = prep.RegistrationRequest(diag, request.context, request.plan, request.store)
            with self.assertRaisesRegex(prep.PreparationError, "production registration is not released"):
                prep.prepare_registered(candidate, allow_cpu=True)
            self.assertEqual(evaluator.calls, [])
            self.assertEqual(evaluator.load_calls, [])

    def test_bad_report_rejected_before_registration(self):
        with request_context(bad_report=True) as (request, trials, evaluator, scene):
            with self.assertRaises(diag.DiagnosticError):
                prep.prepare_registered(request, allow_cpu=True)
            self.assertIsNone(request.lease)
            self.assertTrue(request.failed)
            self.assertEqual(len(evaluator.load_calls), 1)

    def test_original_postload_source_failure_cleans_installed_hooks(self):
        with request_context(bad_postload_sources=True) as (request, trials, evaluator, scene):
            with self.assertRaisesRegex(diag.DiagnosticError, "post-load source provenance"):
                prep.prepare_registered(request, allow_cpu=True)
            self.assertIsNotNone(request.lease)
            self.assertEqual(request.install_count, 1)
            self.assertEqual(request.before_issue_count, 0)
            self.assertTrue(request.lease.closed and request.failed)
            self.assertFalse(any(m._forward_hooks or m._forward_pre_hooks for m in request.model.modules()))

    def test_close_after_preparation_revokes_original_identity(self):
        with request_context() as (request, trials, evaluator, scene):
            prepared, lease, receipt = prep.prepare_registered(request, allow_cpu=True)
            attestation = prepared["_formal40_worker_attestation"]
            request.close()
            self.assertIn(id(attestation), diag._REVOKED_FORMAL40_ATTESTATIONS)
            self.assertTrue(lease.closed)
            self.assertEqual(evaluator.calls.count("model"), 0)

    def test_request_is_single_use(self):
        with request_context() as (request, trials, evaluator, scene):
            prepared, lease, receipt = prep.prepare_registered(request, allow_cpu=True)
            with self.assertRaisesRegex(prep.PreparationError, "single use"):
                prep.prepare_registered(request, allow_cpu=True)
            self.assertEqual(len(evaluator.load_calls), 1)
            self.assertTrue(lease.closed)

    def test_registration_plan_change_rejected_before_load(self):
        with request_context() as (request, trials, evaluator, scene):
            request.plan = replace(request.plan, targets=(request.plan.trials[1],))
            with self.assertRaisesRegex(prep.PreparationError, "changed or failed"):
                prep.prepare_registered(request, allow_cpu=True)
            self.assertEqual(evaluator.load_calls, [])

    def test_instance_installer_replacement_rejected(self):
        with request_context() as (request, trials, evaluator, scene):
            request.install = lambda *_: None
            with self.assertRaisesRegex(prep.PreparationError, "instance method"):
                prep.prepare_registered(request, allow_cpu=True)
            self.assertEqual(evaluator.load_calls, [])

    def test_missing_capability_still_rejected_by_original_guard(self):
        with request_context() as (request, trials, evaluator, scene):
            request.context["_frozen_context_capability"] = None
            with self.assertRaisesRegex(diag.DiagnosticError, "verified frozen provenance"):
                prep.prepare_registered(request, allow_cpu=True)
            self.assertEqual(evaluator.load_calls, [])

    def test_copy_of_receipt_does_not_create_request(self):
        with request_context() as (request, trials, evaluator, scene):
            _, _, receipt = prep.prepare_registered(request, allow_cpu=True)
            with self.assertRaisesRegex(prep.PreparationError, "exact reviewed"):
                prep.prepare_registered(copy.deepcopy(receipt), allow_cpu=True)

    def test_rejected_reuse_does_not_revoke_preexisting_worker(self):
        with request_context() as (request, trials, evaluator, scene):
            prepared, lease, _ = prep.prepare_registered(request, allow_cpu=True)
            attestation = prepared["_formal40_worker_attestation"]
            with tempfile.TemporaryDirectory() as directory:
                with life.capture.CaptureStore(Path(directory) / "new-captures") as store:
                    other = prep.RegistrationRequest(diag, request.context, request.plan, store, hermetic_test=True)
                    other.used = True
                    other.issued_before = frozenset(diag._ISSUED_FORMAL40_ATTESTATIONS)
                    try:
                        with self.assertRaisesRegex(life.LifecycleError, "before original issuance"):
                            other.install(prepared["model"], prepared["load_report"], prepared["device"])
                    finally:
                        other.close()
            self.assertNotIn(id(attestation), diag._REVOKED_FORMAL40_ATTESTATIONS)
            lease.check()
            with diag._prediction_evaluator_context(prepared["evaluator"], model=prepared["model"],
                                                    attestation=attestation):
                self.assertIs(diag._live_inference_attestation(prepared["model"], "old_worker_preserved"), attestation)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Portable boundary/dispatch tests, plus a SEPARATE cold 2.1.1 probe."""
import contextlib
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import torch
import compiled_registration as candidate

life, prep, bridge = candidate.life, candidate.prep, candidate.bridge
prior = bridge._load(Path(__file__).resolve().parent.parent / "targeted_preparation_20260912/test_prepare_registration.py",
                     "bb844d0122b0acc381e4acf2f5b73e709d6449520140877d2b800a996fbb43d8",
                     "compiled_prior_fixtures")
fixtures, diag = prior.prior.fixtures, prior.prior.diag


class TinyCNN(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.stem = torch.nn.Identity()
        self.mix = torch.nn.Identity()
        self.head = torch.nn.Identity()

    def forward(self, cue, scene, background):
        cue, scene = self.stem(cue), self.stem(scene)
        scene = self.mix(scene)
        batch = scene.shape[0]
        base = (scene + cue).reshape(batch, -1).mean(dim=1)
        offsets = torch.arange(800, dtype=base.dtype, device=base.device)
        return self.head(base[:, None] + offsets[None, :] / 1000.0)


class TinyOuter(fixtures._Task4Model):
    def __init__(self, calls=None):
        super().__init__(calls)
        self.model = torch.compile(TinyCNN(), backend="eager")
        self.eval().requires_grad_(False)

    def forward(self, cue, scene, background):
        self.calls.append("model")
        return self.model(cue, scene, background)


class CompiledEvaluator(prior.LazyEvaluator):
    def strict_load_model(self, manifest, model_id, device=None):
        if self.model_to_load is not None or self.strict_load_hook is not None:
            raise AssertionError("no model preinjection")
        self.load_calls.append((manifest, model_id, device))
        model = TinyOuter(self.calls).to(device)
        report = {"key_count": 1, "missing_keys": [], "unexpected_keys": [],
                  "shape_mismatches": {}, "dtype_mismatches": {}, "prefix_rule": "exact",
                  "loaded_trainable_numel": 1, "trainable_numel": 1,
                  "loaded_trainable_numel_ratio": 1.0,
                  "native_preprocessing": "selftrain_singleton_per_example_leveling",
                  "model_module": {"path": "/frozen/src/spatial_attn_lightning.py"}}
        return model, report


@contextlib.contextmanager
def request_context():
    scene = fixtures._Task4SceneAPI()
    evaluator = CompiledEvaluator(scene)
    bank = fixtures._task4_bank(32)
    trials = fixtures._task4_trials(bank)
    with tempfile.TemporaryDirectory(prefix="compiled-registration-") as directory:
        with life.capture.CaptureStore(Path(directory) / "captures", total_bytes=1024**2) as store:
            with fixtures._task4_hermetic_worker_context(evaluator, scene) as context:
                request = candidate.CompiledRequest(diag, context, prior.prior.plan(trials), store, TinyOuter, TinyCNN)
                try:
                    yield request, evaluator, trials
                finally:
                    request.close()


@contextlib.contextmanager
def lease_context():
    with request_context() as (request, evaluator, trials):
        model = TinyOuter()
        binding = candidate.stream.bind_compiled_outer(model, request.plan,
                    expected_outer_type=TinyOuter, expected_cnn_type=TinyCNN)
        lease = candidate.CompiledLease(diag, binding, request.store)
        try:
            yield lease, request, model
        finally:
            lease.close()


class CompiledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.dispatch_records = []

    def test_binding_accepts_compiled_shape_without_claiming_authority(self):
        with lease_context() as (lease, request, model):
            self.assertEqual(lease.plan.stages[0].module, "model._orig_mod.stem")
            self.assertIsNone(lease.compiler)
            self.assertEqual(model.calls, [])

    def test_old_eager_lease_still_rejects_compiled_model(self):
        with lease_context() as (lease, request, model):
            with self.assertRaisesRegex(life.LifecycleError, "compiled models"):
                life.ObservationLease(diag, model, lease.plan, request.store)

    def test_wrapper_replacement_rejected(self):
        with lease_context() as (lease, request, model):
            lease.install_before_issuance()
            model.model = torch.compile(TinyCNN(), backend="eager")
            with self.assertRaises((prep.PreparationError, life.LifecycleError, life.base.TraceError)):
                lease.check()

    def test_binding_receipt_replacement_rejected(self):
        with lease_context() as (lease, request, model):
            lease.install_before_issuance()
            lease.binding = replace(lease.binding)
            with self.assertRaisesRegex(prep.PreparationError, "receipt"):
                lease.check()

    def test_wrong_outer_type_rejected(self):
        with lease_context() as (lease, request, model):
            with self.assertRaises(life.base.TraceError):
                candidate.stream.bind_compiled_outer(model, request.plan,
                         expected_outer_type=TinyCNN, expected_cnn_type=TinyCNN)

    def test_wrong_inner_type_rejected(self):
        with lease_context() as (lease, request, model):
            with self.assertRaises(life.base.TraceError):
                candidate.stream.bind_compiled_outer(model, request.plan,
                         expected_outer_type=TinyOuter, expected_cnn_type=TinyOuter)

    def test_missing_stage_rejected(self):
        with lease_context() as (lease, request, model):
            p = replace(request.plan, stages=(life.base.Stage("missing", "cue"),))
            with self.assertRaises(life.base.TraceError):
                candidate.stream.bind_compiled_outer(model, p, expected_outer_type=TinyOuter, expected_cnn_type=TinyCNN)

    def test_existing_hook_rejected(self):
        with lease_context() as (lease, request, model):
            handle = model.model._orig_mod.stem.register_forward_hook(lambda *_: None)
            try:
                with self.assertRaisesRegex(life.LifecycleError, "existing forward hooks"):
                    lease.install_before_issuance()
            finally:
                handle.remove()

    def test_compiled_instance_stage_override_rejected(self):
        with lease_context() as (lease, request, model):
            lease.install_before_issuance()
            lease.stage = lambda *_: None
            with self.assertRaisesRegex(prep.PreparationError, "instance method"):
                lease.check()

    def test_request_type_replacement_rejected_before_load(self):
        with request_context() as (request, evaluator, trials):
            request.cnn_type = TinyOuter
            with self.assertRaisesRegex(prep.PreparationError, "type binding"):
                candidate.prepare_compiled(request)
            self.assertEqual(evaluator.load_calls, [])

    def test_arbitrary_request_rejected(self):
        with self.assertRaisesRegex(prep.PreparationError, "exact compiled request"):
            candidate.prepare_compiled(object())

    def test_version_gate_does_not_load_model_or_patch_v18(self):
        # Local 2.12.1 validates REJECTION only. Never mock torch version to
        # pretend that its compiler sources are reviewed 2.1.1 sources.
        self.assertNotEqual(str(torch.__version__), "2.1.1+cu118")
        with request_context() as (request, evaluator, trials):
            old = diag._issue_compiler_lifecycle
            with self.assertRaisesRegex(prep.PreparationError, "requires torch 2.1.1"):
                candidate.prepare_compiled(request)
            self.assertEqual(evaluator.load_calls, [])
            self.assertIs(diag._issue_compiler_lifecycle, old)
            self.assertIsNone(request.lease)

    def test_original_compiler_source_version_gate_unchanged(self):
        with lease_context() as (lease, request, model):
            lease.install_before_issuance()
            with self.assertRaisesRegex(diag.DiagnosticError, "reviewed torch 2.1.1"):
                lease.seal_compiler()
            self.assertIsNone(lease.compiler)

    def test_unchanged_preparation_ast_restored(self):
        raw = Path(diag.__file__).read_bytes()
        report = prep.verify_delta(raw, prep.build_candidate(raw).body[0])
        self.assertTrue(report["original_ast_restored_exactly"])

    def test_portable_compiled_dispatch_only_not_original_guards(self):
        with lease_context() as (lease, request, model):
            lease.install_before_issuance()
            ids = lease.plan.trials[:16]
            lease.current = {"pass_id": "pass1", "batch_index": 0, "trials": ids, "index": 0, "captures": []}
            token = life._ACTIVE.set(lease)
            try:
                x = torch.arange(128, dtype=torch.float32).reshape(16, 2, 4)
                # Intentionally test INNER dispatch only, not original worker
                # issuance or root hooks. This must not be called a guard pass.
                with torch.inference_mode():
                    result = model.model(x, x, None)
                self.assertEqual(lease.current["index"], 4)
                self.assertEqual(len(lease.store.refs), 4)
                self.assertEqual(tuple(result.shape), (16, 800))
                for ref in lease.store.refs:
                    self.assertTrue(lease.store.compare(ref, ref))
                self.dispatch_records.append({"backend": "eager", "batches": 1, "stage_invocations": 4,
                                              "capture_records": 4, "original_guards_validated": False})
            finally:
                life._ACTIVE.reset(token)

    def test_close_removes_registered_hooks(self):
        with lease_context() as (lease, request, model):
            lease.install_before_issuance()
            lease.close()
            self.assertFalse(any(m._forward_hooks or m._forward_pre_hooks for m in model.modules()))
            with self.assertRaises(life.LifecycleError):
                lease.check()


def cold_probe():
    """Called only in a NEW remote process, not after local unittest dispatch."""
    torch.set_num_threads(1)
    if str(torch.__version__) != "2.1.1+cu118" or torch.cuda.is_initialized():
        raise RuntimeError("cold probe requires actual HAKUSAN CPU torch")
    with request_context() as (request, evaluator, trials):
        prepared, lease, receipt = candidate.prepare_compiled(request)
        raw = torch.arange(128, dtype=torch.float32).reshape(16, 2, 4)
        result = candidate.first_batch_probe(request, prepared, raw, raw.clone(),
                                             torch.zeros(16, dtype=torch.long),
                                             torch.ones(16, dtype=torch.long))
        if len(evaluator.load_calls) != 1 or evaluator.calls.count("model") != 1:
            raise AssertionError("probe must load once and forward once")
        result.update({"python": __import__("sys").version.split()[0], "torch": torch.__version__,
                       "backend": "eager", "load_calls": 1, "forward_calls": 1,
                       "hooks_removed": not any(m._forward_hooks or m._forward_pre_hooks for m in request.model.modules()),
                       "cuda_initialized": torch.cuda.is_initialized(), "preparation": receipt})
        print(json.dumps(result, sort_keys=True), flush=True)
        return result


if __name__ == "__main__":
    unittest.main(verbosity=2)


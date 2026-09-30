"""Portable unit/static tests only, no CUDA/model load/original compiler issue."""
import ast
from dataclasses import replace
import hashlib
import inspect
from pathlib import Path
import tempfile
import types
import unittest

import torch
import cuda_registration as adapter

ROOT = Path(__file__).resolve().parents[4]
TEST_PATH = ROOT / "docs/superpowers/prototypes/targeted_real_registration_20260913/test_admission.py"
fixture = adapter.bridge._load(TEST_PATH, "6b1d4b900aa7ae52723da7e2b15b3ca930fbdc2cc8fade6a7e8ec8e06b581614",
                               "production_registration_portable_topology")
diag = fixture.DIAG


class EndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_exact_cpu_encoding_parity_for_three_dtypes(self):
        for dtype in (torch.float16, torch.float32, torch.float64):
            with self.subTest(dtype=dtype):
                tensor = torch.arange(100, dtype=dtype).reshape(10, 10)
                self.assertEqual(adapter.endpoint_descriptor(tensor), adapter.life.descriptor(tensor))

    def test_noncontiguous_encoding_parity(self):
        tensor = torch.arange(240, dtype=torch.float32).reshape(10, 24).T[::2]
        self.assertFalse(tensor.is_contiguous())
        self.assertEqual(adapter.endpoint_descriptor(tensor), adapter.life.descriptor(tensor))

    def test_multi_chunk_encoding(self):
        tensor = torch.arange(600000, dtype=torch.float32).reshape(300, 2000).T
        self.assertGreater(tensor.numel() * tensor.element_size(), adapter.CHUNK)
        self.assertEqual(adapter.endpoint_descriptor(tensor), adapter.life.descriptor(tensor))

    def test_state_rng_runtime_and_input_unchanged(self):
        tensor = torch.arange(24, dtype=torch.float32)
        before = tensor.clone(), adapter.life.base.rng_state(), adapter.life.base.runtime_state()
        adapter.endpoint_descriptor(tensor)
        self.assertTrue(torch.equal(before[0], tensor))
        self.assertEqual(before[1:], (adapter.life.base.rng_state(), adapter.life.base.runtime_state()))

    def test_descriptor_does_not_alias_tensor(self):
        tensor = torch.ones(8)
        record = adapter.endpoint_descriptor(tensor)
        digest = record["sha256"]
        tensor.add_(1)
        self.assertEqual(record["sha256"], digest)
        self.assertNotEqual(adapter.endpoint_descriptor(tensor)["sha256"], digest)

    def test_budget_rejected_before_any_meta_transfer(self):
        tensor = torch.empty(adapter.MAX_ENDPOINT // 4 + 1, device="meta")
        with self.assertRaisesRegex(adapter.prep.PreparationError, "byte budget"):
            adapter.endpoint_descriptor(tensor)

    def test_unsupported_device_rejected(self):
        with self.assertRaisesRegex(adapter.life.capture.CaptureError, "device/shape"):
            adapter.endpoint_descriptor(torch.empty(2, device="meta"))

    def test_nonfinite_rejected(self):
        for value in (float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaisesRegex(adapter.life.capture.CaptureError, "nonfinite"):
                adapter.endpoint_descriptor(torch.tensor([value]))

    def test_empty_rejected(self):
        with self.assertRaisesRegex(adapter.prep.PreparationError, "byte budget"):
            adapter.endpoint_descriptor(torch.empty(0))

    def test_dtype_and_subclass_rejected(self):
        for value in (torch.ones(2, dtype=torch.bfloat16), torch.ones(2, dtype=torch.int64),
                      torch.nn.Parameter(torch.ones(2))):
            with self.subTest(dtype=value.dtype), self.assertRaisesRegex(adapter.prep.PreparationError, "native endpoint"):
                adapter.endpoint_descriptor(value)

    def test_changed_derived_global_rejected(self):
        namespace = adapter.CudaCompiledLease.pre.__globals__
        original = namespace["endpoint_descriptor"]
        try:
            namespace["endpoint_descriptor"] = lambda _: {}
            with self.assertRaisesRegex(adapter.prep.PreparationError, "global changed"):
                adapter.source_check()
        finally:
            namespace["endpoint_descriptor"] = original
        adapter.source_check()


class PreparationStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = Path(diag.__file__).read_bytes()
        cls.tree = ast.parse(Path(adapter.__file__).read_bytes())

    def test_original_prepare_delta_restores_exactly(self):
        tree = adapter.prep.build_candidate(self.raw)
        audit = adapter.prep.verify_delta(self.raw, tree.body[0])
        self.assertTrue(audit["original_ast_restored_exactly"])
        self.assertEqual(audit["added_calls"], [adapter.prep.INSTALL, adapter.prep.BEFORE_ISSUE])

    def test_install_then_original_compiler_then_adopt_then_worker(self):
        fn = adapter.prep.build_candidate(self.raw).body[0]
        positions = {}
        for i, statement in enumerate(fn.body):
            text = ast.unparse(statement)
            if text == adapter.prep.INSTALL:
                positions["install"] = i
            if "_issue_compiler_lifecycle(model, model_module_inventory)" in text:
                positions["original_compiler"] = i
            if text == adapter.prep.BEFORE_ISSUE:
                positions["adopt"] = i
            if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "attestation"
                                                         for t in statement.targets):
                positions["worker"] = i
        self.assertEqual(list(positions), ["install", "original_compiler", "adopt", "worker"])
        self.assertEqual(sorted(positions.values()), list(positions.values()))
        self.assertEqual(sum(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                             and n.func.id == "_issue_compiler_lifecycle" for n in ast.walk(fn)), 1)

    def test_adapter_never_issues_or_reseals_compiler(self):
        calls = [ast.unparse(n.func) for n in ast.walk(self.tree) if isinstance(n, ast.Call)]
        for name in ("_issue_compiler_lifecycle", "seal_compiler", "manual_seed"):
            self.assertFalse(any(s.split(".")[-1] == name for s in calls))
        self.assertEqual([s for s in calls if s.split(".")[-1] == "reset"], ["life._ACTIVE.reset"])

    def test_allow_cpu_false_no_forward_or_submission(self):
        fn = next(n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name == "prepare_production")
        values = [k.value.value for n in ast.walk(fn) if isinstance(n, ast.Call) for k in n.keywords
                  if k.arg == "allow_cpu" and isinstance(k.value, ast.Constant)]
        self.assertEqual(values, [False])
        calls = [n.func.attr for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        for name in ("forward", "run_trace_pass", "trace_predict_batch", "Popen", "run", "system"):
            self.assertNotIn(name, calls)

    def test_observed_candidate_keeps_two_passes_parent_gate_and_cleanup(self):
        fn = next(n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_observed_candidate")
        loops = [n for n in ast.walk(fn) if isinstance(n, ast.For) and isinstance(n.target, ast.Tuple)]
        self.assertEqual(len(loops), 1)
        self.assertEqual(ast.literal_eval(loops[0].iter), (("pass1", 16), ("pass2", 1)))
        calls = [ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)]
        for name in ("gate.diag.run_trace_pass", "gate._consume", "gate.gate.finish", "lease.verify_pass",
                     "lease.store.compare", "life._ACTIVE.reset", "lease.close"):
            self.assertIn(name, calls)
        self.assertEqual(calls.count("gate.diag.run_trace_pass"), 1)
        for name in ("torch.compile", "gate.diag.prepare_formal40_worker", "torch.manual_seed"):
            self.assertNotIn(name, calls)

    def test_arbitrary_observer_rejected_without_forward(self):
        with self.assertRaisesRegex(adapter.prep.PreparationError, "exact CUDA observation lease"):
            adapter.run_observed_candidate(object(), object())

    def test_cpu_compiled_adapter_is_unchanged(self):
        self.assertEqual(hashlib.sha256(Path(adapter.compiled.__file__).read_bytes()).hexdigest(),
                         adapter.admission.COMPILED_SHA)
        self.assertIn('"CPU probe only"', inspect.getsource(adapter.compiled.CompiledLease.__init__))

    def test_gpu_candidate_does_not_inherit_cpu_compiled_class(self):
        self.assertEqual(adapter.CudaCompiledLease.__bases__, (adapter.life.ObservationLease,))

    def test_pre_and_post_change_only_endpoint_descriptor(self):
        for name in ("pre", "post"):
            function = adapter.endpoint_method(name)
            self.assertEqual(function.__code__, getattr(adapter.CudaCompiledLease, name).__code__)
        with self.assertRaisesRegex(adapter.prep.PreparationError, "unsupported"):
            adapter.endpoint_method("stage")

    def test_arbitrary_request_rejected(self):
        with self.assertRaisesRegex(adapter.prep.PreparationError, "exact production request"):
            adapter.prepare_production(object())

    def test_forged_context_rejected_before_load(self):
        with self.assertRaisesRegex(RuntimeError, "original production frozen capability"):
            adapter.ProductionRequest(diag, {"cell_id": "B2"}, None, "B2", b"", b"")


class CudaAdmissionTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.temporary = tempfile.TemporaryDirectory(prefix="cuda-admission-portable-")
        self.addCleanup(self.temporary.cleanup)
        self.store = adapter.life.capture.CaptureStore(Path(self.temporary.name) / "capture", total_bytes=1)
        self.addCleanup(self.store.close)
        self.plan = adapter.admission.plan_documents(adapter.admission.PLAN_PATH.read_bytes(),
                                                     fixture.FREEZE.read_bytes(), "B2")
        self.model = fixture.Outer()
        self.binding = adapter.stream.bind_compiled_outer(self.model, self.plan,
                        expected_outer_type=fixture.Outer, expected_cnn_type=fixture.Topology)

    def test_cpu_model_rejected_before_hook_install(self):
        with self.assertRaisesRegex(adapter.prep.PreparationError, "single CUDA device"):
            adapter.CudaCompiledLease(diag, self.binding, self.store)
        self.assertFalse(any(m._forward_hooks or m._forward_pre_hooks for m in self.model.modules()))
        self.assertFalse(diag._ISSUED_COMPILER_LIFECYCLES)

    def test_partial_stage_plan_rejected(self):
        binding = replace(self.binding, plan=replace(self.binding.plan, stages=self.binding.plan.stages[:-1]))
        with self.assertRaisesRegex(adapter.prep.PreparationError, "42-position"):
            adapter.CudaCompiledLease(diag, binding, self.store)

    def test_wrapper_replacement_rejected(self):
        self.model.model = torch.compile(fixture.Topology(), backend="eager")
        with self.assertRaisesRegex(adapter.life.base.TraceError, "binding changed"):
            adapter.CudaCompiledLease(diag, self.binding, self.store)

    def test_original_cpu_lease_still_accepts_empty_binding(self):
        types_by_path = adapter.admission.expected_stage_types(
            types.SimpleNamespace(SimpleAttentionalGain=fixture.Gain), types.SimpleNamespace(HannPooling2d=fixture.Hann))
        lease = adapter.admission.install_empty(diag, self.model, self.plan, self.store,
                    outer_type=fixture.Outer, cnn_type=fixture.Topology, stage_types=types_by_path)
        try:
            self.assertIs(type(lease), adapter.compiled.CompiledLease)
            self.assertEqual(len(lease.handles), 29)
        finally:
            lease.close()
        self.assertFalse(any(m._forward_hooks or m._forward_pre_hooks for m in self.model.modules()))


class CleanupTests(unittest.TestCase):
    """Identity-ownership cleanup fixtures, NOT compiler or worker attestations."""
    def request(self, *, old_compiler=False, adopted=False):
        model, other = object(), object()
        own = types.SimpleNamespace(model=model, revoked=False)
        unrelated = types.SimpleNamespace(model=other, revoked=False)
        revoked = []
        old_worker = types.SimpleNamespace(model=model)
        new_worker = types.SimpleNamespace(model=model)
        other_worker = types.SimpleNamespace(model=other)
        diag_fixture = types.SimpleNamespace(
            _ISSUED_COMPILER_LIFECYCLES={id(model): own, id(other): unrelated},
            _ISSUED_FORMAL40_ATTESTATIONS={id(x): x for x in (old_worker, new_worker, other_worker)},
            _revoke_attestation=lambda a: revoked.append(id(a)))
        request = object.__new__(adapter.ProductionRequest)
        request.diag, request.model = diag_fixture, model
        request.compilers_before = frozenset((id(own), id(unrelated))) if old_compiler else frozenset((id(unrelated),))
        request.issued_before = frozenset((id(old_worker), id(other_worker)))
        closed = []
        request.lease = types.SimpleNamespace(close=lambda: closed.append(True)) if adopted else None
        return request, own, unrelated, old_worker, new_worker, other_worker, revoked, closed

    def test_failure_before_adoption_revokes_only_new_owned_identities(self):
        req, own, other, old_worker, new_worker, other_worker, revoked, closed = self.request()
        req.close()
        self.assertTrue(own.revoked)
        self.assertFalse(other.revoked)
        self.assertEqual(revoked, [id(new_worker)])
        self.assertEqual(closed, [])

    def test_preexisting_compiler_is_not_revoked(self):
        req, own, other, *_ = self.request(old_compiler=True)
        req.close()
        self.assertFalse(own.revoked)
        self.assertFalse(other.revoked)

    def test_adopted_lease_is_closed_on_failure(self):
        req, own, other, old_worker, new_worker, other_worker, revoked, closed = self.request(adopted=True)
        req.close()
        self.assertEqual(closed, [True])
        self.assertTrue(own.revoked)
        self.assertEqual(revoked, [id(new_worker)])

    def test_preload_failure_does_not_revoke_other_models(self):
        req, own, other, old_worker, new_worker, other_worker, revoked, closed = self.request()
        req.model = None
        req.close()
        self.assertFalse(own.revoked)
        self.assertFalse(other.revoked)
        self.assertEqual(revoked, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

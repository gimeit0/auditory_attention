"""Portable synthetic 42-position admission tests; no real checkpoint/load."""
import ast
from dataclasses import replace
from pathlib import Path
import tempfile
import types
import unittest

import torch
import admission as candidate
import probe_cpu

ROOT = Path(__file__).resolve().parents[4]
DIAG = candidate.bridge.load_v19(ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v19/diagnose_batch_invariance.py")
FREEZE = ROOT / "docs/superpowers/evidence/v18-deployment-artifacts/input_freeze.json"


class Gain(torch.nn.Identity):
    pass


class Hann(torch.nn.Identity):
    pass


class Topology(torch.nn.Module):
    """Matching names and shared modules only; NOT the actual architecture."""
    def __init__(self):
        super().__init__()
        self.model_dict = torch.nn.ModuleDict({"norm_coch_rep": torch.nn.LayerNorm(2)})
        for i in range(7):
            self.model_dict.update({f"attn{i}": Gain(), f"conv_block_{i}": torch.nn.Sequential(torch.nn.Identity()),
                                    f"hann_pool_{i}": Hann()})
        self.model_dict["attnfc"] = Gain()
        self.fullyconnected = torch.nn.Linear(2, 2)
        self.relufc = torch.nn.ReLU()
        self.dropout = torch.nn.Dropout()
        self.classification = torch.nn.Linear(2, 2)

    def forward(self, *args):
        raise AssertionError("no forward in registration-only tests")


class Outer(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.model = torch.compile(Topology(), backend="eager")
        self.eval().requires_grad_(False)

    def forward(self, *args):
        raise AssertionError("outer forward must not execute")


class AdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.plan_raw = candidate.PLAN_PATH.read_bytes()
        cls.freeze_raw = FREEZE.read_bytes()
        cls.stage_types = candidate.expected_stage_types(types.SimpleNamespace(SimpleAttentionalGain=Gain),
                                                         types.SimpleNamespace(HannPooling2d=Hann))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="real-registration-local-")
        self.addCleanup(self.temporary.cleanup)
        self.store = candidate.life.capture.CaptureStore(Path(self.temporary.name) / "captures", total_bytes=1)
        self.addCleanup(self.store.close)
        self.model = Outer()
        self.plan = candidate.plan_documents(self.plan_raw, self.freeze_raw, "B2")

    def install(self, **kwargs):
        options = dict(outer_type=Outer, cnn_type=Topology, stage_types=self.stage_types)
        options.update(kwargs)
        lease = candidate.install_empty(DIAG, self.model, self.plan, self.store, **options)
        self.addCleanup(lease.close)
        return lease

    def test_both_cells_keep_original_targets_and_sequence(self):
        for cell, ids in (("A2", (9000, 4126)), ("B2", (1428, 2698))):
            plan = candidate.plan_documents(self.plan_raw, self.freeze_raw, cell)
            self.assertEqual(plan.targets, ids)
            self.assertEqual(len(plan.stages), 42)
            self.assertEqual(len(plan.schedule()), 34)
            self.assertEqual(plan.batch_sizes, (16, 1))

    def test_exact_42_positions_29_actual_callbacks_no_compiler_issue(self):
        lease = self.install()
        self.assertIs(type(lease), candidate.compiled.CompiledLease)
        self.assertEqual(len(lease.handles), 29)
        self.assertEqual(len(lease.binding.modules), 27)
        self.assertIsNone(lease.compiler)
        self.assertIsNone(lease.context)
        self.assertEqual(lease.records, [])
        self.assertEqual(self.store.used_bytes, 0)
        self.assertFalse(DIAG._ISSUED_FORMAL40_ATTESTATIONS)

    def test_install_remove_keeps_state_rng_runtime(self):
        base = candidate.stream.base
        before = base.model_state(self.model), base.rng_state(), base.runtime_state()
        lease = self.install()
        lease.close()
        self.assertEqual(before, (base.model_state(self.model), base.rng_state(), base.runtime_state()))
        self.assertTrue(all(not m._forward_hooks and not m._forward_pre_hooks for m in self.model.modules()))
        self.assertEqual(list(self.store.root.iterdir()), [])

    def test_empty_admission_cannot_forward_without_worker(self):
        self.install()
        with self.assertRaisesRegex(candidate.life.LifecycleError, "outside its active lease"):
            self.model(None, None, None)
        self.assertEqual(self.store.used_bytes, 0)

    def test_plan_bytes_changed_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "plan bytes"):
            candidate.plan_documents(self.plan_raw + b"\n", self.freeze_raw, "B2")

    def test_freeze_bytes_changed_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "freeze bytes"):
            candidate.plan_documents(self.plan_raw, self.freeze_raw + b"\n", "B2")

    def test_unknown_cell_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "unknown diagnostic cell"):
            candidate.plan_documents(self.plan_raw, self.freeze_raw, "B1")

    def test_partial_plan_rejected(self):
        self.plan = replace(self.plan, stages=self.plan.stages[:-1])
        with self.assertRaisesRegex(RuntimeError, "42-position"):
            self.install()

    def test_missing_stage_type_rejected(self):
        types = dict(self.stage_types)
        types.pop("classification")
        with self.assertRaisesRegex(RuntimeError, "27-module"):
            self.install(stage_types=types)

    def test_incorrect_stage_class_rejected(self):
        self.model.model._orig_mod.classification = torch.nn.Identity()
        with self.assertRaisesRegex(RuntimeError, "stage class"):
            self.install()

    def test_wrong_outer_class_rejected(self):
        with self.assertRaises(candidate.stream.base.TraceError):
            self.install(outer_type=Topology)

    def test_wrong_inner_class_rejected(self):
        with self.assertRaises(candidate.stream.base.TraceError):
            self.install(cnn_type=Outer)

    def test_model_training_rejected(self):
        self.model.train()
        with self.assertRaisesRegex(candidate.stream.base.TraceError, "eval mode"):
            self.install()

    def test_unfrozen_parameters_rejected(self):
        self.model.requires_grad_(True)
        with self.assertRaisesRegex(candidate.stream.base.TraceError, "frozen"):
            self.install()

    def test_existing_hook_preserved_on_rejection(self):
        module = self.model.model._orig_mod.classification
        handle = module.register_forward_hook(lambda *_: None)
        self.addCleanup(handle.remove)
        with self.assertRaisesRegex(candidate.life.LifecycleError, "existing forward hooks"):
            self.install()
        self.assertIn(handle.id, module._forward_hooks)

    def test_binding_replacement_rejected(self):
        lease = self.install()
        self.model.model._orig_mod.classification = torch.nn.Linear(2, 2)
        with self.assertRaises((candidate.life.LifecycleError, candidate.stream.base.TraceError)):
            lease.check()

    def test_forward_handle_replacement_rejected(self):
        lease = self.install()
        lease.handles[1].remove()
        with self.assertRaisesRegex(candidate.life.LifecycleError, "hook identity"):
            lease.check()

    def test_fabricated_capability_rejected_before_load(self):
        with self.assertRaisesRegex(RuntimeError, "original production frozen capability"):
            candidate.run_real_cpu(DIAG, {"_frozen_context_capability": types.SimpleNamespace(trust_domain="production")},
                                   "B2", Path(self.temporary.name))

    def test_unissued_diagnostic_module_rejected(self):
        with self.assertRaisesRegex(candidate.bridge.BridgeError, "not issued"):
            candidate.require_real_context(types.SimpleNamespace(), {})

    def test_original_cuda_gate_and_helpers_not_replaced(self):
        candidate.bridge._require_module(DIAG)
        tree = ast.parse(Path(DIAG.__file__).read_bytes())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "prepare_formal40_worker")
        self.assertIn("production formal40 worker requires CUDA runtime", ast.unparse(function))
        source = ast.parse(Path(candidate.__file__).read_bytes())
        called = {n.func.attr for n in ast.walk(source) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertNotIn("prepare_formal40_worker", called)
        self.assertNotIn("trace_predict_batch", called)
        self.assertNotIn("run_trace_pass", called)
        self.assertNotIn("_issue_formal40_worker_attestation", called)

    def allocation(self):
        return {"SLURM_JOB_ID": "1234", "SLURM_CPUS_PER_TASK": "1", "SLURM_NTASKS": "1",
                "SLURM_NNODES": "1", "SLURM_MEM_PER_NODE": "4096", "SLURM_JOB_PARTITION": "TINY",
                "CUDA_VISIBLE_DEVICES": ""}

    def test_allocation_shape(self):
        probe_cpu.check_allocation(self.allocation(), "s2510040", "synthetic-compute-host")

    def test_login_node_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "compute allocation"):
            probe_cpu.check_allocation(self.allocation(), "s2510040", "hakusan1")

    def test_gpu_index_zero_is_not_no_gpu(self):
        env = self.allocation()
        env["SLURM_JOB_GPUS"] = "0"
        with self.assertRaisesRegex(RuntimeError, "compute allocation"):
            probe_cpu.check_allocation(env, "s2510040", "synthetic-compute-host")

    def test_wrong_cpu_memory_or_missing_job_rejected(self):
        for key, value in (("SLURM_CPUS_PER_TASK", "2"), ("SLURM_MEM_PER_NODE", "8192"), ("SLURM_JOB_ID", "")):
            env = self.allocation()
            env[key] = value
            with self.assertRaisesRegex(RuntimeError, "compute allocation"):
                probe_cpu.check_allocation(env, "s2510040", "synthetic-compute-host")


if __name__ == "__main__":
    unittest.main(verbosity=2)

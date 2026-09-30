"""Original v18 guards + pre-issued toy hooks. No production/GPU authority."""

import contextlib
import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import torch

import observer_lifecycle as life


bridge = life.bridge
WORKSPACE = Path(__file__).resolve().parents[4]
SOURCE = WORKSPACE / "same_bank_eval_2026_09_03_v4_numeric_diag_v19"
fixtures = bridge._load(SOURCE / "test_numeric_diag.py",
                       "453973e8948c12dcc924391ec9d1584497be79d3c5d60d3e1cff721c6d5c98bf",
                       "lifecycle_original_test_fixtures")
diag = bridge.load_v19(SOURCE / "diagnose_batch_invariance.py")
fixtures.diagnose = diag


class Toy(fixtures._Task4Model):
    def __init__(self, calls, *, fault=None):
        super().__init__(calls)
        self.stem = torch.nn.Identity()
        self.mix = torch.nn.Identity()
        self.head = torch.nn.Identity()
        self.fault = fault
        self.eval().requires_grad_(False)

    def forward(self, cue, scene, background):
        cue = self.stem(cue)
        scene = self.stem(scene)
        if self.fault != "missing":
            scene = self.mix(scene)
        if self.fault == "extra":
            scene = self.mix(scene)
        if self.fault == "rng":
            torch.rand(1)
        if self.fault == "input":
            scene.add_(1)
        if self.fault == "state":
            self.anchor.add_(1)
        if self.fault == "runtime":
            torch.backends.cudnn.benchmark = True
        value = super().forward(cue, scene, background)
        if self.fault == "endpoint":
            value = value + 1
        return self.head(value)


def plan(trials):
    ids = tuple(t.trial_id for t in trials)
    return life.base.Plan(ids, (ids[0], ids[28]),
                          (life.base.Stage("stem", "cue"), life.base.Stage("stem", "scene"),
                           life.base.Stage("mix", "scene"), life.base.Stage("head", "logits")))


@contextlib.contextmanager
def worker(cell="B2", *, observed=True, fault=None, plan_change=None, budget=1024**2):
    calls = []
    model = Toy(calls, fault=fault)
    evaluator = fixtures._Task4Evaluator(calls=calls, model_to_load=model)
    scene = fixtures._Task4SceneAPI()
    bank = fixtures._task4_bank(32)
    trials = fixtures._task4_trials(bank)
    with tempfile.TemporaryDirectory(prefix="lifecycle-cpu-test-") as temporary:
        with life.capture.CaptureStore(Path(temporary) / "captures", total_bytes=budget) as store:
            lease = None
            try:
                if observed:
                    p = plan(trials)
                    lease = life.ObservationLease(diag, model, p if plan_change is None else plan_change(p), store)
                    lease.install_before_issuance()
                with fixtures._task4_hermetic_worker_context(evaluator, scene) as context:
                    prepared = diag.prepare_formal40_worker(context, allow_cpu=True)
                    run = {**context, **prepared, "bank": bank, "clips_dir": Path("/clips"), "cell_id": cell,
                           "historical_scene_hashes": fixtures._task4_scene_hashes(bank),
                           "scratch_root": temporary, "cache_roots": {}}
                    yield run, trials, evaluator, scene, lease
            finally:
                if lease is not None:
                    lease.close()


def compact(result):
    bounds = {}
    for name in bridge.replay.BOUNDARIES:
        record = result.boundary_records[name] if name in bridge.replay.COARSE else result.boundary_records["derived"][name]
        bounds[name] = {"aggregate": bridge.replay._descriptor(record["aggregate"]),
                        "rows": [{"trial_id": r["trial_id"], **bridge.replay._descriptor(r)} for r in record["per_trial"]],
                        "batches": [bridge.replay._descriptor(g["post_content"]) for g in record["guards"]]}
    outputs = {name: {"dtype": v.dtype.str, "shape": list(v.shape), "sha256": bridge.digest(v.tobytes()),
                      "bytes_hex": v.tobytes().hex()} for name, v in result.outputs.items()}
    return {"batch_size": result.batch_size, "boundaries": bounds, "official_outputs": outputs,
            "runtime": bridge.replay.RUNTIME}


def expected_contract():
    cells = {}
    for cell in ("A2", "B2"):
        with worker(cell, observed=False) as (context, trials, evaluator, scene, _):
            passes = {p: compact(diag.run_trace_pass(context, trials, p, size, cell == "A2", Path(context["scratch_root"])))
                      for p, size in (("pass1", 16), ("pass2", 1))}
            assert evaluator.calls.count("model") == 34
        cells[cell] = {"autocast_enabled": cell == "A2", "passes": passes}
    replay = bridge.replay
    return {"schema_version": 1, "scope": "parent_array_content_only", "parent_job_id": replay.JOB,
            "evaluation_role": replay.ROLE, "production_authority": False,
            "parent_terminal_sha256": replay.TERMINAL_SHA, "parent_inventory_sha256": replay.INVENTORY_SHA,
            "parent_freeze_sha256": replay.FREEZE_SHA, "plan_sha256": replay.PLAN_SHA,
            "trials": [{"ordinal": t.ordinal, "trial_id": t.trial_id, "bank_row_index": t.bank_row_index,
                        "identity": dict(t.identity)} for t in trials], "cells": cells}


class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.contract = expected_contract()
        cls.complete_runs = []

    def gate(self, context, trials, cell="B2", contract=None):
        wire = bridge.replay.canonical(self.contract if contract is None else contract)
        return bridge.BaselineBridge(diag, context, trials, wire, bridge.digest(wire), cell, hermetic_test=True)

    def test_original_guards_accept_preissued_observer_both_cells(self):
        for cell in ("A2", "B2"):
            with self.subTest(cell=cell), worker(cell) as (context, trials, evaluator, scene, lease):
                gate = self.gate(context, trials, cell)
                result = life.run_observed(gate, lease)
                self.assertEqual(result["status"], "HERMETIC_OBSERVER_LIFECYCLE_PASS")
                self.assertEqual(result["batches"], 34)
                self.assertEqual(result["stage_invocations"], 136)
                self.assertEqual(result["capture_records"], 16)
                self.assertEqual(len(evaluator.load_calls), 1)
                self.assertEqual(sum(type(c) is tuple and c[0] == "configure_runtime" for c in evaluator.calls), 1)
                self.assertEqual(evaluator.calls.count("model"), 34)
                self.assertEqual([len(c[0]) for c in scene.raw_calls], [16, 16] + [1] * 32)
                self.assertEqual([len(c[0]) for c in scene.cue_calls], [16, 16] + [1] * 32)
                self.assertIsNone(life._ACTIVE.get())
                self.assertTrue(lease.closed)
                self.assertTrue(all(not m._forward_hooks and not m._forward_pre_hooks for m in gate.model.modules()))
                self.assertIn(id(gate.attestation), diag._REVOKED_FORMAL40_ATTESTATIONS)
                self.assertFalse(torch.cuda.is_initialized())
                self.complete_runs.append({"result": result, "load_calls": len(evaluator.load_calls),
                                           "forward_calls": evaluator.calls.count("model"),
                                           "hooks_removed": True, "old_identity_revoked": True})

    def test_after_issuance_registration_rejected(self):
        with worker(observed=False) as (context, trials, evaluator, scene, _):
            with tempfile.TemporaryDirectory() as directory:
                with life.capture.CaptureStore(Path(directory) / "capture") as store:
                    lease = life.ObservationLease(diag, context["model"], plan(trials), store)
                    with self.assertRaisesRegex(life.LifecycleError, "before original issuance"):
                        lease.install_before_issuance()
            self.assertEqual(evaluator.calls.count("model"), 0)

    def test_hook_outside_active_lease_rejected(self):
        with worker() as (context, trials, evaluator, scene, lease):
            with self.assertRaisesRegex(life.LifecycleError, "outside its active lease"):
                context["model"](torch.zeros(16, 2, 4), torch.zeros(16, 2, 4), None)
            self.assertEqual(evaluator.calls.count("model"), 0)

    def test_removed_hook_rejected_by_original_guard(self):
        with worker() as (context, trials, evaluator, scene, lease):
            gate = self.gate(context, trials)
            lease.handles[1].remove()
            with gate._scope(), self.assertRaises(diag.DiagnosticError):
                gate._live("removed_observer_hook")
            self.assertEqual(evaluator.calls.count("model"), 0)

    def test_replaced_hook_rejected(self):
        with worker() as (context, trials, evaluator, scene, lease):
            gate = self.gate(context, trials)
            hooks = context["model"].stem._forward_hooks
            hooks[next(iter(hooks))] = lambda *_: None
            with self.assertRaisesRegex(life.LifecycleError, "hook identity"):
                life.run_observed(gate, lease)
            self.assertTrue(lease.failed and lease.closed)

    def test_wrong_stage_order_rejected(self):
        def change(p):
            return replace(p, stages=(p.stages[2], *p.stages[:2], p.stages[3]))
        with worker(plan_change=change) as (context, trials, evaluator, scene, lease):
            with self.assertRaisesRegex(life.LifecycleError, "stage order"):
                life.run_observed(self.gate(context, trials), lease)

    def test_missing_stage_rejected(self):
        with worker(fault="missing") as (context, trials, evaluator, scene, lease):
            with self.assertRaisesRegex(life.LifecycleError, "stage order"):
                life.run_observed(self.gate(context, trials), lease)

    def test_extra_stage_rejected(self):
        with worker(fault="extra") as (context, trials, evaluator, scene, lease):
            with self.assertRaisesRegex(life.LifecycleError, "stage order"):
                life.run_observed(self.gate(context, trials), lease)

    def test_rng_change_rejected_without_reset(self):
        with worker(fault="rng") as (context, trials, evaluator, scene, lease):
            before = torch.get_rng_state().clone()
            with self.assertRaisesRegex(life.LifecycleError, "RNG changed"):
                life.run_observed(self.gate(context, trials), lease)
            self.assertFalse(torch.equal(before, torch.get_rng_state()))
            self.assertEqual(evaluator.calls.count("model"), 1)

    def test_runtime_change_rejected(self):
        with worker(fault="runtime") as (context, trials, evaluator, scene, lease):
            # Original v18 readback rejects first, before our comparison.
            # Keep that stronger rejection instead of translating its error.
            with self.assertRaisesRegex(diag.DiagnosticError, "frozen runtime settings are not exact"):
                life.run_observed(self.gate(context, trials), lease)
            self.assertTrue(lease.failed and lease.closed)
            self.assertEqual(evaluator.calls.count("model"), 1)
            self.assertTrue(torch.backends.cudnn.benchmark)

    def test_input_change_rejected(self):
        with worker(fault="input") as (context, trials, evaluator, scene, lease):
            with self.assertRaisesRegex(life.LifecycleError, "inputs changed"):
                life.run_observed(self.gate(context, trials), lease)

    def test_registered_model_state_change_rejected(self):
        with worker(fault="state") as (context, trials, evaluator, scene, lease):
            with self.assertRaises(diag.DiagnosticError):
                life.run_observed(self.gate(context, trials), lease)
            self.assertTrue(lease.failed)

    def test_endpoint_change_rejected_before_pass2(self):
        with worker(fault="endpoint") as (context, trials, evaluator, scene, lease):
            with self.assertRaisesRegex(bridge.BridgeError, "boundary metadata"):
                life.run_observed(self.gate(context, trials), lease)
            self.assertEqual(evaluator.calls.count("model"), 2)

    def test_capture_budget_before_copy_and_cleanup(self):
        with worker(budget=1) as (context, trials, evaluator, scene, lease):
            with self.assertRaisesRegex(life.capture.CaptureError, "budget"):
                life.run_observed(self.gate(context, trials), lease)
            self.assertEqual(lease.store.refs, [])
            self.assertEqual(list(lease.store.root.iterdir()), [])
            self.assertTrue(lease.failed and lease.closed)
            self.assertIsNone(life._ACTIVE.get())

    def test_ledger_mutation_rejected(self):
        with worker() as (context, trials, evaluator, scene, lease):
            gate = self.gate(context, trials)
            lease.records.append({"forged": True})
            with self.assertRaisesRegex(life.LifecycleError, "ledger changed"):
                life.run_observed(gate, lease)

    def test_store_budget_mutation_rejected(self):
        with worker() as (context, trials, evaluator, scene, lease):
            gate = self.gate(context, trials)
            lease.store.total_bytes *= 2
            with self.assertRaisesRegex(life.LifecycleError, "configuration changed"):
                life.run_observed(gate, lease)

    def test_plan_mutation_rejected(self):
        with worker() as (context, trials, evaluator, scene, lease):
            gate = self.gate(context, trials)
            lease.plan = replace(lease.plan, targets=(lease.plan.trials[1],))
            with self.assertRaisesRegex(life.LifecycleError, "configuration changed"):
                life.run_observed(gate, lease)

    def test_changed_recorder_method_rejected(self):
        with worker() as (context, trials, evaluator, scene, lease):
            gate = self.gate(context, trials)
            with mock.patch.object(life.ObservationLease, "stage", lambda *_: None):
                with self.assertRaisesRegex(life.LifecycleError, "callable changed"):
                    life.run_observed(gate, lease)
            self.assertEqual(evaluator.calls.count("model"), 0)

    def test_original_function_replacement_rejected(self):
        with worker() as (context, trials, evaluator, scene, lease):
            gate = self.gate(context, trials)
            with mock.patch.object(diag, "run_trace_pass", lambda *_: None):
                with self.assertRaisesRegex(bridge.BridgeError, "function replaced"):
                    life.run_observed(gate, lease)
            self.assertEqual(evaluator.calls.count("model"), 0)

    def test_instance_recorder_method_rejected_and_revoked(self):
        with worker() as (context, trials, evaluator, scene, lease):
            gate = self.gate(context, trials)
            lease.stage = lambda *_: None
            with self.assertRaisesRegex(life.LifecycleError, "instance recorder method"):
                life.run_observed(gate, lease)
            self.assertTrue(lease.failed and lease.closed)
            self.assertIn(id(gate.attestation), diag._REVOKED_FORMAL40_ATTESTATIONS)

    def test_instance_capture_method_rejected(self):
        with worker() as (context, trials, evaluator, scene, lease):
            gate = self.gate(context, trials)
            lease.store.capture = lambda *_: None
            with self.assertRaisesRegex(life.LifecycleError, "instance capture method"):
                life.run_observed(gate, lease)

    def test_wrong_trial_schedule_rejected_before_execution(self):
        with worker() as (context, trials, evaluator, scene, lease):
            gate = self.gate(context, trials)
            lease.plan = replace(lease.plan, trials=tuple(reversed(lease.plan.trials)))
            with self.assertRaisesRegex(life.LifecycleError, "trial schedule differs"):
                life.run_observed(gate, lease)
            self.assertEqual(evaluator.calls.count("model"), 0)
            self.assertTrue(lease.closed)

    def test_failure_cannot_be_retried(self):
        with worker(budget=1) as (context, trials, evaluator, scene, lease):
            gate = self.gate(context, trials)
            with self.assertRaises(life.capture.CaptureError):
                life.run_observed(gate, lease)
            with self.assertRaisesRegex(life.LifecycleError, "single use"):
                life.run_observed(gate, lease)

    def test_nonhermetic_entry_rejected(self):
        with worker() as (context, trials, evaluator, scene, lease):
            gate = self.gate(context, trials)
            gate.hermetic_test = False
            with self.assertRaisesRegex(life.LifecycleError, "only original hermetic CPU"):
                life.run_observed(gate, lease)
            self.assertEqual(evaluator.calls.count("model"), 0)

    def test_contract_mismatch_does_not_use_existing_success(self):
        contract = copy.deepcopy(self.contract)
        contract["cells"]["B2"]["passes"]["pass1"]["boundaries"]["native_logits"]["rows"][0]["sha256"] = "0" * 64
        with worker() as (context, trials, evaluator, scene, lease):
            with self.assertRaisesRegex(bridge.BridgeError, "boundary metadata"):
                life.run_observed(self.gate(context, trials, contract=contract), lease)
            self.assertEqual(evaluator.calls.count("model"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

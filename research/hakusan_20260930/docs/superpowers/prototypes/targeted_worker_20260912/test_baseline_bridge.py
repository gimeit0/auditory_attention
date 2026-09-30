"""Execute ORIGINAL v18 guards/trace operators with its hermetic CPU fixture.

No claim of real formal40, A100, Inductor, or production provenance acceptance.
The synthetic expected bytes are generated separately using original v18 passes.
"""

import contextlib
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import torch

import baseline_bridge as bridge


WORKSPACE = Path(__file__).resolve().parents[4]
V18 = WORKSPACE / "same_bank_eval_2026_09_03_v4_numeric_diag_v18"
FIXTURE_SHA = "fd79b40b2251e79db88b5907ba9ca8e34fdcbac499b4d06e79622d44666ad1e0"
fixture = bridge._load(V18 / "test_numeric_diag.py", FIXTURE_SHA, "targeted_worker_original_fixtures")
diag = bridge.load_v18(V18 / "diagnose_batch_invariance.py")
fixture.diagnose = diag  # Test-only fixture points to our exact-byte v18 load.
replay = bridge.replay


@contextlib.contextmanager
def worker(cell="B2"):
    evaluator, scene = fixture._Task4Evaluator(), fixture._Task4SceneAPI()
    bank = fixture._task4_bank(32)
    trials = fixture._task4_trials(bank)
    with tempfile.TemporaryDirectory(prefix="baseline-bridge-test-") as temporary:
        with fixture._task4_hermetic_worker_context(evaluator, scene) as context:
            prepared = diag.prepare_formal40_worker(context, allow_cpu=True)
            run = {**context, **prepared, "bank": bank, "clips_dir": Path("/clips"), "cell_id": cell,
                   "historical_scene_hashes": fixture._task4_scene_hashes(bank),
                   "scratch_root": temporary, "cache_roots": {}}
            yield run, trials, evaluator, scene


def compact_pass(result):
    boundaries = {}
    for name in replay.BOUNDARIES:
        record = result.boundary_records[name] if name in replay.COARSE else result.boundary_records["derived"][name]
        boundaries[name] = {"aggregate": replay._descriptor(record["aggregate"]),
                            "rows": [{"trial_id": r["trial_id"], **replay._descriptor(r)} for r in record["per_trial"]],
                            "batches": [replay._descriptor(g["post_content"]) for g in record["guards"]]}
    outputs = {name: {"dtype": v.dtype.str, "shape": list(v.shape), "sha256": replay.sha(v.tobytes()),
                      "bytes_hex": v.tobytes().hex()} for name, v in result.outputs.items()}
    return {"batch_size": result.batch_size, "boundaries": boundaries, "official_outputs": outputs,
            "runtime": replay.RUNTIME}


def expected_contract():
    cells = {}
    for cell in ("A2", "B2"):
        with worker(cell) as (run, trials, evaluator, scene):
            passes = {p: compact_pass(diag.run_trace_pass(run, trials, p, size, cell == "A2", Path(run["scratch_root"])))
                      for p, size in (("pass1", 16), ("pass2", 1))}
            assert evaluator.calls.count("model") == 34
        cells[cell] = {"autocast_enabled": cell == "A2", "passes": passes}
    return {"schema_version": 1, "scope": "parent_array_content_only", "parent_job_id": replay.JOB,
            "evaluation_role": replay.ROLE, "production_authority": False,
            "parent_terminal_sha256": replay.TERMINAL_SHA, "parent_inventory_sha256": replay.INVENTORY_SHA,
            "parent_freeze_sha256": replay.FREEZE_SHA, "plan_sha256": replay.PLAN_SHA,
            "trials": [{"ordinal": t.ordinal, "trial_id": t.trial_id, "bank_row_index": t.bank_row_index,
                        "identity": dict(t.identity)} for t in trials], "cells": cells}


class BaselineBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.contract = expected_contract()
        cls.wire = replay.canonical(cls.contract)
        cls.sha = replay.sha(cls.wire)
        cls.complete_runs = []

    def make(self, context, trials, cell="B2", *, contract=None):
        wire = self.wire if contract is None else replay.canonical(contract)
        return bridge.BaselineBridge(diag, context, trials, wire, replay.sha(wire), cell, hermetic_test=True)

    def test_original_guarded_trace_and_matcher_both_cells(self):
        for cell in ("A2", "B2"):
            with self.subTest(cell=cell), worker(cell) as (context, trials, evaluator, scene):
                session = self.make(context, trials, cell)
                result = session.run()
                self.assertEqual(result["status"], "HERMETIC_V18_BASELINE_BRIDGE_PASS")
                self.assertEqual(evaluator.calls.count("model"), 34)
                self.assertEqual(len(evaluator.load_calls), 1)
                self.assertEqual(sum(type(c) is tuple and c[0] == "configure_runtime" for c in evaluator.calls), 1)
                self.assertEqual([len(c[0]) for c in scene.raw_calls], [16, 16] + [1] * 32)
                self.assertEqual([len(c[0]) for c in scene.cue_calls], [16, 16] + [1] * 32)
                self.assertEqual(result["replay"]["batches"], 34)
                self.assertEqual(result["replay"]["status"], "HERMETIC_ARRAY_SCHEDULE_MATCH")
                self.assertIsNone(result["replay"]["parent_job_id"])
                self.assertEqual(result["original_guard_domain"], "hermetic-test")
                self.assertFalse(result["production_execution_authority_verified"])
                self.assertFalse(result["real_model_validation"])
                self.assertEqual(result["new_hooks_installed"], 0)
                self.assertFalse(torch.cuda.is_initialized())
                self.complete_runs.append({"result": result, "load_calls": len(evaluator.load_calls),
                                           "forward_calls": evaluator.calls.count("model"),
                                           "raw_batch_sizes": [len(c[0]) for c in scene.raw_calls],
                                           "cue_batch_sizes": [len(c[0]) for c in scene.cue_calls]})

    def test_test_evidence_cannot_enter_production_path(self):
        with worker() as (context, trials, evaluator, scene):
            with self.assertRaisesRegex(bridge.BridgeError, "reviewed Job"):
                bridge.BaselineBridge(diag, context, trials, self.wire, self.sha, "B2")
            self.assertEqual(evaluator.calls.count("model"), 0)

    def test_real_contract_does_not_accept_toy_trials(self):
        path = WORKSPACE / "docs/superpowers/evidence/parent-replay-local-20260911T155226Z-rcw6ytm5/PARENT_REPLAY_CONTRACT.json"
        wire = path.read_bytes()
        with worker() as (context, trials, evaluator, scene):
            with self.assertRaisesRegex(bridge.BridgeError, "trial identities"):
                bridge.BaselineBridge(diag, context, trials, wire, bridge.PARENT_SHA, "B2")
            self.assertEqual(evaluator.calls.count("model"), 0)

    def test_fake_module_rejected(self):
        with worker() as (context, trials, evaluator, scene):
            with self.assertRaisesRegex(bridge.BridgeError, "pinned loader"):
                bridge.BaselineBridge(object(), context, trials, self.wire, self.sha, "B2", hermetic_test=True)

    def test_pinned_loader_rejects_modified_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "diagnose.py"
            path.write_bytes((V18 / "diagnose_batch_invariance.py").read_bytes() + b"\n")
            with self.assertRaisesRegex(bridge.BridgeError, "SHA"):
                bridge.load_v18(path)

    def test_no_attestation_or_structural_copy(self):
        with worker() as (context, trials, evaluator, scene):
            for fake in (None, {"status": "PASS"}):
                candidate = {**context, "_formal40_worker_attestation": fake}
                with self.assertRaisesRegex(bridge.BridgeError, "attestation required"):
                    self.make(candidate, trials)

    def test_trial_bank_row_identity_not_just_id(self):
        with worker() as (context, trials, evaluator, scene):
            changed = list(trials)
            changed[0] = diag.TrialSpec(0, trials[0].trial_id, trials[0].bank_row_index + 1, trials[0].identity)
            with self.assertRaisesRegex(bridge.BridgeError, "trial identities"):
                self.make(context, changed)

    def test_wrong_cell_label(self):
        with worker() as (context, trials, evaluator, scene):
            with self.assertRaisesRegex(bridge.BridgeError, "context cell"):
                self.make({**context, "cell_id": "A2"}, trials)

    def test_runtime_label_does_not_replace_live_readback(self):
        with worker() as (context, trials, evaluator, scene):
            session = self.make(context, trials)
            torch.set_float32_matmul_precision("medium")
            with self.assertRaises(diag.DiagnosticError):
                session.run()
            self.assertEqual(evaluator.calls.count("model"), 0)

    def test_exited_original_scene_scope_rejected(self):
        with worker() as (context, trials, evaluator, scene):
            session = self.make(context, trials)
        with self.assertRaises(diag.DiagnosticError):
            session.run()
        self.assertEqual(evaluator.calls.count("model"), 0)

    def test_model_state_change_rejected_by_original_guard(self):
        with worker() as (context, trials, evaluator, scene):
            session = self.make(context, trials)
            with torch.no_grad():
                context["model"].anchor.add_(1)
            with self.assertRaises(diag.DiagnosticError):
                session.run()
            self.assertEqual(evaluator.calls.count("model"), 0)

    def test_added_hook_rejected_by_original_guard(self):
        with worker() as (context, trials, evaluator, scene):
            session = self.make(context, trials)
            handle = context["model"].register_forward_hook(lambda module, args, output: None)
            try:
                with self.assertRaises(diag.DiagnosticError):
                    session.run()
                self.assertEqual(evaluator.calls.count("model"), 0)
            finally:
                handle.remove()

    def test_replaced_v18_function_rejected_before_call(self):
        with worker() as (context, trials, evaluator, scene):
            session = self.make(context, trials)
            with mock.patch.object(diag, "run_trace_pass", side_effect=AssertionError("must not run")):
                with self.assertRaisesRegex(bridge.BridgeError, "function replaced"):
                    session.run()

    def test_parent_difference_stops_before_pass2(self):
        contract = copy.deepcopy(self.contract)
        contract["cells"]["B2"]["passes"]["pass1"]["boundaries"]["native_logits"]["rows"][0]["sha256"] = "0" * 64
        with worker() as (context, trials, evaluator, scene):
            session = self.make(context, trials, contract=contract)
            with self.assertRaisesRegex(bridge.BridgeError, "boundary metadata"):
                session.run()
            self.assertEqual(evaluator.calls.count("model"), 2)
            self.assertIn(id(session.attestation), diag._REVOKED_FORMAL40_ATTESTATIONS)
            with self.assertRaisesRegex(bridge.BridgeError, "single use"):
                session.run()

    def test_matcher_rng_mutation_rejected_without_reset(self):
        with worker() as (context, trials, evaluator, scene):
            session = self.make(context, trials)
            original = session.gate.accept
            def corrupt(*args, **kwargs):
                original(*args, **kwargs)
                torch.rand(1)
            with mock.patch.object(session.gate, "accept", side_effect=corrupt):
                with self.assertRaisesRegex(bridge.BridgeError, "changed RNG"):
                    session.run()
            self.assertEqual(evaluator.calls.count("model"), 2)

    def test_matcher_payload_mutation_rejected_by_commitment(self):
        with worker() as (context, trials, evaluator, scene):
            session = self.make(context, trials)
            original = session.gate.accept
            def corrupt(*args, **kwargs):
                original(*args, **kwargs)
                args[3]["raw_scene"].flat[0] += 1
            with mock.patch.object(session.gate, "accept", side_effect=corrupt):
                with self.assertRaisesRegex(bridge.BridgeError, "commitment changed"):
                    session.run()
            self.assertEqual(evaluator.calls.count("model"), 2)

    def test_successful_bridge_single_use(self):
        with worker() as (context, trials, evaluator, scene):
            session = self.make(context, trials)
            session.run()
            with self.assertRaisesRegex(bridge.BridgeError, "single use"):
                session.run()
            self.assertEqual(evaluator.calls.count("model"), 34)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BaselineBridgeTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful() or bool(result.skipped))

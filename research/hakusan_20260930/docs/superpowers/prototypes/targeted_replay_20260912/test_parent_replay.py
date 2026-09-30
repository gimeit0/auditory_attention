"""Synthetic array tests. Fixture contracts are NOT scientific evidence."""

import copy
import json
import unittest

import numpy as np

import parent_replay as replay


def descriptor(array):
    return {"shape": list(array.shape), "dtype": array.dtype.str,
            "nbytes": array.nbytes, "sha256": replay.sha(array.tobytes(order="C"))}


def fixture():
    ids = list(range(100, 132))
    arrays, cells = {}, {}
    for cell in ("A2", "B2"):
        passes = {}
        for pass_id, size in (("pass1", 16), ("pass2", 1)):
            boundaries, values = {}, {}
            for index, name in enumerate(replay.BOUNDARIES):
                shape = (32, 2, 3) if name in replay.COARSE else (32,)
                dtype = "<f2" if cell == "A2" and name == "native_logits" else "<f4"
                if name == "pred_label":
                    dtype = "<i8"
                if name == "correct":
                    dtype = "|b1"
                array = np.arange(np.prod(shape), dtype="<f4").reshape(shape)
                array = ((array + index + (0.25 if pass_id == "pass2" else 0)) / 100).astype(dtype)
                if name == "pred_label":
                    array = np.arange(32, dtype="<i8")
                values[name] = array
                rows = [{"trial_id": trial, **descriptor(array[i:i + 1].reshape(shape[1:] or (1,)))}
                        for i, trial in enumerate(ids)]
                batches = [descriptor(array[start:start + size]) for start in range(0, 32, size)]
                boundaries[name] = {"aggregate": descriptor(array), "rows": rows,
                                    "batches": batches if name in replay.COARSE else []}
            official = {name: {k: v for k, v in descriptor(values[name]).items() if k != "nbytes"}
                        | {"bytes_hex": values[name].tobytes().hex()} for name in replay.OFFICIAL}
            passes[pass_id] = {"batch_size": size, "boundaries": boundaries,
                               "official_outputs": official, "runtime": replay.RUNTIME}
            arrays[cell, pass_id] = values
        cells[cell] = {"autocast_enabled": cell == "A2", "passes": passes}
    contract = {"schema_version": 1, "scope": "parent_array_content_only",
                "parent_job_id": replay.JOB, "evaluation_role": replay.ROLE,
                "parent_terminal_sha256": replay.TERMINAL_SHA,
                "parent_inventory_sha256": replay.INVENTORY_SHA,
                "parent_freeze_sha256": replay.FREEZE_SHA, "plan_sha256": replay.PLAN_SHA,
                "production_authority": False,
                "trials": [{"ordinal": i, "trial_id": trial} for i, trial in enumerate(ids)],
                "cells": cells}
    return contract, arrays


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract, cls.arrays = fixture()
        cls.wire = replay.canonical(cls.contract)
        cls.digest = replay.sha(cls.wire)

    def gate(self, cell="A2", contract=None):
        wire = self.wire if contract is None else replay.canonical(contract)
        return replay.ParentReplayGate(wire, replay.sha(wire), cell)

    def batch(self, cell="A2", pass_id="pass1", index=0):
        size = 16 if pass_id == "pass1" else 1
        start, stop = index * size, (index + 1) * size
        values = {name: array[start:stop].copy() for name, array in self.arrays[cell, pass_id].items()}
        return {"pass_id": pass_id, "batch_index": index,
                "trial_ids": list(range(100 + start, 100 + stop)), "boundaries": values,
                "official_outputs": {n: values[n].copy() for n in replay.OFFICIAL},
                "runtime": dict(replay.RUNTIME), "autocast_enabled": cell == "A2"}

    def fill(self, gate, cell="A2", *, transform=None):
        for pass_id, count in (("pass1", 2), ("pass2", 32)):
            for index in range(count):
                batch = self.batch(cell, pass_id, index)
                if transform:
                    transform(batch)
                gate.accept(**batch)

    def reject(self, batch):
        gate = self.gate()
        with self.assertRaises(replay.ReplayError):
            gate.accept(**batch)
        with self.assertRaisesRegex(replay.ReplayError, "closed"):
            gate.accept(**self.batch())
        with self.assertRaisesRegex(replay.ReplayError, "closed"):
            gate.finish()

    def test_complete_both_cells(self):
        for cell in ("A2", "B2"):
            gate = self.gate(cell)
            self.fill(gate, cell)
            result = gate.finish()
            self.assertEqual(result["batches"], 34)
            self.assertFalse(result["production_authority"])
            self.assertFalse(result["runtime_independently_attested"])
            self.assertFalse(result["parent_stride_verified"])

    def test_noncontiguous_logical_bytes(self):
        def strided(batch):
            for name, array in batch["boundaries"].items():
                storage = np.empty((*array.shape, 2), dtype=array.dtype)
                storage[..., 0] = array
                batch["boundaries"][name] = storage[..., 0]
        gate = self.gate()
        self.fill(gate, transform=strided)
        self.assertEqual(gate.finish()["status"], "PARENT_ARRAY_REPLAY_MATCH")

    def test_tiny_difference_is_not_tolerated(self):
        batch = self.batch()
        value = batch["boundaries"]["raw_scene"]
        value.flat[1] = np.nextafter(value.flat[1], np.float32(1))
        self.reject(batch)

    def test_shape_difference(self):
        batch = self.batch()
        batch["boundaries"]["raw_scene"] = batch["boundaries"]["raw_scene"].reshape(16, 6)
        self.reject(batch)

    def test_dtype_cast_is_rejected(self):
        batch = self.batch()
        batch["boundaries"]["native_logits"] = batch["boundaries"]["native_logits"].astype("<f4")
        self.reject(batch)

    def test_big_endian_rejected(self):
        batch = self.batch()
        batch["boundaries"]["raw_scene"] = batch["boundaries"]["raw_scene"].astype(">f4")
        self.reject(batch)

    def test_nonfinite_rejected(self):
        for invalid in (float("nan"), float("inf"), -float("inf")):
            batch = self.batch()
            batch["boundaries"]["raw_scene"].flat[0] = invalid
            self.reject(batch)

    def test_object_array_rejected(self):
        batch = self.batch()
        batch["boundaries"]["raw_scene"] = batch["boundaries"]["raw_scene"].astype(object)
        self.reject(batch)

    def test_custom_array_conversion_not_called(self):
        class Unsafe:
            def __array__(self, *args):
                raise AssertionError("must not invoke conversion")
        batch = self.batch()
        batch["boundaries"]["raw_scene"] = Unsafe()
        self.reject(batch)

    def test_budget_checked_before_hashing(self):
        array = np.zeros(10, dtype="<f4")
        with self.assertRaisesRegex(replay.ReplayError, "budget"):
            replay._array_digest(array, [10], "<f4", limit=1)

    def test_multiple_chunks_and_late_change(self):
        array = np.arange(700000, dtype="<f4")
        self.assertEqual(replay._array_digest(array, list(array.shape), "<f4"), descriptor(array)["sha256"])
        before = descriptor(array)["sha256"]
        array[-1] += 1
        self.assertNotEqual(replay._array_digest(array, list(array.shape), "<f4"), before)

    def test_signed_zero_is_not_equal(self):
        batch = self.batch()
        batch["boundaries"]["raw_scene"].flat[0] = np.float32(-0.0)
        self.reject(batch)

    def test_trial_order(self):
        batch = self.batch()
        batch["trial_ids"].reverse()
        self.reject(batch)

    def test_boolean_trial_or_batch_index_rejected(self):
        batch = self.batch()
        batch["batch_index"] = False
        self.reject(batch)
        batch = self.batch()
        batch["trial_ids"][0] = True
        self.reject(batch)

    def test_skip_batch(self):
        self.reject(self.batch(index=1))

    def test_skip_to_second_pass(self):
        self.reject(self.batch(pass_id="pass2"))

    def test_duplicate_batch(self):
        gate = self.gate()
        gate.accept(**self.batch())
        with self.assertRaisesRegex(replay.ReplayError, "order"):
            gate.accept(**self.batch())

    def test_missing_and_extra_boundary(self):
        for extra in (True, False):
            batch = self.batch()
            if extra:
                batch["boundaries"]["surprise"] = np.zeros(16)
            else:
                del batch["boundaries"]["correct"]
            self.reject(batch)

    def test_missing_and_extra_official(self):
        for extra in (True, False):
            batch = self.batch()
            if extra:
                batch["official_outputs"]["surprise"] = np.zeros(16)
            else:
                del batch["official_outputs"]["nll"]
            self.reject(batch)

    def test_actual_official_differs_despite_good_boundaries(self):
        batch = self.batch()
        batch["official_outputs"]["nll"][0] += 1
        self.reject(batch)

    def test_runtime_metadata_change(self):
        for field in replay.RUNTIME:
            batch = self.batch()
            old = batch["runtime"][field]
            batch["runtime"][field] = not old if type(old) is bool else "medium"
            self.reject(batch)

    def test_runtime_boolean_is_not_integer(self):
        batch = self.batch()
        batch["runtime"]["deterministic_algorithms"] = 1
        self.reject(batch)

    def test_autocast_flag(self):
        for value in (False, 1):
            batch = self.batch()
            batch["autocast_enabled"] = value
            self.reject(batch)

    def test_partial_finish_closes_gate(self):
        gate = self.gate()
        gate.accept(**self.batch())
        with self.assertRaisesRegex(replay.ReplayError, "incomplete"):
            gate.finish()
        with self.assertRaisesRegex(replay.ReplayError, "closed"):
            gate.accept(**self.batch(index=1))

    def test_extra_batch_after_complete(self):
        gate = self.gate()
        self.fill(gate)
        with self.assertRaisesRegex(replay.ReplayError, "extra"):
            gate.accept(**self.batch())

    def test_finished_gate_cannot_be_reused(self):
        gate = self.gate()
        self.fill(gate)
        gate.finish()
        with self.assertRaisesRegex(replay.ReplayError, "closed"):
            gate.finish()

    def test_incorrect_aggregate_detected(self):
        contract = copy.deepcopy(self.contract)
        contract["cells"]["A2"]["passes"]["pass1"]["boundaries"]["raw_scene"]["aggregate"]["sha256"] = "0" * 64
        gate = self.gate(contract=contract)
        gate.accept(**self.batch())
        with self.assertRaisesRegex(replay.ReplayError, "aggregate"):
            gate.accept(**self.batch(index=1))

    def test_incorrect_row_detected(self):
        contract = copy.deepcopy(self.contract)
        contract["cells"]["A2"]["passes"]["pass1"]["boundaries"]["raw_scene"]["rows"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(replay.ReplayError, "trial bytes"):
            self.gate(contract=contract).accept(**self.batch())

    def test_external_sha_required(self):
        with self.assertRaisesRegex(replay.ReplayError, "external"):
            replay.ParentReplayGate(self.wire, "0" * 64, "A2")

    def test_noncanonical_duplicate_keys_rejected(self):
        wire = self.wire.replace(b'{', b'{"schema_version":1,', 1)
        with self.assertRaisesRegex(replay.ReplayError, "noncanonical"):
            replay.ParentReplayGate(wire, replay.sha(wire), "A2")

    def test_missing_row_contract_rejected(self):
        contract = copy.deepcopy(self.contract)
        contract["cells"]["A2"]["passes"]["pass1"]["boundaries"]["raw_scene"]["rows"].pop()
        with self.assertRaises(replay.ReplayError):
            self.gate(contract=contract)

    def test_missing_guard_contract_rejected(self):
        contract = copy.deepcopy(self.contract)
        contract["cells"]["A2"]["passes"]["pass1"]["boundaries"]["raw_scene"]["batches"].pop()
        with self.assertRaises(replay.ReplayError):
            self.gate(contract=contract)

    def test_saved_array_match_is_only_partial(self):
        result = replay.verify_saved_array(self.wire, self.digest, "A2", "pass1", "native_logits",
                                           self.arrays["A2", "pass1"]["native_logits"])
        self.assertEqual(result["status"], "SAVED_ARRAY_MATCH_ONLY")
        self.assertFalse(result["full_replay_verified"])
        with self.assertRaisesRegex(replay.ReplayError, "incomplete"):
            self.gate().finish()

    def test_scalar_derived_row(self):
        value = self.arrays["A2", "pass1"]["nll"][0:1]
        result = replay.verify_saved_array(self.wire, self.digest, "A2", "pass1", "nll", value, trial_id=100)
        self.assertFalse(result["full_replay_verified"])

    def test_wrong_saved_pass_or_trial(self):
        value = self.arrays["A2", "pass1"]["raw_scene"][0]
        for pass_id, trial_id in (("pass2", 100), ("pass1", 101)):
            with self.assertRaises(replay.ReplayError):
                replay.verify_saved_array(self.wire, self.digest, "A2", pass_id, "raw_scene", value,
                                          trial_id=trial_id)

    def test_contract_is_private_copy(self):
        contract = json.loads(self.wire)
        gate = self.gate(contract=contract)
        contract["cells"].clear()
        self.fill(gate)
        self.assertEqual(gate.finish()["batches"], 34)


if __name__ == "__main__":
    unittest.main(verbosity=2)

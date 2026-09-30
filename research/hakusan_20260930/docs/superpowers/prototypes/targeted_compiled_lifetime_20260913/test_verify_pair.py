"""Offline verifier positives/negatives; no compiler-version mocking."""
import base64
import copy
import unittest
import verify_pair as verifier


def array_record(shape, dtype="<f4", byte=0):
    import math
    raw = bytes([byte]) * (math.prod(shape) * verifier.WIDTHS[dtype])
    return {**verifier.descriptor(raw, shape, dtype), "base64": base64.b64encode(raw).decode()}


def pair():
    ids = list(range(100, 132))
    stages = [{"module": a, "branch": b} for a, b in
              (("stem", "cue"), ("stem", "scene"), ("mix", "scene"), ("head", "logits"))]
    base = {"status": "HERMETIC_COMPILED_LIFETIME_PASS", "mode": "reference", "pid": 101,
            "python": "3.11.5", "torch": "2.1.1+cu118", "backend": "eager", "cell": "B2",
            "load_calls": 1, "forward_calls": 34, "complete_passes": 2, "stage_invocations": 0,
            "compiler_backend_entered": True, "original_guards_enabled": True,
            "original_compiler_authority": True, "hooks_removed": True, "attestation_revoked": True,
            "production_model_loaded": False, "cuda_initialized": False, "ready_for_gpu": False,
            "real_parent_replay_completed": False, "jobs_submitted": 0, "runtime": verifier.RUNTIME.copy(),
            "trials": [{"ordinal": i, "trial_id": trial, "bank_row_index": i, "identity": {"trial_id": trial}}
                       for i, trial in enumerate(ids)],
            "relative_plan": {"trials": ids, "targets": [100, 128], "batch_sizes": [16, 1], "stages": stages},
            "passes": [], "observer_records": [], "captures": []}
    for pass_id, size in (("pass1", 16), ("pass2", 1)):
        boundaries = {}
        for name in verifier.COARSE + verifier.DERIVED:
            shape = [32, 800] if name in ("native_logits", "log_probabilities") else [32, 2, 4] if name in verifier.COARSE else [32]
            dtype = "<i8" if name == "pred_label" else "|b1" if name == "correct" else "<f4"
            item = array_record(shape, dtype)
            raw = verifier.array_bytes(item)
            width = len(raw) // 32
            item["rows"] = [{"trial_id": trial, **verifier.descriptor(raw[i * width:(i + 1) * width], shape[1:] or [1], dtype)}
                            for i, trial in enumerate(ids)]
            item["batches"] = [verifier.descriptor(raw[i * width:(i + size) * width], [size] + shape[1:], dtype)
                               for i in range(0, 32, size)] if name in verifier.COARSE else []
            boundaries[name] = item
        base["passes"].append({"pass_id": pass_id, "batch_size": size, "trial_ids": ids,
                               "runtime": verifier.RUNTIME.copy(), "autocast_enabled": False,
                               "state_rng_unchanged": True, "boundaries": boundaries,
                               "official_outputs": {name: array_record([32], "<i8" if name == "pred_label" else "<f4")
                                                    for name in verifier.OFFICIAL}})
    observed = copy.deepcopy(base)
    observed.update({"mode": "observed", "pid": 102, "stage_invocations": 136})
    for p, result in enumerate(observed["passes"]):
        size = result["batch_size"]
        for offset in range(0, 32, size):
            batch = offset // size
            group = ids[offset:offset + size]
            record = {"pass_id": result["pass_id"], "batch_index": batch, "trials": group,
                      "inputs": [result["boundaries"][name]["batches"][batch] for name in ("cue_features", "scene_features")],
                      "logits": result["boundaries"]["native_logits"]["batches"][batch], "captures": []}
            for stage in range(4):
                for trial in group:
                    if trial not in (100, 128):
                        continue
                    name = ("cue_features", "scene_features", "scene_features", "native_logits")[stage]
                    shape = result["boundaries"][name]["shape"][1:]
                    arr = array_record(shape)
                    ref = {"ordinal": len(observed["captures"]), "key": [result["pass_id"], batch, stage, trial],
                           "dtype": "torch.float32", "shape": shape, "size": arr["nbytes"], "sha256": arr["sha256"]}
                    record["captures"].append(ref)
                    observed["captures"].append({"record": ref, "base64": arr["base64"]})
            observed["observer_records"].append(record)
    return base, observed


class PairTests(unittest.TestCase):
    def setUp(self):
        self.reference, self.observed = pair()

    def reject(self):
        with self.assertRaises((ValueError, KeyError, TypeError)):
            verifier.verify_pair(self.reference, self.observed)

    def test_valid_complete_pair(self):
        before = copy.deepcopy((self.reference, self.observed))
        result = verifier.verify_pair(self.reference, self.observed)
        self.assertEqual(result["status"], "SYNTHETIC_COMPILED_COLD_PAIR_PASS")
        self.assertEqual(before, (self.reference, self.observed))

    def test_same_process_rejected(self):
        self.observed["pid"] = 101
        self.reject()

    def test_changed_endpoint_even_with_new_digest_rejected(self):
        self.observed["passes"][0]["official_outputs"]["nll"] = array_record([32], byte=1)
        self.reject()

    def test_corrupt_payload_rejected(self):
        self.observed["passes"][0]["boundaries"]["nll"]["base64"] = "AAAA"
        self.reject()

    def test_missing_pass_rejected(self):
        self.observed["passes"].pop()
        self.reject()

    def test_changed_batching_rejected(self):
        self.observed["passes"][1]["batch_size"] = 16
        self.reject()

    def test_wrong_trial_rejected(self):
        self.observed["trials"].reverse()
        self.reject()

    def test_missing_stage_rejected(self):
        self.observed["observer_records"].pop()
        self.reject()

    def test_relabelled_capture_rejected(self):
        self.observed["captures"][0]["record"]["key"][2] = 3
        self.reject()

    def test_capture_corruption_rejected(self):
        self.observed["captures"][0]["base64"] = "AAAA"
        self.reject()

    def test_source_gate_claim_missing_rejected(self):
        self.observed["original_compiler_authority"] = False
        self.reject()

    def test_changed_runtime_rejected(self):
        self.observed["runtime"]["float32_matmul_precision"] = "medium"
        self.reject()

    def test_production_claim_rejected(self):
        self.observed["ready_for_gpu"] = True
        self.reject()

    def test_cleanup_missing_rejected(self):
        self.observed["attestation_revoked"] = False
        self.reject()

    def test_reference_hook_artifacts_rejected(self):
        self.reference["observer_records"] = [self.observed["observer_records"][0]]
        self.reject()

    def test_null_record_rejected(self):
        self.observed = None
        self.reject()


if __name__ == "__main__":
    unittest.main(verbosity=2)

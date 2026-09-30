"""Synthetic 42-stage ledger/files only: no model, CUDA or compiler execution."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import verify_results as verify  # noqa: E402
import process_runner as process  # noqa: E402


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="candidate-capture-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / "captures").mkdir(mode=0o700)
        ids = list(range(32))
        stages = [{"module": f"layer{i}", "branch": "synthetic"} for i in range(42)]
        self.plan = {"post_hook_stages": stages, "targets": {"B2": [{"trial": {"trial_id": i}} for i in (4, 20)]}}
        self.parent = {"trials": [{"trial_id": i} for i in ids], "cells": {"B2": {"passes": {}}}}
        records, refs = [], []
        for pass_id, size in (("pass1", 16), ("pass2", 1)):
            boundaries = {name: {"batches": []} for name in ("cue_features", "scene_features", "native_logits")}
            for offset in range(0, 32, size):
                batch, trials = offset // size, ids[offset:offset + size]
                desc = {"scope": "SYNTHETIC_ENDPOINT", "batch": batch, "size": size}
                captures = []
                for index in range(42):
                    for trial in trials:
                        if trial not in (4, 20):
                            continue
                        raw = np.array([index, trial], dtype="<f4").tobytes()
                        ref = {"ordinal": len(refs), "store_id": "a" * 32, "key": [pass_id, batch, index, trial],
                               "dtype": "torch.float32", "shape": [2], "stride": [1], "size": len(raw),
                               "sha256": hashlib.sha256(raw).hexdigest()}
                        with (self.root / "captures" / f"{len(refs):08d}.bin").open("xb") as stream:
                            stream.write(raw)
                        (self.root / "captures" / f"{len(refs):08d}.bin").chmod(0o600)
                        refs.append(ref)
                        captures.append(ref)
                records.append({"pass_id": pass_id, "batch_index": batch, "trials": trials,
                                "inputs": [desc, desc], "logits": desc, "captures": captures})
                for boundary in boundaries.values():
                    boundary["batches"].append(desc)
            self.parent["cells"]["B2"]["passes"][pass_id] = {"boundaries": boundaries}
        self.observer = {"plan": {"trials": ids, "targets": [4, 20], "batch_sizes": [16, 1],
                                 "stages": [{**s, "module": "model._orig_mod." + s["module"]} for s in stages]},
                         "records": records, "refs": refs}
        self.seal()

    def seal(self):
        self.observer["ledger_sha256"] = hashlib.sha256(verify.archive.canonical(self.observer["records"])).hexdigest()

    def check(self):
        return verify.verify_captures(self.root, self.observer, self.parent, self.plan)

    def test_complete_168_files_with_compiled_prefix(self):
        self.assertEqual(self.check(), {"capture_records": 168, "capture_bytes": 1344})
        self.assertEqual(len(verify.inventory(self.root)["files"]), 168)

    def test_unprefixed_plan_rejected(self):
        self.observer["plan"]["stages"] = self.plan["post_hook_stages"]
        with self.assertRaisesRegex(RuntimeError, "plan differs"):
            self.check()

    def test_corrupt_file_rejected(self):
        with (self.root / "captures/00000000.bin").open("r+b") as out:
            out.write(b"xxxx")
        with self.assertRaisesRegex(RuntimeError, "bytes differ"):
            self.check()

    def test_nonfinite_even_with_matching_new_digest_rejected(self):
        raw = np.array([np.nan, 1], dtype="<f4").tobytes()
        (self.root / "captures/00000000.bin").write_bytes(raw)
        self.observer["refs"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
        self.seal()
        with self.assertRaisesRegex(RuntimeError, "nonfinite"):
            self.check()

    def test_missing_file_rejected(self):
        (self.root / "captures/00000000.bin").unlink()
        with self.assertRaises(FileNotFoundError):
            self.check()

    def test_reordered_capture_rejected(self):
        selected = self.observer["records"][0]["captures"]
        selected[0], selected[1] = selected[1], selected[0]
        self.seal()
        with self.assertRaisesRegex(RuntimeError, "event order"):
            self.check()

    def test_incomplete_schedule_rejected(self):
        self.observer["records"].pop()
        self.seal()
        with self.assertRaises(RuntimeError):
            self.check()

    def test_ref_ledger_divergence_rejected(self):
        self.observer["refs"] = copy.deepcopy(self.observer["refs"])
        self.observer["refs"][0]["key"][3] = 31
        with self.assertRaisesRegex(RuntimeError, "coverage"):
            self.check()

    def test_oversized_capture_rejected_before_read(self):
        self.observer["refs"][0]["shape"] = [134217729]
        self.observer["refs"][0]["size"] = 134217729 * 4
        self.seal()
        with self.assertRaisesRegex(RuntimeError, "byte size"):
            self.check()

    def test_symlink_file_rejected(self):
        path = self.root / "captures/00000000.bin"
        path.rename(self.root / "retained.bin")
        path.symlink_to(self.root / "retained.bin")
        with self.assertRaises(RuntimeError):
            verify.inventory(self.root)
        with self.assertRaises(OSError):
            self.check()

    def test_non_private_file_rejected(self):
        (self.root / "captures/00000000.bin").chmod(0o644)
        with self.assertRaises(RuntimeError):
            verify.inventory(self.root)

    def test_empty_success_document_cannot_be_verified(self):
        process.write_once(self.root / "CHILD.json", {"status": "GPU_CHILD_CANDIDATE_COMPLETE"})
        with self.assertRaisesRegex(RuntimeError, "identity/completion"):
            verify.verify_child(self.root, {"pid": os.getpid()}, role="observed", job="123",
                                package_sha="b" * 64, nonce="c" * 32, diag=None, parent=self.parent)

    def test_partial_failure_ledger_is_not_a_complete_capture(self):
        value = json.loads(json.dumps(self.observer))
        value["refs"] = value["refs"][:1]
        self.observer = value
        with self.assertRaisesRegex(RuntimeError, "complete real capture"):
            self.check()


if __name__ == "__main__":
    unittest.main()


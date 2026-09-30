"""Local-only component acceptance; writes a NEW evidence directory.

No connection, model import/forward, checkpoint read, GPU job or parent edit.
Synthetic full replay + partial real saved-array checks are reported separately.
"""

import datetime
import io
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[3]
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402
import parent_replay as replay  # noqa: E402


def write_new(path, data):
    with path.open("xb") as handle:
        handle.write(data)


def real_checks(wire, digest, root, inventory):
    contract = json.loads(wire)
    records = {f["relative_path"]: f for f in inventory["files"]}
    matches, negatives = [], []

    def load(relative):
        path = root / relative
        record = records[relative]
        replay.require(path.is_file() and not path.is_symlink() and record["size"] <= 16 * replay.MIB,
                       "saved-array source type/size differs")
        raw = path.read_bytes()
        replay.require(len(raw) == record["size"] and replay.sha(raw) == record["sha256"],
                       "saved-array source SHA differs")
        array = np.load(io.BytesIO(raw), allow_pickle=False)
        replay.require(type(array) is np.ndarray and array.nbytes <= 16 * replay.MIB,
                       "saved-array payload type/size differs")
        return array

    def check(cell, pass_id, boundary, value, trial_id=None, source=None):
        result = replay.verify_saved_array(wire, digest, cell, pass_id, boundary, value, trial_id=trial_id)
        matches.append({**result, "source": source})

    def reject(label, callback):
        try:
            callback()
        except replay.ReplayError as error:
            negatives.append({"check": label, "status": "REJECTED_AS_EXPECTED", "message": str(error)})
        else:
            raise AssertionError(f"negative control unexpectedly accepted: {label}")

    for cell in ("A2", "B2"):
        for pass_id, number in (("pass1", 1), ("pass2", 2)):
            relative = f"cells/{cell}/LOGITS_PASS{number}.npy"
            logits = load(relative)
            check(cell, pass_id, "native_logits", logits, source=relative)
            for index, trial in enumerate(contract["trials"]):
                check(cell, pass_id, "native_logits", logits[index], trial["trial_id"], relative)
            mutated = logits.copy()
            mutated[-1, -1] = np.nextafter(mutated[-1, -1], np.array(np.inf, dtype=mutated.dtype))
            reject(f"{cell}/{pass_id}/last_trial_one_ULP",
                   lambda: replay.verify_saved_array(wire, digest, cell, pass_id, "native_logits", mutated))
            other_pass = "pass2" if pass_id == "pass1" else "pass1"
            reject(f"{cell}/{pass_id}/wrong_parent_pass",
                   lambda: replay.verify_saved_array(wire, digest, cell, other_pass, "native_logits", logits))
            for boundary in ("scene_features", "cue_features"):
                relative = f"cells/{cell}/WORST_CASES/{boundary}.{pass_id}.npy"
                value = load(relative)
                check(cell, pass_id, boundary, value, 9000, relative)
            for name, encoded in contract["cells"][cell]["passes"][pass_id]["official_outputs"].items():
                value = np.frombuffer(bytes.fromhex(encoded["bytes_hex"]), dtype=encoded["dtype"]).reshape(encoded["shape"])
                check(cell, pass_id, name, value, source=f"cells/{cell}/CELL_INPUTS.json#official_outputs")
    for cell in ("A2", "B2"):
        reject(f"{cell}/partial_saved_arrays_cannot_finish_real_replay",
               replay.ParentReplayGate(wire, digest, cell).finish)
    replay.require(len(matches) == 156 and len(negatives) == 10, "real check count differs")
    return {"status": "PINNED_SAVED_ARRAY_COMPONENT_CHECKS_PASS",
            "matches": matches, "negative_controls": negatives,
            "full_logits_arrays": 4, "per_trial_logits_rows": 128,
            "single_trial_feature_arrays": 8, "feature_trial_ids": [9000],
            "official_output_arrays": 16, "production_model_loaded": False,
            "real_inputs_regenerated": False, "real_full_replay_verified": False,
            "runtime_independently_attested": False, "production_authority": False,
            "ready_for_gpu": False, "jobs_submitted": 0}


def main():
    os.umask(0o077)
    evidence = WORKSPACE / "docs/superpowers/evidence"
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(tempfile.mkdtemp(prefix=f"parent-replay-local-{timestamp}-", dir=evidence))
    print(f"EVIDENCE_DIRECTORY={folder}", flush=True)
    source_names = ("parent_replay.py", "test_parent_replay.py", "validate_local.py")
    sources = {name: replay.sha((HERE / name).read_bytes()) for name in source_names}
    output = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(HERE), pattern="test_parent_replay.py")
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    write_new(folder / "unit-tests.log", output.getvalue().encode())
    replay.require(result.testsRun == 36 and result.wasSuccessful() and not result.skipped,
                   "unit test count/failure/skip differs; inspect unit-tests.log")
    wire, inventory_check = replay.build_contract(WORKSPACE)
    write_new(folder / "PARENT_REPLAY_CONTRACT.json", wire)
    terminal = json.loads((evidence / "job-685198-v18/DIAGNOSTIC_COMPLETE.json").read_bytes())
    replay.require(replay.sha((evidence / "job-685198-v18/DIAGNOSTIC_COMPLETE.json").read_bytes())
                   == replay.TERMINAL_SHA, "parent terminal changed")
    real = real_checks(wire, replay.sha(wire), evidence / "job-685198-v18/slurm-685198",
                       terminal["artifact_inventory"])
    write_new(folder / "SAVED_ARRAY_CHECKS.json", replay.canonical(real))
    # Rebuild from all pinned parents after testing; verifies all 114 originals
    # again and prevents accepting a changing source contract.
    after, final_inventory = replay.build_contract(WORKSPACE)
    replay.require(after == wire and final_inventory == inventory_check, "parent evidence changed")
    replay.require(sources == {name: replay.sha((HERE / name).read_bytes()) for name in source_names},
                   "component sources changed")
    replay.require("torch" not in sys.modules, "local acceptance must not import torch")
    artifact_names = ("unit-tests.log", "PARENT_REPLAY_CONTRACT.json", "SAVED_ARRAY_CHECKS.json")
    receipt = {
        "status": "LOCAL_PARENT_REPLAY_COMPONENT_PASS", "schema_version": 1,
        "python": platform.python_version(), "numpy": np.__version__, "unit_tests": result.testsRun,
        "unit_skips": 0, "synthetic_complete_schedule_tested": True,
        "parent_job_id": replay.JOB, "contract_sha256": replay.sha(wire),
        "parent_inventory": inventory_check, "source_sha256": sources,
        "artifacts": {name: {"sha256": replay.sha((folder / name).read_bytes()),
                              "size": (folder / name).stat().st_size} for name in artifact_names},
        "saved_array_matches": len(real["matches"]), "real_negative_controls": len(real["negative_controls"]),
        "real_full_replay_verified": False, "real_inputs_regenerated": False,
        "torch_imported": False, "production_model_loaded": False,
        "production_authority": False, "ready_for_gpu": False, "jobs_submitted": 0,
    }
    write_new(folder / "receipt.json", replay.canonical(receipt))
    print(json.dumps(receipt, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()

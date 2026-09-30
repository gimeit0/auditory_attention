"""Exact array-content replay checks against pinned Job685198 evidence.

Offline component only: no torch import, model, hooks, SSH or job submission.
Caller-supplied runtime metadata is compared, NOT independently attested here.
Passing this gate does not issue production authority or prove GPU observation
validity. Parent artifacts did not preserve strides; only shape/dtype/logical
C-order bytes can be compared. No casting, recomputation or numeric tolerance.
"""

import hashlib
import json
import math
from pathlib import Path

import numpy as np


MIB = 1024 * 1024
MAX_ARRAY_BYTES = 128 * MIB
MAX_CONTRACT_BYTES = 8 * MIB
JOB = "685198"
FREEZE_SHA = "bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178"
PLAN_SHA = "727dce6b20292d9eaf61807b80b79cf95080c182916b529d8684ef0598aa70e8"
TERMINAL_SHA = "4db7f8ba6c63bb58b354cc30486a0e839bb186e31c4845676baa26cd741b72c1"
INVENTORY_SHA = "57e589dd8f679715f49ba65cf841ef26b9e099ccf437024f8d13741afebf228b"
OFFLINE_SHA = "005e6dab40e34b2c823deb4ec361d0d6f7304d8403e3a1dfbbb7c5f15c9fafc7"
BINDING_SHA = "1e7e0e0a2668eda482026ea3002c9c249ffc8cc0f84bdb23940b800ce00e5d6f"
ROLE = "REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST"
COARSE = (
    "raw_scene", "raw_cue", "normalized_scene", "normalized_cue",
    "scene_features", "cue_features", "native_logits", "log_probabilities",
)
DERIVED = (
    "target_logit", "logsumexp", "target_log_probability", "nll",
    "p_target", "p_probe_distractor", "pred_label", "correct",
)
BOUNDARIES = COARSE + DERIVED
OFFICIAL = ("nll", "p_target", "p_probe_distractor", "pred_label")
DTYPES = {"torch.float16": "<f2", "torch.float32": "<f4",
          "torch.int64": "<i8", "torch.bool": "|b1"}
RUNTIME = {
    "deterministic_algorithms": True, "cudnn_deterministic": True,
    "cudnn_benchmark": False, "float32_matmul_precision": "high",
    "cuda_matmul_allow_tf32": True, "cudnn_allow_tf32": True,
}


class ReplayError(ValueError):
    """Closed gate; never convert this into an accepted scientific result."""


def require(condition, message):
    if not condition:
        raise ReplayError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _load_helper(path, expected):
    # Execute only the previously reviewed exact helper bytes, never a manifest
    # path or a candidate executable. Both helpers have guarded main functions.
    require(path.is_file() and not path.is_symlink(), "helper is not a regular file")
    raw = path.read_bytes()
    require(sha(raw) == expected, "pinned helper changed")
    namespace = {"__name__": "parent_replay_helper", "__file__": str(path)}
    exec(compile(raw, str(path), "exec"), namespace)
    return namespace


def _descriptor(record):
    return {"shape": record["shape"], "dtype": DTYPES[record["dtype"]],
            "nbytes": record["nbytes"], "sha256": record["sha256"]}


def build_contract(workspace):
    """Read and double-verify the fixed archive; return NEW contract bytes.

    Does not write into any parent/prototype directory. Does not load checkpoints.
    Complete inventory checks are reused unchanged, not replaced with this gate.
    """
    workspace = Path(workspace)
    evidence = workspace / "docs/superpowers/evidence"
    prototypes = workspace / "docs/superpowers/prototypes"
    offline = _load_helper(evidence / "2026-09-11-job685198-offline-analysis.py", OFFLINE_SHA)
    binding = _load_helper(prototypes / "targeted_binding_20260911/probe_cpu.py", BINDING_SHA)
    pinned = binding["pinned"]
    terminal = json.loads(pinned(evidence / "job-685198-v18/DIAGNOSTIC_COMPLETE.json", TERMINAL_SHA))
    freeze = json.loads(pinned(evidence / "v18-deployment-artifacts/input_freeze.json", FREEZE_SHA))
    plan = json.loads(pinned(prototypes / "targeted_trace_20260911/FORMAL40_PLAN_CANDIDATE.json", PLAN_SHA))
    ids = binding["validate_plan"](plan, freeze)
    inventory = terminal["artifact_inventory"]
    require(terminal["job_id"] == JOB and inventory["sha256"] == INVENTORY_SHA,
            "parent job/inventory differs")
    root = evidence / "job-685198-v18/slurm-685198"
    inventory_check = offline["verify_inventory"](root, inventory)
    files = {r["relative_path"]: r for r in inventory["files"]}

    def read(relative):
        record = files[relative]
        raw = pinned(root / relative, record["sha256"], limit=32 * MIB)
        require(len(raw) == record["size"], "parent artifact size differs")
        return raw

    cells = {}
    for cell, autocast in (("A2", True), ("B2", False)):
        prefix = f"cells/{cell}/"
        inputs = json.loads(read(prefix + "CELL_INPUTS.json"))
        runtime = json.loads(read(prefix + "RUNTIME.json"))["passes"]
        lines = [json.loads(line) for line in read(prefix + "BOUNDARY_DIGESTS.jsonl").splitlines()]
        require(inputs["trials"] == freeze["trials"] and len(runtime) == 2,
                "parent trial/runtime coverage differs")
        require(inputs["cell_spec"] == {"cell_id": cell, "autocast_enabled": autocast,
                                        "pass_batch_sizes": [16, 1]}, "parent cell differs")
        require([(r["pass_id"], r["boundary"]) for r in lines]
                == [(p, b) for p in ("pass1", "pass2") for b in BOUNDARIES],
                "parent boundary coverage/order differs")
        passes = {}
        for index, batch_size in enumerate((16, 1)):
            pass_id = f"pass{index + 1}"
            source_pass = inputs["passes"][index]
            payload = source_pass["payload"]
            require(payload["trial_ids"] == list(ids) and payload["pass_id"] == pass_id
                    and payload["batch_size"] == batch_size, "parent pass differs")
            require(canonical(runtime[index]["runtime"]) == canonical(RUNTIME)
                    and runtime[index]["autocast_enabled"] is autocast, "parent runtime differs")
            boundaries = {}
            for item in lines[index * 16:(index + 1) * 16]:
                name, record = item["boundary"], item["record"]
                parent_boundary = payload["boundaries"]
                other = parent_boundary[name] if name in COARSE else parent_boundary["derived"][name]
                require(record == other, f"parent duplicated boundary differs: {name}")
                boundaries[name] = {
                    "aggregate": _descriptor(record["aggregate"]),
                    "rows": [{"trial_id": row["trial_id"], **_descriptor(row)}
                             for row in record["per_trial"]],
                    "batches": [_descriptor(g["post_content"]) for g in record["guards"]],
                }
            official = source_pass["official_outputs"]
            require(official["encoding"] == "ndarray-hex-c-order-v1"
                    and set(official["outputs"]) == set(OFFICIAL), "official encoding differs")
            outputs = official["outputs"]
            for name in OFFICIAL:
                encoded = outputs[name]
                aggregate = boundaries[name]["aggregate"]
                require(all(encoded[k] == aggregate[k] for k in ("dtype", "shape", "sha256")),
                        f"official/derived output differs: {name}")
                raw = bytes.fromhex(encoded["bytes_hex"])
                require(len(raw) == aggregate["nbytes"] and sha(raw) == aggregate["sha256"],
                        "official output bytes differ")
                require(payload["outputs"][name]["sha256"] == aggregate["sha256"],
                        "committed official output differs")
            passes[pass_id] = {"batch_size": batch_size, "boundaries": boundaries,
                               "official_outputs": outputs, "runtime": RUNTIME}
        cells[cell] = {"autocast_enabled": autocast, "passes": passes}
    contract = {
        "schema_version": 1, "scope": "parent_array_content_only",
        "parent_job_id": JOB, "evaluation_role": ROLE, "production_authority": False,
        "parent_terminal_sha256": TERMINAL_SHA, "parent_inventory_sha256": INVENTORY_SHA,
        "parent_freeze_sha256": FREEZE_SHA, "plan_sha256": PLAN_SHA,
        "trials": freeze["trials"], "cells": cells,
        "layout_policy": "dtype_shape_logical_C_bytes_only__parent_stride_not_recorded",
    }
    wire = canonical(contract)
    _decode_contract(wire, sha(wire))
    require(offline["verify_inventory"](root, inventory) == inventory_check,
            "parent inventory changed while reading")
    return wire, inventory_check


def _validate_descriptor(d):
    require(type(d) is dict and d["dtype"] in DTYPES.values(), "unsupported expected dtype")
    shape = d["shape"]
    require(type(shape) is list and len(shape) <= 8
            and all(type(n) is int and 0 < n <= 1000000 for n in shape), "invalid expected shape")
    require(type(d["nbytes"]) is int and d["nbytes"] == math.prod(shape) * np.dtype(d["dtype"]).itemsize,
            "expected byte count differs")
    require(type(d["sha256"]) is str and len(d["sha256"]) == 64
            and all(c in "0123456789abcdef" for c in d["sha256"]), "invalid expected SHA")


def _decode_contract(wire, expected_sha):
    require(type(wire) is bytes and len(wire) <= MAX_CONTRACT_BYTES, "contract size/type differs")
    require(type(expected_sha) is str and sha(wire) == expected_sha, "external contract SHA differs")
    contract = json.loads(wire)
    # Reject duplicate keys, noncanonical JSON and any nonfinite metadata.
    require(canonical(contract) == wire, "noncanonical contract")
    require(contract["schema_version"] == 1 and contract["scope"] == "parent_array_content_only"
            and contract["production_authority"] is False and contract["evaluation_role"] == ROLE,
            "contract scope differs")
    require(contract["parent_job_id"] == JOB
            and contract["parent_terminal_sha256"] == TERMINAL_SHA
            and contract["parent_inventory_sha256"] == INVENTORY_SHA
            and contract["parent_freeze_sha256"] == FREEZE_SHA
            and contract["plan_sha256"] == PLAN_SHA, "contract parent pins differ")
    trials = contract["trials"]
    require(len(trials) == 32 and [t["ordinal"] for t in trials] == list(range(32)), "contract trials differ")
    ids = [t["trial_id"] for t in trials]
    require(all(type(i) is int for i in ids) and len(set(ids)) == 32, "invalid trial IDs")
    require(set(contract["cells"]) == {"A2", "B2"}, "contract cells differ")
    for cell, autocast in (("A2", True), ("B2", False)):
        spec = contract["cells"][cell]
        require(spec["autocast_enabled"] is autocast
                and set(spec["passes"]) == {"pass1", "pass2"}, "contract cell policy differs")
        for pass_id, size in (("pass1", 16), ("pass2", 1)):
            part = spec["passes"][pass_id]
            require(part["batch_size"] == size and canonical(part["runtime"]) == canonical(RUNTIME),
                    "contract runtime/batch policy differs")
            require(set(part["boundaries"]) == set(BOUNDARIES)
                    and set(part["official_outputs"]) == set(OFFICIAL), "incomplete contract coverage")
            for name, record in part["boundaries"].items():
                aggregate, rows = record["aggregate"], record["rows"]
                _validate_descriptor(aggregate)
                require(aggregate["shape"][0] == 32 and [r["trial_id"] for r in rows] == ids,
                        "contract boundary trial coverage differs")
                for row in rows:
                    _validate_descriptor(row)
                    require(row["dtype"] == aggregate["dtype"]
                            and row["shape"] == (aggregate["shape"][1:] or [1])
                            and row["nbytes"] * 32 == aggregate["nbytes"], "contract row metadata differs")
                batches = record["batches"]
                require(len(batches) == (32 // size if name in COARSE else 0), "batch guard coverage differs")
                for batch in batches:
                    _validate_descriptor(batch)
                    require(batch["shape"] == [size, *aggregate["shape"][1:]]
                            and batch["dtype"] == aggregate["dtype"], "batch guard metadata differs")
            for name in OFFICIAL:
                out = part["official_outputs"][name]
                agg = part["boundaries"][name]["aggregate"]
                require(all(out[k] == agg[k] for k in ("dtype", "shape", "sha256")), "official metadata differs")
                raw = bytes.fromhex(out["bytes_hex"])
                require(len(raw) == agg["nbytes"] and sha(raw) == agg["sha256"], "official bytes differ")
    return contract


def _array_digest(value, shape, dtype, *, accumulator=None, limit=MAX_ARRAY_BYTES):
    # Strict ndarray excludes arbitrary conversion methods, object/pickle arrays
    # and GPU transfers. Caller must deliver an independently protected CPU copy.
    require(type(value) is np.ndarray, "candidate must be a concrete NumPy array")
    require(list(value.shape) == shape and value.dtype.str == dtype, "candidate shape/dtype differs")
    require(value.nbytes <= limit, "candidate array exceeds byte budget")
    digest = hashlib.sha256()
    iterator = np.nditer(value, flags=["external_loop", "buffered", "zerosize_ok"],
                         op_flags=["readonly"], order="C", buffersize=MIB // value.itemsize)
    for chunk in iterator:
        require(bool(np.isfinite(chunk).all()), "candidate has nonfinite values")
        raw = chunk.tobytes(order="C")
        require(len(raw) <= MIB, "hash chunk exceeds byte budget")
        digest.update(raw)
        if accumulator is not None:
            accumulator.update(raw)
    return digest.hexdigest()


def verify_saved_array(wire, expected_sha, cell, pass_id, boundary, value, *, trial_id=None):
    """Partial saved-array proof; cannot advance or finish a replay gate."""
    contract = _decode_contract(wire, expected_sha)
    record = contract["cells"][cell]["passes"][pass_id]["boundaries"][boundary]
    descriptor = record["aggregate"]
    if trial_id is not None:
        require(type(trial_id) is int, "trial ID must be an integer")
        rows = [r for r in record["rows"] if r["trial_id"] == trial_id]
        require(len(rows) == 1, "unknown trial ID")
        descriptor = rows[0]
    actual = _array_digest(value, descriptor["shape"], descriptor["dtype"])
    require(actual == descriptor["sha256"], f"saved array differs from parent: {boundary}")
    return {"status": "SAVED_ARRAY_MATCH_ONLY", "cell": cell, "pass_id": pass_id,
            "boundary": boundary, "trial_id": trial_id, "sha256": actual,
            "full_replay_verified": False, "production_authority": False}


class ParentReplayGate:
    """Sequential 32-trial, 16->1 content check. Any failed call poisons it.

    All 16 boundary arrays AND the four actual official output arrays are needed
    per batch. Runtime arguments are labels, not a trusted measurement. A future
    protected worker must provide liveness/source/RNG/state/runtime attestation.
    """

    def __init__(self, wire, expected_sha, cell):
        self._contract = _decode_contract(wire, expected_sha)
        require(cell in ("A2", "B2"), "unknown replay cell")
        self._cell = cell
        self._sha = expected_sha
        self._spec = self._contract["cells"][cell]
        self._ids = [t["trial_id"] for t in self._contract["trials"]]
        self._schedule = [(p, start // size, start, min(start + size, 32))
                          for p, size in (("pass1", 16), ("pass2", 1))
                          for start in range(0, 32, size)]
        self._hashers = {(p, n): hashlib.sha256() for p in ("pass1", "pass2") for n in BOUNDARIES}
        self._position = 0
        self._closed = False

    def accept(self, pass_id, batch_index, trial_ids, boundaries, official_outputs, *, runtime, autocast_enabled):
        require(not self._closed, "replay gate is closed")
        try:
            self._accept(pass_id, batch_index, trial_ids, boundaries, official_outputs,
                         runtime, autocast_enabled)
        except Exception:
            self._closed = True
            raise

    def _accept(self, pass_id, batch_index, trial_ids, boundaries, official_outputs, runtime, autocast):
        require(self._position < len(self._schedule), "extra replay batch")
        expected_pass, expected_index, start, stop = self._schedule[self._position]
        require(type(batch_index) is int and (pass_id, batch_index) == (expected_pass, expected_index),
                "replay pass/batch order differs")
        require(type(trial_ids) in (tuple, list) and all(type(i) is int for i in trial_ids)
                and list(trial_ids) == self._ids[start:stop], "replay trial order differs")
        part = self._spec["passes"][pass_id]
        require(canonical(runtime) == canonical(part["runtime"])
                and autocast is self._spec["autocast_enabled"], "replay runtime label differs")
        require(type(boundaries) is dict and set(boundaries) == set(BOUNDARIES)
                and type(official_outputs) is dict and set(official_outputs) == set(OFFICIAL),
                "replay array coverage differs")
        for name in BOUNDARIES:
            value, record = boundaries[name], part["boundaries"][name]
            aggregate = record["aggregate"]
            batch_sha = _array_digest(value, [stop - start, *aggregate["shape"][1:]], aggregate["dtype"],
                                      accumulator=self._hashers[pass_id, name])
            if record["batches"]:
                require(batch_sha == record["batches"][batch_index]["sha256"], f"parent batch bytes differ: {name}")
            for local, row in enumerate(record["rows"][start:stop]):
                candidate = value[local:local + 1].reshape(row["shape"])
                require(_array_digest(candidate, row["shape"], row["dtype"]) == row["sha256"],
                        f"parent trial bytes differ: {name}/{row['trial_id']}")
        for name in OFFICIAL:
            encoded = part["official_outputs"][name]
            raw = bytes.fromhex(encoded["bytes_hex"])
            itemsize = np.dtype(encoded["dtype"]).itemsize
            expected = raw[start * itemsize:stop * itemsize]
            require(_array_digest(official_outputs[name], [stop - start], encoded["dtype"]) == sha(expected),
                    f"actual official output differs: {name}")
        if stop == 32:
            for name in BOUNDARIES:
                expected = part["boundaries"][name]["aggregate"]["sha256"]
                require(self._hashers[pass_id, name].hexdigest() == expected, f"parent aggregate differs: {name}")
        self._position += 1

    def finish(self):
        require(not self._closed, "replay gate is closed")
        self._closed = True
        require(self._position == len(self._schedule), "incomplete replay; all 34 batches required")
        return {"status": "PARENT_ARRAY_REPLAY_MATCH", "cell": self._cell,
                "parent_job_id": JOB, "contract_sha256": self._sha,
                "trials": 32, "pass_batch_sizes": [16, 1], "batches": 34,
                "boundaries_per_batch": 16, "official_outputs_per_batch": 4,
                "scope": "array_content_and_caller_labels_only",
                "runtime_independently_attested": False, "parent_stride_verified": False,
                "production_authority": False, "ready_for_gpu": False}

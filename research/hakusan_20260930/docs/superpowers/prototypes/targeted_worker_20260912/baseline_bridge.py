"""Bridge unchanged v18 trace passes to the parent-array gate, without hooks.

This is an in-process integration component, not a Slurm entry or a production
authorization issuer. Production still needs coordinator-owned input/scratch/
process/artifact verification. Hermetic CPU tests are explicitly separated.
"""

import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import types
import uuid

import numpy as np


HERE = Path(__file__).resolve().parent
V18_SHA = "7ba4d1f143fd1b957639588b209600377d745bf34e1207768cdd577e3f1d5a7b"
REPLAY_SHA = "6d5f784fcabd4a45e4d8ea997b230f1c5c5a22dbdde4affef359e01538e265ae"
PARENT_SHA = "95e25bde17fa8358cd20f90c2edf27a94a4ffd6f49aab8bd9fa3395b6c7c7b34"
_LOADED = {}


class BridgeError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise BridgeError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _load(path, expected, name):
    path = Path(path).absolute()
    require(path.is_file() and not path.is_symlink(), "source must be a regular file")
    raw = path.read_bytes()
    require(digest(raw) == expected, "source SHA differs")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    return module


replay = _load(HERE.parent / "targeted_replay_20260912/parent_replay.py", REPLAY_SHA,
               "targeted_worker_parent_replay")


def load_v18(path):
    """Load pinned bytes once; no source rewriting or replacement of v18 APIs."""
    module = _load(path, V18_SHA, "targeted_worker_v18_" + uuid.uuid4().hex)
    functions = {name: (value, value.__code__)
                 for name, value in vars(module).items()
                 if type(value) is types.FunctionType and value.__module__ == module.__name__}
    _LOADED[id(module)] = (module, functions)
    return module


def _require_module(module):
    issued = _LOADED.get(id(module))
    require(issued is not None and issued[0] is module, "v18 module not issued by pinned loader")
    path = Path(module.__file__)
    require(not path.is_symlink() and digest(path.read_bytes()) == V18_SHA, "v18 source changed")
    for name, (function, code) in issued[1].items():
        require(getattr(module, name, None) is function and function.__code__ is code,
                f"v18 function replaced: {name}")
    require(digest((HERE.parent / "targeted_replay_20260912/parent_replay.py").read_bytes()) == REPLAY_SHA,
            "parent matcher source changed")


def _wire(diag, value):
    return diag._get_trace().canonical_json_bytes(value)


def _pass_digest(diag, result):
    require(type(result) is diag.PassResult, "result is not an original v18 PassResult")
    current = digest(_wire(diag, diag._pass_commitment_payload(result)))
    commitment = result.boundary_records.get("pass_commitment", {})
    require(commitment.get("binding_sha256") == current, "original pass commitment changed")
    return current


class BaselineBridge:
    """Consume two passes from ONE original prepared model; never insert hooks.

    run() calls unchanged run_trace_pass twice, sizes 16 then 1. It does not
    configure runtime, reload the model, reset RNG/Dynamo, rebind commitments,
    replay individual trials, or write production completion markers.
    """

    def __init__(self, diag, context, trials, wire, expected_sha, cell, *, hermetic_test=False):
        _require_module(diag)
        require(type(hermetic_test) is bool, "test switch must be a bool")
        require(cell in ("A2", "B2"), "only A2/B2 baseline paths are in scope")
        if not hermetic_test:
            require(expected_sha == PARENT_SHA, "production path requires reviewed Job685198 contract")
        self.diag, self.context, self.trials = diag, dict(context), tuple(trials)
        self.cell, self.hermetic_test = cell, hermetic_test
        self.contract = replay._decode_contract(wire, expected_sha)
        self.gate = replay.ParentReplayGate(wire, expected_sha, cell)
        self.model = self.context.get("model")
        self.attestation = self.context.get("_formal40_worker_attestation")
        self._finished = False
        require(type(self.attestation) is diag._Formal40WorkerAttestation,
                "original prepared worker attestation required")
        require(self.context.get("cell_id") == cell, "context cell differs")
        trial_records = [{"ordinal": t.ordinal, "trial_id": t.trial_id,
                          "bank_row_index": t.bank_row_index, "identity": dict(t.identity)} for t in self.trials]
        require(replay.canonical(trial_records) == replay.canonical(self.contract["trials"]),
                "complete trial identities differ from parent contract")
        with self._scope():
            self._live("bridge_initial")

    def _scope(self):
        return self.diag._prediction_evaluator_context(self.context["evaluator"], model=self.model,
                                                        attestation=self.attestation)

    def _live(self, boundary):
        import torch
        _require_module(self.diag)
        actual = self.diag._live_inference_attestation(self.model, boundary)
        require(actual is self.attestation and actual.worker_pid == os.getpid(), "worker identity differs")
        expected_domain = "hermetic-test" if self.hermetic_test else "production"
        require(actual.frozen_capability.trust_domain == expected_domain, "worker trust domain differs")
        require(self.hermetic_test or self.context["device"].type == "cuda", "production requires CUDA")
        self.diag._require_active_inference_attestation(self.model, boundary + "_full")
        self.diag._validate_issued_model_state(actual)
        runtime = self.diag._read_frozen_numeric_runtime(torch)
        require(_wire(self.diag, runtime) == _wire(self.diag, self.context["runtime"]),
                "live runtime differs from context label")
        return runtime

    def _consume(self, result, pass_id, size):
        diag = self.diag
        require(result.pass_id == pass_id and result.batch_size == size
                and result.trial_ids == tuple(t.trial_id for t in self.trials), "returned pass identity differs")
        before_commitment = _pass_digest(diag, result)
        before_rng = _wire(diag, diag._get_trace().snapshot_rng_state())
        runtime = self._live("bridge_pre_consume")
        metadata = result.boundary_records["metadata"]
        require(_wire(diag, metadata["runtime"]) == _wire(diag, runtime)
                and metadata["autocast_enabled"] is (self.cell == "A2"), "returned runtime metadata differs")
        require(metadata["attestation"] == self.attestation.public_record()
                and metadata["worker_pid"] == os.getpid()
                and metadata["worker_nonce"] == self.attestation.worker_nonce
                and metadata["model_nonce"] == self.attestation.model_nonce,
                "returned worker provenance differs")
        expected_rows = [{"trial_id": t.trial_id, "bank_row_index": t.bank_row_index} for t in self.trials]
        require(metadata["trial_bank_rows"] == expected_rows, "returned bank rows differ")
        expected = self.contract["cells"][self.cell]["passes"][pass_id]
        for name in replay.BOUNDARIES:
            record = result.boundary_records[name] if name in replay.COARSE else result.boundary_records["derived"][name]
            # Also bind original guards/row records, not just the tensor returned
            # next to them. Object IDs/devices/versions are process diagnostics.
            compact = {"aggregate": replay._descriptor(record["aggregate"]),
                       "rows": [{"trial_id": r["trial_id"], **replay._descriptor(r)} for r in record["per_trial"]],
                       "batches": [replay._descriptor(g["post_content"]) for g in record["guards"]]}
            require(compact == expected["boundaries"][name], f"original boundary metadata differs: {name}")
        for start in range(0, 32, size):
            values = {}
            for name in replay.BOUNDARIES:
                record = result.boundary_records[name] if name in replay.COARSE else result.boundary_records["derived"][name]
                tensor = record["tensor"]
                # Original run_trace_pass captures CPU tensors AFTER official
                # outputs. No new GPU transfer, cast, clone or forward here.
                require(tensor.device.type == "cpu" and not tensor.requires_grad,
                        "boundary must be original detached CPU capture")
                values[name] = tensor[start:start + size].detach().numpy()
            outputs = {name: result.outputs[name][start:start + size] for name in replay.OFFICIAL}
            require(all(type(v) is np.ndarray for v in outputs.values()), "official output is not a NumPy array")
            self.gate.accept(pass_id, start // size, result.trial_ids[start:start + size], values, outputs,
                             runtime=runtime, autocast_enabled=metadata["autocast_enabled"])
        self._live("bridge_post_consume")
        require(_wire(diag, diag._get_trace().snapshot_rng_state()) == before_rng,
                "parent-array consumption changed RNG")
        require(_pass_digest(diag, result) == before_commitment, "parent-array consumption changed pass evidence")
        return {"pass_id": pass_id, "batch_size": size, "original_commitment_sha256": before_commitment}

    def run(self, *, scratch=None):
        """Production scratch must come from the old coordinator's scoped API.

        The hermetic small-model path does not spill and cannot authorize GPU.
        This function does not replace coordinator input/scheduler validation.
        """
        require(not self._finished, "bridge is single use")
        self._finished = True
        diag = self.diag
        if not self.hermetic_test:
            require(type(scratch) is diag._WorkerScratch and bool(scratch.anchors),
                    "production baseline requires original pinned worker scratch")
        passes, summaries = [], []
        try:
            with self._scope():
                for pass_id, size in (("pass1", 16), ("pass2", 1)):
                    self._live("bridge_pre_" + pass_id)
                    if scratch is not None:
                        scratch.check()
                    result = diag.run_trace_pass(self.context, self.trials, pass_id, size,
                                                 self.cell == "A2", Path(self.context["scratch_root"]))
                    if scratch is not None:
                        scratch.spill(result)
                    # Preserve the original two-pass lifetime; do not warm up,
                    # replay targets only or release pass1 before pass2.
                    passes.append(result)
                    summaries.append(self._consume(result, pass_id, size))
                if scratch is not None:
                    scratch.verify_spills()
                self._live("bridge_finished")
                replay_result = self.gate.finish()
                if self.hermetic_test:
                    # Never publish the reusable gate's fixed parent-job label
                    # as if synthetic fixture arrays reproduced the real job.
                    replay_result = {**replay_result, "status": "HERMETIC_ARRAY_SCHEDULE_MATCH",
                                     "parent_job_id": None,
                                     "scope": "synthetic_expected_arrays_not_Job685198_replay"}
            return {"status": "HERMETIC_V18_BASELINE_BRIDGE_PASS" if self.hermetic_test else "BASELINE_ARRAY_BRIDGE_PASS",
                    "cell": self.cell, "passes": summaries, "replay": replay_result,
                    "worker_pid": os.getpid(), "worker_nonce": self.attestation.worker_nonce,
                    "model_nonce": self.attestation.model_nonce, "original_v18_sha256": V18_SHA,
                    "original_guard_domain": self.attestation.frozen_capability.trust_domain,
                    "new_hooks_installed": 0, "runtime_read_from_torch": True,
                    "production_execution_authority_verified": False,
                    "real_model_validation": False if self.hermetic_test else "requires_coordinator_verification",
                    "ready_for_gpu": False, "jobs_submitted": 0}
        except BaseException:
            diag._revoke_attestation(self.attestation)
            raise

"""One NEW hermetic CPU process, one compiled model, two original v18 passes.

The reference has NO observation hooks. The observed process uses the already
reviewed exact CompiledRequest/CompiledLease. Neither mode opens production.
"""
import ast
import base64
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "targeted_compiled_20260912"
PINS = {
    "compiled_registration.py": "f0f820bebdcc35bd3892b5930abb144f9e942ea4800676040537c5891cebdcb2",
    "test_compiled_registration.py": "236eaeda6d67587c663ccc81fe503cd36057bbb5d98c03def84de1fc322c936e",
}
for name, digest in PINS.items():
    if hashlib.sha256((OLD / name).read_bytes()).hexdigest() != digest:
        raise RuntimeError("pinned compiled candidate differs")
sys.path.insert(0, str(OLD))
import test_compiled_registration as fixture  # noqa: E402
import torch  # noqa: E402

candidate = fixture.candidate
life, prep, bridge, diag = candidate.life, candidate.prep, candidate.bridge, fixture.diag


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


class ReferenceRegistration:
    """Synthetic CPU compiler issuance only; never installs observation hooks.

Uses the SAME audited two-call AST insertion points. All original preparation
statements and original inference functions remain; no model preinjection.
"""
    def __init__(self, context):
        self.context = context
        self.model = self.compiler = self.prepared = self.before = None
        self.install_count = self.check_count = 0

    def snapshot(self):
        return prep.wire({"state": diag._snapshot_model_entries(self.model),
                          "rng": diag._get_trace().snapshot_rng_state(),
                          "runtime": diag._read_frozen_numeric_runtime(torch)})

    def check(self):
        bridge._require_module(diag)
        candidate.source_check()
        require(self.context["_frozen_context_capability"].trust_domain == "hermetic-test",
                "reference is only a hermetic CPU experiment")
        if self.model is not None:
            require(not any(m._forward_hooks or m._forward_pre_hooks
                            for m in self.model.modules()), "reference acquired a hook")
        if self.compiler is not None:
            self.compiler.verify()

    def install(self, model, report, device):
        self.check()
        require(type(self) is ReferenceRegistration and self.install_count == 0
                and self.model is None and device.type == "cpu" and type(report) is dict,
                "reference registration order/device differs")
        self.model = model
        self.before = self.snapshot()
        require(type(model) is fixture.TinyOuter, "reference must use exact synthetic outer")
        inventory = diag._direct_model_module_inventory(model)
        self.compiler = diag._issue_compiler_lifecycle(model, inventory)
        require(self.compiler is not None and not self.compiler.entered, "reference compiler is not cold")
        self.install_count += 1
        self.check()
        require(self.snapshot() == self.before, "reference issuance changed state/RNG/runtime")

    def before_issue(self, model):
        self.check()
        require(model is self.model and self.install_count == 1 and self.check_count == 0
                and not self.compiler.entered, "reference pre-issuance order differs")
        require(self.snapshot() == self.before, "reference pre-issuance state changed")
        self.check_count += 1

    def prepare(self):
        require(str(torch.__version__) == "2.1.1+cu118", "original compiler requires actual torch 2.1.1+cu118")
        self.check()
        raw = Path(diag.__file__).read_bytes()
        tree = prep.build_candidate(raw)
        audit = prep.verify_delta(raw, tree.body[0])
        namespace = dict(vars(diag))
        bindings = {node.id: namespace[node.id] for node in ast.walk(tree)
                    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                    and node.id in namespace}
        exec(compile(tree, str(HERE / "<reference-preparation>"), "exec"), namespace)
        self.prepared = namespace[prep.CANDIDATE_NAME](self.context, allow_cpu=True, _registration=self)
        require(all(vars(diag)[name] is value for name, value in bindings.items()), "original helper changed")
        require(prep.CANDIDATE_NAME not in vars(diag), "original namespace changed")
        self.check()
        require(self.install_count == self.check_count == 1 and self.snapshot() == self.before,
                "reference preparation changed state or skipped registration")
        return self.prepared, audit

    def close(self):
        # Revoke only identities belonging to this freshly loaded model.
        if self.model is not None:
            for attestation in diag._ISSUED_FORMAL40_ATTESTATIONS.values():
                if attestation.model is self.model:
                    diag._revoke_attestation(attestation)
            authority = diag._ISSUED_COMPILER_LIFECYCLES.get(id(self.model))
            if authority is not None:
                authority.revoked = True


def encode_array(value):
    array = value.detach().cpu().numpy() if type(value) is torch.Tensor else value
    raw = array.tobytes(order="C")
    require(len(raw) <= 256 * 1024, "synthetic array budget exceeded")
    return {"shape": list(array.shape), "dtype": array.dtype.str, "nbytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(), "base64": base64.b64encode(raw).decode()}


def encode_pass(result, attestation):
    commitment = bridge._pass_digest(diag, result)
    meta = result.boundary_records["metadata"]
    require(meta["attestation"] == attestation.public_record() and meta["worker_pid"] == os.getpid(),
            "original pass provenance differs")
    require(meta["runtime"] == diag._read_frozen_numeric_runtime(torch), "pass runtime label differs")
    for record in (result.model_snapshots, result.rng_snapshots):
        require(prep.wire(record["before"]) == prep.wire(record["after"]), "pass changed model state or RNG")
    boundaries = {}
    for name in bridge.replay.BOUNDARIES:
        record = result.boundary_records[name] if name in bridge.replay.COARSE else result.boundary_records["derived"][name]
        value = encode_array(record["tensor"])
        desc = {k: value[k] for k in ("shape", "dtype", "nbytes", "sha256")}
        require(desc == bridge.replay._descriptor(record["aggregate"]), "original aggregate content differs")
        value["rows"] = [{"trial_id": row["trial_id"], **bridge.replay._descriptor(row)}
                         for row in record["per_trial"]]
        value["batches"] = [bridge.replay._descriptor(guard["post_content"]) for guard in record["guards"]]
        boundaries[name] = value
    require(bridge._pass_digest(diag, result) == commitment, "encoding mutated original pass")
    return {"pass_id": result.pass_id, "batch_size": result.batch_size,
            "trial_ids": list(result.trial_ids), "runtime": meta["runtime"],
            "autocast_enabled": meta["autocast_enabled"], "boundaries": boundaries,
            "official_outputs": {name: encode_array(value) for name, value in result.outputs.items()},
            "original_pass_commitment": commitment, "state_rng_unchanged": True}


def run(mode):
    require(mode in ("reference", "observed"), "unknown worker mode")
    require(str(torch.__version__) == "2.1.1+cu118" and not torch.cuda.is_initialized(),
            "only actual same-version synthetic CPU execution is admitted")
    torch.set_num_threads(1)
    with fixture.request_context() as (request, evaluator, trials):
        reference = ReferenceRegistration(request.context) if mode == "reference" else None
        lease = None
        try:
            if reference:
                prepared, audit = reference.prepare()
                compiler = reference.compiler
            else:
                prepared, lease, audit = candidate.prepare_compiled(request)
                compiler = lease.compiler
            require(not compiler.entered and evaluator.calls.count("model") == 0, "forward before measured lifetime")
            with tempfile.TemporaryDirectory(prefix="compiled-full-pass-") as scratch:
                bank = fixture.fixtures._task4_bank(32)
                context = {**request.context, **prepared, "bank": bank, "clips_dir": Path("/clips"),
                           "cell_id": "B2", "historical_scene_hashes": fixture.fixtures._task4_scene_hashes(bank),
                           "scratch_root": scratch, "cache_roots": {}}
                attestation = prepared["_formal40_worker_attestation"]
                require(life._ACTIVE.get() is None, "nested observer")
                token = life._ACTIVE.set(lease) if lease else None
                passes, encoded = [], []
                try:
                    if lease:
                        lease.used = True
                    for pass_id, size in (("pass1", 16), ("pass2", 1)):
                        if lease:
                            lease.pass_id = pass_id
                        result = diag.run_trace_pass(context, trials, pass_id, size, False, Path(scratch))
                        passes.append(result)  # keep BOTH original passes alive
                        with diag._prediction_evaluator_context(prepared["evaluator"], model=prepared["model"],
                                                               attestation=attestation):
                            diag._live_inference_attestation(prepared["model"], "compiled_full_pass_complete")
                            diag._validate_issued_model_state(attestation)
                            compiler.verify()
                            if lease:
                                lease.verify_pass(result)
                            else:
                                reference.check()
                            encoded.append(encode_pass(result, attestation))
                    require(len(passes) == 2 and len(evaluator.load_calls) == 1
                            and evaluator.calls.count("model") == 34 and compiler.entered,
                            "two passes require one load and exactly 34 original forwards")
                    captures = []
                    if lease:
                        lease.check()
                        require(len(lease.records) == 34 and lease.current is None, "incomplete observation lifetime")
                        for ref in lease.store.refs:
                            require(lease.store.compare(ref, ref), "capture reread failed")
                            with lease.store._open(ref) as stream:
                                raw = stream.read(ref.size + 1)
                            require(len(raw) == ref.size and hashlib.sha256(raw).hexdigest() == ref.sha256,
                                    "capture export changed bytes")
                            captures.append({"record": asdict(ref), "base64": base64.b64encode(raw).decode()})
                    value = {"status": "HERMETIC_COMPILED_LIFETIME_PASS", "mode": mode,
                             "pid": os.getpid(), "python": sys.version.split()[0], "torch": torch.__version__,
                             "backend": "eager", "cell": "B2", "load_calls": 1, "forward_calls": 34,
                             "complete_passes": 2, "stage_invocations": 136 if lease else 0,
                             "compiler_backend_entered": bool(compiler.entered), "original_guards_enabled": True,
                             "original_compiler_authority": True, "runtime": context["runtime"],
                             "trials": [{"ordinal": t.ordinal, "trial_id": t.trial_id,
                                         "bank_row_index": t.bank_row_index, "identity": dict(t.identity)}
                                        for t in trials], "relative_plan": asdict(request.plan),
                             "passes": encoded, "captures": captures,
                             "observer_records": lease.records if lease else [],
                             "preparation_audit": audit, "production_model_loaded": False,
                             "cuda_initialized": torch.cuda.is_initialized(), "ready_for_gpu": False,
                             "jobs_submitted": 0, "real_parent_replay_completed": False}
                finally:
                    if token is not None:
                        life._ACTIVE.reset(token)
        finally:
            if reference:
                reference.close()
            else:
                request.close()
        model = prepared["model"]
        value["hooks_removed"] = not any(m._forward_hooks or m._forward_pre_hooks for m in model.modules())
        value["attestation_revoked"] = id(attestation) in diag._REVOKED_FORMAL40_ATTESTATIONS
        require(value["hooks_removed"] and value["attestation_revoked"], "hook/attestation cleanup failed")
        return value


if __name__ == "__main__":
    os.umask(0o077)
    print("LIFETIME_CHILD=" + json.dumps(run(sys.argv[1]), sort_keys=True), flush=True)

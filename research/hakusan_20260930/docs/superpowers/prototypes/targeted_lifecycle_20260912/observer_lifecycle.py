"""Guard-compatible observation lifecycle: HERMETIC CPU EXPERIMENT ONLY.

The original v18 functions are not patched, copied, resealed or replaced.
Tests install immutable dispatch hooks on a toy model BEFORE original worker
issuance. ContextVar contents are not covered by v18's callable seal: this
component separately checks its declared mutable recorder. This is not a new
production capability, a security sandbox, or Inductor validation.
"""

from contextvars import ContextVar
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import sys
import types

import torch


HERE = Path(__file__).resolve().parent
PINS = {
    "targeted_worker_20260912/baseline_bridge.py": "ad3578d245956df7f7fe355adcb3bfde303fdfa93c143405b89252876dd0f43c",
    "targeted_trace_20260911/trace_observer.py": "dcbe162257fc130450a2f2b4a2fd5680caded503d10c67b704c6a0331ec86328",
    "targeted_stream_20260911/stream_capture.py": "e0a0282a80b4e68aa0c0d250a0d1383238bfc948b871b9ab05baa585d386c01e",
}
for relative, expected in PINS.items():
    source = HERE.parent / relative
    if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
        raise RuntimeError("pinned lifecycle dependency differs: " + relative)
    sys.path.insert(0, str(source.parent))
import baseline_bridge as bridge  # noqa: E402
import trace_observer as base  # noqa: E402
import stream_capture as capture  # noqa: E402

for module, relative in ((bridge, "targeted_worker_20260912/baseline_bridge.py"),
                         (base, "targeted_trace_20260911/trace_observer.py"),
                         (capture, "targeted_stream_20260911/stream_capture.py")):
    if Path(module.__file__).resolve() != (HERE.parent / relative).resolve():
        raise RuntimeError("unexpected lifecycle dependency module")

_ACTIVE = ContextVar("hermetic_observer_lease", default=None)
_SELF_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class LifecycleError(RuntimeError):
    pass


def require(ok, message):
    if not ok:
        raise LifecycleError(message)


def _pre(module, arguments):
    active = _ACTIVE.get()
    if active is None:
        raise LifecycleError("observer invoked outside its active lease")
    active.pre(module, arguments)


def _post(module, arguments, output):
    active = _ACTIVE.get()
    if active is None:
        raise LifecycleError("observer invoked outside its active lease")
    active.post(module, arguments, output)


def _stage_hook(path):
    def hook(module, arguments, output):
        active = _ACTIVE.get()
        if active is None:
            raise LifecycleError("observer invoked outside its active lease")
        active.stage(path, module, output)
    return hook


def _source_check():
    require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_SHA,
            "lifecycle source changed")
    for relative, expected in PINS.items():
        require(hashlib.sha256((HERE.parent / relative).read_bytes()).hexdigest() == expected,
                "lifecycle dependency source changed")
    for owner, name, function, code in _CODE:
        require(vars(owner).get(name) is function and function.__code__ is code,
                "lifecycle callable changed: " + name)


def descriptor(tensor):
    require(type(tensor) is torch.Tensor and tensor.device.type == "cpu",
            "lifecycle prototype only accepts native CPU tensors")
    value = base.copy_tensor(tensor)
    return {"dtype": tensor.detach().numpy().dtype.str, "shape": list(value.shape),
            "nbytes": len(value.data), "sha256": value.sha256}


def _wire(value):
    return bridge.replay.canonical(value)


class ObservationLease:
    """Static hooks, explicit single-use recorder, and declared append-only log.

    Not a production preparation path: caller must provide a preconstructed
    hermetic model. Installing on an already-issued model is rejected. No
    hook removal/reinstallation during passes, new forward, or RNG reset.
    """

    def __init__(self, diag, model, plan, store):
        bridge._require_module(diag)
        require(type(plan) is base.Plan and len(plan.trials) == 32
                and plan.batch_sizes == (16, 1), "requires exact 32-trial 16-to-1 plan")
        require(type(store) is capture.CaptureStore and not store.refs, "requires fresh capture store")
        require(not any(isinstance(m, torch._dynamo.eval_frame.OptimizedModule) for m in model.modules()),
                "compiled models are not admitted by this CPU lifecycle prototype")
        require(all(t.device.type == "cpu" for t in model.state_dict().values()), "CPU model required")
        self.diag, self.model, self.plan, self.store = diag, model, plan, store
        self.schedule = plan.schedule()
        self.modules = tuple(model.named_modules())
        self.handles = []
        self.hooks = None
        self.records = []
        self.record_seal = _wire(self.records)
        self.current = None
        self.context = None
        self.pass_id = None
        self.failed = self.used = self.closed = False
        self.pid = os.getpid()
        self.config = (id(diag), id(model), _wire(asdict(plan)), id(store), store.root, store.fd,
                       store.store_id, store.chunk_bytes, store.total_bytes, store.tensor_bytes,
                       store.max_records, self.modules, self.schedule)

    def _hook_state(self):
        return tuple((path, module, tuple((name, tuple(getattr(module, name).items()))
                                          for name in ("_forward_pre_hooks", "_forward_hooks",
                                                       "_forward_hooks_with_kwargs", "_forward_hooks_always_called",
                                                       "_forward_pre_hooks_with_kwargs")))
                     for path, module in self.model.named_modules())

    def install_before_issuance(self):
        require(not self.handles and not self.closed and not self.used, "lease installation is single use")
        require(not any(a.model is self.model for a in self.diag._ISSUED_FORMAL40_ATTESTATIONS.values()),
                "hooks must be installed before original issuance")
        base.model_state(self.model)
        require(all(not m._forward_hooks and not m._forward_pre_hooks for _, m in self.modules),
                "existing forward hooks are not admitted")
        modules = dict(self.modules)
        paths = tuple(dict.fromkeys(s.module for s in self.plan.stages))
        require(all(path in modules and path for path in paths), "unknown/root stage module")
        require(len({id(modules[p]) for p in paths}) == len(paths), "stage aliases rejected")
        try:
            self.handles.append(self.model.register_forward_pre_hook(_pre))
            for path in paths:
                self.handles.append(modules[path].register_forward_hook(_stage_hook(path)))
            self.handles.append(self.model.register_forward_hook(_post))
            self.hooks = self._hook_state()
            self.check()
        except BaseException:
            self.failed = True
            self.close()
            raise
        return self

    def check(self):
        _source_check()
        require(not any(name in vars(self) for name, value in vars(ObservationLease).items()
                        if type(value) is types.FunctionType), "instance recorder method replaced")
        require(not any(name in vars(self.store) for name, value in vars(capture.CaptureStore).items()
                        if type(value) is types.FunctionType), "instance capture method replaced")
        require(not self.failed and not self.closed and os.getpid() == self.pid, "lease failed, closed, or moved process")
        now = (id(self.diag), id(self.model), _wire(asdict(self.plan)), id(self.store), self.store.root,
               self.store.fd, self.store.store_id, self.store.chunk_bytes, self.store.total_bytes,
               self.store.tensor_bytes, self.store.max_records, tuple(self.model.named_modules()), self.plan.schedule())
        require(now == self.config and self.schedule == self.config[-1], "observer configuration changed")
        require(self.hooks is not None and self.hooks == self._hook_state(), "observer hook identity/flags changed")
        require(_wire(self.records) == self.record_seal, "observer ledger changed")
        refs = [r for b in self.records for r in b["captures"]]
        if self.current is not None:
            refs.extend(self.current["captures"])
        require(refs == [asdict(r) for r in self.store.refs], "capture issuance ledger changed")
        require(self.store.keys == {r.key for r in self.store.refs}
                and self.store.used_bytes == sum(r.size for r in self.store.refs), "capture accounting changed")
        self.store._check()

    def pre(self, module, arguments):
        self.check()
        require(module is self.model and self.current is None and len(self.records) < len(self.schedule),
                "unexpected/extra/reentrant model invocation")
        p, index, ids = self.schedule[len(self.records)]
        require(self.pass_id == p, "model invocation in wrong pass")
        require(type(arguments) is tuple and len(arguments) == 3 and arguments[2] is None,
                "frozen model argument layout differs")
        cue, scene, _ = arguments
        require(cue.shape[0] == scene.shape[0] == len(ids), "model batch size differs")
        actual = self.diag._ACTIVE_PREDICTION_CONTEXT.get()
        require(actual is not None and actual.get("model") is self.model
                and actual.get("attestation") is self.context["_formal40_worker_attestation"],
                "original prediction scope missing or changed")
        self.current = {"pass_id": p, "batch_index": index, "trials": ids, "index": 0,
                        "captures": [], "inputs": (descriptor(cue), descriptor(scene)),
                        "rng": self.diag._get_trace().snapshot_rng_state(),
                        "runtime": self.diag._read_frozen_numeric_runtime(torch)}

    def stage(self, path, module, output):
        self.check()
        active = self.current
        require(active is not None, "stage outside model call")
        index = active["index"]
        require(index < len(self.plan.stages) and self.plan.stages[index].module == path
                and dict(self.modules)[path] is module, "stage order/object differs")
        require(type(output) is torch.Tensor and output.ndim > 0
                and output.shape[0] == len(active["trials"]), "stage batch shape differs")
        for row, trial in enumerate(active["trials"]):
            if trial in self.plan.targets:
                ref = self.store.capture(output[row], (active["pass_id"], active["batch_index"], index, trial))
                active["captures"].append(asdict(ref))
        active["index"] += 1
        self.check()

    def post(self, module, arguments, output):
        self.check()
        active = self.current
        require(module is self.model and active is not None and active["index"] == len(self.plan.stages),
                "missing stage or wrong model post-hook")
        require(active["inputs"] == (descriptor(arguments[0]), descriptor(arguments[1])), "model inputs changed")
        require(_wire(active["rng"]) == _wire(self.diag._get_trace().snapshot_rng_state()), "model/observer RNG changed")
        require(_wire(active["runtime"]) == _wire(self.diag._read_frozen_numeric_runtime(torch)),
                "model/observer runtime changed")
        record = {k: active[k] for k in ("pass_id", "batch_index", "trials", "captures", "inputs")}
        record["logits"] = descriptor(output)
        self.records.append(record)
        self.record_seal = _wire(self.records)
        self.current = None
        self.check()

    def verify_pass(self, result):
        self.check()
        records = [b for b in self.records if b["pass_id"] == result.pass_id]
        require(len(records) == (2 if result.pass_id == "pass1" else 32), "incomplete pass observations")
        for index, record in enumerate(records):
            for name, actual in (("cue_features", record["inputs"][0]),
                                 ("scene_features", record["inputs"][1]), ("native_logits", record["logits"])):
                expected = bridge.replay._descriptor(result.boundary_records[name]["guards"][index]["post_content"])
                require(actual == expected, "observer endpoint differs from original pass: " + name)
            expected_keys = [(result.pass_id, index, i, trial) for i in range(len(self.plan.stages))
                             for trial in record["trials"] if trial in self.plan.targets]
            require([tuple(r["key"]) for r in record["captures"]] == expected_keys, "capture order/coverage differs")

    def close(self):
        if not self.closed:
            if self.context is not None:
                # Removing hooks changes execution identity; old identity must
                # never be usable after the observer lifetime ends.
                self.diag._revoke_attestation(self.context["_formal40_worker_attestation"])
            for handle in self.handles:
                handle.remove()
            self.closed = True


def _run_observed(gate, lease):
    """Two unchanged v18 passes; consume unchanged parent gate; CPU test only.

    Caller installs hooks before original prepare_formal40_worker. This helper
    does NOT invent a production loader insertion API or authorize GPU work.
    """
    _source_check()
    require(type(gate) is bridge.BaselineBridge and gate.hermetic_test is True
            and gate.attestation.frozen_capability.trust_domain == "hermetic-test"
            and gate.context["device"].type == "cpu", "only original hermetic CPU worker is admitted")
    require(type(lease) is ObservationLease and lease.model is gate.model and lease.diag is gate.diag,
            "observer/worker mismatch")
    require(not lease.used and not gate._finished and _ACTIVE.get() is None, "observer run is single use/non-nested")
    require(tuple(t.trial_id for t in gate.trials) == lease.plan.trials, "observer trial schedule differs")
    lease.context = gate.context
    lease.used = gate._finished = True
    token = _ACTIVE.set(lease)
    passes, summaries = [], []
    try:
        with gate._scope():
            for pass_id, size in (("pass1", 16), ("pass2", 1)):
                lease.check()
                lease.pass_id = pass_id
                gate._live("observer_pre_" + pass_id)
                result = gate.diag.run_trace_pass(gate.context, gate.trials, pass_id, size,
                                                 gate.cell == "A2", Path(gate.context["scratch_root"]))
                passes.append(result)
                summaries.append(gate._consume(result, pass_id, size))
                lease.verify_pass(result)
                gate._live("observer_post_" + pass_id)
            gate.gate.finish()
            lease.check()
            require(lease.current is None and len(lease.records) == 34, "incomplete observer lifetime")
            # Read every issued file, not merely the stored hashes.
            for ref in lease.store.refs:
                require(lease.store.compare(ref, ref), "capture reread differs")
            gate._live("observer_final")
            _source_check()
        return {"status": "HERMETIC_OBSERVER_LIFECYCLE_PASS", "cell": gate.cell,
                "worker_pid": os.getpid(), "batches": len(lease.records),
                "stage_invocations": len(lease.records) * len(lease.plan.stages),
                "capture_records": len(lease.store.refs), "capture_bytes": lease.store.used_bytes,
                "observer_ledger_sha256": hashlib.sha256(lease.record_seal).hexdigest(),
                "original_passes": summaries, "original_guard_domain": "hermetic-test",
                "source_prepare_and_pass_functions_unchanged": True,
                "mutable_observer_state_covered_by_original_v18_seal": False,
                "separate_observer_lifecycle_checked": True,
                "real_parent_replay_completed": False, "production_model_loaded": False,
                "compiled_backend": None, "ready_for_gpu": False, "jobs_submitted": 0}
    except BaseException:
        lease.failed = True
        gate.diag._revoke_attestation(gate.attestation)
        raise
    finally:
        _ACTIVE.reset(token)
        lease.close()


def run_observed(gate, lease):
    # Even early admission/source failures close owned hooks and revoke the
    # matching original worker. No partial success can be reused for a retry.
    try:
        return _run_observed(gate, lease)
    except BaseException:
        if type(lease) is ObservationLease:
            lease.failed = True
            if type(gate) is bridge.BaselineBridge and gate.model is lease.model and gate.diag is lease.diag:
                lease.diag._revoke_attestation(gate.attestation)
            lease.close()
        raise


_CODE = tuple((owner, name, value, value.__code__)
              for owner in (sys.modules[__name__], ObservationLease, capture, capture.CaptureStore,
                            base, base.Plan, base.Stage, bridge, bridge.BaselineBridge)
              for name, value in vars(owner).items() if type(value) is types.FunctionType)

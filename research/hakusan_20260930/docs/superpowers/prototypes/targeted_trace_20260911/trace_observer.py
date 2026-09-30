"""Bounded synthetic observer prototype, NOT a production evaluator.

Hooks deliberately run outside Dynamo. This can change graph partitioning and
numerics. Endpoint equality is necessary, not sufficient to transfer internal
observations to an uninstrumented compiled program. No submission/file writing.
"""

from dataclasses import dataclass, fields, is_dataclass, replace
import hashlib
import json

import torch
import torch._dynamo


class TraceError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise TraceError(message)


@dataclass(frozen=True)
class Stage:
    module: str
    branch: str


@dataclass(frozen=True)
class TensorCopy:
    dtype: str
    shape: tuple
    stride: tuple
    data: bytes

    @property
    def sha256(self):
        return hashlib.sha256(self.data).hexdigest()


def copy_tensor(value, max_bytes=128 * 1024 * 1024):
    require(type(value) is torch.Tensor, "only native tensors are supported")
    require(value.layout == torch.strided and value.dtype in
            (torch.float16, torch.float32, torch.float64), "unsupported tensor dtype/layout")
    size = value.numel() * value.element_size()
    require(0 < size <= max_bytes, "tensor byte budget exceeded or tensor empty")
    require(bool(torch.isfinite(value).all().item()), "nonfinite tensor")
    # Immutable bytes snapshot now, not a reference that later in-place ops can overwrite.
    payload = value.detach().to("cpu").contiguous().numpy().tobytes()
    require(len(payload) == size, "tensor byte length differs")
    return TensorCopy(str(value.dtype), tuple(value.shape), tuple(value.stride()), payload)


def same_values(left, right):
    return (left.dtype, left.shape, left.data) == (right.dtype, right.shape, right.data)


def tensor_key(value):
    snapshot = copy_tensor(value)
    return snapshot.dtype, snapshot.shape, snapshot.stride, snapshot.sha256


def model_state(model):
    require(all(not module.training for module in model.modules()), "model must be in eval mode")
    require(all(not p.requires_grad for p in model.parameters()), "parameters must be frozen")
    state = model.state_dict()
    require(len(state) <= 128 and sum(x.numel() * x.element_size() for x in state.values())
            <= 1024 * 1024 * 1024, "model state budget exceeded")
    # Do not retain another full copy of the weights for every batch.
    return tuple((name, tensor_key(tensor)) for name, tensor in state.items())


def rng_state():
    cpu = torch.random.get_rng_state().numpy().tobytes()
    cuda = ()
    if torch.cuda.is_initialized():
        cuda = tuple(x.cpu().numpy().tobytes() for x in torch.cuda.get_rng_state_all())
    return cpu, cuda


def runtime_state():
    return (torch.are_deterministic_algorithms_enabled(),
            torch.backends.cudnn.deterministic, torch.backends.cudnn.benchmark,
            torch.get_float32_matmul_precision(), torch.backends.cuda.matmul.allow_tf32,
            torch.backends.cudnn.allow_tf32)


@dataclass(frozen=True)
class Event:
    index: int
    stage: Stage
    trial_id: int
    tensor: TensorCopy


@dataclass(frozen=True)
class Batch:
    pass_id: str
    batch_index: int
    trials: tuple
    inputs: tuple
    logits: TensorCopy
    events: tuple
    state_before: tuple
    state_after: tuple
    rng_before: tuple
    rng_after: tuple
    runtime_before: tuple
    runtime_after: tuple
    record_digest: str = ""


def record_digest(batch):
    def normalize(value):
        if type(value) is bytes:
            return {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
        if is_dataclass(value):
            return {f.name: normalize(getattr(value, f.name)) for f in fields(value)
                    if f.name != "record_digest"}
        if type(value) is tuple:
            return [normalize(v) for v in value]
        require(type(value) in (str, int, bool) or value is None, "invalid record field")
        return value
    wire = json.dumps(normalize(batch), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(wire.encode("utf-8")).hexdigest()


def seal(batch):
    return replace(batch, record_digest=record_digest(batch))


@dataclass(frozen=True)
class Plan:
    trials: tuple
    targets: tuple
    stages: tuple
    batch_sizes: tuple = (16, 1)

    def __post_init__(self):
        require(type(self.trials) is tuple and 0 < len(self.trials) <= 32,
                "trial list must be a bounded tuple")
        require(all(type(x) is int and x >= 0 for x in self.trials)
                and len(set(self.trials)) == len(self.trials), "invalid/duplicate trial ids")
        require(type(self.targets) is tuple and 0 < len(self.targets) <= 4
                and len(set(self.targets)) == len(self.targets)
                and all(type(t) is int and t in self.trials for t in self.targets),
                "invalid target ids")
        require(type(self.stages) is tuple and 0 < len(self.stages) <= 128
                and all(type(s) is Stage and type(s.module) is str and s.module
                        and type(s.branch) is str and s.branch for s in self.stages),
                "invalid stages")
        require(type(self.batch_sizes) is tuple and len(self.batch_sizes) == 2
                and all(type(n) is int and 0 < n <= 16 for n in self.batch_sizes),
                "invalid batch sizes")

    def schedule(self):
        return tuple((f"pass{p + 1}", start // size, self.trials[start:start + size])
                     for p, size in enumerate(self.batch_sizes)
                     for start in range(0, len(self.trials), size))


def evaluate_batch(model, call, pass_id, batch_index, trials, cue, mixture):
    require(type(trials) is tuple and cue.shape[0] == mixture.shape[0] == len(trials),
            "batch identity/shape mismatch")
    before, rng, runtime = model_state(model), rng_state(), runtime_state()
    inputs = (tensor_key(cue), tensor_key(mixture))
    with torch.inference_mode():
        logits = call(cue, mixture)
    require(type(logits) is torch.Tensor and logits.ndim == 2
            and logits.shape[0] == len(trials) and 1 < logits.shape[1] <= 800,
            "invalid endpoint shape")
    endpoint = copy_tensor(logits)
    after, after_rng, after_runtime = model_state(model), rng_state(), runtime_state()
    require(before == after, "model state changed")
    require(rng == after_rng, "RNG changed")
    require(runtime == after_runtime, "runtime flags changed")
    require(inputs == (tensor_key(cue), tensor_key(mixture)), "input tensor changed")
    return seal(Batch(pass_id, batch_index, trials, inputs, endpoint, (), before, after,
                      rng, after_rng, runtime, after_runtime))


class Observer:
    """Install BEFORE compile; no dynamic hook toggling on a compiled instance.

    Stores full selected tensors only for a bounded prototype. Real-model memory
    feasibility and source/capability attestation are deliberately NOT certified.
    """

    def __init__(self, model, plan, max_bytes=16 * 1024 * 1024):
        require(type(plan) is Plan, "invalid plan")
        require(type(max_bytes) is int and 0 < max_bytes <= 128 * 1024 * 1024,
                "invalid total capture budget")
        self.model, self.plan, self.max_bytes = model, plan, max_bytes
        self.used_bytes = 0
        self.handles, self.expected_hooks, self.batches = [], [], []
        self.active, self.installed, self.invalid = None, False, False

    def __enter__(self):
        require(not self.installed and not self.handles, "observer already installed")
        model_state(self.model)
        modules = dict(self.model.named_modules())
        for module in modules.values():
            require(not module._forward_hooks and not module._forward_pre_hooks,
                    "existing forward hooks are not allowed")
        paths = tuple(dict.fromkeys(s.module for s in self.plan.stages))
        require(all(path in modules for path in paths), "unknown module path")
        require(len({id(modules[p]) for p in paths}) == len(paths), "aliased module paths")
        try:
            for path in paths:
                callback = self._callback(path)
                handle = modules[path].register_forward_hook(callback)
                self.handles.append(handle)
            self.expected_hooks = [(m, tuple(m._forward_hooks.items()),
                                    tuple(m._forward_pre_hooks.items())) for m in modules.values()]
            self.installed = True
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        for handle in self.handles:
            handle.remove()
        self.handles = []
        self.installed = False

    def _check_hooks(self):
        require(self.installed, "observer is not installed")
        for module, post, pre in self.expected_hooks:
            require(tuple(module._forward_hooks.items()) == post
                    and tuple(module._forward_pre_hooks.items()) == pre, "observer hooks changed")

    def _callback(self, path):
        # Explicit graph break boundary: this is a controlled *alternate* trace.
        @torch._dynamo.disable
        def hook(_module, _arguments, output):
            require(self.active is not None, "hook outside a declared batch")
            index = self.active["index"]
            require(index < len(self.plan.stages), "extra boundary invocation")
            stage = self.plan.stages[index]
            require(stage.module == path, "boundary order differs")
            require(type(output) is torch.Tensor and output.ndim > 0
                    and output.shape[0] == len(self.active["trials"]), "boundary batch shape differs")
            for row, trial in enumerate(self.active["trials"]):
                if trial in self.plan.targets:
                    tensor = output[row]
                    needed = tensor.numel() * tensor.element_size()
                    require(self.used_bytes + needed <= self.max_bytes, "total capture budget exceeded")
                    snapshot = copy_tensor(tensor, self.max_bytes - self.used_bytes)
                    self.used_bytes += len(snapshot.data)
                    self.active["events"].append(Event(index, stage, trial, snapshot))
            self.active["index"] += 1
            return None
        return hook

    def record(self, call, pass_id, batch_index, trials, cue, mixture):
        require(not self.invalid, "failed observer cannot resume")
        try:
            self._check_hooks()
            require(self.active is None, "nested batch is forbidden")
            schedule = self.plan.schedule()
            require(len(self.batches) < len(schedule), "extra batch")
            require((pass_id, batch_index, trials) == schedule[len(self.batches)],
                    "batch schedule/trial identity differs")
            self.active = {"index": 0, "trials": trials, "events": []}
            result = evaluate_batch(self.model, call, pass_id, batch_index, trials, cue, mixture)
            self._check_hooks()
            require(self.active["index"] == len(self.plan.stages), "missing boundary invocation")
            result = seal(replace(result, events=tuple(self.active["events"])))
            self.batches.append(result)
            return result
        except BaseException:
            self.invalid = True
            raise
        finally:
            self.active = None

    def finish(self):
        require(not self.invalid and len(self.batches) == len(self.plan.schedule()),
                "incomplete or failed trace")
        self._check_hooks()
        return tuple(self.batches)


def endpoint_gate(reference, observed):
    require((reference.pass_id, reference.batch_index, reference.trials)
            == (observed.pass_id, observed.batch_index, observed.trials), "endpoint identities differ")
    require(reference.inputs == observed.inputs, "reference/observed inputs differ")
    for batch in (reference, observed):
        require(batch.state_before == batch.state_after, "model state changed")
        require(batch.rng_before == batch.rng_after, "RNG changed")
        require(batch.runtime_before == batch.runtime_after, "runtime flags changed")
    require(reference.state_before == observed.state_before, "reference/observed model differs")
    require(reference.rng_before == observed.rng_before, "reference/observed RNG differs")
    require(reference.runtime_before == observed.runtime_before, "reference/observed runtime differs")
    require(same_values(reference.logits, observed.logits), "OBSERVATION_INTERFERENCE: endpoint differs")
    for batch in (reference, observed):
        require(batch.record_digest == record_digest(batch), "record digest differs")


def compare_passes(plan, reference, observed):
    require(len(reference) == len(observed) == len(plan.schedule()), "incomplete pass pair")
    maps = {"pass1": {}, "pass2": {}}
    for expected, baseline, trace in zip(plan.schedule(), reference, observed):
        require((trace.pass_id, trace.batch_index, trace.trials) == expected, "trace schedule differs")
        endpoint_gate(baseline, trace)
        expected_keys = tuple((i, s, trial) for i, s in enumerate(plan.stages)
                              for trial in trace.trials if trial in plan.targets)
        actual_keys = tuple((e.index, e.stage, e.trial_id) for e in trace.events)
        require(actual_keys == expected_keys, "missing/duplicate/relabelled trace event")
        for event in trace.events:
            key = event.index, event.trial_id
            require(key not in maps[trace.pass_id], "duplicate trace key")
            maps[trace.pass_id][key] = event.tensor
    differences = []
    for trial in plan.trials:
        if trial not in plan.targets:
            continue
        first = None
        for index, stage in enumerate(plan.stages):
            one, two = maps["pass1"][index, trial], maps["pass2"][index, trial]
            require((one.dtype, one.shape) == (two.dtype, two.shape), "cross-pass tensor metadata differs")
            if not same_values(one, two) and first is None:
                first = {"index": index, "module": stage.module, "branch": stage.branch}
        differences.append({"trial_id": trial, "first_observed_boundary": first})
    return {"status": "PROTOTYPE_ENDPOINT_GATED_TRACE", "targets": differences,
            "intermediate_equivalence_to_uninstrumented_compilation_proven": False,
            "scope": "synthetic prototype only; no production model/root-cause certification"}

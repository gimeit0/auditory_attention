"""Synthetic integration with the unchanged, SHA-pinned CPU observer.

This adds disk captures and structural wrapper binding, not production authority.
Hooks still introduce graph breaks. No compile/runtime/threshold overrides here.
"""

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import sys

import torch
from torch._dynamo.eval_frame import OptimizedModule

_BASE = Path(__file__).resolve().parent.parent / "targeted_trace_20260911"
_SHA = "dcbe162257fc130450a2f2b4a2fd5680caded503d10c67b704c6a0331ec86328"
if hashlib.sha256((_BASE / "trace_observer.py").read_bytes()).hexdigest() != _SHA:
    raise RuntimeError("reviewed base observer changed")
sys.path.insert(0, str(_BASE))
import trace_observer as base  # noqa: E402
if Path(base.__file__).resolve() != (_BASE / "trace_observer.py").resolve():
    raise RuntimeError("unexpected base observer import")

from stream_capture import BlobRef, CaptureStore  # noqa: E402


@dataclass(frozen=True)
class WrapperBinding:
    outer: object
    wrapper: object
    cnn: object
    plan: object
    modules: tuple

    def check(self):
        base.require(self.outer._modules.get("model") is self.wrapper
                     and type(self.wrapper) is OptimizedModule
                     and self.wrapper._modules.get("_orig_mod") is self.cnn,
                     "compiled wrapper binding changed")
        current = dict(self.outer.named_modules())
        base.require(all(current.get(path) is module for path, module in self.modules),
                     "bound stage module changed")


def bind_compiled_outer(outer, relative_plan, *, expected_outer_type, expected_cnn_type):
    """Exact object/path binding only; caller-provided types are NOT provenance."""
    base.require(type(relative_plan) is base.Plan and type(outer) is expected_outer_type,
                 "unexpected outer model or plan")
    wrapper = outer._modules.get("model")
    base.require(type(wrapper) is OptimizedModule, "expected compiled inner model")
    cnn = wrapper._modules.get("_orig_mod")
    base.require(type(cnn) is expected_cnn_type, "unexpected raw CNN type")
    plan = replace(relative_plan, stages=tuple(
        base.Stage("model._orig_mod." + s.module, s.branch) for s in relative_plan.stages))
    modules = dict(outer.named_modules())
    paths = tuple(dict.fromkeys(s.module for s in plan.stages))
    base.require(all(p in modules for p in paths), "missing bound stage")
    selected = tuple((p, modules[p]) for p in paths)
    base.require(len({id(m) for _, m in selected}) == len(selected), "aliased bound stage")
    result = WrapperBinding(outer, wrapper, cnn, plan, selected)
    result.check()
    return result


class StreamObserver(base.Observer):
    def __init__(self, model, plan, store, binding=None):
        base.require(type(store) is CaptureStore, "expected capture store")
        super().__init__(model, plan)
        self.store, self.binding = store, binding
        if binding is not None:
            base.require(binding.outer is model and binding.plan == plan, "binding/observer mismatch")

    def _check_hooks(self):
        super()._check_hooks()
        if self.binding is not None:
            self.binding.check()

    def _callback(self, path):
        @torch._dynamo.disable
        def hook(_module, _arguments, output):
            base.require(self.active is not None, "hook outside a declared batch")
            index = self.active["index"]
            base.require(index < len(self.plan.stages), "extra boundary invocation")
            stage = self.plan.stages[index]
            base.require(stage.module == path, "boundary order differs")
            base.require(type(output) is torch.Tensor and output.ndim > 0
                         and output.shape[0] == len(self.active["trials"]), "boundary batch shape differs")
            for row, trial in enumerate(self.active["trials"]):
                if trial in self.plan.targets:
                    ref = self.store.capture(output[row], (*self.current_batch, index, trial))
                    self.active["events"].append(base.Event(index, stage, trial, ref))
            self.active["index"] += 1
        return hook

    def record(self, call, pass_id, batch_index, trials, cue, mixture):
        self.current_batch = pass_id, batch_index
        return super().record(call, pass_id, batch_index, trials, cue, mixture)


def compare_streamed(plan, reference, observed, store):
    base.require(len(reference) == len(observed) == len(plan.schedule()), "incomplete pass pair")
    captures = {"pass1": {}, "pass2": {}}
    seen = []
    for expected, baseline, record in zip(plan.schedule(), reference, observed):
        base.require((record.pass_id, record.batch_index, record.trials) == expected, "trace schedule differs")
        base.endpoint_gate(baseline, record)
        keys = tuple((i, s, trial) for i, s in enumerate(plan.stages)
                     for trial in record.trials if trial in plan.targets)
        base.require(tuple((e.index, e.stage, e.trial_id) for e in record.events) == keys,
                     "missing/duplicate/relabelled trace event")
        for event in record.events:
            ref = event.tensor
            key = record.pass_id, record.batch_index, event.index, event.trial_id
            base.require(type(ref) is BlobRef and ref.key == key, "capture/event binding differs")
            captures[record.pass_id][event.index, event.trial_id] = ref
            seen.append(ref)
    base.require(tuple(seen) == tuple(store.refs), "unreferenced or reordered stored captures")
    differences = []
    for trial in plan.trials:
        if trial not in plan.targets:
            continue
        first = None
        for index, stage in enumerate(plan.stages):
            one, two = captures["pass1"][index, trial], captures["pass2"][index, trial]
            equal = store.compare(one, two)
            if not equal and first is None:
                first = {"index": index, "module": stage.module, "branch": stage.branch}
        differences.append({"trial_id": trial, "first_observed_boundary": first})
    return {"status": "SYNTHETIC_STREAM_ENDPOINT_GATED", "targets": differences,
            "capture_bytes": store.used_bytes, "largest_encoded_chunk": store.peak_payload_bytes,
            "intermediate_equivalence_to_uninstrumented_compilation_proven": False,
            "production_authority_validated": False, "ready_for_gpu": False}

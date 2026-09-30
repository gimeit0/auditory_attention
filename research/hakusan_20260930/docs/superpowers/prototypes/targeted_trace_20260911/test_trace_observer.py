"""Small CPU fixtures; no checkpoint, bank audio, GPU or job submission."""

from dataclasses import replace
import unittest

import torch

from trace_observer import (
    Observer, Plan, Stage, TraceError, compare_passes, copy_tensor,
    endpoint_gate, evaluate_batch,
)


class Gain(torch.nn.Module):
    def __init__(self, batch_dependent=False):
        super().__init__()
        self.batch_dependent = batch_dependent

    def forward(self, value):
        return value + (value.shape[0] if self.batch_dependent else 0.0)


class Toy(torch.nn.Module):
    def __init__(self, batch_dependent=False):
        super().__init__()
        with torch.random.fork_rng(devices=[]):
            self.shared = torch.nn.Linear(3, 3, bias=False, dtype=torch.float64)
        with torch.no_grad():
            self.shared.weight.copy_(torch.eye(3, dtype=torch.float64))
        self.gain = Gain(batch_dependent)
        self.head = torch.nn.Identity()
        self.eval().requires_grad_(False)

    def forward(self, cue, mixture):
        cue = self.shared(cue)
        mixture = self.shared(mixture)
        mixture = self.gain(mixture)
        return self.head(cue + mixture)


def plan():
    return Plan((9000, 1428, 2698, 4126), (9000, 1428, 2698, 4126),
                (Stage("shared", "cue"), Stage("shared", "mixture"),
                 Stage("gain", "mixture"), Stage("head", "logits")), (2, 1))


def inputs(ids, value_offset=0.):
    values = torch.tensor([[t % 11 + value_offset, t % 7, t % 5] for t in ids],
                          dtype=torch.float64)
    return values + 0.25, values + 0.5


def baseline(model, trace_plan, call=None):
    invoke = model if call is None else call
    return tuple(evaluate_batch(model, invoke, p, i, ids, *inputs(ids))
                 for p, i, ids in trace_plan.schedule())


def traced(model, trace_plan, compiled=False, max_bytes=16 * 1024 * 1024):
    with Observer(model, trace_plan, max_bytes) as observer:
        call = torch.compile(model, backend="eager") if compiled else model
        for p, i, ids in trace_plan.schedule():
            observer.record(call, p, i, ids, *inputs(ids))
        return observer.finish(), observer.used_bytes


class TraceTests(unittest.TestCase):
    def test_exact_shared_module_branch_order(self):
        trace_plan = plan()
        reference = baseline(Toy(), trace_plan)
        observed, used = traced(Toy(), trace_plan)
        result = compare_passes(trace_plan, reference, observed)
        self.assertTrue(all(x["first_observed_boundary"] is None for x in result["targets"]))
        self.assertEqual([(e.stage.branch, e.trial_id) for e in observed[0].events[:4]],
                         [("cue", 9000), ("cue", 1428), ("mixture", 9000), ("mixture", 1428)])
        self.assertEqual(used, 2 * 4 * 4 * 3 * 8)

    def test_known_batch_dependent_first_boundary(self):
        trace_plan = plan()
        reference = baseline(Toy(True), trace_plan)
        observed, _ = traced(Toy(True), trace_plan)
        result = compare_passes(trace_plan, reference, observed)
        self.assertTrue(all(x["first_observed_boundary"] ==
                            {"index": 2, "module": "gain", "branch": "mixture"}
                            for x in result["targets"]))
        self.assertFalse(result["intermediate_equivalence_to_uninstrumented_compilation_proven"])

    def test_dynamo_eager_backend_endpoint_gate(self):
        # Tests Dynamo + explicit hook graph breaks; NOT Inductor or A100 numerics.
        # Synthetic isolation only: a fresh model does not imply a fresh Dynamo cache.
        # Production validation must use separate cold processes instead of this reset.
        torch._dynamo.reset()
        self.addCleanup(torch._dynamo.reset)
        trace_plan = plan()
        model = Toy()
        reference = baseline(model, trace_plan, torch.compile(model, backend="eager"))
        torch._dynamo.reset()
        observed, _ = traced(Toy(), trace_plan, compiled=True)
        result = compare_passes(trace_plan, reference, observed)
        self.assertEqual(result["status"], "PROTOTYPE_ENDPOINT_GATED_TRACE")

    def test_interfering_callable_is_rejected(self):
        trace_plan = plan()
        reference = baseline(Toy(), trace_plan)
        model = Toy()
        with Observer(model, trace_plan) as observer:
            p, i, ids = trace_plan.schedule()[0]
            actual = observer.record(lambda c, m: model(c, m) + 0.125, p, i, ids, *inputs(ids))
        with self.assertRaisesRegex(TraceError, "OBSERVATION_INTERFERENCE"):
            endpoint_gate(reference[0], actual)

    def test_wrong_trial_order_is_rejected(self):
        trace_plan = plan()
        model = Toy()
        with Observer(model, trace_plan) as observer:
            with self.assertRaisesRegex(TraceError, "schedule/trial"):
                observer.record(model, "pass1", 0, (1428, 9000), *inputs((1428, 9000)))
            with self.assertRaisesRegex(TraceError, "cannot resume"):
                observer.record(model, *trace_plan.schedule()[0], *inputs((9000, 1428)))

    def test_wrong_pass_rejected(self):
        model = Toy()
        with Observer(model, plan()) as observer:
            with self.assertRaisesRegex(TraceError, "schedule/trial"):
                observer.record(model, "pass2", 0, (9000, 1428), *inputs((9000, 1428)))

    def test_missing_boundary(self):
        model = Toy()
        with Observer(model, plan()) as observer:
            with self.assertRaisesRegex(TraceError, "missing boundary"):
                observer.record(lambda c, m: c + m, "pass1", 0, (9000, 1428), *inputs((9000, 1428)))

    def test_extra_boundary(self):
        model = Toy()
        with Observer(model, plan()) as observer:
            with self.assertRaisesRegex(TraceError, "extra boundary"):
                observer.record(lambda c, m: model.head(model(c, m)),
                                "pass1", 0, (9000, 1428), *inputs((9000, 1428)))

    def test_wrong_module_order(self):
        bad = replace(plan(), stages=(Stage("gain", "mixture"),) + plan().stages)
        model = Toy()
        with Observer(model, bad) as observer:
            with self.assertRaisesRegex(TraceError, "boundary order"):
                observer.record(model, "pass1", 0, (9000, 1428), *inputs((9000, 1428)))

    def test_existing_hooks_rejected(self):
        model = Toy()
        handle = model.shared.register_forward_hook(lambda *_: None)
        self.addCleanup(handle.remove)
        with self.assertRaisesRegex(TraceError, "existing forward hooks"):
            with Observer(model, plan()):
                pass

    def test_later_hook_replacement_rejected(self):
        model = Toy()
        with Observer(model, plan()) as observer:
            model.shared._forward_hooks.clear()
            with self.assertRaisesRegex(TraceError, "hooks changed"):
                observer.record(model, "pass1", 0, (9000, 1428), *inputs((9000, 1428)))

    def test_hooks_removed_on_error(self):
        model = Toy()
        with self.assertRaises(TraceError):
            with Observer(model, plan(), max_bytes=1) as observer:
                observer.record(model, "pass1", 0, (9000, 1428), *inputs((9000, 1428)))
        self.assertTrue(all(not m._forward_hooks for m in model.modules()))

    def test_budget_before_copy(self):
        with self.assertRaisesRegex(TraceError, "tensor byte budget"):
            copy_tensor(torch.zeros(5), max_bytes=4)
        for budget in (0, True, 128 * 1024 * 1024 + 1):
            with self.assertRaisesRegex(TraceError, "invalid total capture budget"):
                Observer(Toy(), plan(), max_bytes=budget)

    def test_nonfinite_output(self):
        for value in (float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaisesRegex(TraceError, "nonfinite"):
                copy_tensor(torch.tensor([value]))

    def test_unsupported_dtype(self):
        with self.assertRaisesRegex(TraceError, "unsupported tensor dtype"):
            copy_tensor(torch.tensor([1], dtype=torch.int64))

    def test_snapshot_does_not_alias(self):
        tensor = torch.arange(3, dtype=torch.float32)
        snapshot = copy_tensor(tensor)
        tensor.add_(1)
        self.assertNotEqual(snapshot.data, copy_tensor(tensor).data)

    def test_noncontiguous_metadata(self):
        tensor = torch.arange(12, dtype=torch.float64).reshape(3, 4).t()
        snapshot = copy_tensor(tensor)
        self.assertEqual(snapshot.stride, (1, 4))
        self.assertEqual(snapshot.data, copy_tensor(tensor.contiguous()).data)

    def test_parameter_change_rejected(self):
        model = Toy()
        def mutate(c, m):
            model.shared.weight.add_(1)
            return model(c, m)
        with self.assertRaisesRegex(TraceError, "model state changed"):
            evaluate_batch(model, mutate, "pass1", 0, (9000,), *inputs((9000,)))

    def test_rng_change_rejected(self):
        model = Toy()
        def mutate(c, m):
            torch.rand(1)
            return model(c, m)
        with self.assertRaisesRegex(TraceError, "RNG changed"):
            evaluate_batch(model, mutate, "pass1", 0, (9000,), *inputs((9000,)))

    def test_training_mode_rejected(self):
        with self.assertRaisesRegex(TraceError, "eval mode"):
            baseline(Toy().train(), plan())

    def test_unfrozen_parameters_rejected(self):
        with self.assertRaisesRegex(TraceError, "must be frozen"):
            baseline(Toy().requires_grad_(True), plan())

    def test_input_mutation_rejected(self):
        model = Toy()
        def mutate(c, m):
            c.add_(1)
            return model(c, m)
        with self.assertRaisesRegex(TraceError, "input tensor changed"):
            evaluate_batch(model, mutate, "pass1", 0, (9000,), *inputs((9000,)))

    def test_incomplete_trace_rejected(self):
        with Observer(Toy(), plan()) as observer:
            with self.assertRaisesRegex(TraceError, "incomplete"):
                observer.finish()

    def test_event_relabel_duplicate_missing_rejected(self):
        trace_plan = plan()
        reference = baseline(Toy(), trace_plan)
        observed, _ = traced(Toy(), trace_plan)
        original = observed[0]
        for events in (original.events[:-1], original.events + original.events[:1],
                       (replace(original.events[0], trial_id=1428),) + original.events[1:]):
            with self.subTest(events=len(events)), self.assertRaisesRegex(TraceError, "trace event|record digest"):
                altered = (replace(original, events=events),) + observed[1:]
                compare_passes(trace_plan, reference, altered)

    def test_event_payload_change_is_rejected(self):
        trace_plan = plan()
        reference = baseline(Toy(), trace_plan)
        observed, _ = traced(Toy(), trace_plan)
        original = observed[0]
        event = original.events[0]
        changed = replace(event, tensor=replace(event.tensor, data=b"x" * len(event.tensor.data)))
        altered = (replace(original, events=(changed,) + original.events[1:]),) + observed[1:]
        with self.assertRaisesRegex(TraceError, "record digest"):
            compare_passes(trace_plan, reference, altered)

    def test_runtime_change_is_rejected(self):
        model = Toy()
        before = torch.backends.cudnn.benchmark
        self.addCleanup(setattr, torch.backends.cudnn, "benchmark", before)
        def mutate(c, m):
            torch.backends.cudnn.benchmark = not before
            return model(c, m)
        with self.assertRaisesRegex(TraceError, "runtime flags changed"):
            evaluate_batch(model, mutate, "pass1", 0, (9000,), *inputs((9000,)))

    def test_reference_input_mismatch_rejected(self):
        model = Toy()
        trace_plan = plan()
        reference = baseline(model, trace_plan)
        observed, _ = traced(Toy(), trace_plan)
        wrong = replace(reference[0], inputs=(copy_tensor(torch.zeros(2, 3)), reference[0].inputs[1]))
        with self.assertRaisesRegex(TraceError, "inputs differ"):
            endpoint_gate(wrong, observed[0])

    def test_invalid_plan(self):
        for kwargs in ({"trials": (1, 1)}, {"targets": (55,)}, {"batch_sizes": (0, 1)},
                       {"trials": (True,)}, {"stages": ()}):
            with self.subTest(kwargs=kwargs), self.assertRaises(TraceError):
                replace(plan(), **kwargs)


if __name__ == "__main__":
    unittest.main(verbosity=2)

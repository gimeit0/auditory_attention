"""Exact collection seals and source-bound worker fixtures; CPU, not A100."""

import ast
from collections import UserList, deque
import hashlib
import importlib.util
import pathlib
import sys
import unittest
from unittest import mock

import torch


PACKAGE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "collection_worker_fixtures", PACKAGE / "test_numeric_diag.py"
)
fixtures = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fixtures
spec.loader.exec_module(fixtures)
diag = fixtures.diagnose
SOURCE = pathlib.Path(
    "/Users/gigi/projects/auditory_attention/src/spatial_attn_lightning.py"
)
SOURCE_SHA = "6531a6548cc24dcdcffdb14c8b6b1d7040bc6f1f7ea53dd870d4d021327467c9"


def source_window(maxlen=1000):
    """Execute only the exact deque expression from the SHA-bound source."""
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise AssertionError("frozen model source fixture SHA differs")
    model = next(
        node
        for node in ast.parse(raw).body
        if isinstance(node, ast.ClassDef) and node.name == "BinauralAttentionModule"
    )
    init = next(
        node
        for node in model.body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    assignment = next(
        node
        for node in init.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and target.attr == "_amp_overflow_window"
            for target in node.targets
        )
    )
    expression = ast.Expression(assignment.value)
    if ast.dump(expression) != ast.dump(
        ast.parse("deque(maxlen=overflow_window_steps)", mode="eval")
    ):
        raise AssertionError("source deque constructor changed")
    return eval(
        compile(expression, str(SOURCE), "eval"),
        {"__builtins__": {}, "deque": deque, "overflow_window_steps": maxlen},
    )


class CollectionSealTests(unittest.TestCase):
    def test_source_amp_window_is_accepted_without_conversion(self):
        window = source_window()
        window.extend([0, 1, 0])
        model = torch.nn.Module()
        model._amp_overflow_window = window
        before = diag._module_config_fingerprint(model)
        self.assertEqual(before, diag._module_config_fingerprint(model))
        self.assertIs(model._amp_overflow_window, window)
        self.assertIs(type(window), deque)
        self.assertEqual(list(window), [0, 1, 0])
        self.assertEqual(window.maxlen, 1000)

    def test_exact_torch_size_preserves_type_identity_and_dimensions(self):
        size = torch.Size([1, 2, 3])
        seal = diag._container_execution_identity(size)
        self.assertEqual(seal, diag._container_execution_identity(size))
        self.assertIn(id(type(size)), seal)
        self.assertIn(id(size), seal)
        self.assertNotEqual(seal, diag._container_execution_identity((1, 2, 3)))
        self.assertNotEqual(
            seal, diag._container_execution_identity(torch.Size([1, 4, 3]))
        )
        same = diag._container_execution_identity(torch.Size([1, 2, 3]))
        different = diag._container_execution_identity(torch.Size([1, 4, 3]))
        self.assertEqual(seal[:1] + seal[2:], same[:1] + same[2:])
        self.assertNotEqual(seal[:1] + seal[2:], different[:1] + different[2:])

    def test_deque_mutations_are_detected(self):
        for mutate in (
            lambda q: q.append(1),
            lambda q: q.popleft(),
            lambda q: q.rotate(1),
            lambda q: q.__setitem__(0, 9),
            lambda q: q.clear(),
        ):
            with self.subTest(mutate=mutate):
                window = deque([0, 1, 2], maxlen=3)
                before = diag._container_execution_identity(window)
                mutate(window)
                self.assertNotEqual(before, diag._container_execution_identity(window))

    def test_deque_replacement_is_detected(self):
        left, right = deque([0], maxlen=10), deque([0], maxlen=10)
        self.assertNotEqual(
            diag._container_execution_identity(left),
            diag._container_execution_identity(right),
        )

    def test_deque_capacity_is_in_seal_even_with_identity_normalized(self):
        left, right = deque([0], maxlen=10), deque([0], maxlen=20)
        same = deque([0], maxlen=10)
        a = diag._container_execution_identity(left)
        b = diag._container_execution_identity(right)
        c = diag._container_execution_identity(same)
        self.assertEqual(a[:1] + a[2:], c[:1] + c[2:])
        self.assertNotEqual(a[:1] + a[2:], b[:1] + b[2:])

    def test_unbounded_and_zero_capacity_deque_are_recorded(self):
        for maximum in (None, 0):
            with self.subTest(maxlen=maximum):
                window = deque(maxlen=maximum)
                self.assertEqual(
                    diag._container_execution_identity(window),
                    diag._container_execution_identity(window),
                )
                self.assertIs(window.maxlen, maximum)

    def test_nested_content_and_cycles_are_bounded(self):
        nested = [1]
        window = deque([nested])
        before = diag._container_execution_identity(window)
        nested.append(2)
        self.assertNotEqual(before, diag._container_execution_identity(window))
        window.append(window)
        cycle = diag._container_execution_identity(window)
        self.assertEqual(cycle, diag._container_execution_identity(window))

    def test_work_and_depth_budgets_reject_large_or_deep_deques(self):
        with self.assertRaisesRegex(diag.DiagnosticError, "budget|limit"):
            diag._container_execution_identity(deque([None] * 600001))
        value = None
        for _ in range(15):
            value = deque([value])
        with self.assertRaisesRegex(diag.DiagnosticError, "depth|limit"):
            diag._container_execution_identity(value)

    def test_torch_size_work_budget_is_not_bypassed(self):
        with self.assertRaisesRegex(diag.DiagnosticError, "budget|limit"):
            diag._container_execution_identity(torch.Size([1] * 600001))

    def test_tensor_payload_is_never_read_or_transformed(self):
        tensor = torch.tensor([1.0])
        value = deque([tensor])
        with (
            mock.patch.object(
                torch.Tensor, "numpy", side_effect=AssertionError("numpy")
            ),
            mock.patch.object(
                torch.Tensor, "tolist", side_effect=AssertionError("tolist")
            ),
            mock.patch.object(torch.Tensor, "item", side_effect=AssertionError("item")),
            mock.patch.object(torch.Tensor, "cpu", side_effect=AssertionError("cpu")),
        ):
            self.assertTrue(diag._container_execution_identity(value))
        self.assertIs(value[0], tensor)

    def test_deque_mutation_during_iteration_is_reported(self):
        window = deque([1, 2, 3])
        original = diag._container_execution_identity

        def observe(value, *args, **kwargs):
            if type(value) is int and value == 1:
                window.append(4)
            return original(value, *args, **kwargs)

        with mock.patch.object(diag, "_container_execution_identity", observe):
            with self.assertRaisesRegex(
                diag.DiagnosticError, "deque changed.*path=module.window"
            ):
                original(window, _path="module.window")

    def test_plain_collection_subclasses_and_unknown_range_remain_rejected(self):
        class ListSubclass(list):
            pass

        class TupleSubclass(tuple):
            pass

        for value in (ListSubclass([1]), TupleSubclass([1]), range(3)):
            with self.subTest(type=type(value).__name__):
                with self.assertRaisesRegex(diag.DiagnosticError, "collection.*path="):
                    diag._container_execution_identity(value, _path="module.unknown")

    def test_unknown_type_cannot_impersonate_torch_size_by_name(self):
        class Impersonator(tuple):
            pass

        Impersonator.__module__ = "torch"
        Impersonator.__qualname__ = "Size"
        with self.assertRaisesRegex(diag.DiagnosticError, "collection"):
            diag._container_execution_identity(Impersonator([1, 2]))

    def test_tensor_identity_not_payload_is_the_collection_seal_contract(self):
        tensor = torch.tensor([1.0])
        window = deque([tensor])
        before = diag._container_execution_identity(window)
        tensor.add_(1)
        # Payload/version checks for registered state are elsewhere; this seal
        # must not synchronize or read tensor data to detect such modifications.
        self.assertEqual(before, diag._container_execution_identity(window))
        window[0] = tensor.clone()
        self.assertNotEqual(before, diag._container_execution_identity(window))

    def test_callable_child_is_not_invoked_but_code_change_is_detected(self):
        events = []

        def child():
            events.append("invoked")

        window = deque([child])
        before = diag._execution_configuration_fingerprint(window)
        original = child.__code__

        # Preserve the single free variable to allow a legitimate code assignment.
        def changed():
            events.append("changed")

        try:
            child.__code__ = changed.__code__
            self.assertNotEqual(
                before, diag._execution_configuration_fingerprint(window)
            )
        finally:
            child.__code__ = original
        self.assertEqual(events, [])

    def test_callable_child_configuration_change_is_detected(self):
        options = {"gain": 1}

        def child():
            return options["gain"]

        window = deque([child])
        before = diag._execution_configuration_fingerprint(window)
        options["gain"] = 2
        self.assertNotEqual(before, diag._execution_configuration_fingerprint(window))

    def test_deque_subclasses_cannot_dispatch_iteration_or_call(self):
        events = []

        class Hostile(deque):
            def __iter__(self):
                events.append("iter")
                raise AssertionError("iteration dispatched")

            def __len__(self):
                events.append("len")
                raise AssertionError("length dispatched")

            def __repr__(self):
                events.append("repr")
                raise AssertionError("repr dispatched")

        class CallableHostile(Hostile):
            def __call__(self):
                events.append("call")

        for value in (Hostile([1]), CallableHostile([1])):
            with self.subTest(type=type(value).__name__):
                with self.assertRaisesRegex(diag.DiagnosticError, "collection"):
                    diag._container_execution_identity(value)
        self.assertEqual(events, [])

    def test_unknown_collection_error_contains_static_type_and_path(self):
        with self.assertRaises(diag.DiagnosticError) as caught:
            diag._container_execution_identity(UserList(), _path="module.unknown")
        self.assertIn("path=module.unknown", str(caught.exception))
        self.assertIn("type=collections.UserList", str(caught.exception))

    def test_unknown_mapping_error_contains_static_type_and_path(self):
        from collections import UserDict

        with self.assertRaises(diag.DiagnosticError) as caught:
            diag._container_execution_identity(UserDict(), _path="module.mapping")
        self.assertIn("path=module.mapping", str(caught.exception))
        self.assertIn("type=collections.UserDict", str(caught.exception))

    def test_nested_error_keeps_parent_attribute_path(self):
        with self.assertRaises(diag.DiagnosticError) as caught:
            diag._container_execution_identity(
                deque([UserList()]), _path="module._amp_overflow_window"
            )
        self.assertIn("path=module._amp_overflow_window[0]", str(caught.exception))
        self.assertIn("type=collections.UserList", str(caught.exception))

    def test_error_does_not_dispatch_metaclass_or_instance_repr(self):
        events = []

        class Meta(type):
            def __getattribute__(cls, name):
                if name in {"__module__", "__qualname__"}:
                    events.append(name)
                return super().__getattribute__(name)

        class Hostile(deque, metaclass=Meta):
            def __repr__(self):
                events.append("repr")
                return "poison"

        with self.assertRaisesRegex(diag.DiagnosticError, "Hostile"):
            diag._container_execution_identity(Hostile(), _path="module.queue")
        self.assertEqual(events, [])

    def test_torch_module_containers_remain_callable_not_generic_collections(self):
        # ModuleList/Sequential are legitimate callable model containers.
        for module in (
            torch.nn.ModuleList([torch.nn.Identity()]),
            torch.nn.Sequential(),
        ):
            with self.subTest(type=type(module).__name__):
                self.assertTrue(diag._container_execution_identity(module))

    def test_error_does_not_execute_metaclass_property(self):
        events = []

        class Meta(type):
            @property
            def __module__(cls):
                events.append("property")
                raise AssertionError("metaclass property dispatched")

        class Hostile(deque, metaclass=Meta):
            pass

        with self.assertRaisesRegex(diag.DiagnosticError, "Hostile"):
            diag._container_execution_identity(Hostile(), _path="module.queue")
        self.assertEqual(events, [])


class SourceAttributeWorkerTests(unittest.TestCase):
    def model_and_evaluator(self):
        model = fixtures._Task4Model()
        model._amp_overflow_window = source_window()
        model._amp_overflow_window.extend([0, 0, 1])
        model._source_shape_fixture = torch.Size([2, 4])
        evaluator = fixtures._Task4Evaluator(model_to_load=model)
        return model, evaluator

    def test_source_attributes_pass_worker_issuance_and_live_reverification(self):
        model, evaluator = self.model_and_evaluator()
        window = model._amp_overflow_window
        with fixtures._task4_attested_context(evaluator, model):
            self.assertTrue(
                diag._live_inference_attestation(model, "collection_fixture")
            )
            self.assertTrue(
                diag._live_inference_attestation(model, "collection_fixture_repeat")
            )
        self.assertIs(model._amp_overflow_window, window)
        self.assertEqual(list(window), [0, 0, 1])

    def test_post_issuance_window_mutation_rejected_before_prediction(self):
        for change in ("content", "replacement", "capacity", "shape"):
            with self.subTest(change=change):
                model, evaluator = self.model_and_evaluator()
                with fixtures._task4_attested_context(evaluator, model):
                    if change == "content":
                        model._amp_overflow_window.append(1)
                    elif change == "replacement":
                        model._amp_overflow_window = deque([0, 0, 1], maxlen=1000)
                    elif change == "capacity":
                        model._amp_overflow_window = deque([0, 0, 1], maxlen=999)
                    else:
                        model._source_shape_fixture = torch.Size([4, 2])
                    with self.assertRaises(diag.DiagnosticError):
                        diag._live_inference_attestation(model, "changed_collection")

    def test_full_default_capacity_window_fits_worker_seal_budget(self):
        model, evaluator = self.model_and_evaluator()
        model._amp_overflow_window.extend([0] * 1000)
        self.assertEqual(len(model._amp_overflow_window), 1000)
        with fixtures._task4_attested_context(evaluator, model):
            self.assertTrue(diag._live_inference_attestation(model, "full_window"))


if __name__ == "__main__":
    unittest.main()

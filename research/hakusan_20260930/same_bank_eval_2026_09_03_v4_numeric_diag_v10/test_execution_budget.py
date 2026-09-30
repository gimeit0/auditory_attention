"""Real PyTorch module traversal and immutable-only bytecode reuse regressions."""

import contextlib
import dis
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import torch


spec = importlib.util.spec_from_file_location(
    "execution_budget_diag", Path(__file__).with_name("diagnose_batch_invariance.py")
)
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)


@contextlib.contextmanager
def budget_scope():
    budget = diag._SealBudget()
    token = diag._ACTIVE_SEAL_BUDGET.set(budget)
    try:
        yield budget
    finally:
        diag._ACTIVE_SEAL_BUDGET.reset(token)


def module_fixture(count=66):
    # 67 actual torch modules, matching the observed full-model inventory size.
    # Tiny weights and no forward; not a formal40/architecture substitute.
    model = torch.nn.Sequential(*(torch.nn.Linear(1, 1) for _ in range(count)))
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    return model


class ExecutionBudgetTests(unittest.TestCase):
    def test_repeated_real_module_inventory_fits_original_budget(self):
        model = module_fixture()
        with budget_scope() as budget:
            first = diag._model_execution_fingerprint(model)
        self.assertEqual(len(first), 68)  # Includes the audio-transform record.
        self.assertLessEqual(budget.work, 200_000)
        self.assertEqual(first, diag._model_execution_fingerprint(model))

    def test_immutable_code_is_disassembled_once_per_check(self):
        def function(value):
            return value.example

        original = dis.get_instructions
        with (
            budget_scope(),
            mock.patch.object(dis, "get_instructions", wraps=original) as decode,
        ):
            first = diag._seal_instructions(function.__code__)
            second = diag._seal_instructions(function.__code__)
            self.assertIs(first, second)
            self.assertEqual(decode.call_count, 1)
        with mock.patch.object(dis, "get_instructions", wraps=original) as decode:
            diag._seal_instructions(function.__code__)
            self.assertEqual(decode.call_count, 1)

    def test_code_replacement_does_not_reuse_old_analysis(self):
        def first(value):
            return value.first

        def second(value):
            return value.second

        with budget_scope():
            before = diag._seal_instructions(first.__code__)
            first.__code__ = second.__code__
            after = diag._seal_instructions(first.__code__)
        self.assertIsNot(before, after)
        self.assertNotEqual(
            [(item.opname, item.argval) for item in before],
            [(item.opname, item.argval) for item in after],
        )

    def test_repeated_live_attributes_are_not_cached(self):
        target = types.SimpleNamespace(value=1)

        def function():
            return target.value

        with budget_scope():
            before = diag._callable_graph_fingerprint(function)
            target.value = 2
            after = diag._callable_graph_fingerprint(function)
        self.assertNotEqual(before, after)

    def test_work_limit_still_rejects(self):
        with budget_scope() as budget:
            budget.visit(cost=600_000)
            self.assertEqual(budget.work, 600_000)
            with self.assertRaisesRegex(diag.DiagnosticError, "work budget"):
                budget.visit()

    def test_work_limit_cannot_be_supplied_by_caller(self):
        with self.assertRaises(TypeError):
            diag._SealBudget(max_work=1_000_000)

    def test_distinct_work_above_old_limit_has_fixed_new_boundary(self):
        with budget_scope() as budget:
            for _ in range(3):
                budget.visit(cost=200_000)
            with self.assertRaisesRegex(diag.DiagnosticError, "work budget"):
                budget.visit(cost=1)

    def test_repeated_literal_default_anchors_fit_budget(self):
        def function(value=1, scale=0.5, label="frozen", optional=None):
            return value

        with budget_scope() as budget:
            first = diag._callable_anchor(function)
            for _ in range(100_000):
                self.assertEqual(first, diag._callable_anchor(function))
        self.assertLessEqual(budget.work, 200_000)

    def test_mutable_default_contents_are_never_cached(self):
        def function(value=[1], *, options={"factor": 1}):
            return value

        with budget_scope():
            first = diag._callable_anchor(function)
            function.__defaults__[0].append(2)
            second = diag._callable_anchor(function)
            self.assertNotEqual(first, second)
            function.__kwdefaults__["options"]["factor"] = 2
            self.assertNotEqual(second, diag._callable_anchor(function))

    def test_literal_default_rebinding_is_detected(self):
        def function(value=1):
            return value

        with budget_scope():
            first = diag._callable_anchor(function)
            function.__defaults__ = None
            absent = diag._callable_anchor(function)
            self.assertNotEqual(first, absent)
            function.__defaults__ = (1,)
            restored = diag._callable_anchor(function)
            self.assertNotEqual(absent, restored)
            function.__defaults__ = (2,)
            self.assertNotEqual(restored, diag._callable_anchor(function))

    def test_default_records_match_uncached_sealer(self):
        cases = (None, (), (None, True, 7, -0.0, float("nan"), "text", b"bytes"))
        with budget_scope():
            for value in cases:
                expected = diag._container_execution_identity(value)
                self.assertEqual(expected, diag._default_anchor_identity(value))
                self.assertEqual(expected, diag._default_anchor_identity(value))

    def test_default_cache_is_identity_bound_and_per_check(self):
        left, right = tuple([1, "x"]), tuple([1, "x"])
        self.assertIsNot(left, right)
        with budget_scope() as budget:
            first = diag._default_anchor_identity(left)
            self.assertIs(first, diag._default_anchor_identity(left))
            second = diag._default_anchor_identity(right)
            self.assertNotEqual(first, second)
            self.assertIs(budget.literal_defaults[id(left)][0], left)
            self.assertIs(budget.literal_defaults[id(right)][0], right)
        with budget_scope() as budget:
            self.assertFalse(budget.literal_defaults)
            self.assertEqual(first, diag._default_anchor_identity(left))

    def test_nested_mutable_tuple_is_not_cached(self):
        value = (([1],),)
        with budget_scope() as budget:
            before = diag._default_anchor_identity(value)
            value[0][0].append(2)
            self.assertNotEqual(before, diag._default_anchor_identity(value))
            self.assertNotIn(id(value), budget.literal_defaults)

    def test_scalar_subclass_uses_uncached_fallback(self):
        class Integer(int):
            pass

        scalar = Integer(1)
        scalar.setting = 1
        value = (scalar,)
        original = diag._container_execution_identity
        with (
            budget_scope() as budget,
            mock.patch.object(
                diag, "_container_execution_identity", wraps=original
            ) as seal,
        ):
            diag._default_anchor_identity(value)
            calls = seal.call_count
            scalar.setting = 2
            diag._default_anchor_identity(value)
            self.assertGreater(seal.call_count, calls)
            self.assertNotIn(id(value), budget.literal_defaults)

    def test_callable_default_is_not_cached(self):
        def first():
            return 1

        def replacement():
            return 2

        value = (first,)
        with budget_scope() as budget:
            before = diag._default_anchor_identity(value)
            first.__code__ = replacement.__code__
            self.assertNotEqual(before, diag._default_anchor_identity(value))
            self.assertNotIn(id(value), budget.literal_defaults)

    def test_large_default_tuple_is_rejected_before_content_seal(self):
        value = (None,) * 600_001
        with (
            budget_scope(),
            mock.patch.object(diag, "_container_execution_identity") as seal,
        ):
            with self.assertRaisesRegex(diag.DiagnosticError, "work budget"):
                diag._default_anchor_identity(value)
            seal.assert_not_called()

    def test_large_code_is_rejected_before_disassembly(self):
        def function():
            return None

        large = function.__code__.replace(co_code=b"\x09\x00" * 600_001)
        with mock.patch.object(dis, "get_instructions") as decode:
            with self.assertRaisesRegex(diag.DiagnosticError, "work budget"):
                diag._seal_instructions(large)
        decode.assert_not_called()

    def test_equal_but_distinct_code_objects_have_separate_entries(self):
        def function(value):
            return value.attribute

        left = function.__code__
        right = left.replace()
        self.assertIsNot(left, right)
        original = dis.get_instructions
        with (
            budget_scope() as budget,
            mock.patch.object(dis, "get_instructions", wraps=original) as decode,
        ):
            diag._seal_instructions(left)
            diag._seal_instructions(right)
            self.assertEqual(decode.call_count, 2)
            self.assertIs(budget.instructions[id(left)][0], left)
            self.assertIs(budget.instructions[id(right)][0], right)

    def test_many_unique_code_objects_are_all_charged(self):
        def function():
            return None

        code_objects = [function.__code__.replace() for _ in range(100)]
        original = dis.get_instructions
        with (
            budget_scope() as budget,
            mock.patch.object(dis, "get_instructions", wraps=original) as decode,
        ):
            for code in code_objects:
                diag._seal_instructions(code)
            self.assertEqual(decode.call_count, len(code_objects))
            self.assertGreaterEqual(
                budget.work, sum(len(code.co_code) // 2 for code in code_objects)
            )

    def test_failed_decode_does_not_poison_next_check(self):
        def function():
            return None

        with mock.patch.object(dis, "get_instructions", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                diag._seal_instructions(function.__code__)
        self.assertIsNone(diag._ACTIVE_SEAL_BUDGET.get())
        self.assertTrue(diag._seal_instructions(function.__code__))

    def test_invalid_code_type_is_rejected(self):
        with self.assertRaisesRegex(diag.DiagnosticError, "unsupported type"):
            diag._seal_instructions(types.SimpleNamespace(co_code=b""))
        self.assertEqual(diag._seal_instructions(None), ())

    def test_global_rebinding_in_same_check_is_detected(self):
        namespace = {"TARGET": types.SimpleNamespace(value=1)}
        exec("def function():\n    return TARGET.value\n", namespace)
        function = namespace["function"]
        with budget_scope():
            before = diag._callable_graph_fingerprint(function)
            namespace["TARGET"] = types.SimpleNamespace(value=2)
            self.assertNotEqual(before, diag._callable_graph_fingerprint(function))

    def test_defaults_kwdefaults_and_closures_remain_live(self):
        closed = types.SimpleNamespace(value=1)

        def function(value=1, *, factor=2):
            return closed.value, value, factor

        with budget_scope():
            before = diag._callable_graph_fingerprint(function)
            function.__defaults__ = (3,)
            after_default = diag._callable_graph_fingerprint(function)
            self.assertNotEqual(before, after_default)
            function.__kwdefaults__["factor"] = 4
            after_kw = diag._callable_graph_fingerprint(function)
            self.assertNotEqual(after_default, after_kw)
            closed.value = 5
            self.assertNotEqual(after_kw, diag._callable_graph_fingerprint(function))

    def test_bound_self_is_not_substituted_by_shared_code(self):
        class Target:
            def method(self):
                return self.value

        left, right = Target(), Target()
        left.value, right.value = 1, 2
        with budget_scope():
            first = diag._callable_graph_fingerprint(left.method)
            self.assertNotEqual(first, diag._callable_graph_fingerprint(right.method))
            left.value = 3
            self.assertNotEqual(first, diag._callable_graph_fingerprint(left.method))

    def test_module_configuration_and_hooks_remain_live(self):
        model = module_fixture(1)
        before = diag._model_execution_fingerprint(model)
        model[0].extra_configuration = 7
        configured = diag._model_execution_fingerprint(model)
        self.assertNotEqual(before, configured)
        handle = model[0].register_forward_hook(lambda module, args, out: out)
        try:
            self.assertNotEqual(configured, diag._model_execution_fingerprint(model))
        finally:
            handle.remove()
        self.assertEqual(configured, diag._model_execution_fingerprint(model))

    def test_registered_parameter_version_remains_live(self):
        model = module_fixture(1)
        before = diag._model_execution_fingerprint(model)
        with torch.no_grad():
            model[0].weight.add_(1)
        self.assertNotEqual(before, diag._model_execution_fingerprint(model))


if __name__ == "__main__":
    unittest.main(verbosity=2)

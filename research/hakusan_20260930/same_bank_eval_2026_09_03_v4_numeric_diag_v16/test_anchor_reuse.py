"""Reuse immutable anchor records, never the live binding/graph checks."""

import contextlib
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PACKAGE = Path(__file__).resolve().parent
diag = load("anchor_reuse_diag", PACKAGE / "diagnose_batch_invariance.py")
old = load(
    "anchor_reuse_old",
    PACKAGE.parent
    / "same_bank_eval_2026_09_03_v4_numeric_diag_v14/diagnose_batch_invariance.py",
)


@contextlib.contextmanager
def scope():
    budget = diag._SealBudget()
    token = diag._ACTIVE_SEAL_BUDGET.set(budget)
    try:
        yield budget
    finally:
        diag._ACTIVE_SEAL_BUDGET.reset(token)


class AnchorReuseTests(unittest.TestCase):
    def test_exact_immutable_anchor_is_reused_within_check(self):
        def function(value=1):
            return value

        with scope():
            first = diag._callable_anchor(function)
            with mock.patch.object(
                diag,
                "_default_anchor_identity",
                side_effect=AssertionError("duplicate immutable serialization"),
            ):
                self.assertIs(first, diag._callable_anchor(function))

    def test_repeated_module_checks_fit_existing_work_budget(self):
        namespace = {}
        exec(
            "\n".join(f"def f{i}(value=1): return value" for i in range(300)), namespace
        )
        functions = [namespace[f"f{i}"] for i in range(300)]
        with scope() as budget:
            budget.visit(cost=400_000)
            for _ in range(1000):
                for function in functions:
                    diag._callable_anchor(function)
            self.assertLess(budget.work, 410_000)

    def test_same_fingerprints_as_predecessor(self):
        def a(x=None, label="a", scale=-0.0):
            return x

        def b(x=[1], *, options={"a": 1}):
            return x

        for function in (a, b, len, types.SimpleNamespace):
            with self.subTest(function=function), scope():
                expected = old._callable_anchor(function)
                self.assertEqual(expected, diag._callable_anchor(function))
                self.assertEqual(expected, diag._callable_anchor(function))

    def test_cache_is_per_check(self):
        def function(value=1):
            return value

        with scope() as first_budget:
            first = diag._callable_anchor(function)
            self.assertTrue(first_budget.callable_anchors)
        with scope() as second_budget:
            self.assertFalse(second_budget.callable_anchors)
            second = diag._callable_anchor(function)
            self.assertIsNot(first, second)
            self.assertEqual(first, second)

    def test_nested_exact_literal_tuples_can_be_reused(self):
        def function(stride=(1, 1), padding=(0, 0), dilation=(1, 1)):
            return stride

        with scope():
            first = diag._callable_anchor(function)
            self.assertEqual(first, old._callable_anchor(function))
            self.assertIs(first, diag._callable_anchor(function))

    def test_nested_tuple_alias_record_is_unchanged(self):
        shared = tuple([1, 2])

        def function(value=None):
            return value

        function.__defaults__ = (shared, shared, (shared,))
        with scope():
            first = diag._callable_anchor(function)
            self.assertEqual(first, old._callable_anchor(function))
            self.assertIs(first, diag._callable_anchor(function))

    def test_tuple_subclass_is_not_cached(self):
        class Custom(tuple):
            pass

        def function(value=Custom((1,))):
            return value

        with scope() as budget:
            with self.assertRaises(diag.DiagnosticError):
                diag._callable_anchor(function)
            self.assertFalse(budget.callable_anchors)

    def test_deep_literal_defaults_still_reject(self):
        nested = 1
        for _ in range(14):
            nested = (nested,)

        def function(value=None):
            return value

        function.__defaults__ = (nested,)
        with scope(), self.assertRaisesRegex(diag.DiagnosticError, "depth limit"):
            diag._callable_anchor(function)

    def test_no_anchor_cache_outside_a_budget(self):
        def function(value=1):
            return value

        self.assertIsNot(
            diag._callable_anchor(function), diag._callable_anchor(function)
        )

    def test_code_replacement_is_detected_within_check(self):
        def function(value=1):
            return value

        def replacement(value=1):
            return value + 1

        with scope():
            first = diag._callable_anchor(function)
            function.__code__ = replacement.__code__
            self.assertNotEqual(first, diag._callable_anchor(function))

    def test_equal_default_tuple_replacement_is_detected(self):
        def function(value=1):
            return value

        with scope():
            first = diag._callable_anchor(function)
            function.__defaults__ = tuple([1])
            self.assertNotEqual(first, diag._callable_anchor(function))

    def test_none_and_literal_defaults_switch_is_detected(self):
        def function(value=1):
            return value

        with scope():
            first = diag._callable_anchor(function)
            function.__defaults__ = None
            second = diag._callable_anchor(function)
            self.assertNotEqual(first, second)
            function.__defaults__ = (2,)
            self.assertNotEqual(second, diag._callable_anchor(function))

    def test_keyword_defaults_added_after_cache_are_detected(self):
        def function(value=1):
            return value

        with scope():
            first = diag._callable_anchor(function)
            function.__kwdefaults__ = {}
            second = diag._callable_anchor(function)
            self.assertNotEqual(first, second)
            function.__kwdefaults__["x"] = 3
            self.assertNotEqual(second, diag._callable_anchor(function))

    def test_mutable_positional_default_never_cached(self):
        def function(value=[1]):
            return value

        with scope() as budget:
            first = diag._callable_anchor(function)
            function.__defaults__[0].append(2)
            self.assertNotEqual(first, diag._callable_anchor(function))
            self.assertFalse(budget.callable_anchors)

    def test_keyword_defaults_remain_live_even_if_empty(self):
        def function(value=1):
            return value

        function.__kwdefaults__ = {}
        with scope() as budget:
            first = diag._callable_anchor(function)
            function.__kwdefaults__["extra"] = 2
            self.assertNotEqual(first, diag._callable_anchor(function))
            self.assertFalse(budget.callable_anchors)

    def test_nested_mutable_default_is_not_cached(self):
        def function(value=([1],)):
            return value

        with scope() as budget:
            first = diag._callable_anchor(function)
            function.__defaults__[0][0].append(2)
            self.assertNotEqual(first, diag._callable_anchor(function))
            self.assertFalse(budget.callable_anchors)

    def test_callable_default_code_remains_live(self):
        def nested():
            return 1

        def changed():
            return 2

        def function(value=nested):
            return value

        with scope() as budget:
            first = diag._callable_anchor(function)
            nested.__code__ = changed.__code__
            self.assertNotEqual(first, diag._callable_anchor(function))
            self.assertFalse(budget.callable_anchors)

    def test_bound_self_identity_is_not_reused(self):
        class Target:
            def method(self, value=1):
                return value

        left, right = Target(), Target()
        with scope():
            a = diag._callable_anchor(left.method)
            b = diag._callable_anchor(right.method)
            self.assertIs(a[0], left)
            self.assertIs(b[0], right)
            self.assertIs(a, diag._callable_anchor(left.method))
            self.assertIs(b, diag._callable_anchor(right.method))

    def test_globals_and_closure_graphs_still_change(self):
        state = types.SimpleNamespace(value=1)

        def function(value=1):
            return state.value + value

        with scope():
            first = diag._callable_graph_fingerprint(function)
            state.value = 2
            self.assertNotEqual(first, diag._callable_graph_fingerprint(function))

    def test_original_work_limit_still_rejects(self):
        with scope() as budget:
            budget.visit(cost=600_000)
            with self.assertRaisesRegex(diag.DiagnosticError, "work budget"):
                budget.visit()


if __name__ == "__main__":
    unittest.main(verbosity=2)

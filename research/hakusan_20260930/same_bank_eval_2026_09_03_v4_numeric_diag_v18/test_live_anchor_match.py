"""Immutable match reuse still reads every live function metadata binding."""

import contextlib
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    'live_anchor_match_tests', Path(__file__).with_name('diagnose_batch_invariance.py')
)
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)


@contextlib.contextmanager
def scope():
    budget = diag._SealBudget()
    token = diag._ACTIVE_SEAL_BUDGET.set(budget)
    try:
        yield budget
    finally:
        diag._ACTIVE_SEAL_BUDGET.reset(token)


class MatchTests(unittest.TestCase):
    def test_exact_type_anchor_has_no_python_function_metadata(self):
        cls = type('Plain', (), {'__code__': 3, '__defaults__': [4]})
        anchor = diag._callable_anchor(cls)
        self.assertIsNone(diag._safe_instance_dict(cls))
        with scope(), mock.patch.object(diag, '_callable_anchor', side_effect=AssertionError('rebuilt class')):
            self.assertTrue(diag._callable_anchor_matches(cls, anchor))

    def test_plain_class_identity_replacement_is_rejected(self):
        a, b = type('Plain', (), {}), type('Plain', (), {})
        anchor = diag._callable_anchor(a)
        with scope():
            self.assertTrue(diag._callable_anchor_matches(a, anchor))
            self.assertFalse(diag._callable_anchor_matches(b, anchor))

    def test_custom_metaclass_still_uses_full_anchor_reader(self):
        class Meta(type):
            pass
        cls = Meta('Custom', (), {})
        anchor = diag._callable_anchor(cls)
        with scope(), mock.patch.object(diag, '_callable_anchor', wraps=diag._callable_anchor) as reader:
            self.assertTrue(diag._callable_anchor_matches(cls, anchor))
            self.assertEqual(reader.call_count, 1)

    def test_repeated_exact_immutable_match_does_not_rebuild_record(self):
        def fn(value=(1, 2)):
            return value
        anchor = diag._callable_anchor(fn)
        with scope():
            self.assertTrue(diag._callable_anchor_matches(fn, anchor))
            with mock.patch.object(diag, '_callable_anchor', side_effect=AssertionError('rebuilt')):
                self.assertTrue(diag._callable_anchor_matches(fn, anchor))

    def test_code_change_within_check_rejected(self):
        def fn(value=1):
            return value
        def replacement(value=1):
            return value + 1
        anchor = diag._callable_anchor(fn)
        with scope():
            self.assertTrue(diag._callable_anchor_matches(fn, anchor))
            fn.__code__ = replacement.__code__
            self.assertFalse(diag._callable_anchor_matches(fn, anchor))

    def test_defaults_rebinding_and_kwdefaults_are_live(self):
        for action in (lambda f: setattr(f, '__defaults__', (2,)),
                       lambda f: setattr(f, '__defaults__', None),
                       lambda f: setattr(f, '__kwdefaults__', {})):
            def fn(value=1):
                return value
            anchor = diag._callable_anchor(fn)
            with scope():
                self.assertTrue(diag._callable_anchor_matches(fn, anchor))
                action(fn)
                self.assertFalse(diag._callable_anchor_matches(fn, anchor))

    def test_equal_but_distinct_defaults_rejected(self):
        def fn(value=1):
            return value
        anchor = diag._callable_anchor(fn)
        with scope():
            self.assertTrue(diag._callable_anchor_matches(fn, anchor))
            fn.__defaults__ = tuple([1])
            self.assertFalse(diag._callable_anchor_matches(fn, anchor))

    def test_mutable_default_contents_never_reused(self):
        def fn(value=[1]):
            return value
        anchor = diag._callable_anchor(fn)
        with scope():
            self.assertTrue(diag._callable_anchor_matches(fn, anchor))
            fn.__defaults__[0].append(2)
            self.assertFalse(diag._callable_anchor_matches(fn, anchor))

    def test_mutable_keyword_default_contents_never_reused(self):
        def fn(*, value=[1]):
            return value
        anchor = diag._callable_anchor(fn)
        with scope():
            self.assertTrue(diag._callable_anchor_matches(fn, anchor))
            fn.__kwdefaults__['value'].append(2)
            self.assertFalse(diag._callable_anchor_matches(fn, anchor))

    def test_different_function_with_same_code_rejected(self):
        def fn(value=1):
            return value
        other = types.FunctionType(fn.__code__, fn.__globals__, argdefs=fn.__defaults__)
        anchor = diag._callable_anchor(fn)
        with scope():
            self.assertTrue(diag._callable_anchor_matches(fn, anchor))
            self.assertFalse(diag._callable_anchor_matches(other, anchor))

    def test_distinct_anchor_result_not_reused(self):
        def fn(value=1):
            return value
        anchor = diag._callable_anchor(fn)
        wrong = (None, fn, fn.__code__, ('incorrect',), anchor[4])
        with scope():
            self.assertTrue(diag._callable_anchor_matches(fn, anchor))
            self.assertFalse(diag._callable_anchor_matches(fn, wrong))

    def test_cache_not_reused_across_checks(self):
        def fn(value=1):
            return value
        anchor = diag._callable_anchor(fn)
        with scope():
            self.assertTrue(diag._callable_anchor_matches(fn, anchor))
        with scope(), mock.patch.object(diag, '_callable_anchor', wraps=diag._callable_anchor) as reader:
            self.assertTrue(diag._callable_anchor_matches(fn, anchor))
            self.assertEqual(reader.call_count, 1)

    def test_bound_self_is_not_reused(self):
        class C:
            def fn(self, value=1):
                return value
        a, b = C(), C()
        anchor = diag._callable_anchor(a.fn)
        with scope():
            self.assertTrue(diag._callable_anchor_matches(a.fn, anchor))
            self.assertFalse(diag._callable_anchor_matches(b.fn, anchor))

    def test_empty_keyword_dictionary_change_is_live(self):
        def fn(value=1):
            return value
        fn.__kwdefaults__ = {}
        anchor = diag._callable_anchor(fn)
        with scope():
            self.assertTrue(diag._callable_anchor_matches(fn, anchor))
            fn.__kwdefaults__['value'] = 2
            self.assertFalse(diag._callable_anchor_matches(fn, anchor))


if __name__ == '__main__':
    unittest.main()

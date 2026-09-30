"""Cache name classification only; reread every live registry and bound object."""

import contextlib
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    'module_name_classification_tests', Path(__file__).with_name('diagnose_batch_invariance.py')
)
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)


@contextlib.contextmanager
def scope(registry):
    token = diag._ACTIVE_SEAL_BUDGET.set(diag._SealBudget())
    try:
        with mock.patch.object(sys, 'modules', registry):
            yield
    finally:
        diag._ACTIVE_SEAL_BUDGET.reset(token)


class ClassificationTests(unittest.TestCase):
    def scan(self, tops=('src',)):
        return diag._live_protected_module_bindings(set(tops))

    def test_all_bindings_match_original_filter(self):
        registry = {name: object() for name in ('src', 'src.a', 'srcx', 'src\n',
                    'other.src', 'numpy.x', 'selftrain', 'selftrain.x', '')}
        with scope(registry):
            for tops in ((), ('src',), ('src', 'selftrain'), ('',)):
                expected = {k: v for k, v in registry.items() if k.partition('.')[0] in tops}
                self.assertEqual(self.scan(tops), expected)
                self.assertEqual(self.scan(tops), expected)

    def test_same_check_protected_replacement_is_live(self):
        registry = {'src.a': object(), 'numpy': object()}
        with scope(registry):
            before = self.scan()
            registry['src.a'] = object()
            after = self.scan()
            self.assertIsNot(before['src.a'], after['src.a'])

    def test_new_protected_name_and_removal_are_live(self):
        registry = {'src.a': object(), 'numpy': object()}
        with scope(registry):
            self.scan()
            registry['src.b'] = object()
            self.assertEqual(set(self.scan()), {'src.a', 'src.b'})
            del registry['src.a']
            self.assertEqual(set(self.scan()), {'src.b'})

    def test_new_unprotected_name_is_excluded_by_name_only(self):
        registry = {'src.a': object()}
        with scope(registry):
            self.scan()
            registry['other'] = object()
            self.assertEqual(set(self.scan()), {'src.a'})
            registry['other'] = types.ModuleType('src')
            self.assertEqual(set(self.scan()), {'src.a'})

    def test_changed_protected_top_set_does_not_reuse_exclusion(self):
        registry = {'src.a': object(), 'other.a': object()}
        with scope(registry):
            self.scan()
            self.assertEqual(set(self.scan(('other',))), {'other.a'})
            self.assertEqual(set(self.scan(('src', 'other'))), set(registry))

    def test_excluded_name_removed_then_added_with_new_value_still_checked_by_name(self):
        registry = {'src': object(), 'other': object()}
        with scope(registry):
            self.scan()
            del registry['other']
            self.scan()
            registry['other'] = object()
            self.assertEqual(set(self.scan()), {'src'})
            self.assertEqual(set(self.scan(('other',))), {'other'})

    def test_no_budget_still_reads_new_values(self):
        registry = {'src.a': object()}
        with mock.patch.object(sys, 'modules', registry):
            first = self.scan()
            registry['src.a'] = object()
            self.assertIsNot(first['src.a'], self.scan()['src.a'])

    def test_string_subclass_rejected_before_hash_or_partition(self):
        class Name(str):
            def partition(self, *args):
                raise AssertionError('partition dispatched')
        key = Name('other')
        registry = {key: object()}
        with scope(registry), self.assertRaises(diag.DiagnosticError):
            self.scan()

    def test_late_nonstring_key_is_rejected(self):
        registry = {'src': object()}
        with scope(registry):
            self.scan()
            registry[7] = object()
            with self.assertRaises(diag.DiagnosticError):
                self.scan()

    def test_name_type_with_custom_metaclass_hash_is_not_hashed(self):
        class Meta(type):
            def __hash__(self):
                raise AssertionError('metaclass hash dispatched')
        class Name(str, metaclass=Meta):
            pass
        registry = {Name('other'): object()}
        with scope(registry), self.assertRaises(diag.DiagnosticError):
            self.scan()

    def test_protected_name_type_with_custom_metaclass_hash_is_not_hashed(self):
        class Meta(type):
            def __hash__(self):
                raise AssertionError('metaclass hash dispatched')
        class Name(str, metaclass=Meta):
            pass
        with scope({}), self.assertRaises(diag.DiagnosticError):
            self.scan((Name('src'),))

    def test_unsupported_registry_does_not_dispatch_items(self):
        class Registry(dict):
            def items(self):
                raise AssertionError('items dispatched')
        with scope(Registry()), self.assertRaises(diag.DiagnosticError):
            self.scan()

    def test_cache_contains_names_not_module_objects_or_pass_result(self):
        registry = {'src.a': object(), 'other': object()}
        with scope(registry):
            self.scan()
            cache = diag._ACTIVE_SEAL_BUDGET.get().unprotected_module_names
            self.assertEqual(cache, {frozenset({'src'}): frozenset({'other'})})
            self.assertTrue(all(type(name) is str for names in cache.values() for name in names))


if __name__ == '__main__':
    unittest.main()

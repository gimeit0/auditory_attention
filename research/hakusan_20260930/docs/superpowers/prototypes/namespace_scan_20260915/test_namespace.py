"""Differential hostile-object and live-mutation tests for the local overlay."""
import ast
import importlib.util
import random
import statistics
import sys
import time
import types
import unittest
from unittest import mock

import candidate


def original_function(diag):
    tree = ast.parse(candidate.SOURCE.read_bytes())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == candidate.NAME)
    namespace = dict(vars(diag))
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<unchanged-namespace-reference>', 'exec',
                 dont_inherit=True), namespace)
    return namespace[candidate.NAME]


def make_suite(diag, fixture):
    original = original_function(diag)
    current = diag._safe_instance_dict

    class NamespaceTests(unittest.TestCase):
        def compare(self, obj):
            outcomes = []
            for function in (original, current):
                try:
                    result = function(obj)
                    outcomes.append(('ok', id(result), result))
                except Exception as exc:
                    outcomes.append(('error', type(exc), str(exc)))
            self.assertEqual(outcomes[0][:2], outcomes[1][:2])
            if outcomes[0][0] == 'ok':
                self.assertIs(outcomes[0][2], outcomes[1][2])
            else:
                self.assertEqual(outcomes[0][2], outcomes[1][2])
            return outcomes[0]

        def test_overlay_changes_only_one_function(self):
            old, new = ast.parse(candidate.SOURCE.read_bytes()), ast.parse(candidate.assemble())
            self.assertEqual(len(old.body), len(new.body))
            changed = [getattr(a, 'name', None) for a, b in zip(old.body, new.body) if ast.dump(a) != ast.dump(b)]
            self.assertEqual(changed, [candidate.NAME])
            fn = next(n for n in new.body if isinstance(n, ast.FunctionDef) and n.name == candidate.NAME)
            self.assertEqual(sum(isinstance(n, ast.For) for n in ast.walk(fn)), 3)
            self.assertFalse(any(isinstance(n, ast.GeneratorExp) for n in ast.walk(fn)))

        def test_actual_namespace_identity_and_empty(self):
            class Plain: pass
            for obj in (types.ModuleType('test'), Plain(), types.SimpleNamespace()):
                namespace = obj.__dict__
                namespace.clear()
                self.assertIs(current(obj), namespace)
                namespace.update(a=1, b=object())
                self.compare(obj)

        def test_slots_and_builtin_without_dict(self):
            class Slots: __slots__ = ('a',)
            class WithDict: __slots__ = ('a', '__dict__')
            for obj in (Slots(), WithDict(), None, 1, 'str', [], (), {}, object(), lambda: None):
                self.compare(obj)

        def test_module_subclass_no_getattribute_dispatch(self):
            class Module(types.ModuleType):
                def __getattribute__(self, key):
                    raise AssertionError('user attribute protocol executed')
            obj = Module('test')
            namespace = types.ModuleType.__getattribute__(obj, '__dict__')
            self.assertIs(current(obj), namespace)
            self.compare(obj)

        def test_hostile_attribute_and_dict_property_not_called(self):
            class Hostile:
                def __getattribute__(self, key):
                    raise AssertionError('getattribute executed')
                @property
                def __dict__(self):
                    raise AssertionError('dict property executed')
            self.assertIsNone(current(Hostile()))
            self.compare(Hostile())

        def test_inherited_dict_with_hostile_metaclass(self):
            class Meta(type):
                def __getattribute__(self, key):
                    raise AssertionError('metaclass protocol executed')
            class Parent: pass
            class Child(Parent, metaclass=Meta): pass
            obj = Child()
            obj.x = 1
            self.compare(obj)

        def test_nonstring_first_middle_last_rejected(self):
            for bad in (1, False, None, (1,), b'bytes'):
                for position in (0, 3, 6):
                    obj = types.ModuleType('test')
                    namespace = obj.__dict__
                    namespace.clear()
                    for i in range(7):
                        namespace[bad if i == position else 'x' + str(i)] = object()
                    self.assertEqual(self.compare(obj)[0], 'error')

        def test_hostile_string_subclass_hash_eq_not_called(self):
            events = []
            class String(str):
                def __hash__(self):
                    events.append('hash')
                    return str.__hash__(self)
                def __eq__(self, other):
                    events.append('eq')
                    raise AssertionError('key equality executed')
            obj = types.SimpleNamespace()
            obj.__dict__[String('bad')] = 1
            events.clear()
            self.assertEqual(self.compare(obj)[0], 'error')
            self.assertEqual(events, [])

        def test_hostile_key_type_equality_not_called(self):
            events = []
            class Meta(type):
                def __eq__(self, other):
                    events.append('type equality')
                    raise AssertionError('type equality executed')
            class Key(metaclass=Meta): pass
            obj = types.SimpleNamespace()
            obj.__dict__[Key()] = 1
            self.assertEqual(self.compare(obj)[0], 'error')
            self.assertEqual(events, [])

        def test_success_never_cached_after_same_size_key_replacement(self):
            obj = types.SimpleNamespace(x=1, y=2)
            for _ in range(4): self.compare(obj)
            namespace = obj.__dict__
            del namespace['y']
            namespace[3] = 2
            self.assertEqual(self.compare(obj)[0], 'error')
            del namespace[3]
            namespace['y'] = 2
            self.assertEqual(self.compare(obj)[0], 'ok')

        def test_values_returned_live_not_copied(self):
            obj = types.SimpleNamespace(x=object())
            first = current(obj)
            replacement = object()
            obj.x = replacement
            self.assertIs(current(obj), first)
            self.assertIs(first['x'], replacement)
            self.compare(obj)

        def test_randomized_live_mutations(self):
            rng = random.Random(20260915)
            obj = types.SimpleNamespace()
            for _ in range(600):
                obj.__dict__.clear()
                for i in range(rng.randrange(64)):
                    obj.__dict__['x' + str(i)] = object()
                if rng.randrange(3) == 0:
                    obj.__dict__[rng.randrange(10)] = 1
                self.compare(obj)

        def test_foreign_test_module_not_accepted_as_release(self):
            with self.assertRaises(fixture.bridge.BridgeError):
                fixture.bridge._require_module(diag)

        def test_model_bad_key_rejected_before_forward(self):
            with fixture.worker('B2') as (run, trials, evaluator, scene):
                run['model'].__dict__[1] = None
                with self.assertRaises(diag.DiagnosticError):
                    diag.run_trace_pass(run, trials, 'pass1', 16, False, candidate.HERE)
                self.assertEqual(evaluator.calls.count('model'), 0)

        def test_state_tensor_mutation_rejected_before_forward(self):
            with fixture.worker('B2') as (run, trials, evaluator, scene):
                with fixture.torch.no_grad():
                    run['model'].anchor.add_(1)
                with self.assertRaises(diag.DiagnosticError):
                    diag.run_trace_pass(run, trials, 'pass1', 16, False, candidate.HERE)
                self.assertEqual(evaluator.calls.count('model'), 0)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(NamespaceTests)
    # Existing behavior tests explicitly point to candidate. Their fixture code
    # and assertions are unchanged. No production loader acceptance is claimed.
    original_count = 0
    for name in ('test_binding_scan', 'test_module_name_classification', 'test_execution_collections',
                 'test_environment_mapping', 'test_execution_budget', 'test_ordered_registries'):
        path = candidate.SOURCE.with_name(name + '.py')
        spec = importlib.util.spec_from_file_location('namespace_overlay_' + name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module.diag = diag
        for fixture_name in ('fixtures', 'fixture'):
            item = getattr(module, fixture_name, None)
            if item is not None and hasattr(item, 'diagnose'):
                item.diagnose = diag
        group = unittest.defaultTestLoader.loadTestsFromModule(module)
        original_count += group.countTestCases()
        suite.addTests(group)
    return suite, original_count


def microbenchmark(diag):
    original = original_function(diag)
    rows = []
    for count in (8, 256, 3000):
        obj = types.ModuleType('synthetic_microbench')
        obj.__dict__.clear()
        obj.__dict__.update({str(i): None for i in range(count)})
        timings = {'original': [], 'candidate': []}
        for repeat in range(6):
            order = ('original', 'candidate') if repeat % 2 == 0 else ('candidate', 'original')
            for variant in order:
                function = original if variant == 'original' else diag._safe_instance_dict
                start = time.perf_counter()
                for _ in range(2000):
                    result = function(obj)
                timings[variant].append(time.perf_counter() - start)
                if result is not obj.__dict__:
                    raise AssertionError('namespace identity changed')
        medians = {v: statistics.median(t) for v, t in timings.items()}
        rows.append({'namespace_keys': count, 'calls_per_repeat': 2000, 'repeats': 6,
                     'unprofiled_seconds': timings, 'median_seconds': medians,
                     'speedup': medians['original'] / medians['candidate']})
    return rows


def run(diag, fixture):
    suite, original_count = make_suite(diag, fixture)
    expected = suite.countTestCases()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.testsRun != expected or result.skipped:
        raise RuntimeError('namespace candidate regression failed')
    return {'tests': result.testsRun, 'new_tests': 15, 'existing_tests': original_count,
            'skips': 0, 'microbenchmark': microbenchmark(diag)}

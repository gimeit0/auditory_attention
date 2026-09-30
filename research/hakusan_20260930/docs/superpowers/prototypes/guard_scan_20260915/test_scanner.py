"""Candidate differential/rejection tests, including original loader regressions."""
import ast
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import random
import sys
import types
import unittest
from unittest import mock

import candidate


def load_file(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def original_scanner(diag):
    node = next(n for n in ast.parse(candidate.SOURCE.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == candidate.NAME)
    # Same dependency namespace and original function text; not installed in diag.
    namespace = dict(vars(diag))
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<original-scan-control>", "exec"), namespace)
    return namespace[candidate.NAME]


@contextmanager
def scan_context(diag, registry, budget):
    token = diag._ACTIVE_SEAL_BUDGET.set(budget)
    try:
        with mock.patch.object(sys, "modules", registry):
            yield
    finally:
        diag._ACTIVE_SEAL_BUDGET.reset(token)


def make_suite(diag, fixture):
    suite = unittest.TestSuite()
    for basename in ("test_binding_scan", "test_module_name_classification"):
        module = load_file(candidate.SOURCE.with_name(basename + ".py"), "guard_candidate_" + basename)
        module.diag = diag  # Apply original tests to THIS candidate, not just original.
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))

    class DifferentialTests(unittest.TestCase):
        def test_exactly_one_function_changed(self):
            original = ast.parse(candidate.SOURCE.read_text())
            new = ast.parse(candidate.assemble())
            self.assertEqual(len(original.body), len(new.body))
            changed = [getattr(a, "name", None) for a, b in zip(original.body, new.body)
                       if ast.dump(a, include_attributes=False) != ast.dump(b, include_attributes=False)]
            self.assertEqual(changed, [candidate.NAME])

        def test_randomized_live_registry_changes_match_original(self):
            original = original_scanner(diag)
            rng = random.Random(20260915)
            names = ["src", "src.a", "src.b", "selftrain.x", "numpy.x", "other", "", "srcx", "src\n"]
            registry = {name: object() for name in names[:3]}
            budgets = [diag._SealBudget(), diag._SealBudget()]
            for step in range(600):
                name = rng.choice(names)
                if rng.randrange(3):
                    registry[name] = object()
                else:
                    registry.pop(name, None)
                tops = rng.choice([set(), {"src"}, {"selftrain"}, {"src", "selftrain"}, {""}])
                values = []
                for function, budget in zip((original, diag._live_protected_module_bindings), budgets):
                    with scan_context(diag, registry, budget):
                        values.append(function(tops))
                self.assertEqual(set(values[0]), set(values[1]), step)
                self.assertTrue(all(values[0][k] is values[1][k] for k in values[0]), step)
                self.assertEqual(budgets[0].unprotected_module_names, budgets[1].unprotected_module_names)

        def test_equal_string_subclass_cannot_enter_warm_exclusion_cache(self):
            class Hostile(str):
                armed = False
                def __hash__(self):
                    if self.armed:
                        raise AssertionError("hostile hash dispatched")
                    return str.__hash__(self)
                def __eq__(self, other):
                    if self.armed:
                        raise AssertionError("hostile equality dispatched")
                    return str.__eq__(self, other)
                def partition(self, *_):
                    raise AssertionError("hostile partition dispatched")
            budget = diag._SealBudget()
            registry = {"src": object(), "other": object()}
            with scan_context(diag, registry, budget):
                diag._live_protected_module_bindings({"src"})
                del registry["other"]
                registry[Hostile("other")] = object()
                Hostile.armed = True
                with self.assertRaisesRegex(diag.DiagnosticError, "names require exact strings"):
                    diag._live_protected_module_bindings({"src"})

        def test_same_size_key_replacement_cannot_be_hidden(self):
            registry = {"src": object(), "other": object()}
            with scan_context(diag, registry, diag._SealBudget()):
                diag._live_protected_module_bindings({"src"})
                del registry["other"]
                registry["src.new"] = object()
                self.assertEqual(set(diag._live_protected_module_bindings({"src"})), {"src", "src.new"})

        def test_bad_late_name_does_not_publish_partial_cache(self):
            budget = diag._SealBudget()
            registry = {"src": object(), "other": object(), 1: object()}
            with scan_context(diag, registry, budget):
                with self.assertRaises(diag.DiagnosticError):
                    diag._live_protected_module_bindings({"src"})
                self.assertEqual(budget.unprotected_module_names, {})

        def test_original_bridge_cannot_accept_candidate_as_frozen_v18(self):
            with self.assertRaisesRegex(fixture.bridge.BridgeError, "not issued"):
                fixture.bridge._require_module(diag)

        def test_original_registry_replacement_guard_is_retained(self):
            with mock.patch.object(sys, "modules", dict(sys.modules)):
                with self.assertRaisesRegex(diag.DiagnosticError, "registry object was replaced"):
                    diag._verify_active_import_authority()

        def reject_mutation(self, mutate):
            with fixture.worker("B2") as (run, trials, evaluator, scene):
                mutate(run)
                with self.assertRaises(diag.DiagnosticError):
                    diag.run_trace_pass(run, trials, "pass1", 16, False, Path(run["scratch_root"]))
                self.assertEqual(evaluator.calls.count("model"), 0)

        def test_parameter_change_rejected_before_forward(self):
            def mutate(run):
                with fixture.torch.no_grad():
                    run["model"].anchor.add_(1)
            self.reject_mutation(mutate)

        def test_hook_change_rejected_before_forward(self):
            self.reject_mutation(lambda r: r["model"].register_forward_hook(lambda *args: None))

        def test_original_runtime_reader_rejects_change(self):
            # Runtime readback is an outer bridge/preparation check, not part
            # of bare run_trace_pass. Exercise that unchanged reader explicitly.
            with fixture.worker("B2") as (run, trials, evaluator, scene):
                fixture.torch.set_float32_matmul_precision("highest")
                with self.assertRaisesRegex(diag.DiagnosticError, "runtime settings are not exact"):
                    diag._read_frozen_numeric_runtime(fixture.torch)
                self.assertEqual(evaluator.calls.count("model"), 0)

    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(DifferentialTests))
    return suite

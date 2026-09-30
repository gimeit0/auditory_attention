"""Full live binding scans retain rejection during and between observations."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    'binding_scan_tests', Path(__file__).with_name('diagnose_batch_invariance.py')
)
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.name = '_binding_scan_fixture'
        self.loader = diag._SnapshotLoader(Path('/unused'), {self.name + '.py': {}}, None)
        self.module = types.ModuleType(self.name)
        self.module.__loader__ = self.loader
        self.module.__file__ = '/unused/' + self.name + '.py'
        self.module.__spec__ = importlib.util.spec_from_loader(
            self.name, self.loader, origin=self.module.__file__
        )
        exec('def function(value=1): return value', vars(self.module))
        self.loader._bind_module(self.module)
        sys.modules[self.name] = self.module
        sys.meta_path.insert(0, self.loader)
        self.addCleanup(self.cleanup)
        self.loader.seal_runtime_bindings()

    def cleanup(self):
        if self.loader in sys.meta_path:
            sys.meta_path.remove(self.loader)
        for name in tuple(sys.modules):
            if name == self.name or name.startswith(self.name + '.'):
                sys.modules.pop(name)

    def during_scan(self, action):
        original = diag._snapshot_defined_callables

        def observed(module):
            result = original(module)
            if module is self.module:
                action()
            return result

        with mock.patch.object(diag, '_snapshot_defined_callables', side_effect=observed):
            with self.assertRaises(diag.DiagnosticError):
                self.loader.verify_runtime_bindings()
        self.assertTrue(self.loader.invalid)

    def test_addition_during_scan_rejected(self):
        self.during_scan(lambda: sys.modules.__setitem__(self.name + '.extra', types.ModuleType('extra')))

    def test_replacement_during_scan_rejected(self):
        self.during_scan(lambda: sys.modules.__setitem__(self.name, types.ModuleType(self.name)))

    def test_removal_during_scan_rejected(self):
        self.during_scan(lambda: sys.modules.pop(self.name))

    def test_unchanged_scans_and_same_check_mutation(self):
        token = diag._ACTIVE_SEAL_BUDGET.set(diag._SealBudget())
        try:
            for _ in range(3):
                self.loader.verify_runtime_bindings()
            self.module.function.__defaults__ = (2,)
            with self.assertRaises(diag.DiagnosticError):
                self.loader.verify_runtime_bindings()
        finally:
            diag._ACTIVE_SEAL_BUDGET.reset(token)

    def test_unprotected_addition_still_allowed(self):
        unrelated = '_unprotected_binding_fixture'
        try:
            sys.modules[unrelated] = types.ModuleType(unrelated)
            self.loader.verify_runtime_bindings()
        finally:
            sys.modules.pop(unrelated, None)


if __name__ == '__main__':
    unittest.main()

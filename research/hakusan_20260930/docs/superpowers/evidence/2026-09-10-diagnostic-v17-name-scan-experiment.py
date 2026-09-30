"""Synthetic, process-local experiment; never changes frozen production code.

Tests native map/is identity checks against Python generator exact-type checks.
Timing is not a real-model or GPU measurement and does not authorize a release.
"""

import hashlib
import importlib.util
import inspect
import itertools
import operator
from pathlib import Path
import sys
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "binding_microprofile", HERE / "2026-09-10-diagnostic-v17-binding-microprofile.py"
)
PROFILE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROFILE
SPEC.loader.exec_module(PROFILE)
DIAG = PROFILE.DIAG
ORIGINAL = DIAG._live_protected_module_bindings
SOURCE = inspect.getsource(ORIGINAL)
for name in ("top_names", "names"):
    old = f"any(type(name) is not str for name in {name})"
    if SOURCE.count(old) != 1:
        raise RuntimeError("unexpected frozen helper source")
    SOURCE = SOURCE.replace(
        old, f"not all(map(_identity_is, map(type, {name}), _repeat(str)))"
    )
NAMESPACE = dict(vars(DIAG), _identity_is=operator.is_, _repeat=itertools.repeat)
exec(compile(SOURCE, "<synthetic-native-name-scan>", "exec"), NAMESPACE)
ALTERNATIVE = NAMESPACE[ORIGINAL.__name__]


class ExtraRejectionTests(unittest.TestCase):
    def test_custom_metaclass_equality_and_hash_never_called(self):
        calls = []

        class Meta(type):
            def __eq__(self, other):
                calls.append("eq")
                raise AssertionError("custom equality called")

            def __hash__(self):
                calls.append("hash")
                raise AssertionError("custom hash called")

        class Name(str, metaclass=Meta):
            pass

        for scanner in (ORIGINAL, ALTERNATIVE):
            for registry, tops in (({Name("other"): None}, ("src",)),
                                   ({}, (Name("src"),))):
                with mock.patch.object(sys, "modules", registry):
                    with self.assertRaises(DIAG.DiagnosticError):
                        scanner(tops)
        self.assertEqual(calls, [])


def main():
    test_path = PROFILE.SOURCE.with_name("test_module_name_classification.py")
    spec = importlib.util.spec_from_file_location("name_scan_regressions", test_path)
    tests = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = tests
    spec.loader.exec_module(tests)
    tests.diag = DIAG
    try:
        for label, scanner in (("ORIGINAL", ORIGINAL), ("EXPERIMENT", ALTERNATIVE)):
            DIAG._live_protected_module_bindings = scanner
            suite = unittest.TestSuite([
                unittest.defaultTestLoader.loadTestsFromModule(tests),
                unittest.defaultTestLoader.loadTestsFromTestCase(ExtraRejectionTests),
            ])
            print(f"VARIANT={label}", flush=True)
            result = unittest.TextTestRunner(verbosity=1).run(suite)
            if not result.wasSuccessful():
                raise RuntimeError("synthetic semantic regression")
            PROFILE.main()
    finally:
        DIAG._live_protected_module_bindings = ORIGINAL
    if hashlib.sha256(PROFILE.SOURCE.read_bytes()).hexdigest() != PROFILE.SHA:
        raise RuntimeError("frozen v17 changed")
    print("EXPERIMENT_SCOPE=LOCAL_SYNTHETIC_ONLY_NO_RELEASE_NO_REMOTE_CHANGE")


if __name__ == "__main__":
    main()

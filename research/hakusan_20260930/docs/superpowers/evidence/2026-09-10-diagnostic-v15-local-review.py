"""Exact optimization scope, predecessor preservation, negative regressions."""

import ast
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v14"
NEW = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v15"
MANIFEST = (
    ROOT
    / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v14-candidate-manifest.sha256"
)


def version_only(text):
    for prefix in ("_20260903_v", "_2026-09-03_v", "_numeric_diag_v"):
        text = text.replace(prefix + "14", prefix + "15")
    return text


def main():
    assert (
        hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
        == "022ca5b14069a37e46f05e8e0cf23f2718ddaca17ca0cfa9fa814417e196ae35"
    )
    for line in MANIFEST.read_text().splitlines():
        sha, name = line.split()
        data = (OLD / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == sha, name
        if name not in ("README.md", "diagnose_batch_invariance.py"):
            assert version_only(data.decode()) == (NEW / name).read_text(), name
    left = ast.parse(version_only((OLD / "diagnose_batch_invariance.py").read_text()))
    right = ast.parse((NEW / "diagnose_batch_invariance.py").read_text())
    a = {n.name: n for n in left.body if hasattr(n, "name")}
    b = {n.name: n for n in right.body if hasattr(n, "name")}
    assert set(b) - set(a) == {"_has_only_immutable_default_literals"}
    assert not set(a) - set(b)
    changed = {name for name in a if ast.dump(a[name]) != ast.dump(b[name])}
    assert changed == {"_SealBudget", "_callable_anchor", "_default_anchor_identity"}, (
        changed
    )
    assert [ast.dump(n) for n in left.body if not hasattr(n, "name")] == [
        ast.dump(n) for n in right.body if not hasattr(n, "name")
    ]
    old_budget, new_budget = a["_SealBudget"], b["_SealBudget"]
    old_init = next(
        n
        for n in old_budget.body
        if isinstance(n, ast.FunctionDef) and n.name == "__init__"
    )
    new_init = next(
        n
        for n in new_budget.body
        if isinstance(n, ast.FunctionDef) and n.name == "__init__"
    )
    added = new_init.body.pop()
    assert ast.unparse(added) == "self.callable_anchors = {}"
    assert ast.dump(old_init) == ast.dump(new_init)
    assert ast.dump(old_budget) == ast.dump(new_budget)
    print("V14_20_FILES_PRESERVED_645_OLD_TESTS_UNWEAKENED=PASS")
    print(
        "V15_SCOPE_IMMUTABLE_ANCHORS_ONLY_ALL_LOADER_LIVE_GRAPH_STATE_AND_BUDGET_LIMITS_UNCHANGED=PASS"
    )

    spec = importlib.util.spec_from_file_location(
        "v15_review_tests", NEW / "test_anchor_reuse.py"
    )
    tests = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = tests
    spec.loader.exec_module(tests)
    diag = tests.diag

    def reject(name, replacement):
        case = tests.AnchorReuseTests(name)
        with mock.patch.object(diag, "_callable_anchor", replacement):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(
                unittest.TestSuite([case])
            )
        assert not result.wasSuccessful(), name
        print("MUTATION_CAUGHT=" + name)

    reject(
        "test_repeated_module_checks_fit_existing_work_budget",
        types.FunctionType(tests.old._callable_anchor.__code__, vars(diag)),
    )
    original = diag._callable_anchor

    def stale_cache():
        saved = {}

        def stale(value):
            key = (
                id(diag._callable_function(value)),
                id(diag._callable_metadata(value, "__self__")),
            )
            if key not in saved:
                saved[key] = original(value)
            return saved[key]

        return stale

    for name in (
        "test_code_replacement_is_detected_within_check",
        "test_equal_default_tuple_replacement_is_detected",
        "test_keyword_defaults_added_after_cache_are_detected",
        "test_mutable_positional_default_never_cached",
        "test_callable_default_code_remains_live",
        "test_cache_is_per_check",
    ):
        reject(name, stale_cache())


if __name__ == "__main__":
    main()

"""Exact predecessor preservation, AST scope and regression mutation checks."""

import ast
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v12"
NEW = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v13"
MANIFEST = (
    ROOT
    / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v12-candidate-manifest.sha256"
)


def version_only(text):
    for old, new in (
        ("_20260903_v12", "_20260903_v13"),
        ("_2026-09-03_v12", "_2026-09-03_v13"),
        ("_numeric_diag_v12", "_numeric_diag_v13"),
    ):
        text = text.replace(old, new)
    return text


def main():
    assert (
        hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
        == "afb0549063938ecc853c8110b4b4a211357624dfb20fc46dd9da0d1630e5a31b"
    )
    for line in MANIFEST.read_text().splitlines():
        sha, name = line.split()
        data = (OLD / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == sha, name
        if name not in ("README.md", "diagnose_batch_invariance.py"):
            assert version_only(data.decode()) == (NEW / name).read_text(), name
    left = ast.parse(version_only((OLD / "diagnose_batch_invariance.py").read_text()))
    right = ast.parse((NEW / "diagnose_batch_invariance.py").read_text())
    a = {node.name: node for node in left.body if hasattr(node, "name")}
    b = {node.name: node for node in right.body if hasattr(node, "name")}
    assert set(b) - set(a) == {"_frozen_module_binding_error"}
    changed = {name for name in a if ast.dump(a[name]) != ast.dump(b[name])}
    assert changed == {"_SnapshotLoader", "_bounded_exception_diagnostic"}, changed
    # Only change in the entire loader is the object used by the same raise.
    count = 0
    for node in ast.walk(b["_SnapshotLoader"]):
        if (
            isinstance(node, ast.Raise)
            and isinstance(node.exc, ast.Call)
            and isinstance(node.exc.func, ast.Name)
            and node.exc.func.id == "_frozen_module_binding_error"
        ):
            assert (
                ast.unparse(node.exc)
                == "_frozen_module_binding_error(self.sealed_bindings, bindings)"
            )
            node.exc = ast.parse(
                'DiagnosticError("sealed frozen module bindings changed")', mode="eval"
            ).body
            count += 1
    assert count == 1
    assert ast.dump(a["_SnapshotLoader"]) == ast.dump(b["_SnapshotLoader"])
    assert [ast.dump(n) for n in left.body if not hasattr(n, "name")] == [
        ast.dump(n) for n in right.body if not hasattr(n, "name")
    ]
    print("V12_18_FILES_PRESERVED_612_OLD_TESTS_VERSION_ONLY=PASS")
    print("V13_SCOPE_ONLY_FAILURE_METADATA_NO_ACCEPTANCE_RUNTIME_SCIENCE_CHANGE=PASS")

    path = NEW / "test_compiler_failure_diagnostics.py"
    spec = importlib.util.spec_from_file_location("v13_review_tests", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    diag = module.diag

    def fails(test_name, target, replacement):
        suite = unittest.TestSuite([module.CompilerDiagnosticsTests(test_name)])
        with mock.patch.object(diag, target, replacement):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        assert not result.wasSuccessful(), test_name
        print("MUTATION_CAUGHT=" + test_name)

    spec = importlib.util.spec_from_file_location(
        "v12_review_original", OLD / "diagnose_batch_invariance.py"
    )
    original = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = original
    spec.loader.exec_module(original)
    fails(
        "test_real_pytorch_inner_edge",
        "_bounded_exception_diagnostic",
        original._bounded_exception_diagnostic,
    )
    fails(
        "test_module_delta_exact_counts_and_categories",
        "_frozen_module_binding_error",
        lambda *args: diag.DiagnosticError("sealed frozen module bindings changed"),
    )
    fails(
        "test_delta_collection_failure_keeps_original_rejection",
        "_frozen_module_binding_error",
        lambda *args: ValueError("replaced failure"),
    )
    with mock.patch.object(
        diag._SnapshotLoader, "verify_runtime_bindings", lambda *args: None
    ):
        suite = unittest.TestSuite(
            [
                module.CompilerDiagnosticsTests(
                    "test_real_loader_rejection_and_sticky_revocation"
                )
            ]
        )
        result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        assert not result.wasSuccessful()
    print("MUTATION_CAUGHT=loader_rejection_bypass")


if __name__ == "__main__":
    main()

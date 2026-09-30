"""Bounded main-agent scope/behavior review; no remote operation or inference."""

import ast
import dis
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v9"
NEW = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v10"


def normalize(text):
    return text.replace(
        "same_bank_v4_job646900_2026-09-03_v9",
        "same_bank_v4_job646900_2026-09-03_v10",
    ).replace(
        "formal40_batch_invariance_diag_20260903_v9",
        "formal40_batch_invariance_diag_20260903_v10",
    )


def main():
    r2 = (
        ROOT / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation"
        / "snapshots/v10-default-anchor-r2/diagnose_batch_invariance.py"
    ).read_text()
    assert r2.count("if self.work > 200_000:") == 1
    assert r2.replace("if self.work > 200_000:", "if self.work > 600_000:") == (
        NEW / "diagnose_batch_invariance.py"
    ).read_text()
    print("R3_PRODUCTION_DIFF_ONE_FIXED_WORK_BOUND=PASS", flush=True)
    manifest = (
        ROOT
        / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v9-candidate-manifest.sha256"
    )
    for line in manifest.read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        assert hashlib.sha256((OLD / name).read_bytes()).hexdigest() == digest
    left = ast.parse(normalize((OLD / "diagnose_batch_invariance.py").read_text()))
    right = ast.parse((NEW / "diagnose_batch_invariance.py").read_text())
    old_nodes = {
        getattr(node, "name", f"index{index}"): node
        for index, node in enumerate(left.body)
    }
    new_functions = {
        node.name: node
        for node in right.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    old_functions = {
        node.name: node
        for node in left.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    changed = {
        name
        for name, node in old_functions.items()
        if ast.dump(node) != ast.dump(new_functions[name])
    }
    assert changed == {
        "_callable_anchor",
        "_SealBudget",
        "_materialize_callable_direct_imports",
        "_referenced_attribute_values",
        "_callable_graph_fingerprint_impl",
        "_class_reachable_callable_fingerprint",
    }, changed
    assert set(new_functions) - set(old_functions) == {
        "_seal_instructions", "_default_anchor_identity"
    }
    left_rest = [
        node
        for node in left.body
        if not isinstance(node, (ast.FunctionDef, ast.ClassDef))
    ]
    right_rest = [
        node
        for node in right.body
        if not isinstance(node, (ast.FunctionDef, ast.ClassDef))
    ]
    assert [ast.dump(node) for node in left_rest] == [
        ast.dump(node) for node in right_rest
    ]
    del old_nodes
    for name in (
        "numeric_trace.py",
        "submit_numeric_diag.py",
        "run_numeric_diag.sbatch",
    ):
        assert normalize((OLD / name).read_text()) == (NEW / name).read_text(), name
    for path in OLD.glob("test_*.py"):
        expected = normalize(path.read_text())
        if path.name == "test_execution_collections.py":
            assert expected.count("* 200001") == 2
            expected = expected.replace("* 200001", "* 600001")
        assert expected == (NEW / path.name).read_text(), path.name
    print("AST_AND_OLD_INPUT_SCOPE=PASS", flush=True)
    spec = importlib.util.spec_from_file_location(
        "budget_review_fixtures", NEW / "test_execution_budget.py"
    )
    fixtures = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = fixtures
    spec.loader.exec_module(fixtures)
    diag = fixtures.diag
    model = fixtures.module_fixture()
    original_decoder = dis.get_instructions
    with (
        fixtures.budget_scope() as budget,
        mock.patch.object(dis, "get_instructions", wraps=original_decoder) as decode,
    ):
        fingerprint = diag._model_execution_fingerprint(model)
        print(
            json.dumps(
                {
                    "scope": "SYNTHETIC_67_REAL_TORCH_MODULES_NO_FORWARD",
                    "work": budget.work,
                    "unique_callable_nodes": len(budget.nodes),
                    "decode_calls": decode.call_count,
                    "cached_code_objects": len(budget.instructions),
                    "fingerprint_records": len(fingerprint),
                }
            ),
            flush=True,
        )

    # A no-cache implementation must again fail the real structural regression.
    @diag._bounded_seal
    def uncached(code):
        if code is None:
            return ()
        diag._seal_visit(cost=max(1, len(code.co_code) // 2))
        return tuple(dis.get_instructions(code))

    original = diag._seal_instructions
    try:
        diag._seal_instructions = uncached
        suite = unittest.TestSuite(
            [
                fixtures.ExecutionBudgetTests(
                    "test_repeated_real_module_inventory_fits_original_budget"
                ),
                fixtures.ExecutionBudgetTests(
                    "test_immutable_code_is_disassembled_once_per_check"
                ),
            ]
        )
        result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        assert len(result.failures) + len(result.errors) == 2, (
            "regressions did not catch removed reuse"
        )
        print("REMOVED_REUSE_MUTATION_CAUGHT=2/2", flush=True)
    finally:
        diag._seal_instructions = original
    # Cached analysis changes no graph records for the same live small model.
    small = fixtures.module_fixture(1)
    cached = diag._model_execution_fingerprint(small)
    with mock.patch.object(diag, "_seal_instructions", uncached):
        assert cached == diag._model_execution_fingerprint(small)
    print("CACHED_UNCACHED_SMALL_MODEL_RECORD_PARITY=PASS", flush=True)
    with mock.patch.object(
        diag, "_default_anchor_identity", diag._container_execution_identity
    ):
        suite = unittest.TestSuite([
            fixtures.ExecutionBudgetTests(
                "test_repeated_literal_default_anchors_fit_budget"
            )
        ])
        result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        assert len(result.failures) + len(result.errors) == 1
    print("REMOVED_DEFAULT_REUSE_MUTATION_CAUGHT=1/1", flush=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        fixtures.ExecutionBudgetTests
    )
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(suite)
    assert result.wasSuccessful()


if __name__ == "__main__":
    main()

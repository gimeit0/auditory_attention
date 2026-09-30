"""Read-only AST scope check and in-memory regression mutations; not remote QA."""

import ast
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v7"
NEW = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v8"
ledger = ROOT / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation"
for line in (ledger / "v7-candidate-manifest.sha256").read_text().splitlines():
    expected, name = line.split(maxsplit=1)
    assert hashlib.sha256((OLD / name).read_bytes()).hexdigest() == expected, name


def normalized(raw):
    return raw.replace(
        "same_bank_v4_job646900_2026-09-03_v7",
        "same_bank_v4_job646900_2026-09-03_v8",
    ).replace(
        "formal40_batch_invariance_diag_20260903_v7",
        "formal40_batch_invariance_diag_20260903_v8",
    )


for name in (
    "numeric_trace.py",
    "submit_numeric_diag.py",
    "run_numeric_diag.sbatch",
    "test_numeric_diag.py",
    "test_submit_numeric_diag.py",
    "test_loader_record.py",
    "test_real_evaluator_scope.py",
    "test_v4_manifest_json.py",
    "test_runtime_contract.py",
):
    assert normalized((OLD / name).read_text()) == (NEW / name).read_text(), name

before = ast.parse(normalized((OLD / "diagnose_batch_invariance.py").read_text()))
after = ast.parse((NEW / "diagnose_batch_invariance.py").read_text())
excluded = {"_container_execution_identity", "_unsupported_execution_container"}


def stable_nodes(tree):
    return [
        ast.dump(node)
        for node in tree.body
        if not (
            isinstance(node, ast.FunctionDef)
            and node.name in excluded
            or isinstance(node, ast.ImportFrom)
            and node.module == "collections"
            and [(alias.name, alias.asname) for alias in node.names]
            == [("deque", None)]
        )
    ]


assert stable_nodes(before) == stable_nodes(after), "out-of-scope production AST change"
v4 = ROOT / "same_bank_eval_2026_08_29_v4"
for name, expected in (
    (
        "locked_same_bank_eval.py",
        "31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4",
    ),
    (
        "run_locked_same_bank_eval.sbatch",
        "b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495",
    ),
):
    assert hashlib.sha256((v4 / name).read_bytes()).hexdigest() == expected, name
print("V8_AST_SCOPE_AND_OLD_SHA=PASS", flush=True)

spec = importlib.util.spec_from_file_location(
    "collection_regressions", NEW / "test_execution_collections.py"
)
tests = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tests
spec.loader.exec_module(tests)
diag = tests.diag
original = diag._container_execution_identity
original_error = diag._unsupported_execution_container


def function(tree, name):
    return copy.deepcopy(
        next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
    )


def install(node):
    tree = ast.Module(body=[node], type_ignores=[])
    exec(
        compile(ast.fix_missing_locations(tree), "<v8-in-memory-mutation>", "exec"),
        diag.__dict__,
    )


def check_mutant(label, node, names):
    install(node)
    try:
        suite = unittest.TestSuite(tests.CollectionSealTests(name) for name in names)
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream).run(suite)
        assert not result.wasSuccessful(), f"mutation not caught: {label}"
        print(
            json.dumps(
                {
                    "mutation": label,
                    "tests": result.testsRun,
                    "failures": len(result.failures),
                    "errors": len(result.errors),
                    "status": "REGRESSION_DETECTED",
                }
            ),
            flush=True,
        )
    finally:
        diag._container_execution_identity = original
        diag._unsupported_execution_container = original_error


check_mutant(
    "restore_v7_container",
    function(before, "_container_execution_identity"),
    [
        "test_source_amp_window_is_accepted_without_conversion",
        "test_exact_torch_size_preserves_type_identity_and_dimensions",
    ],
)

for label, tag, position, value, case in (
    (
        "omit_deque_capacity",
        "deque",
        3,
        None,
        "test_deque_capacity_is_in_seal_even_with_identity_normalized",
    ),
    ("omit_deque_contents", "deque", 4, (), "test_deque_mutations_are_detected"),
    ("omit_deque_identity", "deque", 1, 0, "test_deque_replacement_is_detected"),
    (
        "omit_shape_dimensions",
        "torch-size",
        3,
        (),
        "test_exact_torch_size_preserves_type_identity_and_dimensions",
    ),
):
    node = function(after, "_container_execution_identity")
    returns = [
        item
        for item in ast.walk(node)
        if isinstance(item, ast.Return)
        and isinstance(item.value, ast.Tuple)
        and isinstance(item.value.elts[0], ast.Constant)
        and item.value.elts[0].value == tag
    ]
    assert len(returns) == 1
    returns[0].value.elts[position] = ast.Constant(value=value)
    check_mutant(label, node, [case])

node = function(after, "_unsupported_execution_container")
for statement in node.body:
    if isinstance(statement, ast.Assign) and statement.targets[0].id in {
        "module",
        "name",
    }:
        target = statement.targets[0].id
        field = "__module__" if target == "module" else "__qualname__"
        statement.value = ast.parse(
            f'type.__getattribute__(value_type, "{field}")', mode="eval"
        ).body
check_mutant(
    "unsafe_metaclass_metadata",
    node,
    ["test_error_does_not_execute_metaclass_property"],
)

print("V8_IN_MEMORY_MUTATIONS=PASS; no candidate files changed", flush=True)

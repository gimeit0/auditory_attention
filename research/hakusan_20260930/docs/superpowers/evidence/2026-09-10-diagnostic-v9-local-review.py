"""Local read-only scope checks and in-memory negative controls; not GPU QA."""

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
OLD = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v8"
NEW = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v9"
LEDGER = ROOT / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation"
for line in (LEDGER / "v8-candidate-manifest.sha256").read_text().splitlines():
    digest, name = line.split(maxsplit=1)
    assert hashlib.sha256((OLD / name).read_bytes()).hexdigest() == digest, name


def normalized(value):
    for prefix in (
        "same_bank_v4_job646900_2026-09-03_v",
        "formal40_batch_invariance_diag_20260903_v",
        "same_bank_eval_2026_09_03_v4_numeric_diag_v",
    ):
        value = value.replace(prefix + "8", prefix + "9")
    return value


for path in OLD.iterdir():
    if (
        path.suffix in (".py", ".sbatch")
        and path.name != "diagnose_batch_invariance.py"
    ):
        assert normalized(path.read_text()) == (NEW / path.name).read_text(), path.name

before = ast.parse(normalized((OLD / "diagnose_batch_invariance.py").read_text()))
after = ast.parse((NEW / "diagnose_batch_invariance.py").read_text())
helpers = {
    "_environment_binding_identity",
    "_environment_structure",
    "_environment_execution_identity",
    "_torch_version_execution_identity",
}
anchors = {
    "_PROCESS_ENVIRON",
    "_PROCESS_ENVIRON_TYPE",
    "_PROCESS_ENVIRON_DATA",
    "_PROCESS_ENVIRON_STRUCTURE",
    "_ENVIRONMENT_HASH_FACTORY",
    "_ENVIRONMENT_HASH_KEY",
    "_ENVIRONMENT_MAX_ITEMS",
    "_ENVIRONMENT_MAX_BYTES",
}
reduced = copy.deepcopy(after)
reduced.body = [
    node
    for node in reduced.body
    if not (isinstance(node, ast.FunctionDef) and node.name in helpers)
    and not (
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id in anchors
            for target in node.targets
        )
    )
]
container = next(
    n
    for n in reduced.body
    if isinstance(n, ast.FunctionDef) and n.name == "_container_execution_identity"
)
index = next(
    i
    for i, n in enumerate(container.body)
    if isinstance(n, ast.Assign)
    and isinstance(n.targets[0], ast.Name)
    and n.targets[0].id == "type_record"
)
added = container.body[index + 1 : index + 5]
assert len(added) == 4 and [type(n) for n in added] == [
    ast.If,
    ast.Assign,
    ast.Assign,
    ast.If,
]
assert added[1].targets[0].id == "version_module"
assert added[2].targets[0].id == "version_type"
del container.body[index + 1 : index + 5]
assert ast.dump(before) == ast.dump(reduced), "out-of-scope production AST change"
for name, digest in (
    (
        "locked_same_bank_eval.py",
        "31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4",
    ),
    (
        "run_locked_same_bank_eval.sbatch",
        "b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495",
    ),
):
    assert (
        hashlib.sha256(
            (ROOT / "same_bank_eval_2026_08_29_v4" / name).read_bytes()
        ).hexdigest()
        == digest
    )
print("V9_SCOPE_OLD_TESTS_AND_OLD_SHA=PASS", flush=True)

spec = importlib.util.spec_from_file_location(
    "v9_environment_regressions", NEW / "test_environment_mapping.py"
)
tests = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tests
spec.loader.exec_module(tests)
diag = tests.diag
names = helpers | {"_container_execution_identity"}
original = {name: getattr(diag, name) for name in names}


def function(tree, name):
    return copy.deepcopy(
        next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    )


def run_cases(cases):
    stream = io.StringIO()
    suite = unittest.TestSuite(tests.EnvironmentSealTests(name) for name in cases)
    return unittest.TextTestRunner(stream=stream).run(suite)


baseline_cases = [
    "test_original_environment_is_accepted_and_repeatable",
    "test_environment_changes_are_detected_without_cleartext",
    "test_mapping_class_and_instance_method_replacements_are_not_called",
    "test_keyed_digest_has_framing",
    "test_content_digest_depends_on_private_process_key",
    "test_torch_version_identity_and_text",
    "test_torch_version_overrides_sealed_without_invocation",
]
assert run_cases(baseline_cases).wasSuccessful(), "positive control failed"
print("V9_MUTATION_POSITIVE_CONTROL=PASS", flush=True)


def mutant(label, node, cases):
    try:
        tree = ast.Module(body=[node], type_ignores=[])
        exec(
            compile(ast.fix_missing_locations(tree), "<v9-in-memory-mutation>", "exec"),
            diag.__dict__,
        )
        result = run_cases(cases)
        assert not result.wasSuccessful(), "mutation escaped: " + label
        print(
            json.dumps(
                {
                    "mutation": label,
                    "tests": result.testsRun,
                    "errors": len(result.errors),
                    "failures": len(result.failures),
                    "status": "REGRESSION_DETECTED",
                }
            ),
            flush=True,
        )
    finally:
        for name, value in original.items():
            setattr(diag, name, value)


mutant(
    "restore_v8_container",
    function(before, "_container_execution_identity"),
    [baseline_cases[0], baseline_cases[5]],
)
node = function(after, "_environment_execution_identity")
next(n for n in node.body if isinstance(n, ast.Return)).value.elts[-1] = ast.Constant(
    "omitted"
)
mutant("omit_environment_digest", node, [baseline_cases[1]])

node = function(after, "_environment_execution_identity")
for n in ast.walk(node):
    if (
        isinstance(n, ast.Compare)
        and isinstance(n.left, ast.Call)
        and isinstance(n.left.func, ast.Name)
        and n.left.func.id == "_environment_structure"
    ):
        n.left = ast.Name(id="_PROCESS_ENVIRON_STRUCTURE", ctx=ast.Load())
mutant("omit_environment_method_seal", node, [baseline_cases[2]])

node = function(after, "_environment_execution_identity")
for n in ast.walk(node):
    if (
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_ENVIRONMENT_HASH_FACTORY"
    ):
        next(k for k in n.keywords if k.arg == "key").value = ast.Constant(b"fixed-key")
mutant("omit_private_process_key", node, [baseline_cases[4]])

node = function(after, "_environment_execution_identity")
loop = next(
    n
    for n in node.body
    if isinstance(n, ast.For)
    and isinstance(n.iter, ast.Call)
    and isinstance(n.iter.func, ast.Name)
    and n.iter.func.id == "sorted"
)
loop.body = [n for n in loop.body if ".to_bytes(" not in ast.unparse(n)]
mutant("omit_environment_length_framing", node, [baseline_cases[3]])

node = function(after, "_torch_version_execution_identity")
next(n for n in node.body if isinstance(n, ast.Return)).value.elts[-1] = ast.Tuple(
    elts=[], ctx=ast.Load()
)
mutant("omit_version_method_bindings", node, [baseline_cases[6]])

node = function(after, "_torch_version_execution_identity")
next(n for n in node.body if isinstance(n, ast.Return)).value.elts[3] = ast.Constant(
    "omitted"
)
mutant("omit_version_text", node, [baseline_cases[5]])
assert run_cases(baseline_cases).wasSuccessful(), "restoration failed"
print("V9_LOCAL_REVIEW=PASS; NO_REMOTE_EXECUTION; NO_GPU_INFERENCE", flush=True)

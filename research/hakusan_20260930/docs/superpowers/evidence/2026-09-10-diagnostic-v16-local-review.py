"""Compare the frozen predecessor and exercise targeted rejected regressions."""

import ast
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v15"
NEW = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v16"
MANIFEST = (
    ROOT
    / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v15-candidate-manifest.sha256"
)


def normalize(text):
    for prefix in ("_20260903_v", "_2026-09-03_v", "_numeric_diag_v"):
        text = text.replace(prefix + "15", prefix + "16")
    return text


def main():
    assert (
        hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
        == "d2f61015d5275f6ee50be70c40a90d54d198a10194d91150ca42b1cc063c6337"
    )
    for line in MANIFEST.read_text().splitlines():
        sha, name = line.split()
        source = (OLD / name).read_bytes()
        assert hashlib.sha256(source).hexdigest() == sha, name
        if name not in ("README.md", "diagnose_batch_invariance.py"):
            assert normalize(source.decode()) == (NEW / name).read_text(), name
    old = ast.parse(normalize((OLD / "diagnose_batch_invariance.py").read_text()))
    new = ast.parse((NEW / "diagnose_batch_invariance.py").read_text())
    a = {node.name: node for node in old.body if hasattr(node, "name")}
    b = {node.name: node for node in new.body if hasattr(node, "name")}
    changed = {name for name in a if ast.dump(a[name]) != ast.dump(b[name])}
    assert changed == {
        "_graph_container_identity",
        "_model_execution_fingerprint",
        "prepare_formal40_worker",
        "_live_inference_attestation",
        "_bounded_exception_diagnostic",
    }, changed
    assert set(b) - set(a) == {
        "_compiler_closure_binding",
        "_compiler_source_codes",
        "_require_compiler_source_function",
        "_CompilerLifecycle",
        "_issue_compiler_lifecycle",
        "_with_compiler_lifecycle",
        "_guard_mismatch_error",
    }
    # The complete model/state/config/hook fingerprint body is untouched.
    assert [ast.dump(n) for n in a["_model_execution_fingerprint"].body] == [
        ast.dump(n) for n in b["_model_execution_fingerprint"].body
    ]
    old_other = [n for n in old.body if not hasattr(n, "name")]
    new_other = [n for n in new.body if not hasattr(n, "name")]
    allowed_added = {
        "_COMPILER_SOURCE_SHAS",
        "_ACTIVE_COMPILER_LIFECYCLE",
        "_ISSUED_COMPILER_LIFECYCLES",
        "_COMPILER_LIFECYCLE_RECEIPTS",
        "_GUARD_COMPONENTS",
        "_GUARD_DIFF_KINDS",
    }
    filtered = []
    for node in new_other:
        target = (
            node.targets[0]
            if isinstance(node, ast.Assign)
            else node.target
            if isinstance(node, ast.AnnAssign)
            else None
        )
        if isinstance(target, ast.Name) and target.id in allowed_added:
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "collections":
            node.names = [
                n for n in node.names if n.name not in ("Counter", "defaultdict")
            ]
        filtered.append(node)
    assert [ast.dump(n) for n in old_other] == [ast.dump(n) for n in filtered]
    print("V15_21_FILES_PRESERVED_665_OLD_TESTS_UNWEAKENED=PASS")
    print(
        "V16_SCOPE_FIVE_FUNCTIONS_MODEL_FINGERPRINT_BODY_SCIENTIFIC_CODE_BUDGET_UNCHANGED=PASS"
    )

    spec = importlib.util.spec_from_file_location(
        "v16_mutation_tests", NEW / "test_compiler_lifecycle.py"
    )
    tests = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = tests
    spec.loader.exec_module(tests)
    verification = next(
        n
        for n in b["_CompilerLifecycle"].body
        if isinstance(n, ast.FunctionDef) and n.name == "verify"
    )
    for message, case_name in (
        (
            "compiler lifecycle backend transition differs",
            "test_replacement_backend_sticky_rejection",
        ),
        (
            "compiler lifecycle issuance receipt changed",
            "test_issuance_fields_cannot_be_rebased",
        ),
        ("compiler lifecycle closure binding changed", "test_closure_replacement"),
        ("compiler lifecycle counter alias changed", "test_counter_alias_replacement"),
        ("compiler lifecycle callable binding changed", "test_code_replacement"),
    ):

        class RemoveRejection(ast.NodeTransformer):
            hits = 0

            def visit_Raise(self, node):
                if (
                    isinstance(node.exc, ast.Call)
                    and node.exc.args
                    and isinstance(node.exc.args[0], ast.Constant)
                    and node.exc.args[0].value == message
                ):
                    self.hits += 1
                    return ast.copy_location(ast.Pass(), node)
                return node

        mutation = RemoveRejection()
        tree = ast.parse(ast.unparse(verification))
        tree = mutation.visit(tree)
        assert mutation.hits == 1
        namespace = dict(vars(tests.diag))
        exec(
            compile(ast.fix_missing_locations(tree), "<v16-mutation>", "exec"),
            namespace,
        )
        with mock.patch.object(
            tests.diag._CompilerLifecycle, "verify", namespace["verify"]
        ):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(
                unittest.TestSuite([tests.CompilerLifecycleTests(case_name)])
            )
        assert not result.wasSuccessful(), case_name
        print("MUTATION_CAUGHT=" + case_name)


if __name__ == "__main__":
    main()

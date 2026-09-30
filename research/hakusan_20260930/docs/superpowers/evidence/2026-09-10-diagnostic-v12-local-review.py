"""Main-agent scope and mutation review; no independent or GPU certification."""

import ast
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation"
OLD = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v11"
NEW = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v12"
BASE_SHA = "1b6e6f83115f995548bf9a859c02db86ed199f3bdcc5d05dfea386e351b990a9"


def version_only(text):
    for left, right in (
        ("_20260903_v11", "_20260903_v12"),
        ("_2026-09-03_v11", "_2026-09-03_v12"),
        ("_numeric_diag_v11", "_numeric_diag_v12"),
    ):
        text = text.replace(left, right)
    return text


def load(name):
    spec = importlib.util.spec_from_file_location(name[:-3], NEW / name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main():
    manifest = LEDGER / "v11-r2-candidate-manifest.sha256"
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == BASE_SHA
    for line in manifest.read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        raw = (OLD / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest, name
        if name not in ("README.md", "diagnose_batch_invariance.py"):
            assert version_only(raw.decode()) == (NEW / name).read_text(), name
    left = ast.parse(version_only((OLD / "diagnose_batch_invariance.py").read_text()))
    right = ast.parse((NEW / "diagnose_batch_invariance.py").read_text())
    old_nodes = {n.name: n for n in left.body if hasattr(n, "name")}
    new_nodes = {n.name: n for n in right.body if hasattr(n, "name")}
    assert set(new_nodes) - set(old_nodes) == {"_bounded_exception_diagnostic"}
    changed = {
        name
        for name in old_nodes
        if ast.dump(old_nodes[name]) != ast.dump(new_nodes[name])
    }
    assert changed == {"child_environment", "main"}, changed
    before = old_nodes["child_environment"]
    after = new_nodes["child_environment"]
    # Removing only the three approved literal entries must restore original AST.
    expected = {
        "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
        "OMP_NUM_THREADS": "8",
        "TOKENIZERS_PARALLELISM": "false",
    }
    removed = {}
    for node in ast.walk(after):
        if not isinstance(node, ast.Dict):
            continue
        keep = []
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value in expected:
                removed[key.value] = ast.literal_eval(value)
            else:
                keep.append((key, value))
        node.keys = [k for k, _ in keep]
        node.values = [v for _, v in keep]
    assert removed == expected
    assert ast.dump(before) == ast.dump(after)
    # Only one supplemental stderr try/except is added to main's original catch.
    old_main, new_main = old_nodes["main"], new_nodes["main"]
    old_handler = next(n for n in old_main.body if isinstance(n, ast.Try)).handlers[0]
    new_handler = next(n for n in new_main.body if isinstance(n, ast.Try)).handlers[0]
    assert len(new_handler.body) == len(old_handler.body) + 1
    extra = new_handler.body.pop(1)
    assert isinstance(extra, ast.Try)
    assert "DIAGNOSTIC_EXCEPTION_CHAIN=" in ast.unparse(extra)
    assert "file=sys.stderr" in ast.unparse(extra)
    assert ast.dump(old_main) == ast.dump(new_main)
    assert [ast.dump(n) for n in left.body if not hasattr(n, "name")] == [
        ast.dump(n) for n in right.body if not hasattr(n, "name")
    ]
    print("V11_16_FILES_PRESERVED_594_OLD_TESTS_VERSION_ONLY=PASS")
    print("V12_SCOPE_THREE_ENV_LITERALS_AND_STDERR_DIAGNOSTICS=PASS")

    env = load("test_launch_environment.py")
    err = load("test_exception_diagnostics.py")

    def mutation(module, cls, names, target, replacement, label):
        suite = unittest.TestSuite(getattr(module, cls)(n) for n in names)
        with mock.patch.object(module.diag, target, replacement):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        assert not result.wasSuccessful(), label
        print("MUTATION_CAUGHT=" + label)

    original_env = env.diag.child_environment
    for key in expected:

        def omit(*args, _key=key, **kwargs):
            result = original_env(*args, **kwargs)
            result.pop(_key)
            return result

        mutation(
            env,
            "LaunchEnvironmentTests",
            ["test_all_cold_roles_and_coordinator_receive_fixed_values"],
            "child_environment",
            omit,
            "omit_" + key,
        )

    def inherit(*args, **kwargs):
        result = original_env(*args, **kwargs)
        result.update({k: args[4][k] for k in expected})
        return result

    mutation(
        env,
        "LaunchEnvironmentTests",
        ["test_hostile_parent_cannot_override_fixed_values"],
        "child_environment",
        inherit,
        "inherit_parent_overrides",
    )
    original_error = err.diag._bounded_exception_diagnostic

    def leak(error):
        result = original_error(error)
        result["unsafe_message"] = str(error.__cause__)
        return result

    mutation(
        err,
        "ExceptionDiagnosticsTests",
        ["test_no_raw_messages_args_locals_source_or_full_paths"],
        "_bounded_exception_diagnostic",
        leak,
        "raw_cause_message_leak",
    )
    mutation(
        err,
        "ExceptionDiagnosticsTests",
        ["test_explicit_cause_location_and_reason_are_recorded"],
        "_bounded_exception_diagnostic",
        lambda e: {"chain": []},
        "lost_cause",
    )
    print("MAIN_AGENT_V12_REVIEW=PASS; NOT_GPU_OR_INDEPENDENT_REVIEW")


if __name__ == "__main__":
    main()

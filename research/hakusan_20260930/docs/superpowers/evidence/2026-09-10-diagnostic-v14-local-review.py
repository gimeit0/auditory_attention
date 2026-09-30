"""Predecessor preservation, exact approved scope and negative regression checks."""

import ast
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v13"
NEW = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v14"
MANIFEST = (
    ROOT
    / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v13-candidate-manifest.sha256"
)
OLD_PATH = ":/usr/local/bin:/usr/bin:/bin"
NEW_PATH = OLD_PATH + ":/usr/sbin:/sbin"


def version_only(text):
    for prefix in ("_20260903_v", "_2026-09-03_v", "_numeric_diag_v"):
        text = text.replace(prefix + "13", prefix + "14")
    return text


def main():
    assert (
        hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
        == "9cee85c7940c0ee3e5f75aeff28f7beea2124ef3b25dd30e55a2250f6e935839"
    )
    for line in MANIFEST.read_text().splitlines():
        sha, name = line.split()
        data = (OLD / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == sha, name
        if name not in ("README.md", "diagnose_batch_invariance.py"):
            expected = version_only(data.decode())
            if name in ("run_numeric_diag.sbatch", "test_numeric_diag.py"):
                assert expected.count(OLD_PATH) == 1
                expected = expected.replace(OLD_PATH, NEW_PATH)
            assert expected == (NEW / name).read_text(), name
    left = ast.parse(version_only((OLD / "diagnose_batch_invariance.py").read_text()))
    right = ast.parse((NEW / "diagnose_batch_invariance.py").read_text())
    a = {n.name: n for n in left.body if hasattr(n, "name")}
    b = {n.name: n for n in right.body if hasattr(n, "name")}
    helper = "_restore_missing_snapshot_modules_before_seal"
    assert set(b) - set(a) == {helper}
    assert set(a) - set(b) == set()
    changed = {name for name in a if ast.dump(a[name]) != ast.dump(b[name])}
    assert changed == {"prepare_formal40_worker", "child_environment"}, changed
    assert ast.dump(a["_SnapshotLoader"]) == ast.dump(b["_SnapshotLoader"])
    before = b["prepare_formal40_worker"].body
    insertion = [
        n for n in before if isinstance(n, ast.If) and helper in ast.unparse(n)
    ]
    assert len(insertion) == 1
    assert ast.unparse(insertion[0].test) == "capability.trust_domain == 'production'"
    assert len(insertion[0].body) == 1 and not insertion[0].orelse
    before.remove(insertion[0])
    assert ast.dump(a["prepare_formal40_worker"]) == ast.dump(
        b["prepare_formal40_worker"]
    )
    old_env = ast.unparse(a["child_environment"]).replace(OLD_PATH, NEW_PATH)
    assert old_env == ast.unparse(b["child_environment"])
    assert [ast.dump(n) for n in left.body if not hasattr(n, "name")] == [
        ast.dump(n) for n in right.body if not hasattr(n, "name")
    ]
    print("V13_19_FILES_PRESERVED_629_TESTS_NO_SCIENCE_ASSERTION_WEAKENED=PASS")
    print("V14_EXACT_SCOPE_PATH_PRESEAL_ONLY_LOADER_POSTSEAL_UNCHANGED=PASS")

    spec = importlib.util.spec_from_file_location(
        "v14_review_tests", NEW / "test_preseal_import_lifecycle.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    diag = module.diag

    def rejects(name, target, attribute, replacement):
        test = module.PresealLifecycleTests(name)
        with mock.patch.object(target, attribute, replacement):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(
                unittest.TestSuite([test])
            )
        assert not result.wasSuccessful(), name
        print("MUTATION_CAUGHT=" + name)

    rejects(
        "test_restore_exact_original_objects_without_reexecution",
        diag,
        helper,
        lambda authority: (),
    )
    rejects(
        "test_changed_missing_callable_rejected_and_insertions_rolled_back",
        diag._SnapshotLoader,
        "verify_runtime_bindings",
        lambda self: None,
    )
    rejects(
        "test_post_seal_addition_replacement_and_removal_still_rejected",
        diag._SnapshotLoader,
        "verify_runtime_bindings",
        lambda self: None,
    )
    original = diag.child_environment

    def old_path(*args):
        env = original(*args)
        env["PATH"] = env["PATH"].replace(NEW_PATH, OLD_PATH)
        return env

    with mock.patch.object(diag, "child_environment", old_path):
        suite = unittest.TestSuite(
            [module.CompilerPathTests("test_all_roles_use_fixed_appended_system_sbin")]
        )
        result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        assert not result.wasSuccessful()
    print("MUTATION_CAUGHT=compiler_path_regression")


if __name__ == "__main__":
    main()

"""Bounded native eval-scope review and regression mutation checks."""

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
OLD = LEDGER / "snapshots/v11-ordered-registry-r1"
NEW = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v11"


def main():
    manifest = OLD / "candidate-manifest.sha256"
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == (
        "2e72c2dccda2a50980a097581b7b43da8f6502147ac97ced335b5e8fcd55ea01"
    )
    for line in manifest.read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        assert hashlib.sha256((OLD / name).read_bytes()).hexdigest() == digest
        if name not in ("README.md", "diagnose_batch_invariance.py"):
            assert (OLD / name).read_bytes() == (NEW / name).read_bytes()
    left = ast.parse((OLD / "diagnose_batch_invariance.py").read_text())
    right = ast.parse((NEW / "diagnose_batch_invariance.py").read_text())
    old_nodes = {n.name: n for n in left.body if hasattr(n, "name")}
    new_nodes = {n.name: n for n in right.body if hasattr(n, "name")}
    assert set(new_nodes) - set(old_nodes) == {"_require_registered_modules_eval"}
    changed = {
        name
        for name in old_nodes
        if ast.dump(old_nodes[name]) != ast.dump(new_nodes[name])
    }
    assert changed == {"prepare_formal40_worker"}, changed
    before = old_nodes["prepare_formal40_worker"]
    after = new_nodes["prepare_formal40_worker"]
    index = next(
        i
        for i, n in enumerate(before.body)
        if isinstance(n, ast.If) and "not in eval mode" in ast.unparse(n)
    )
    before.body[index] = ast.parse("_require_registered_modules_eval(model)").body[0]
    assert ast.dump(before) == ast.dump(after)
    old_other = [ast.dump(n) for n in left.body if not hasattr(n, "name")]
    new_other = [ast.dump(n) for n in right.body if not hasattr(n, "name")]
    assert old_other == new_other
    print("R1_PRESERVED_AND_585_EXISTING_TESTS_UNCHANGED=PASS")
    print("R2_SCOPE_ONE_HELPER_ONE_GUARD_NO_SCIENCE_OR_SEAL_CHANGES=PASS")

    spec = importlib.util.spec_from_file_location(
        "native_eval_review", NEW / "test_native_eval_scope.py"
    )
    fixtures = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = fixtures
    spec.loader.exec_module(fixtures)
    diag = fixtures.diag

    def run_mutation(label, replacement, names):
        suite = unittest.TestSuite(fixtures.NativeEvalScopeTests(n) for n in names)
        with mock.patch.object(diag, "_require_registered_modules_eval", replacement):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        assert not result.wasSuccessful(), label
        print("MUTATION_CAUGHT=" + label)

    run_mutation(
        "skip_eval_guard",
        lambda model: None,
        [
            "test_every_registered_module_still_requires_eval",
            "test_invalid_registered_training_state_rejected",
        ],
    )

    def force_eval(model):
        for _, child, _, _ in diag._direct_model_module_inventory(model):
            child.training = False

    run_mutation(
        "force_audio_mode",
        force_eval,
        [
            "test_native_list_modes_preserved_but_inventory_kept",
        ],
    )

    def old_guard(model):
        if any(
            diag._direct_module_training_state(m)
            for _, m, _, _ in diag._direct_model_module_inventory(model)
        ):
            raise diag.DiagnosticError("old all-inventory eval guard")

    run_mutation(
        "old_all_inventory_guard",
        old_guard,
        [
            "test_worker_accepts_native_modes_without_mutating_them",
        ],
    )
    print("MAIN_AGENT_R2_REVIEW=PASS; NOT_INDEPENDENT_OR_GPU_VALIDATION")


if __name__ == "__main__":
    main()

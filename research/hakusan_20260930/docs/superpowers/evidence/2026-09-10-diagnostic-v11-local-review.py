"""Main-agent scope and mutation review; no remote side effects or forward."""

import ast
from collections import OrderedDict
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v10"
NEW = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v11"


def normalize(text):
    return text.replace("20260903_v10", "20260903_v11").replace(
        "2026-09-03_v10", "2026-09-03_v11"
    )


def main():
    manifest = (
        ROOT
        / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v10-r3-candidate-manifest.sha256"
    )
    assert (
        hashlib.sha256(manifest.read_bytes()).hexdigest()
        == "ca282426ebead30831fb87b22ce6de0f1fb93cf09c397a8cc1c75c41745bdee1"
    )
    for line in manifest.read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        assert hashlib.sha256((OLD / name).read_bytes()).hexdigest() == digest
    print("PUBLISHED_V10_FOURTEEN_FILES_UNCHANGED=PASS")
    left = ast.parse(normalize((OLD / "diagnose_batch_invariance.py").read_text()))
    right = ast.parse((NEW / "diagnose_batch_invariance.py").read_text())
    definitions = (ast.FunctionDef, ast.ClassDef)
    old_functions = {
        node.name: node for node in left.body if isinstance(node, definitions)
    }
    new_functions = {
        node.name: node for node in right.body if isinstance(node, definitions)
    }
    changed = {
        name
        for name, node in old_functions.items()
        if ast.dump(node) != ast.dump(new_functions[name])
    }
    assert changed == {
        "_static_attribute",
        "_container_execution_identity",
        "_direct_model_module_inventory",
        "_registered_state_fingerprint",
        "_require_frozen_direct_parameters",
        "_snapshot_model_entries",
    }, changed
    assert set(new_functions) - set(old_functions) == {
        "_native_registry_items",
        "_require_native_ordered_key",
        "_native_ordered_execution_items",
    }
    old_other = [node for node in left.body if not isinstance(node, definitions)]
    new_other = [node for node in right.body if not isinstance(node, definitions)]
    for index, node in enumerate(old_other):
        if isinstance(node, ast.ImportFrom) and node.module == "collections":
            old_other[index] = ast.parse(
                "from collections import OrderedDict, deque"
            ).body[0]
    assert [ast.dump(node) for node in old_other] == [
        ast.dump(node) for node in new_other
    ]
    for name in (
        "numeric_trace.py",
        "submit_numeric_diag.py",
        "run_numeric_diag.sbatch",
    ):
        assert normalize((OLD / name).read_text()) == (NEW / name).read_text(), name
    for path in OLD.glob("test_*.py"):
        assert normalize(path.read_text()) == (NEW / path.name).read_text(), path.name
    print("AST_SCOPE_SIX_CHANGED_THREE_NEW_FUNCTIONS=PASS")
    print("SCIENCE_BUDGET_AND_561_EXISTING_TESTS_UNCHANGED=PASS")

    spec = importlib.util.spec_from_file_location(
        "ordered_review_fixtures", NEW / "test_ordered_registries.py"
    )
    fixtures = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = fixtures
    spec.loader.exec_module(fixtures)
    diag = fixtures.diag

    def require_caught(label, target, replacement, names):
        suite = unittest.TestSuite(
            fixtures.OrderedRegistryTests(name) for name in names
        )
        with mock.patch.object(diag, target, replacement):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        count = len(result.failures) + len(result.errors)
        assert count == len(names), (label, count, len(names))
        print(f"MUTATION_CAUGHT={label}:{count}/{len(names)}")

    old_snapshot = ast.Module(
        body=[old_functions["_snapshot_model_entries"]], type_ignores=[]
    )
    namespace = dict(vars(diag))
    exec(compile(old_snapshot, "published_v10_snapshot", "exec"), namespace)
    previous = namespace["_snapshot_model_entries"]
    require_caught(
        "old_snapshot",
        "_snapshot_model_entries",
        previous,
        ["test_snapshot_parameters_buffers_scalar_and_repeat"],
    )
    require_caught(
        "lost_order",
        "_native_ordered_execution_items",
        lambda value, path: tuple(dict.items(value)),
        [
            "test_configuration_and_hooks_preserve_order",
            "test_real_hook_reorder_changes_complete_fingerprint",
        ],
    )
    require_caught(
        "unsafe_keys",
        "_native_registry_items",
        lambda registry: tuple(OrderedDict.items(registry)),
        ["test_registry_key_rejected_without_hash_equality_or_repr"],
    )
    original_static = diag._static_attribute

    def no_registered_lookup(value, name, default=None):
        namespace = diag._safe_instance_dict(value)
        if namespace is not None:
            for registry_name in ("_parameters", "_buffers", "_modules"):
                registry = namespace.get(registry_name)
                if type(registry) is OrderedDict and name in registry:
                    return default
        return original_static(value, name, default)

    require_caught(
        "missing_registered_lookup",
        "_static_attribute",
        no_registered_lookup,
        ["test_static_lookup_resolves_children_parameters_buffers"],
    )
    import torch

    model = torch.nn.Linear(2, 1).eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    assert previous(model) == diag._snapshot_model_entries(model)
    print("EXACT_DICT_SNAPSHOT_SCHEMA_CONTENT_PARITY=PASS")
    print("MAIN_AGENT_REVIEW=PASS; NOT_INDEPENDENT_REVIEW; NOT_GPU_VALIDATION")


if __name__ == "__main__":
    main()

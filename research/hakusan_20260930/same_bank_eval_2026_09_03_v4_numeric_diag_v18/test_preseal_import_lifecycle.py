"""Pre-seal exact-object restoration and immutable post-seal rejection tests."""

import ast
import contextlib
import hashlib
import importlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

PACKAGE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "preseal_lifecycle_diag", PACKAGE / "diagnose_batch_invariance.py"
)
diag = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diag
SPEC.loader.exec_module(diag)


@contextlib.contextmanager
def fixture():
    saved = {
        name: value
        for name, value in sys.modules.items()
        if name == "src" or name.startswith("src.")
    }
    for name in saved:
        sys.modules.pop(name)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        sources = {
            "src/__init__.py": "",
            "src/helper.py": "def shift(x):\n    return x + 1\n",
            "src/model.py": "from src.helper import shift\ndef forward(x):\n    return shift(x)\n",
        }
        records = {}
        for name, source in sources.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
            records[name] = {
                "sha256": hashlib.sha256(source.encode()).hexdigest(),
                "size": len(source.encode()),
            }
        loader = diag._SnapshotLoader(root, records, diag._get_trace())
        sys.meta_path.insert(0, loader)
        token = diag._ACTIVE_SNAPSHOT_AUTHORITY.set(loader)
        try:
            model = importlib.import_module("src.model")
            issued = {
                name: entries[0][0] for name, entries in loader.issued_modules.items()
            }
            yield loader, issued, model
        finally:
            diag._ACTIVE_SNAPSHOT_AUTHORITY.reset(token)
            sys.meta_path.remove(loader)
            for name in tuple(sys.modules):
                if name == "src" or name.startswith("src."):
                    sys.modules.pop(name)
            sys.modules.update(saved)


def remove(issued):
    for name in issued:
        sys.modules.pop(name)


class PresealLifecycleTests(unittest.TestCase):
    def restore(self, loader):
        return diag._restore_missing_snapshot_modules_before_seal(loader)

    def test_restore_exact_original_objects_without_reexecution(self):
        with fixture() as (loader, issued, model):
            function, globals_dict = model.forward, model.forward.__globals__
            remove(issued)
            with mock.patch.object(
                loader, "exec_module", side_effect=AssertionError("must not reload")
            ):
                self.assertEqual(self.restore(loader), tuple(sorted(issued)))
            for name, module in issued.items():
                self.assertIs(sys.modules[name], module)
            self.assertIs(model.forward, function)
            self.assertIs(model.forward.__globals__, globals_dict)
            self.assertEqual(model.forward(8), 9)
            loader.seal_runtime_bindings()
            loader.verify_runtime_bindings()

    def test_cpu_dynamo_cross_module_trace_keeps_restored_seal(self):
        import torch

        torch._dynamo.reset()
        try:
            with fixture() as (loader, issued, model):
                compiled = torch.compile(
                    model.forward, backend=lambda graph, inputs: graph.forward
                )
                remove(issued)
                self.restore(loader)
                loader.seal_runtime_bindings()
                before = dict(loader.sealed_bindings)
                values = torch.arange(8, dtype=torch.float32)
                self.assertTrue(torch.equal(compiled(values), values + 1))
                loader.verify_runtime_bindings()
                self.assertEqual(loader.sealed_bindings, before)
                for name, module in issued.items():
                    self.assertIs(sys.modules[name], module)
        finally:
            torch._dynamo.reset()

    def test_existing_bindings_are_untouched(self):
        with fixture() as (loader, issued, _):
            self.assertEqual(self.restore(loader), ())
            for name, module in issued.items():
                self.assertIs(sys.modules[name], module)

    def test_missing_children_do_not_replace_existing_parent(self):
        with fixture() as (loader, issued, _):
            sys.modules.pop("src.helper")
            sys.modules.pop("src.model")
            parent = sys.modules["src"]
            self.assertEqual(self.restore(loader), ("src.helper", "src.model"))
            self.assertIs(sys.modules["src"], parent)
            self.assertIs(parent.helper, issued["src.helper"])

    def test_ambiguous_issued_versions_rejected_without_insertion(self):
        with fixture() as (loader, issued, _):
            remove(issued)
            importlib.import_module("src.model")
            remove(issued)
            with self.assertRaisesRegex(diag.DiagnosticError, "ambiguous"):
                self.restore(loader)
            self.assertFalse(any(name in sys.modules for name in issued))
            self.assertTrue(loader.invalid)

    def test_current_unissued_object_is_not_overwritten(self):
        with fixture() as (loader, issued, _):
            remove(issued)
            foreign = types.ModuleType("src.helper")
            sys.modules["src.helper"] = foreign
            with self.assertRaisesRegex(diag.DiagnosticError, "unissued"):
                self.restore(loader)
            self.assertIs(sys.modules["src.helper"], foreign)
            self.assertNotIn("src", sys.modules)
            self.assertTrue(loader.invalid)

    def test_changed_missing_callable_rejected_and_insertions_rolled_back(self):
        with fixture() as (loader, issued, model):
            remove(issued)
            model.forward = lambda x: x
            with self.assertRaisesRegex(diag.DiagnosticError, "callable changed"):
                self.restore(loader)
            self.assertFalse(any(name in sys.modules for name in issued))
            self.assertTrue(loader.invalid)

    def test_changed_missing_origin_rejected(self):
        with fixture() as (loader, issued, model):
            remove(issued)
            model.__file__ = "/untrusted/source.py"
            with self.assertRaisesRegex(diag.DiagnosticError, "origin changed"):
                self.restore(loader)
            self.assertFalse(any(name in sys.modules for name in issued))

    def test_parent_child_conflict_is_not_rewritten(self):
        with fixture() as (loader, issued, _):
            foreign = object()
            issued["src"].helper = foreign
            remove(issued)
            with self.assertRaisesRegex(diag.DiagnosticError, "parent binding"):
                self.restore(loader)
            self.assertIs(issued["src"].helper, foreign)
            self.assertFalse(any(name in sys.modules for name in issued))

    def test_previously_required_removal_is_not_repaired(self):
        with fixture() as (loader, issued, _):
            loader.verify_runtime_bindings()
            sys.modules.pop("src.helper")
            with self.assertRaisesRegex(diag.DiagnosticError, "removed"):
                self.restore(loader)
            self.assertNotIn("src.helper", sys.modules)

    def test_helper_cannot_run_after_seal(self):
        with fixture() as (loader, _, _):
            loader.seal_runtime_bindings()
            with self.assertRaisesRegex(diag.DiagnosticError, "before seal"):
                self.restore(loader)
            self.assertTrue(loader.invalid)

    def test_helper_requires_active_authority_and_original_registry(self):
        with fixture() as (loader, issued, _):
            remove(issued)
            token = diag._ACTIVE_SNAPSHOT_AUTHORITY.set(None)
            try:
                with self.assertRaises(diag.DiagnosticError):
                    self.restore(loader)
            finally:
                diag._ACTIVE_SNAPSHOT_AUTHORITY.reset(token)
            self.assertFalse(any(name in sys.modules for name in issued))
        with fixture() as (loader, _, _):
            with mock.patch.object(sys, "modules", dict(sys.modules)):
                with self.assertRaisesRegex(diag.DiagnosticError, "registry"):
                    self.restore(loader)

    def test_post_seal_addition_replacement_and_removal_still_rejected(self):
        for mutation in ("add", "replace", "remove"):
            with self.subTest(mutation=mutation), fixture() as (loader, issued, _):
                remove(issued)
                self.restore(loader)
                loader.seal_runtime_bindings()
                if mutation == "add":
                    sys.modules["src.extra"] = types.ModuleType("src.extra")
                elif mutation == "replace":
                    sys.modules["src.helper"] = types.ModuleType("src.helper")
                else:
                    sys.modules.pop("src.helper")
                with self.assertRaisesRegex(
                    diag.DiagnosticError, "sealed frozen module"
                ):
                    loader.verify_runtime_bindings()
                with self.assertRaisesRegex(diag.DiagnosticError, "revoked"):
                    loader.verify_runtime_bindings()

    def test_production_restores_after_strict_load_before_any_model_graph(self):
        tree = ast.parse((PACKAGE / "diagnose_batch_invariance.py").read_text())
        worker = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "prepare_formal40_worker"
        )
        calls = [node for node in ast.walk(worker) if isinstance(node, ast.Call)]
        restore = [
            node
            for node in calls
            if ast.unparse(node.func) == "_restore_missing_snapshot_modules_before_seal"
        ]
        strict = next(
            node
            for node in calls
            if ast.unparse(node.func) == "evaluator.strict_load_model"
        )
        graph = next(
            node for node in calls if ast.unparse(node.func) == "_callable_graphs"
        )
        self.assertEqual(len(restore), 1)
        self.assertLess(strict.lineno, restore[0].lineno)
        self.assertLess(restore[0].lineno, graph.lineno)


class CompilerPathTests(unittest.TestCase):
    def test_all_roles_use_fixed_appended_system_sbin(self):
        expected = f"{diag.PRODUCTION_PYTHON.parent}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        parent = {
            "SLURM_JOB_ID": "123",
            "CUDA_VISIBLE_DEVICES": "0",
            "PATH": "/untrusted",
        }
        for cell in (None, "A2", "A1", "B1", "B2"):
            env = diag.child_environment(
                "_child-reference" if cell is None else "_child-cell",
                "123",
                cell,
                "/tmp/audattn_v4_numdiag_123",
                parent,
            )
            self.assertEqual(env["PATH"], expected)
        env = diag.coordinator_environment("123", "/tmp/audattn_v4_numdiag_123", parent)
        self.assertEqual(env["PATH"], expected)
        self.assertEqual(parent["PATH"], "/untrusted")

    def test_shell_bootstrap_has_same_fixed_path(self):
        runner = (PACKAGE / "run_numeric_diag.sbatch").read_text()
        line = "  PATH=/home/s2510040/miniconda3/envs/attn/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin \\"
        self.assertEqual(runner.splitlines().count(line), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

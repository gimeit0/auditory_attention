"""Lifecycle checks for the experimental policy, not production acceptance."""

import hashlib
import importlib.util
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock
import json

PACKAGE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "real_evaluator_scope_tests", PACKAGE / "diagnose_batch_invariance.py"
)
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)
path = PACKAGE.parent / "same_bank_eval_2026_08_29_v4/locked_same_bank_eval.py"
payload = path.read_bytes()
assert hashlib.sha256(payload).hexdigest() == diag.V4_EVALUATOR_SHA256
facade = diag.load_verified_v4_evaluator(
    diag._get_trace(),
    path,
    len(payload),
    diag.V4_EVALUATOR_SHA256,
    allowed_root=path.parent,
)
values = {n: getattr(facade, n) for n in diag.V4_EVALUATOR_WHITELIST}
baseline = diag._VERIFIED_PRODUCTION_EVALUATORS[id(facade)][3]


def graph():
    return diag._callable_graphs(values, materialize_module_attributes=True)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name).resolve()
        files = {
            "selftrain/__init__.py": b"",
            "selftrain/data/__init__.py": b"",
            "selftrain/data/diotic_attention.py": b"class WaveformCache: pass\n",
            "selftrain/scripts/__init__.py": b"",
            "selftrain/scripts/eval_full_pilot.py": (
                b"def _raw_scene_batch(): return 'raw'\n"
                b"def _correct_cue_batch(): return 'cue'\n"
            ),
        }
        self.records = {}
        for relative, payload in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            self.records[relative] = {
                "path": relative,
                "type": "file",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }

    def test_context_restores_registry_and_revokes_callback(self):
        before = {
            n: m for n, m in sys.modules.items() if n.partition(".")[0] == "selftrain"
        }
        with diag.frozen_scene_context(self.root, self.records) as api:
            self.assertEqual(api.raw_scene_batch(), "raw")
        after = {
            n: m for n, m in sys.modules.items() if n.partition(".")[0] == "selftrain"
        }
        self.assertEqual(before, after)
        with self.assertRaisesRegex(diag.DiagnosticError, "after context exit"):
            api.raw_scene_batch()

    def test_tampered_source_rejected_at_import(self):
        (self.root / "selftrain/data/diotic_attention.py").write_text(
            "class Changed: pass\n"
        )
        with self.assertRaisesRegex(ImportError, "identity mismatch"):
            with diag.frozen_scene_context(self.root, self.records):
                self.fail("tampered source entered context")

    def test_protected_module_replacement_changes_active_graph(self):
        with diag.frozen_scene_context(self.root, self.records):
            graph()
            name = "selftrain.data.diotic_attention"
            original = sys.modules[name]
            try:
                sys.modules[name] = types.ModuleType(name)
                with self.assertRaises(diag.DiagnosticError):
                    graph()
            finally:
                sys.modules[name] = original

    def test_legitimate_context_entry_keeps_evaluator_seal_valid(self):
        before = graph()
        with diag.frozen_scene_context(self.root, self.records):
            self.assertTrue(
                graph() == before,
                "authorized frozen scope still invalidates evaluator graph",
            )

    def test_real_evaluator_cleanup_and_pandas_import(self):
        self.assertEqual(graph(), baseline)
        import pandas as pd
        import io

        pd.read_csv(io.StringIO("trial_id\n1\n"), sep="\t")
        self.assertEqual(graph(), baseline)

    def test_nested_real_v4_context_restores_authorized_modules(self):
        with diag.frozen_scene_context(self.root, self.records) as api:
            self.assertEqual(graph(), baseline)
            original = sys.modules["selftrain.data.diotic_attention"]
            with facade._frozen_import_context(self.root):
                import importlib

                loaded = importlib.import_module("selftrain.data.diotic_attention")
                self.assertIsNot(loaded, original)
            self.assertIs(sys.modules["selftrain.data.diotic_attention"], original)
            self.assertEqual(api.raw_scene_batch(), "raw")
            self.assertEqual(graph(), baseline)

    def test_function_code_mutation_is_rejected(self):
        with diag.frozen_scene_context(self.root, self.records):
            module = sys.modules["selftrain.scripts.eval_full_pilot"]
            original = module._raw_scene_batch.__code__
            try:
                module._raw_scene_batch.__code__ = (lambda: "wrong").__code__
                with self.assertRaises(diag.DiagnosticError):
                    graph()
            finally:
                module._raw_scene_batch.__code__ = original

    def test_real_runtime_configuration_keeps_code_graph(self):
        self.assertEqual(graph(), baseline)
        facade._configure_runtime(True)
        self.assertEqual(graph(), baseline)

    def test_unrelated_registry_changes_do_not_disable_function_guard(self):
        name = "_benign_scope_fixture"
        self.assertNotIn(name, sys.modules)
        try:
            sys.modules[name] = types.ModuleType(name)
            self.assertEqual(graph(), baseline)
            original = values["strict_load_model"]
            try:
                values["strict_load_model"] = lambda *a, **k: None
                self.assertNotEqual(graph(), baseline)
            finally:
                values["strict_load_model"] = original
        finally:
            sys.modules.pop(name, None)

    def test_general_callables_still_seal_registry_contents(self):
        def untrusted():
            return sys.modules

        before = diag._callable_graph_fingerprint(untrusted)
        name = "_general_registry_fixture"
        try:
            self.assertNotIn(name, sys.modules)
            sys.modules[name] = types.ModuleType(name)
            self.assertNotEqual(diag._callable_graph_fingerprint(untrusted), before)
        finally:
            sys.modules.pop(name, None)

    def test_direct_import_dependency_replacement_is_detected(self):
        import yaml

        original = yaml
        before = graph()
        try:
            sys.modules["yaml"] = types.ModuleType("yaml")
            self.assertTrue(
                graph() != before, "direct import replacement went undetected"
            )
        finally:
            sys.modules["yaml"] = original

    def test_initialized_seed_callable_replacement_is_detected(self):
        import torch

        before = graph()
        original = torch.manual_seed
        try:
            torch.manual_seed = lambda seed: None
            self.assertNotEqual(graph(), before)
        finally:
            torch.manual_seed = original

    def test_declared_lazy_import_is_bound_then_frozen(self):
        relative = "selftrain/late_helper.py"
        payload = b"VALUE = 42\n"
        (self.root / relative).write_bytes(payload)
        self.records[relative] = {
            "path": relative,
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "type": "file",
        }
        with diag.frozen_scene_context(self.root, self.records):
            import importlib

            loaded = importlib.import_module("selftrain.late_helper")
            self.assertEqual(loaded.VALUE, 42)
            self.assertEqual(graph(), baseline)
            authority = diag._ACTIVE_SNAPSHOT_AUTHORITY.get()
            authority.seal_runtime_bindings()
            self.assertEqual(graph(), baseline)
            original = sys.modules["selftrain.late_helper"]
            try:
                sys.modules["selftrain.late_helper"] = types.ModuleType(
                    "selftrain.late_helper"
                )
                with self.assertRaisesRegex(diag.DiagnosticError, "sealed"):
                    graph()
            finally:
                sys.modules["selftrain.late_helper"] = original

    def test_spec_origin_mutation_rejected(self):
        with diag.frozen_scene_context(self.root, self.records):
            spec = sys.modules["selftrain.data.diotic_attention"].__spec__
            original = spec.origin
            try:
                spec.origin = "/unreviewed/source.py"
                with self.assertRaisesRegex(diag.DiagnosticError, "origin"):
                    graph()
            finally:
                spec.origin = original

    def test_defaults_mutation_is_rejected(self):
        with diag.frozen_scene_context(self.root, self.records):
            function = sys.modules["selftrain.scripts.eval_full_pilot"]._raw_scene_batch
            original = function.__defaults__
            try:
                function.__defaults__ = ("unreviewed",)
                with self.assertRaisesRegex(diag.DiagnosticError, "callable changed"):
                    graph()
            finally:
                function.__defaults__ = original

    def test_finder_removal_is_rejected(self):
        with diag.frozen_scene_context(self.root, self.records):
            authority = diag._ACTIVE_SNAPSHOT_AUTHORITY.get()
            index = sys.meta_path.index(authority)
            sys.meta_path.remove(authority)
            try:
                with self.assertRaisesRegex(diag.DiagnosticError, "finder was removed"):
                    graph()
            finally:
                sys.meta_path.insert(index, authority)

    def test_whole_registry_replacement_is_rejected(self):
        original = sys.modules
        try:
            sys.modules = dict(original)
            with self.assertRaises(diag.DiagnosticError):
                graph()
        finally:
            sys.modules = original

    def test_initialized_dependency_code_mutation_is_detected(self):
        import torch

        function = torch.manual_seed
        original = function.__code__
        before = graph()
        # Preserve the closure arity of the installed wrapper, if any.
        count = len(function.__closure__ or ())
        cells = ", ".join(f"x{i}" for i in range(count))
        source = "def outer():\n"
        for index in range(count):
            source += f"    x{index} = None\n"
        source += f"    def inner(*args, **kwargs): return ({cells})\n"
        source += "    return inner\n"
        namespace = {}
        exec(source, namespace)
        try:
            function.__code__ = namespace["outer"]().__code__
            self.assertNotEqual(graph(), before)
        finally:
            function.__code__ = original

    def test_real_source_reaches_production_context_registration(self):
        tools = self.root / "tools"
        tools.mkdir()
        evaluator_path = tools / "locked_same_bank_eval.py"
        evaluator_path.write_bytes(payload)
        source_manifest = self.root / "manifest.json"
        source_manifest.write_text("{}")
        bank = self.root / "bank.tsv"
        bank.write_text("trial_id\n1\n")
        manifest_path = self.root / "input_freeze.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "roots": {
                        "snapshot_files": str(self.root),
                        "run_root": str(self.root),
                    },
                    "inputs": {
                        "bank": {
                            "path": str(bank),
                            "size": bank.stat().st_size,
                            "sha256": hashlib.sha256(bank.read_bytes()).hexdigest(),
                        }
                    },
                }
            )
        )
        trace = diag._get_trace()
        _, evaluator_record = trace.read_stable_bytes(
            evaluator_path, allowed_root=self.root
        )
        _, source_record = trace.read_stable_bytes(
            self.root / "selftrain/data/diotic_attention.py", allowed_root=self.root
        )
        contract = types.SimpleNamespace(
            v4_root=self.root,
            manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            evaluator_sha256=diag.V4_EVALUATOR_SHA256,
        )
        # The real source and production registration are not mocked. Only the
        # scientific manifest/history fixture, unavailable locally, is substituted.
        with (
            mock.patch.object(
                diag,
                "_collect_pinned_records",
                return_value=[{"path": str(source_manifest)}],
            ),
            mock.patch.object(diag, "validate_v4_manifest", return_value={}),
            mock.patch.object(
                diag, "_verify_v4_pinned_records", return_value=[evaluator_record]
            ),
            mock.patch.object(
                diag, "collect_snapshot_records", return_value=[source_record]
            ),
            mock.patch.object(diag, "_historical_scene_binding", return_value={}),
        ):
            context = diag.read_frozen_context(contract=contract)
        cap = context["_frozen_context_capability"]
        self.assertEqual(cap.trust_domain, "production")
        diag._validate_frozen_capability_contents(cap)
        with diag.frozen_scene_context(self.root, self.records):
            diag._validate_frozen_capability_contents(cap)
        diag._validate_frozen_capability_contents(cap)

    def test_sealed_scope_rejects_even_authorized_new_module(self):
        relative = "selftrain/late_helper.py"
        raw = b"VALUE = 1\n"
        (self.root / relative).write_bytes(raw)
        self.records[relative] = {
            "path": relative,
            "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "type": "file",
        }
        with diag.frozen_scene_context(self.root, self.records):
            authority = diag._ACTIVE_SNAPSHOT_AUTHORITY.get()
            authority.seal_runtime_bindings()
            import importlib

            importlib.import_module("selftrain.late_helper")
            with self.assertRaisesRegex(diag.DiagnosticError, "sealed"):
                graph()

    def test_revocation_is_sticky_until_scope_exit(self):
        with diag.frozen_scene_context(self.root, self.records):
            graph()
            name = "selftrain.data.diotic_attention"
            original = sys.modules.pop(name)
            try:
                with self.assertRaises(diag.DiagnosticError):
                    graph()
            finally:
                sys.modules[name] = original
            with self.assertRaisesRegex(diag.DiagnosticError, "revoked"):
                graph()
        self.assertEqual(graph(), baseline)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Local regression only; does not modify or publish the reviewed v2 package."""

import ast
import hashlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock


PACKAGE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "v2_loader_regression", PACKAGE / "diagnose_batch_invariance.py"
)
diag = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diag
SPEC.loader.exec_module(diag)


class LoaderRecordRegression(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        # This standalone fixture owns a separate diagnostic module. Do not leave
        # its verified trace module in the interpreter used by the other suites.
        if sys.modules.get("_numeric_trace_verified") is diag._TRACE:
            sys.modules.pop("_numeric_trace_verified", None)
        diag._TRACE = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()
        (self.root / "tools").mkdir()
        self.path = self.root / "tools" / "locked_same_bank_eval.py"
        source = (
            "\n".join(
                f"def {name}(*args, **kwargs): return None"
                for name in diag.V4_EVALUATOR_WHITELIST
            )
            + "\n"
        )
        self.path.write_text(source)
        self.trace = diag._get_trace()
        # Exactly the two read roots used by read_frozen_context and its loader.
        self.payload, self.outer = self.trace.read_stable_bytes(
            self.path, allowed_root=self.root
        )
        self.facade = diag.load_verified_v4_evaluator(
            self.trace,
            self.path,
            len(self.payload),
            hashlib.sha256(self.payload).hexdigest(),
            allowed_root=self.root,
        )
        self.addCleanup(diag._VERIFIED_PRODUCTION_EVALUATORS.pop, id(self.facade), None)
        self.inner = diag._VERIFIED_PRODUCTION_EVALUATORS[id(self.facade)][1]

    def test_actual_reads_use_identical_root_relative_records(self):
        self.assertEqual(self.outer["relative_path"], "tools/locked_same_bank_eval.py")
        self.assertEqual(dict(self.inner), self.outer)
        self.assertEqual(
            {k: v for k, v in self.outer.items() if k != "relative_path"},
            {k: v for k, v in self.inner.items() if k != "relative_path"},
        )

    def test_same_verified_file_can_register_production_capability(self):
        # Desired behavior: a genuinely loaded unchanged file must register.
        # No fake evaluator registry entry and no bypass of capability validation.
        manifest = {"fixture": True}
        manifest_path = self.root / "input_freeze.json"
        manifest_path.write_text('{"fixture": true}\n')
        _, manifest_record = self.trace.read_stable_bytes(
            manifest_path, allowed_root=self.root
        )
        source_path = self.root / "source.py"
        source_path.write_text("VALUE = 1\n")
        _, source_record = self.trace.read_stable_bytes(
            source_path, allowed_root=self.root
        )
        diag._VERIFIED_PRODUCTION_MANIFESTS[id(manifest)] = (manifest, manifest_record)
        diag._VERIFIED_PRODUCTION_INVENTORIES[id(manifest)] = (
            manifest,
            (self.outer,),
            (source_record,),
            self.root,
        )
        self.addCleanup(diag._VERIFIED_PRODUCTION_MANIFESTS.pop, id(manifest), None)
        self.addCleanup(diag._VERIFIED_PRODUCTION_INVENTORIES.pop, id(manifest), None)
        capability = diag._register_frozen_context_capability(
            evaluator=self.facade,
            manifest=manifest,
            evaluator_record=self.outer,
            manifest_record=manifest_record,
            pinned_records=[self.outer],
            source_records=[source_record],
            root=self.root,
            source_root=self.root,
            trust_domain="production",
        )
        self.assertEqual(capability.trust_domain, "production")

    def test_outer_context_passes_its_root_to_real_loader(self):
        tree = ast.parse((PACKAGE / "diagnose_batch_invariance.py").read_text())
        context = next(
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "read_frozen_context"
        )
        calls = [
            n
            for n in ast.walk(context)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "load_verified_v4_evaluator"
        ]
        self.assertEqual(len(calls), 1)
        roots = [k.value for k in calls[0].keywords if k.arg == "allowed_root"]
        self.assertEqual(len(roots), 1)
        self.assertEqual(
            ast.dump(roots[0]), ast.dump(ast.Name(id="root", ctx=ast.Load()))
        )

    def test_wrong_hash_is_still_rejected(self):
        with self.assertRaisesRegex(diag.DiagnosticError, "identity mismatch"):
            diag.load_verified_v4_evaluator(
                self.trace,
                self.path,
                len(self.payload),
                "0" * 64,
                allowed_root=self.root,
            )

    def test_read_frozen_context_reaches_real_capability_registration(self):
        # Real orchestration, file reads, evaluator load, and capability checks.
        # Scientific inventory/bank-history validation is outside this fixture.
        source = self.root / "source.py"
        source.write_text("VALUE = 1\n")
        _, source_record = self.trace.read_stable_bytes(source, allowed_root=self.root)
        source_manifest = self.root / "manifest.json"
        source_manifest.write_text("{}\n")
        bank = self.root / "bank.tsv"
        bank.write_text("trial_id\n1\n")
        bank_record = {
            "path": str(bank),
            "size": bank.stat().st_size,
            "sha256": hashlib.sha256(bank.read_bytes()).hexdigest(),
        }
        manifest = {
            "roots": {"snapshot_files": str(self.root), "run_root": str(self.root)},
            "inputs": {"bank": bank_record},
        }
        manifest_path = self.root / "input_freeze.json"
        manifest_path.write_text(json.dumps(manifest))
        contract = types.SimpleNamespace(
            v4_root=self.root,
            manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            evaluator_sha256=hashlib.sha256(self.payload).hexdigest(),
        )
        with (
            mock.patch.object(
                diag,
                "_collect_pinned_records",
                return_value=[{"path": str(source_manifest)}],
            ),
            mock.patch.object(diag, "validate_v4_manifest", return_value={}),
            mock.patch.object(
                diag, "_verify_v4_pinned_records", return_value=[self.outer]
            ),
            mock.patch.object(
                diag, "collect_snapshot_records", return_value=[source_record]
            ),
            mock.patch.object(diag, "_historical_scene_binding", return_value={}),
        ):
            context = diag.read_frozen_context(contract=contract)
        self.assertEqual(
            context["_frozen_context_capability"].trust_domain, "production"
        )
        self.assertEqual(context["evaluator_record"], self.outer)
        diag._VERIFIED_PRODUCTION_EVALUATORS.pop(id(context["evaluator"]), None)
        diag._VERIFIED_PRODUCTION_MANIFESTS.pop(id(context["manifest"]), None)
        diag._VERIFIED_PRODUCTION_INVENTORIES.pop(id(context["manifest"]), None)

    def test_outside_root_is_still_rejected(self):
        other = self.root / "other"
        other.mkdir()
        with self.assertRaisesRegex(diag.DiagnosticError, "stable read failed"):
            diag.load_verified_v4_evaluator(
                self.trace,
                self.path,
                len(self.payload),
                hashlib.sha256(self.payload).hexdigest(),
                allowed_root=other,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)

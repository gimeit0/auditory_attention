"""Supplemental failure metadata only; all original rejection gates remain."""

import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

PACKAGE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "compiler_error_tests", PACKAGE / "diagnose_batch_invariance.py"
)
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)


def backend_error(inner):
    cls = type(
        "BackendCompilerFailed", (RuntimeError,), {"__module__": "torch._dynamo.exc"}
    )
    error = cls("private wrapper")
    error.inner_exception = inner
    return error


class CompilerDiagnosticsTests(unittest.TestCase):
    def test_real_pytorch_inner_edge(self):
        from torch._dynamo.exc import BackendCompilerFailed

        inner = RuntimeError("ptxas private")
        kwargs = (
            {"first_useful_frame": None}
            if "first_useful_frame"
            in inspect.signature(BackendCompilerFailed).parameters
            else {}
        )
        outer = BackendCompilerFailed(lambda *a: None, inner, **kwargs)
        result = diag._bounded_exception_diagnostic(outer)
        self.assertEqual(
            [n["type"] for n in result["chain"]],
            ["BackendCompilerFailed", "RuntimeError"],
        )
        self.assertEqual(result["chain"][1]["relation"], "inner_exception")
        self.assertIn("PTXAS_MENTIONED", result["chain"][1]["reason_codes"])

    def test_nested_internal_and_cause_chain(self):
        inner = ValueError("private")
        inner.__cause__ = OSError("Permission denied: PRIVATE_TOKEN")
        wrapper = backend_error(inner)
        outer = diag.DiagnosticError("outer")
        outer.__cause__ = wrapper
        result = diag._bounded_exception_diagnostic(outer)
        self.assertEqual(
            [n["type"] for n in result["chain"]],
            ["DiagnosticError", "BackendCompilerFailed", "ValueError", "OSError"],
        )
        self.assertEqual(
            result["chain"][-1]["reason_codes"], ["PERMISSION_DENIED_MENTIONED"]
        )
        self.assertNotIn("PRIVATE_TOKEN", json.dumps(result))

    def test_distinct_standard_cause_not_lost(self):
        outer = backend_error(ValueError("inner"))
        outer.__cause__ = KeyError("cause")
        result = diag._bounded_exception_diagnostic(outer)
        self.assertEqual(
            [n["type"] for n in result["chain"]],
            ["BackendCompilerFailed", "ValueError", "KeyError"],
        )

    def test_duplicate_standard_edge_once(self):
        inner = ValueError("inner")
        outer = backend_error(inner)
        outer.__cause__ = inner
        result = diag._bounded_exception_diagnostic(outer)
        self.assertEqual(len(result["chain"]), 2)
        self.assertFalse(result["chain_truncated"])

    def test_cyclic_internal_edge_bounded(self):
        outer = backend_error(None)
        outer.inner_exception = outer
        result = diag._bounded_exception_diagnostic(outer)
        self.assertEqual(len(result["chain"]), 1)
        self.assertTrue(result["chain_truncated"])

    def test_nested_internal_depth_bounded(self):
        error = RuntimeError("private" * 100000)
        for _ in range(20):
            error = backend_error(error)
        result = diag._bounded_exception_diagnostic(error)
        self.assertEqual(len(result["chain"]), 6)
        self.assertTrue(result["chain_truncated"])
        self.assertLess(len(json.dumps(result).encode()), 16384)

    def test_arbitrary_exception_field_ignored(self):
        error = RuntimeError("outer")
        error.inner_exception = ValueError("private")
        self.assertEqual(len(diag._bounded_exception_diagnostic(error)["chain"]), 1)

    def test_hostile_properties_not_executed(self):
        def hostile(*args):
            self.fail("arbitrary exception hook executed")

        cls = type(
            "BackendCompilerFailed",
            (RuntimeError,),
            {
                "__module__": "torch._dynamo.exc",
                "__getattribute__": hostile,
                "inner_exception": property(hostile),
                "__str__": hostile,
                "__repr__": hostile,
            },
        )
        result = diag._bounded_exception_diagnostic(cls("private"))
        self.assertEqual(len(result["chain"]), 1)

    def test_non_exception_field_not_traversed(self):
        class Hostile:
            def __getattribute__(self, name):
                raise AssertionError("read arbitrary field object")

        result = diag._bounded_exception_diagnostic(backend_error(Hostile()))
        self.assertEqual(len(result["chain"]), 1)

    def test_field_scan_bounded(self):
        outer = backend_error(None)
        del outer.inner_exception
        for index in range(70):
            vars(outer)[str(index)] = "private"
        outer.inner_exception = ValueError("inner")
        self.assertEqual(len(diag._bounded_exception_diagnostic(outer)["chain"]), 1)

    def test_module_delta_exact_counts_and_categories(self):
        a, b, c = object(), object(), object()
        error = diag._frozen_module_binding_error(
            {"src.same": a, "src.remove": b, "src.swap": b},
            {"src.same": a, "src.add": b, "src.swap": c},
        )
        self.assertIs(type(error), diag.DiagnosticError)
        self.assertEqual(str(error), "sealed frozen module bindings changed")
        record = diag._bounded_exception_diagnostic(error)["chain"][0]
        self.assertEqual(
            record["binding_delta"],
            {
                "added": {"count": 1, "names": ["src.add"]},
                "removed": {"count": 1, "names": ["src.remove"]},
                "replaced": {"count": 1, "names": ["src.swap"]},
            },
        )

    def test_delta_names_and_output_bounded(self):
        before = {"src." + "x" * 1000 + str(i): object() for i in range(30)}
        after = {"src." + "y" * 1000 + str(i): object() for i in range(30)}
        error = diag._frozen_module_binding_error(before, after)
        delta = diag._bounded_exception_diagnostic(error)["chain"][0]["binding_delta"]
        self.assertEqual(delta["added"]["count"], 30)
        self.assertEqual(len(delta["added"]["names"]), 3)
        self.assertTrue(all(len(n) <= 64 for n in delta["added"]["names"]))
        self.assertLess(len(json.dumps(delta).encode()), 16384)

    def test_malformed_metadata_ignored(self):
        error = diag.DiagnosticError("failure")
        for value in (
            None,
            object(),
            {"private": "secret"},
            (("added", 1, (object(),)),) * 3,
        ):
            error._binding_delta = value
            self.assertNotIn(
                "binding_delta", diag._bounded_exception_diagnostic(error)["chain"][0]
            )

    def test_delta_collection_failure_keeps_original_rejection(self):
        error = diag._frozen_module_binding_error(None, None)
        self.assertIs(type(error), diag.DiagnosticError)
        self.assertEqual(str(error), "sealed frozen module bindings changed")

    def test_worst_case_metadata_remains_under_display_budget(self):
        name = "f" * 96
        namespace = {}
        source = (
            f"def {name}(n):\n"
            f"    if n: return {name}(n-1)\n"
            "    raise RuntimeError('synthetic')\n"
        )
        exec(compile(source, "p" * 96 + ".py", "exec"), namespace)
        try:
            namespace[name](8)
        except RuntimeError as caught:
            tb = caught.__traceback__
        error = None
        for _ in range(6):
            before = {"src." + "x" * 100 + str(i): object() for i in range(12)}
            after = {"src." + "y" * 100 + str(i): object() for i in range(12)}
            newer = diag._frozen_module_binding_error(before, after)
            newer.__traceback__ = tb
            newer.__cause__ = error
            error = newer
        result = diag._bounded_exception_diagnostic(error)
        self.assertLessEqual(len(json.dumps(result, separators=(",", ":"))), 12288)
        self.assertLess(len(json.dumps(result).encode()), 16384)
        self.assertEqual(len(result["chain"]), 6)

    def test_fixed_compiler_labels_never_emit_raw_details(self):
        error = RuntimeError(
            "libcuda.so ptxas gcc g++ No such file or directory PRIVATE_PATH TOKEN=secret"
        )
        result = diag._bounded_exception_diagnostic(backend_error(error))
        record = result["chain"][-1]
        for label in (
            "LIBCUDA_MENTIONED",
            "PTXAS_MENTIONED",
            "GCC_MENTIONED",
            "GXX_MENTIONED",
            "MISSING_PATH_MENTIONED",
        ):
            self.assertIn(label, record["reason_codes"])
        for private in ("PRIVATE_PATH", "TOKEN=secret"):
            self.assertNotIn(private, json.dumps(result))

    def test_real_loader_rejection_and_sticky_revocation(self):
        name = "diagnostic_toy_binding_v13"
        self.assertNotIn(name, sys.modules)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            payload = b"def forward(): return 1\n"
            (root / (name + ".py")).write_bytes(payload)
            records = {
                name + ".py": {
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            }
            finder = diag._SnapshotLoader(root, records, diag._get_trace())
            sys.meta_path.insert(0, finder)
            try:
                original = importlib.import_module(name)
                finder.seal_runtime_bindings()
                finder.verify_runtime_bindings()
                sys.modules[name] = types.ModuleType(name)
                with self.assertRaisesRegex(
                    diag.DiagnosticError, "sealed frozen module bindings changed"
                ) as caught:
                    finder.verify_runtime_bindings()
                self.assertTrue(finder.invalid)
                delta = diag._bounded_exception_diagnostic(caught.exception)["chain"][
                    0
                ]["binding_delta"]
                self.assertEqual(delta["replaced"], {"count": 1, "names": [name]})
                sys.modules[name] = original
                with self.assertRaisesRegex(diag.DiagnosticError, "revoked"):
                    finder.verify_runtime_bindings()
            finally:
                sys.meta_path.remove(finder)
                sys.modules.pop(name, None)


if __name__ == "__main__":
    unittest.main()

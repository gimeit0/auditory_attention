"""Bounded cause metadata: no raw backend messages, locals, source or env dumps."""

import contextlib
import importlib.util
import io
import json
import pathlib
import sys
import unittest
from unittest import mock

PACKAGE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "exception_diagnostic_fixtures", PACKAGE / "diagnose_batch_invariance.py"
)
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)


class ExceptionDiagnosticsTests(unittest.TestCase):
    def chain(self):
        try:
            secret_local = "PRIVATE_LOCAL_VALUE"
            raise RuntimeError("CUBLAS_WORKSPACE_CONFIG private-token=PRIVATE_ARG")
        except RuntimeError as inner:
            try:
                raise diag.DiagnosticError(
                    "frozen reference prediction failed"
                ) from inner
            except diag.DiagnosticError as outer:
                self.assertEqual(secret_local, "PRIVATE_LOCAL_VALUE")
                return outer

    def test_explicit_cause_location_and_reason_are_recorded(self):
        result = diag._bounded_exception_diagnostic(self.chain())
        self.assertEqual(
            [n["type"] for n in result["chain"]], ["DiagnosticError", "RuntimeError"]
        )
        self.assertEqual(
            result["chain"][1]["reason_codes"], ["CUBLAS_WORKSPACE_CONFIG"]
        )
        self.assertEqual(result["chain"][1]["relation"], "cause")
        self.assertEqual(result["chain"][1]["frames"][-1]["function"], "chain")
        self.assertGreater(result["chain"][1]["frames"][-1]["line"], 0)

    def test_no_raw_messages_args_locals_source_or_full_paths(self):
        payload = json.dumps(diag._bounded_exception_diagnostic(self.chain()))
        for private in (
            "PRIVATE_LOCAL_VALUE",
            "PRIVATE_ARG",
            "private-token",
            str(PACKAGE),
            "raise RuntimeError",
        ):
            self.assertNotIn(private, payload)

    def test_implicit_context_is_recorded(self):
        try:
            raise ValueError("private")
        except ValueError:
            try:
                raise RuntimeError("private wrapper")
            except RuntimeError as error:
                result = diag._bounded_exception_diagnostic(error)
        self.assertEqual(result["chain"][1]["relation"], "context")

    def test_suppressed_context_stays_suppressed(self):
        outer = RuntimeError("outer")
        outer.__context__ = ValueError("private suppressed")
        outer.__suppress_context__ = True
        self.assertEqual(len(diag._bounded_exception_diagnostic(outer)["chain"]), 1)

    def test_cause_cycle_and_depth_are_bounded(self):
        first, second = RuntimeError("one"), ValueError("two")
        first.__cause__, second.__cause__ = second, first
        result = diag._bounded_exception_diagnostic(first)
        self.assertEqual(len(result["chain"]), 2)
        self.assertTrue(result["chain_truncated"])
        for _ in range(30):
            newer = RuntimeError("huge" * 10000)
            newer.__cause__ = first
            first = newer
        result = diag._bounded_exception_diagnostic(first)
        self.assertLessEqual(len(result["chain"]), 6)
        self.assertTrue(result["chain_truncated"])
        self.assertLess(len(json.dumps(result).encode()), 16384)

    def test_custom_str_repr_and_attribute_hooks_are_not_called(self):
        class Hostile(RuntimeError):
            def __str__(self):
                raise AssertionError("str executed")

            def __repr__(self):
                raise AssertionError("repr executed")

            def __getattribute__(self, name):
                raise AssertionError("attribute executed")

        result = diag._bounded_exception_diagnostic(Hostile(object()))
        self.assertEqual(result["chain"][0]["type"], "Hostile")
        self.assertEqual(result["chain"][0]["reason_codes"], [])

    def test_traceback_walk_and_output_are_bounded(self):
        def recurse(n):
            if n:
                return recurse(n - 1)
            raise ValueError("private")

        try:
            recurse(170)
        except ValueError as error:
            result = diag._bounded_exception_diagnostic(error)
        self.assertLessEqual(len(result["chain"][0]["frames"]), 6)
        self.assertTrue(result["chain"][0]["frames_truncated"])
        self.assertLess(len(json.dumps(result).encode()), 16384)

    def test_main_emits_supplemental_stderr_and_preserves_failure_contract(self):
        error = self.chain()
        out = io.StringIO()
        with (
            mock.patch.object(diag, "audit_inputs", side_effect=error),
            mock.patch.object(diag, "_emit") as emit,
            contextlib.redirect_stderr(out),
        ):
            self.assertEqual(diag.main(["audit-inputs"]), 2)
        emit.assert_called_once_with(
            {
                "status": "ERROR",
                "error_type": "DiagnosticError",
                "message": "frozen reference prediction failed",
            }
        )
        record = next(
            s.split("=", 1)[1]
            for s in out.getvalue().splitlines()
            if s.startswith("DIAGNOSTIC_EXCEPTION_CHAIN=")
        )
        self.assertEqual(json.loads(record)["chain"][1]["type"], "RuntimeError")
        self.assertNotIn("PRIVATE_ARG", out.getvalue())

    def test_success_does_not_emit_error_diagnostics(self):
        with (
            mock.patch.object(
                diag, "audit_inputs", return_value={"status": "AUDIT_PASS"}
            ),
            mock.patch.object(diag, "_emit"),
            contextlib.redirect_stderr(io.StringIO()) as err,
        ):
            self.assertEqual(diag.main(["audit-inputs"]), 0)
        self.assertEqual(err.getvalue(), "")

    def test_diagnostic_formatter_failure_preserves_original_error_and_exit(self):
        with (
            mock.patch.object(diag, "audit_inputs", side_effect=self.chain()),
            mock.patch.object(
                diag, "_bounded_exception_diagnostic", side_effect=ValueError("private")
            ),
            mock.patch.object(diag, "_emit") as emit,
            contextlib.redirect_stderr(io.StringIO()) as err,
        ):
            self.assertEqual(diag.main(["audit-inputs"]), 2)
        self.assertEqual(
            emit.call_args.args[0]["message"], "frozen reference prediction failed"
        )
        self.assertIn("DIAGNOSTIC_EXCEPTION_CHAIN_UNAVAILABLE", err.getvalue())
        self.assertNotIn("private", err.getvalue())


if __name__ == "__main__":
    unittest.main()

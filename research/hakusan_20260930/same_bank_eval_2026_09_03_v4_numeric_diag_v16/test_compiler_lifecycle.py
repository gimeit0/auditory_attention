"""Exact-edge lifecycle rules; fixtures are not production source attestations."""

import contextlib
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from collections import Counter, defaultdict
from unittest import mock

spec = importlib.util.spec_from_file_location(
    "compiler_lifecycle_tests", Path(__file__).with_name("diagnose_batch_invariance.py")
)
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)


@contextlib.contextmanager
def issued():
    modules = {
        name: types.ModuleType(name)
        for name in (
            "torch._dynamo.eval_frame",
            "torch._dynamo.convert_frame",
            "torch._dynamo.utils",
        )
    }
    eval_frame = modules["torch._dynamo.eval_frame"]
    convert_frame = modules["torch._dynamo.convert_frame"]
    counters = defaultdict(Counter)
    modules["torch._dynamo.utils"].counters = counters
    convert_frame.counters = counters
    eval_frame.most_recent_backend = None
    exec(
        "def make(compiler):\n def on_enter():\n  global most_recent_backend\n  most_recent_backend=compiler\n return on_enter\n",
        vars(eval_frame),
    )
    exec("def writer():\n counters['frames']['total'] += 1\n", vars(convert_frame))

    def compiler(x):
        return x

    on_enter = eval_frame.make(compiler)
    context = types.SimpleNamespace(on_enter=on_enter)
    model = types.SimpleNamespace(dynamo_ctx=context)
    authority = diag._CompilerLifecycle(
        model,
        [(model, context, on_enter, compiler, vars(eval_frame))],
        modules.items(),
        [on_enter, convert_frame.writer],
        [convert_frame.writer],
        counters,
    )
    with (
        mock.patch.dict(sys.modules, modules),
        mock.patch.dict(diag._ISSUED_COMPILER_LIFECYCLES, {id(model): authority}),
        mock.patch.dict(
            diag._COMPILER_LIFECYCLE_RECEIPTS,
            {
                id(authority): (
                    authority.model,
                    authority.contexts,
                    authority.modules,
                    authority.functions,
                    authority.counter_functions,
                    authority.counters,
                )
            },
        ),
    ):
        authority.verify()
        yield authority, eval_frame, convert_frame, compiler


class CompilerLifecycleTests(unittest.TestCase):
    def test_cold_to_exact_compiler_and_repeated_warm(self):
        with issued() as (a, frame, writer, compiler):
            cold = a.global_record(
                a.contexts[0][2], None, "root.global[most_recent_backend]"
            )
            frame.most_recent_backend = compiler
            writer.writer()
            a.verify()
            a.verify()
            warm = a.global_record(
                a.contexts[0][2], compiler, "root.global[most_recent_backend]"
            )
            self.assertEqual(cold, warm)
            self.assertEqual(a.entered, {id(a.contexts[0][1])})

    def test_replacement_backend_sticky_rejection(self):
        with issued() as (a, frame, _, compiler):
            frame.most_recent_backend = lambda x: x
            with self.assertRaisesRegex(diag.DiagnosticError, "backend"):
                a.verify()
            frame.most_recent_backend = compiler
            with self.assertRaisesRegex(diag.DiagnosticError, "revoked"):
                a.verify()

    def test_reset_to_none_after_enter_rejected(self):
        with issued() as (a, frame, _, compiler):
            frame.most_recent_backend = compiler
            a.verify()
            frame.most_recent_backend = None
            with self.assertRaisesRegex(diag.DiagnosticError, "backend"):
                a.verify()

    def test_foreign_function_or_path_gets_no_exception(self):
        with issued() as (a, _, writer, _):
            self.assertIsNone(
                a.global_record(lambda: None, a.counters, "root.global[counters]")
            )
            self.assertIsNone(
                a.global_record(writer.writer, a.counters, "root.global[not_counters]")
            )

    def test_only_issued_writer_global_has_statistics_identity(self):
        with issued() as (a, _, writer, _):
            before = a.global_record(writer.writer, a.counters, "root.global[counters]")
            writer.writer()
            a.verify()
            self.assertEqual(
                before,
                a.global_record(writer.writer, a.counters, "root.global[counters]"),
            )

    def test_unscoped_and_foreign_same_named_mapping_still_sealed(self):
        with issued() as (a, _, writer, _):
            before = diag._graph_container_identity(
                writer.writer, a.counters, _path="root.global[counters]"
            )
            writer.writer()
            after = diag._graph_container_identity(
                writer.writer, a.counters, _path="root.global[counters]"
            )
            self.assertNotEqual(before, after)

    def test_context_replacement(self):
        with issued() as (a, _, _, _):
            a.model.dynamo_ctx = types.SimpleNamespace(on_enter=a.contexts[0][2])
            with self.assertRaisesRegex(diag.DiagnosticError, "context"):
                a.verify()

    def test_on_enter_replacement(self):
        with issued() as (a, _, _, _):
            a.model.dynamo_ctx.on_enter = lambda: None
            with self.assertRaisesRegex(diag.DiagnosticError, "context"):
                a.verify()

    def test_code_replacement(self):
        with issued() as (a, _, writer, _):
            writer.writer.__code__ = (lambda: None).__code__
            with self.assertRaisesRegex(diag.DiagnosticError, "callable"):
                a.verify()

    def test_closure_replacement(self):
        with issued() as (a, _, _, _):
            a.contexts[0][2].__closure__[0].cell_contents = lambda x: x
            with self.assertRaisesRegex(diag.DiagnosticError, "closure"):
                a.verify()

    def test_counter_alias_replacement(self):
        with issued() as (a, _, writer, _):
            writer.counters = defaultdict(Counter)
            with self.assertRaisesRegex(diag.DiagnosticError, "alias"):
                a.verify()

    def test_counter_factory_replacement(self):
        with issued() as (a, _, _, _):
            a.counters.default_factory = dict
            with self.assertRaisesRegex(diag.DiagnosticError, "binding/type"):
                a.verify()

    def test_callback_inside_statistics_rejected(self):
        with issued() as (a, _, _, _):
            a.counters["frames"]["private"] = lambda: None
            with self.assertRaisesRegex(diag.DiagnosticError, "value"):
                a.verify()

    def test_counter_subclass_rejected_without_hooks(self):
        class Hostile(Counter):
            def __iter__(self):
                raise AssertionError("hook executed")

        with issued() as (a, _, _, _):
            a.counters["frames"] = Hostile()
            with self.assertRaisesRegex(diag.DiagnosticError, "shape"):
                a.verify()

    def test_counter_budget(self):
        with issued() as (a, _, _, _):
            a.counters["frames"].update({str(i): 1 for i in range(4097)})
            with self.assertRaisesRegex(diag.DiagnosticError, "budget"):
                a.verify()

    def test_dependency_module_replacement(self):
        with issued() as (a, _, _, _):
            sys.modules["torch._dynamo.eval_frame"] = types.ModuleType(
                "torch._dynamo.eval_frame"
            )
            with self.assertRaisesRegex(diag.DiagnosticError, "module binding"):
                a.verify()

    def test_unissued_authority_rejected(self):
        with issued() as (a, _, _, _):
            diag._ISSUED_COMPILER_LIFECYCLES.pop(id(a.model))
            with self.assertRaisesRegex(diag.DiagnosticError, "unissued"):
                a.verify()

    def test_scoped_adapter_restores_context_on_failure(self):
        with issued() as (a, _, _, _):

            def failing(model):
                self.assertIs(diag._ACTIVE_COMPILER_LIFECYCLE.get(), a)
                raise ValueError("fixture")

            with self.assertRaises(ValueError):
                diag._with_compiler_lifecycle(failing)(a.model)
            self.assertIsNone(diag._ACTIVE_COMPILER_LIFECYCLE.get())
            self.assertTrue(a.revoked)

    def test_issuance_fields_cannot_be_rebased(self):
        with issued() as (a, _, _, _):
            a.functions = ()
            with self.assertRaisesRegex(diag.DiagnosticError, "receipt"):
                a.verify()

    def test_missing_backend_binding_rejected(self):
        with issued() as (a, frame, _, _):
            del frame.most_recent_backend
            with self.assertRaisesRegex(diag.DiagnosticError, "missing"):
                a.verify()

    def test_counter_executable_attributes_rejected(self):
        with issued() as (a, _, _, _):
            a.counters["frames"].callback = lambda: None
            with self.assertRaisesRegex(diag.DiagnosticError, "attributes"):
                a.verify()

    def test_native_model_no_compiler_exception(self):
        model = object()
        self.assertIsNone(diag._issue_compiler_lifecycle(model, (("", model, {}, ()),)))

    def test_source_codes_compiled_not_executed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.py"
            source = b'def f(): return 1\nraise AssertionError("module executed")\n'
            path.write_bytes(source)
            module = types.ModuleType("fixture")
            module.__file__ = str(path)
            result = diag._compiler_source_codes(
                module, hashlib.sha256(source).hexdigest()
            )
            self.assertEqual(result[0], path)
            self.assertIn("f", {code.co_name for code in result[1]})
            with self.assertRaisesRegex(diag.DiagnosticError, "SHA"):
                diag._compiler_source_codes(module, "0" * 64)

    def test_same_name_source_spoof_rejected(self):
        module = types.ModuleType("fake")

        def function():
            return None

        with self.assertRaisesRegex(diag.DiagnosticError, "pinned source"):
            diag._require_compiler_source_function(
                function,
                module,
                (Path(function.__code__.co_filename), (function.__code__,)),
            )


if __name__ == "__main__":
    unittest.main()

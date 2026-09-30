"""Frozen v4 setter semantics and strict readback; not a GPU numeric test."""

import ast
import hashlib
import importlib.util
import json
import pathlib
import sys
import types
import unittest
from unittest import mock

import torch

PACKAGE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "runtime_contract_fixtures", PACKAGE / "test_numeric_diag.py"
)
fixtures = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fixtures
spec.loader.exec_module(fixtures)
diag = fixtures.diagnose

EXPECTED = {
    "deterministic_algorithms": True,
    "cudnn_deterministic": True,
    "cudnn_benchmark": False,
    "float32_matmul_precision": "high",
    "cuda_matmul_allow_tf32": True,
    "cudnn_allow_tf32": True,
}


class Torch211Semantics:
    """Explicit CPU-only API model of v2.1.1 Context.cpp, not installed torch.

    setAllowTF32CuBLAS(true) assigns HIGH; it is not an independent boolean.
    The user also observed medium -> high on HAKUSAN's 2.1.1+cu118.
    """

    __version__ = "2.1.1+cu118"

    def __init__(self):
        self.precision = "highest"
        self.deterministic = False
        self.events = []
        self.backends = types.SimpleNamespace(
            cuda=types.SimpleNamespace(matmul=self),
            cudnn=types.SimpleNamespace(
                deterministic=False, benchmark=True, allow_tf32=False
            ),
        )
        self.cuda = types.SimpleNamespace(is_available=lambda: False)

    def set_float32_matmul_precision(self, value):
        self.events.append(("precision", value))
        self.precision = value

    def get_float32_matmul_precision(self):
        return self.precision

    @property
    def allow_tf32(self):
        return self.precision != "highest"

    @allow_tf32.setter
    def allow_tf32(self, value):
        self.events.append(("matmul_tf32", value))
        self.precision = "high" if value else "highest"

    def use_deterministic_algorithms(self, value):
        self.deterministic = value

    def are_deterministic_algorithms_enabled(self):
        return self.deterministic

    def manual_seed(self, seed):
        self.events.append(("seed", seed))

    def device(self, name):
        return name


def configure_from_frozen_source(torch_api):
    """Execute the exact SHA-bound function, not a retyped setter sequence."""
    path = PACKAGE.parent / "same_bank_eval_2026_08_29_v4/locked_same_bank_eval.py"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != diag.V4_EVALUATOR_SHA256:
        raise AssertionError("frozen evaluator bytes changed")
    tree = ast.parse(raw)
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_configure_runtime"
    ]
    seeds = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "BOOTSTRAP_SEED" for t in node.targets
        )
    ]
    if len(functions) != 1 or len(seeds) != 1:
        raise AssertionError("frozen configurator or seed is not unique")
    namespace = {
        "Any": object,
        "random": fixtures.random,
        "BOOTSTRAP_SEED": ast.literal_eval(seeds[0]),
        "EvaluationError": RuntimeError,
    }
    exec(
        compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"),
        namespace,
    )
    with mock.patch.dict(sys.modules, {"torch": torch_api}):
        return namespace["_configure_runtime"](True)


class FrozenRuntimeContractTests(unittest.TestCase):
    def test_exact_frozen_setter_order_reads_high_under_211_semantics(self):
        api = Torch211Semantics()
        self.assertEqual(configure_from_frozen_source(api), "cpu")
        self.assertEqual(
            api.events,
            [("seed", 20260829), ("precision", "medium"), ("matmul_tf32", True)],
        )
        self.assertEqual(api.get_float32_matmul_precision(), "high")
        self.assertEqual(diag._read_frozen_numeric_runtime(api), EXPECTED)

    def test_medium_and_tf32_are_not_independent_in_211_api_model(self):
        api = Torch211Semantics()
        api.set_float32_matmul_precision("medium")
        self.assertEqual(api.get_float32_matmul_precision(), "medium")
        api.allow_tf32 = True
        self.assertEqual(api.get_float32_matmul_precision(), "high")
        api.allow_tf32 = False
        self.assertEqual(api.get_float32_matmul_precision(), "highest")

    def test_worker_accepts_observed_high_before_one_strict_load(self):
        evaluator = fixtures._Task4Evaluator()
        with fixtures._task4_hermetic_worker_context(evaluator) as context:
            prepared = diag.prepare_formal40_worker(context, allow_cpu=True)
        self.assertEqual(prepared["runtime"], EXPECTED)
        self.assertEqual(len(evaluator.load_calls), 1)
        self.assertEqual(evaluator.load_calls[0][1], "formal40")

    def test_worker_rejects_medium_with_actual_expected_version_before_load(self):
        evaluator = fixtures._Task4Evaluator()
        with (
            mock.patch.object(
                torch, "get_float32_matmul_precision", return_value="medium"
            ),
            fixtures._task4_hermetic_worker_context(evaluator) as context,
        ):
            with self.assertRaises(diag.DiagnosticError) as caught:
                diag.prepare_formal40_worker(context, allow_cpu=True)
        details = json.loads(str(caught.exception).split(": ", 1)[1])
        self.assertEqual(details["actual"]["float32_matmul_precision"], "medium")
        self.assertEqual(details["expected"], EXPECTED)
        self.assertEqual(details["torch_version"], torch.__version__)
        self.assertEqual(evaluator.load_calls, [])

    def test_getter_exception_never_becomes_a_successful_fabricated_value(self):
        for message in ("mix of the legacy and new APIs", "unrelated read failure"):
            evaluator = fixtures._Task4Evaluator()
            with (
                self.subTest(message=message),
                mock.patch.object(
                    torch,
                    "get_float32_matmul_precision",
                    side_effect=RuntimeError(message),
                ),
                fixtures._task4_hermetic_worker_context(evaluator) as context,
            ):
                with self.assertRaises(diag.DiagnosticError) as caught:
                    diag.prepare_formal40_worker(context, allow_cpu=True)
            details = json.loads(str(caught.exception).split(": ", 1)[1])
            self.assertEqual(details["expected"], EXPECTED)
            self.assertEqual(details["torch_version"], torch.__version__)
            error = details["actual"]["float32_matmul_precision"]["read_error"]
            self.assertIn(message, error)
            self.assertEqual(evaluator.load_calls, [])

    def test_each_field_is_exact_with_no_missing_extra_or_bool_int_coercion(self):
        invalid = [None, {}, dict(EXPECTED, extra=True)]
        for key, value in EXPECTED.items():
            missing = dict(EXPECTED)
            missing.pop(key)
            invalid.append(missing)
            bad = not value if isinstance(value, bool) else "medium"
            invalid.append(dict(EXPECTED, **{key: bad}))
            invalid.append(
                dict(EXPECTED, **{key: int(value) if isinstance(value, bool) else None})
            )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(diag.DiagnosticError):
                diag._require_frozen_numeric_runtime(value, "test runtime")
        diag._require_frozen_numeric_runtime(EXPECTED, "test runtime")

    def test_expected_contract_is_immutable(self):
        self.assertEqual(dict(diag._FROZEN_NUMERIC_RUNTIME), EXPECTED)
        with self.assertRaises(TypeError):
            diag._FROZEN_NUMERIC_RUNTIME["float32_matmul_precision"] = "medium"

    def test_reader_does_not_set_or_repair_runtime(self):
        api = Torch211Semantics()
        configure_from_frozen_source(api)
        events = list(api.events)
        diag._read_frozen_numeric_runtime(api)
        self.assertEqual(api.events, events)
        api.set_float32_matmul_precision("medium")
        events = list(api.events)
        with self.assertRaises(diag.DiagnosticError):
            diag._read_frozen_numeric_runtime(api)
        self.assertEqual(api.events, events)

    def test_other_flag_read_errors_are_explicit(self):
        api = Torch211Semantics()
        configure_from_frozen_source(api)
        with mock.patch.object(
            api,
            "are_deterministic_algorithms_enabled",
            side_effect=RuntimeError("cannot inspect deterministic"),
        ):
            with self.assertRaisesRegex(
                diag.DiagnosticError, "cannot inspect deterministic"
            ):
                diag._read_frozen_numeric_runtime(api)

    def test_native_installed_torch_readback_is_not_forged(self):
        # Real installed torch, original frozen source, no getter mock. On local
        # 2.12.1 the legacy/new API mix raises; on compatible 2.1.1 it reads high.
        configure_from_frozen_source(torch)
        try:
            observed = torch.get_float32_matmul_precision()
        except RuntimeError as error:
            with self.assertRaises(diag.DiagnosticError) as caught:
                diag._read_frozen_numeric_runtime(torch)
            self.assertIn(str(error), str(caught.exception))
            self.assertIn(torch.__version__, str(caught.exception))
        else:
            self.assertEqual(observed, "high")
            self.assertEqual(diag._read_frozen_numeric_runtime(torch), EXPECTED)

    def test_all_runtime_consumers_use_the_shared_strict_validator(self):
        tree = ast.parse((PACKAGE / "diagnose_batch_invariance.py").read_text())
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        for name in (
            "_read_frozen_numeric_runtime",
            "_require_equivalence_metadata",
            "_validate_cell_pass",
            "_bind_persisted_worker",
        ):
            with self.subTest(name=name):
                calls = [
                    n.func.id
                    for n in ast.walk(functions[name])
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                ]
                self.assertIn("_require_frozen_numeric_runtime", calls)

    def test_all_cell_roles_accept_high_and_reject_medium(self):
        for cell in ("A1", "A2", "B1", "B2"):
            spec = diag.CELL_SPECS[cell]
            pair = fixtures._task5_pair(cell)
            for index, result in enumerate(pair):
                with self.subTest(cell=cell, index=index):
                    diag._validate_cell_pass(result, spec, index)
                    result.boundary_records["metadata"]["runtime"][
                        "float32_matmul_precision"
                    ] = "medium"
                    diag._bind_pass_commitment(result)
                    with self.assertRaisesRegex(diag.DiagnosticError, "cell runtime"):
                        diag._validate_cell_pass(result, spec, index)

    def test_equivalence_rejects_medium_on_either_side_even_when_resealed(self):
        for side in (0, 1):
            fixture = fixtures.ReferenceEquivalenceTests()
            self.addCleanup(fixture.doCleanups)
            pair = fixture._pair()
            pair[side].boundary_records["metadata"]["runtime"][
                "float32_matmul_precision"
            ] = "medium"
            authenticated = [
                diag._authenticate_hermetic_pass_result(fixture._pair_capability, p)
                for p in pair
            ]
            with (
                self.subTest(side=side),
                self.assertRaisesRegex(
                    diag.DiagnosticError, "reference equivalence runtime"
                ),
            ):
                diag._compare_reference_equivalence_hermetic(*authenticated)

    def test_persisted_worker_accepts_high_and_rejects_each_altered_flag(self):
        fixture = fixtures.PersistedMatrixTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        launch = fixture.publish("A2")
        metadata = fixture.data("A2")["passes"][0].boundary_records["metadata"]
        diag._bind_persisted_worker(metadata, launch, fixture.sources)
        for key, original in EXPECTED.items():
            bad = not original if isinstance(original, bool) else "medium"
            altered = dict(metadata, runtime=dict(EXPECTED, **{key: bad}))
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(
                    diag.DiagnosticError, "persisted worker runtime"
                ),
            ):
                diag._bind_persisted_worker(altered, launch, fixture.sources)


if __name__ == "__main__":
    unittest.main()

"""Process-local environment seals and SHA-bound constructor regressions."""

import ast
import contextlib
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import torch


PACKAGE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "environment_collection_fixtures", PACKAGE / "test_execution_collections.py"
)
collections = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = collections
spec.loader.exec_module(collections)
diag = collections.diag
fixtures = collections.fixtures
PROJECT = Path("/Users/gigi/projects/auditory_attention")
DATASET = PROJECT / "selftrain/data/diotic_attention.py"
DATASET_SHA = "26b5cf965aec1652f2d77be517f867bb284a2f53c2f53706b2c5aa2cc0ad9e8a"
ANCHOR_SHA = "7fd32f00cad55aec42d285fd6a3992c03f2bf1b62a57580b43bc9fdee96813a1"
PROBE_KEY = "AUDATTN_V9_ENVIRONMENT_TEST_ONLY"
MODEL_SOURCE_PINS = {
    "src/spatial_attn_lightning.py": "6531a6548cc24dcdcffdb14c8b6b1d7040bc6f1f7ea53dd870d4d021327467c9",
    "src/audio_transforms.py": "8910af4b94d24852ca6ba582937783cb1866e26f4e2c47c5a5b445842e293085",
    "src/audio_attention_transforms.py": "d8ec3a7c3d17e799cb140a9a49f6dda9ed68202af8a9cfa6e333847217794b06",
    "src/custom_modules.py": "98f0d393ee7a1a5fe1a8a8bd1302b0d6b574a4ef846946e30cf176adf860adad",
    "src/spatial_attn_architecture.py": "84e68e051f2a2a7a2373aab5c510b72e626aa3b11a9d54f5ec9e35ddbe570eed",
    "src/time_domain_cochleagram.py": "05bb2dc42aeb397570fbd63238871cfa1677f915cdc6ec6fb7f0e4c57f870abe",
    "src/layers/conv2d_same.py": "826e2882b489157c578af68241303526079a529cd6d1dc04c1961b5a7e9cab1f",
    "src/layers/padding.py": "4fbca19c54a30696c4dc8b27314e58ca2cc3c451ab8a9192dadea4eb07302213",
    "corpus/binaural_attention_h5.py": "02f07a5c88c4836340ad90592320aa19d905652a4f804624a776557baa5f299a",
}


def source_payload():
    payload = DATASET.read_bytes()
    if hashlib.sha256(payload).hexdigest() != DATASET_SHA:
        raise AssertionError("source dataset SHA differs")
    return payload


def source_constructor():
    model = next(
        n
        for n in ast.parse(source_payload()).body
        if isinstance(n, ast.ClassDef) and n.name == "DioticAttentionDataset"
    )
    init = next(
        n for n in model.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"
    )
    expected = ast.parse('clips_dir = os.environ.get("CV_CLIPS", clips_dir)').body[0]
    statement = next(n for n in init.body if ast.dump(n) == ast.dump(expected))
    tree = ast.parse(
        "class SourceDataset:\n    def __init__(self, clips_dir=None):\n        pass\n"
    )
    tree.body[0].body[0].body = [statement]
    namespace = {"os": os, "__name__": "source_environment_fixture"}
    exec(compile(ast.fix_missing_locations(tree), str(DATASET), "exec"), namespace)
    return namespace["SourceDataset"]


def full_source_dataset():
    """Load real source/dependencies; never instantiate or read a dataset."""
    source_payload()
    anchor = PROJECT / "selftrain/data/anchor_index.py"
    if hashlib.sha256(anchor.read_bytes()).hexdigest() != ANCHOR_SHA:
        raise AssertionError("source anchor SHA differs")
    spec = importlib.util.spec_from_file_location(
        "environment_full_source_dataset", DATASET
    )
    module = importlib.util.module_from_spec(spec)
    with mock.patch.object(sys, "path", [str(PROJECT), *sys.path]):
        spec.loader.exec_module(module)
    return module.DioticAttentionDataset


def full_source_model_class():
    """Import real model source only: no constructor, checkpoint or forward."""
    for relative, digest in MODEL_SOURCE_PINS.items():
        if hashlib.sha256((PROJECT / relative).read_bytes()).hexdigest() != digest:
            raise AssertionError("model dependency SHA differs: " + relative)
    source_payload()
    spec = importlib.util.spec_from_file_location(
        "environment_full_source_model", PROJECT / "src/spatial_attn_lightning.py"
    )
    module = importlib.util.module_from_spec(spec)
    with mock.patch.object(sys, "path", [str(PROJECT), *sys.path]):
        spec.loader.exec_module(module)
    return module.BinauralAttentionModule


@contextlib.contextmanager
def probe_value(value):
    present = PROBE_KEY in os.environ
    old = os.environ.get(PROBE_KEY)
    os.environ[PROBE_KEY] = value
    try:
        yield
    finally:
        if present:
            os.environ[PROBE_KEY] = old
        else:
            del os.environ[PROBE_KEY]


class EnvironmentSealTests(unittest.TestCase):
    def test_original_environment_is_accepted_and_repeatable(self):
        first = diag._container_execution_identity(os.environ)
        self.assertEqual(first, diag._container_execution_identity(os.environ))

    def test_source_constructor_graph_is_accepted_without_instantiation(self):
        model_class = source_constructor()
        first = diag._callable_graph_fingerprint(model_class)
        self.assertEqual(first, diag._callable_graph_fingerprint(model_class))

    def test_actual_dataset_constructor_graph(self):
        model_class = full_source_dataset()
        first = diag._callable_graph_fingerprint(model_class)
        self.assertEqual(first, diag._callable_graph_fingerprint(model_class))

    def test_actual_model_constructor_dependency_graph(self):
        model_class = full_source_model_class()
        first = diag._callable_graph_fingerprint(model_class)
        self.assertEqual(first, diag._callable_graph_fingerprint(model_class))

    def test_torch_version_identity_and_text(self):
        value = torch.__version__
        first = diag._container_execution_identity(value)
        self.assertEqual(first, diag._container_execution_identity(value))
        self.assertEqual(
            first[:4], ("torch-version", id(value), id(type(value)), str.__str__(value))
        )
        replacement = type(value)(str.__str__(value))
        self.assertNotEqual(first, diag._container_execution_identity(replacement))
        changed = type(value)("0.0.0+synthetic")
        self.assertNotEqual(first[3], diag._container_execution_identity(changed)[3])

    def test_torch_version_overrides_sealed_without_invocation(self):
        value = torch.__version__
        events = []

        def hostile(*args, **kwargs):
            events.append("called")
            raise AssertionError("version method invoked")

        for name in ("__str__", "__repr__", "__iter__", "__eq__", "split"):
            first = diag._container_execution_identity(value)
            with self.subTest(name=name):
                with mock.patch.object(type(value), name, hostile, create=True):
                    self.assertNotEqual(
                        first, diag._container_execution_identity(value)
                    )
        self.assertEqual(events, [])

    def test_torch_version_inplace_method_code_change_is_detected(self):
        value = torch.__version__
        function = type(value).__dict__["_cmp_wrapper"]
        before = diag._container_execution_identity(value)
        original_code = function.__code__
        replacement = original_code.replace(co_name="mutated_version_method")
        try:
            function.__code__ = replacement
            self.assertNotEqual(before, diag._container_execution_identity(value))
        finally:
            function.__code__ = original_code

    def test_torch_version_subclass_is_rejected_without_hooks(self):
        events = []

        class Hostile(type(torch.__version__)):
            def __call__(self):
                events.append("call")

            def __str__(self):
                events.append("str")
                raise AssertionError("version hook invoked")

        value = str.__new__(Hostile, "1.0")
        with self.assertRaisesRegex(diag.DiagnosticError, "version"):
            diag._container_execution_identity(value)
        self.assertEqual(events, [])

    def test_unknown_string_subclass_is_still_rejected(self):
        class Unknown(str):
            pass

        with self.assertRaisesRegex(diag.DiagnosticError, "unsupported execution"):
            diag._container_execution_identity(Unknown("1.0"))

    def test_torch_version_budget_and_instance_attributes(self):
        with self.assertRaisesRegex(diag.DiagnosticError, "budget"):
            diag._container_execution_identity(type(torch.__version__)("a" * 257))
        with mock.patch.object(
            diag, "_safe_instance_dict", return_value={"unexpected": True}
        ):
            with self.assertRaisesRegex(diag.DiagnosticError, "attributes"):
                diag._container_execution_identity(torch.__version__)

    def test_environment_changes_are_detected_without_cleartext(self):
        with probe_value("synthetic-private-value-111"):
            first = diag._container_execution_identity(os.environ)
            self.assertFalse(PROBE_KEY in repr(first), "environment key leaked")
            self.assertFalse(
                "synthetic-private-value-111" in repr(first), "environment value leaked"
            )
            os.environ[PROBE_KEY] = "synthetic-private-value-222"
            self.assertNotEqual(first, diag._container_execution_identity(os.environ))

    def test_add_delete_restore_and_order_independence(self):
        with probe_value("value"):
            first = diag._container_execution_identity(os.environ)
            del os.environ[PROBE_KEY]
            self.assertNotEqual(first, diag._container_execution_identity(os.environ))
            os.environ[PROBE_KEY] = "value"
            self.assertEqual(first, diag._container_execution_identity(os.environ))

    def test_alias_has_the_same_identity(self):
        alias = os.environ
        self.assertEqual(
            diag._container_execution_identity(alias),
            diag._container_execution_identity(os.environ),
        )

    def test_replacing_os_environment_with_dict_is_rejected(self):
        original = os.environ
        with mock.patch.object(os, "environ", {}):
            for value in (os.environ, original):
                with self.assertRaisesRegex(diag.DiagnosticError, "environment"):
                    diag._container_execution_identity(value)

    def test_environment_clone_is_rejected(self):
        env_type = type(os.environ)
        namespace = object.__getattribute__(os.environ, "__dict__")
        clone = env_type(
            {},
            namespace["encodekey"],
            namespace["decodekey"],
            namespace["encodevalue"],
            namespace["decodevalue"],
        )
        with self.assertRaisesRegex(diag.DiagnosticError, "environment"):
            diag._container_execution_identity(clone)

    def test_callable_environment_subclass_never_runs(self):
        events = []

        class Hostile(type(os.environ)):
            def __call__(self):
                events.append("call")

            def __iter__(self):
                events.append("iter")
                raise AssertionError("iterator invoked")

            def __getattribute__(self, name):
                events.append("getattr")
                raise AssertionError("attribute invoked")

        value = object.__new__(Hostile)
        with self.assertRaisesRegex(diag.DiagnosticError, "environment"):
            diag._container_execution_identity(value)
        self.assertEqual(events, [])

    def test_mapping_class_and_instance_method_replacements_are_not_called(self):
        events = []

        def hostile(*args, **kwargs):
            events.append("called")
            raise AssertionError("method invoked")

        for name in ("get", "__getitem__", "__iter__", "items", "__getattribute__"):
            with self.subTest(name=name):
                with mock.patch.object(type(os.environ), name, hostile, create=True):
                    with self.assertRaisesRegex(diag.DiagnosticError, "environment"):
                        diag._container_execution_identity(os.environ)
        with mock.patch.object(os.environ, "get", hostile):
            with self.assertRaisesRegex(diag.DiagnosticError, "environment"):
                diag._container_execution_identity(os.environ)
        self.assertEqual(events, [])

    def test_in_place_method_code_change_is_rejected(self):
        method = type(os.environ).__getitem__
        original = method.__code__

        def changed(self, key):
            raise AssertionError("not called")

        try:
            method.__code__ = changed.__code__
            with self.assertRaisesRegex(diag.DiagnosticError, "environment"):
                diag._container_execution_identity(os.environ)
        finally:
            method.__code__ = original

    def test_inherited_get_default_change_is_rejected(self):
        method = type(os.environ).get
        original = method.__defaults__
        try:
            method.__defaults__ = ("wrong-default",)
            with self.assertRaisesRegex(diag.DiagnosticError, "environment"):
                diag._container_execution_identity(os.environ)
        finally:
            method.__defaults__ = original

    def test_codec_replacement_is_rejected_without_execution(self):
        events = []

        def hostile(value):
            events.append("codec")
            raise AssertionError("codec invoked")

        with mock.patch.object(os.environ, "encodekey", hostile):
            with self.assertRaisesRegex(diag.DiagnosticError, "environment"):
                diag._container_execution_identity(os.environ)
        self.assertEqual(events, [])

    def test_codec_closure_mutation_is_rejected(self):
        codec = object.__getattribute__(os.environ, "__dict__")["encodekey"]
        self.assertIs(type(codec), types.FunctionType)
        cell = codec.__closure__[0]
        original = cell.cell_contents
        try:
            cell.cell_contents = "different-codec"
            with self.assertRaisesRegex(diag.DiagnosticError, "environment"):
                diag._container_execution_identity(os.environ)
        finally:
            cell.cell_contents = original

    def test_backing_dictionary_replacement_rejected(self):
        data = object.__getattribute__(os.environ, "__dict__")["_data"]
        with mock.patch.object(os.environ, "_data", dict.copy(data)):
            with self.assertRaisesRegex(diag.DiagnosticError, "environment"):
                diag._container_execution_identity(os.environ)

    def test_plaintext_not_in_error_for_bad_backing_value(self):
        data = object.__getattribute__(os.environ, "__dict__")["_data"]
        key = b"AUDATTN_V9_BAD_VALUE_TEST_ONLY"
        marker = "synthetic-sensitive-error-marker"
        self.assertNotIn(key, data)
        data[key] = marker
        try:
            with self.assertRaises(diag.DiagnosticError) as caught:
                diag._container_execution_identity(os.environ)
            self.assertFalse(marker in str(caught.exception), "error leaked value")
            self.assertFalse(key.decode() in str(caught.exception), "error leaked key")
        finally:
            del data[key]

    def test_item_byte_and_structural_budgets(self):
        for name in ("_ENVIRONMENT_MAX_ITEMS", "_ENVIRONMENT_MAX_BYTES"):
            with mock.patch.object(diag, name, 0):
                with self.assertRaisesRegex(diag.DiagnosticError, "budget"):
                    diag._container_execution_identity(os.environ)
        with mock.patch.object(
            type(os.environ), "extra_namespace_item", None, create=True
        ):
            with self.assertRaisesRegex(diag.DiagnosticError, "environment"):
                diag._container_execution_identity(os.environ)

    def test_mapping_content_change_during_digest_is_rejected(self):
        factory = diag._ENVIRONMENT_HASH_FACTORY

        def changed(**kwargs):
            os.environ[PROBE_KEY] = "changed-mid-seal"
            return factory(**kwargs)

        with probe_value("before"):
            with mock.patch.object(diag, "_ENVIRONMENT_HASH_FACTORY", changed):
                with self.assertRaisesRegex(
                    diag.DiagnosticError, "changed while sealing"
                ):
                    diag._container_execution_identity(os.environ)

    def test_keyed_digest_has_framing(self):
        data = object.__getattribute__(os.environ, "__dict__")["_data"]
        key1, key2 = b"AUDATTN_V9_FRAME_A", b"AUDATTN_V9_FRAME_AB"
        self.assertNotIn(key1, data)
        self.assertNotIn(key2, data)
        try:
            data[key1] = b"BC"
            first = diag._container_execution_identity(os.environ)[-1]
            del data[key1]
            data[key2] = b"C"
            self.assertNotEqual(
                first, diag._container_execution_identity(os.environ)[-1]
            )
        finally:
            data.pop(key1, None)
            data.pop(key2, None)

    def test_content_digest_depends_on_private_process_key(self):
        first = diag._container_execution_identity(os.environ)[-1]
        with mock.patch.object(diag, "_ENVIRONMENT_HASH_KEY", b"synthetic-second-key"):
            self.assertNotEqual(
                first, diag._container_execution_identity(os.environ)[-1]
            )


class EnvironmentWorkerTests(unittest.TestCase):
    def make(self):
        model = fixtures._Task4Model()
        model._amp_overflow_window = collections.source_window()
        model._source_shape_fixture = torch.Size([2, 4])
        model.dataset = source_constructor()
        return model, fixtures._Task4Evaluator(model_to_load=model)

    def test_source_environment_worker_issuance_and_repeat_validation(self):
        model, evaluator = self.make()
        with fixtures._task4_attested_context(evaluator, model):
            self.assertTrue(diag._live_inference_attestation(model, "env-first"))
            self.assertTrue(diag._live_inference_attestation(model, "env-repeat"))

    def test_environment_change_revokes_worker(self):
        model, evaluator = self.make()
        with probe_value("original"):
            with fixtures._task4_attested_context(evaluator, model):
                os.environ[PROBE_KEY] = "changed"
                with self.assertRaises(diag.DiagnosticError):
                    diag._live_inference_attestation(model, "env-change")
                os.environ[PROBE_KEY] = "original"
                with self.assertRaises(diag.DiagnosticError):
                    diag._live_inference_attestation(model, "env-reverted")

    def test_actual_dataset_class_in_worker_configuration(self):
        model, evaluator = self.make()
        model.dataset = full_source_dataset()
        with fixtures._task4_attested_context(evaluator, model):
            self.assertTrue(
                diag._live_inference_attestation(model, "actual-dataset-class")
            )


if __name__ == "__main__":
    unittest.main()

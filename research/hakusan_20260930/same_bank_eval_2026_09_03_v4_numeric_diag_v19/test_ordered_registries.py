"""Torch 2.1-style registries, native ordering, state and no-dispatch checks."""

from collections import OrderedDict, UserDict
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import torch


spec = importlib.util.spec_from_file_location(
    "ordered_registry_diag", Path(__file__).with_name("diagnose_batch_invariance.py")
)
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)


def old_torch_registries(model):
    for child in model.modules():
        for name in ("_parameters", "_buffers", "_modules"):
            child.__dict__[name] = OrderedDict(child.__dict__[name])
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    return model


def state_model():
    model = torch.nn.Sequential(torch.nn.Linear(2, 2), torch.nn.Linear(2, 1))
    model.register_buffer("scalar", torch.tensor(7, dtype=torch.int64))
    model.register_buffer("optional", None)
    return old_torch_registries(model)


class OrderedRegistryTests(unittest.TestCase):
    def test_native_registry_items_preserve_order(self):
        for cls in (dict, OrderedDict):
            registry = cls(a=1, b=2)
            self.assertEqual(
                diag._native_registry_items(registry), (("a", 1), ("b", 2))
            )
        registry.move_to_end("a")
        self.assertEqual(diag._native_registry_items(registry), (("b", 2), ("a", 1)))

    def test_snapshot_parameters_buffers_scalar_and_repeat(self):
        model = state_model()
        entries = diag._snapshot_model_entries(model)
        self.assertEqual(len(entries), 5)
        self.assertEqual(entries, diag._snapshot_model_entries(model))
        scalar = next(item for item in entries if item["name"] == "scalar")
        self.assertEqual(scalar["shape"], [])
        self.assertEqual(scalar["kind"], "buffer")
        self.assertTrue(all(len(item["sha256"]) == 64 for item in entries))

    def test_snapshot_deduplicates_shared_state(self):
        model = state_model()
        model.register_parameter("alias", model[0].weight)
        self.assertEqual(len(diag._snapshot_model_entries(model)), 5)

    def test_snapshot_does_not_dispatch_named_iterators(self):
        model = state_model()
        with (
            mock.patch.object(model, "named_parameters", side_effect=AssertionError),
            mock.patch.object(model, "named_buffers", side_effect=AssertionError),
            mock.patch.object(model, "named_modules", side_effect=AssertionError),
        ):
            self.assertEqual(len(diag._snapshot_model_entries(model)), 5)

    def test_static_lookup_resolves_children_parameters_buffers(self):
        model = state_model()
        self.assertIs(diag._static_attribute(model, "0"), model[0])
        self.assertIs(diag._static_attribute(model[0], "weight"), model[0].weight)
        self.assertIs(diag._static_attribute(model, "scalar"), model.scalar)
        self.assertIsNone(diag._static_attribute(model, "optional", object()))
        sentinel = object()
        self.assertIs(diag._static_attribute(model, "missing", sentinel), sentinel)

    def test_static_lookup_does_not_call_replaced_getattr(self):
        model = state_model()
        with mock.patch.object(
            torch.nn.Module, "__getattr__", side_effect=AssertionError
        ):
            self.assertIs(
                diag._static_attribute(model, "scalar"), model._buffers["scalar"]
            )

    def test_module_reorder_changes_inventory(self):
        model = state_model()
        before = diag._direct_model_module_inventory(model)
        model._modules.move_to_end("0")
        after = diag._direct_model_module_inventory(model)
        self.assertEqual([item[0] for item in after], ["", "1", "0"])
        with self.assertRaisesRegex(diag.DiagnosticError, "inventory changed"):
            diag._validate_model_module_inventory(model, before)

    def test_module_registry_replacement_changes_inventory(self):
        model = state_model()
        before = diag._direct_model_module_inventory(model)
        model.__dict__["_modules"] = OrderedDict(model._modules)
        with self.assertRaisesRegex(diag.DiagnosticError, "inventory changed"):
            diag._validate_model_module_inventory(model, before)

    def test_list_audio_modules_are_in_inventory_and_snapshot(self):
        model = old_torch_registries(torch.nn.Module())
        extra = old_torch_registries(torch.nn.Linear(2, 1))
        model.audio_transforms = types.SimpleNamespace(transforms=[extra])
        inventory = diag._direct_model_module_inventory(model)
        self.assertEqual(
            [item[0] for item in inventory], ["", "audio_transforms.transforms[0]"]
        )
        self.assertEqual(len(diag._snapshot_model_entries(model)), 2)
        extra.weight.requires_grad_(True)
        with self.assertRaisesRegex(diag.DiagnosticError, "trainable"):
            diag._require_frozen_direct_parameters(inventory)

    def test_shared_audio_modules_are_not_lost(self):
        model = old_torch_registries(torch.nn.Module())
        extra = old_torch_registries(torch.nn.Linear(2, 1))
        model.transforms = [extra, extra]
        self.assertEqual(len(diag._direct_model_module_inventory(model)), 3)
        self.assertEqual(len(diag._snapshot_model_entries(model)), 2)

    def test_parameter_order_content_and_replacement_are_live(self):
        model = state_model()[0]
        before = diag._registered_state_fingerprint(model, "_parameters")
        model._parameters.move_to_end("weight")
        reordered = diag._registered_state_fingerprint(model, "_parameters")
        self.assertNotEqual(before, reordered)
        with torch.no_grad():
            model.weight.add_(1)
        changed = diag._registered_state_fingerprint(model, "_parameters")
        self.assertNotEqual(reordered, changed)
        model.weight = torch.nn.Parameter(model.weight.clone(), requires_grad=False)
        self.assertNotEqual(
            changed, diag._registered_state_fingerprint(model, "_parameters")
        )

    def test_buffer_content_in_snapshot_is_live_even_data_write(self):
        model = state_model()
        before = diag._snapshot_model_entries(model)
        model.scalar.data.fill_(8)
        self.assertNotEqual(before, diag._snapshot_model_entries(model))

    def test_parameter_fingerprint_does_not_read_tensor_bytes(self):
        model = state_model()
        with mock.patch.object(
            diag._get_trace(), "tensor_record", side_effect=AssertionError
        ):
            diag._registered_state_fingerprint(model[0], "_parameters")
            diag._require_frozen_direct_parameters(
                diag._direct_model_module_inventory(model)
            )

    def test_configuration_and_hooks_preserve_order(self):
        for path in ("root.config", "root._forward_hooks"):
            mapping = OrderedDict([(1, None), (2, None)])
            before = diag._execution_configuration_fingerprint(mapping, path=path)
            mapping.move_to_end(1)
            self.assertNotEqual(
                before, diag._execution_configuration_fingerprint(mapping, path=path)
            )

    def test_real_hook_reorder_changes_complete_fingerprint(self):
        model = old_torch_registries(torch.nn.Linear(1, 1))
        model.register_forward_hook(lambda *args: None)
        model.register_forward_hook(lambda *args: None)
        before = diag._model_execution_fingerprint(model)
        first = next(iter(model._forward_hooks))
        model._forward_hooks.move_to_end(first)
        self.assertNotEqual(before, diag._model_execution_fingerprint(model))

    def test_registry_subclasses_and_user_mapping_are_rejected_without_dispatch(self):
        calls = []

        def poison(*args, **kwargs):
            calls.append(True)
            raise AssertionError("overridden registry protocol")

        for base in (dict, OrderedDict, UserDict):
            cls = type(
                "PoisonRegistry",
                (base,),
                {
                    "items": poison,
                    "__iter__": poison,
                    "__len__": poison,
                    "__getitem__": poison,
                    "__contains__": poison,
                },
            )
            for registry_name in ("_modules", "_parameters", "_buffers"):
                model = state_model()
                model.__dict__[registry_name] = cls()
                calls.clear()
                with self.assertRaises(diag.DiagnosticError):
                    diag._snapshot_model_entries(model)
                with self.assertRaises(diag.DiagnosticError):
                    diag._static_attribute(model, "not_a_member")
                self.assertEqual(calls, [])

    def test_callable_ordered_subclass_is_not_accepted_via_callable_branch(self):
        calls = []

        class Poison(OrderedDict):
            def __call__(self):
                calls.append(True)

        with self.assertRaisesRegex(
            diag.DiagnosticError, "unsupported execution mapping"
        ):
            diag._execution_configuration_fingerprint(Poison())
        self.assertEqual(calls, [])

    def test_registry_key_rejected_without_hash_equality_or_repr(self):
        calls = []

        class Key:
            def __hash__(self):
                calls.append("hash")
                return 1

            def __repr__(self):
                calls.append("repr")
                raise AssertionError

        registry = OrderedDict([(Key(), None)])
        calls.clear()
        with self.assertRaisesRegex(diag.DiagnosticError, "non-string key"):
            diag._native_registry_items(registry)
        self.assertEqual(calls, [])

    def test_oversized_registry_stays_bounded(self):
        registry = OrderedDict((str(i), None) for i in range(600_001))
        with self.assertRaisesRegex(diag.DiagnosticError, "budget"):
            diag._native_registry_items(registry)

    def test_execution_keys_are_checked_before_native_rehash(self):
        calls = []

        class Key:
            def __hash__(self):
                calls.append("hash")
                return 1

            def __repr__(self):
                calls.append("repr")
                return "unsafe"

        for key in (Key(), (Key(),), frozenset([Key()])):
            mapping = OrderedDict([(key, None)])
            calls.clear()
            with self.assertRaisesRegex(
                diag.DiagnosticError, "unsupported execution mapping key"
            ):
                diag._execution_configuration_fingerprint(mapping, path="test.order")
            self.assertEqual(calls, [])

    def test_native_immutable_execution_keys_and_reorder(self):
        mapping = OrderedDict(
            [
                ("a", None),
                (7, None),
                (1.5, None),
                (b"x", None),
                (None, None),
                (True, None),
                (("y", 9), None),
                (frozenset(["z", 2]), None),
            ]
        )
        before = diag._container_execution_identity(mapping)
        mapping.move_to_end("a")
        self.assertNotEqual(before, diag._container_execution_identity(mapping))

    def test_ordered_key_depth_limit(self):
        key = "value"
        for _ in range(110):
            key = (key,)
        with self.assertRaisesRegex(diag.DiagnosticError, "budget|depth|nesting"):
            diag._container_execution_identity(OrderedDict([(key, None)]))

    def test_generic_dict_subclass_still_bypasses_overridden_items(self):
        class UnusedOverride(dict):
            def items(self):
                raise AssertionError("not native storage")

        mapping = UnusedOverride(a=1)
        self.assertEqual(
            diag._container_execution_identity(mapping),
            diag._container_execution_identity(mapping),
        )

    def test_unchanged_complete_model_fingerprint_and_rng(self):
        model = state_model()
        trace = diag._get_trace()
        rng = trace.snapshot_rng_state()
        before = diag._model_execution_fingerprint(model)
        entries = diag._snapshot_model_entries(model)
        self.assertEqual(before, diag._model_execution_fingerprint(model))
        self.assertEqual(entries, diag._snapshot_model_entries(model))
        self.assertEqual(rng, trace.snapshot_rng_state())


if __name__ == "__main__":
    unittest.main()

"""Preserve native list-held transform modes without weakening live seals."""

import ast
from collections import OrderedDict
import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

import torch


spec = importlib.util.spec_from_file_location(
    "native_eval_fixtures", Path(__file__).with_name("test_numeric_diag.py")
)
fixtures = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fixtures
spec.loader.exec_module(fixtures)
diag = fixtures.diagnose


class ListAudio(torch.nn.Module):
    def __init__(self, child):
        super().__init__()
        self.transforms = [child]

    def forward(self, value):
        for transform in self.transforms:
            value = transform(value)
        return value


def model_with_list_audio(child=None):
    model = fixtures._Task4Model([])
    model.audio_transforms = ListAudio(torch.nn.Identity() if child is None else child)
    model.eval()
    return model


class NativeEvalScopeTests(unittest.TestCase):
    def test_native_list_modes_preserved_but_inventory_kept(self):
        model = model_with_list_audio()
        for registry_type in (dict, OrderedDict):
            with self.subTest(registry_type=registry_type):
                inventory = diag._direct_model_module_inventory(model)
                for _, child, _, _ in inventory:
                    child.__dict__["_modules"] = registry_type(child._modules)
                diag._require_registered_modules_eval(model)
                modes = {
                    name: child.training
                    for name, child, _, _ in diag._direct_model_module_inventory(model)
                }
                self.assertFalse(modes[""])
                self.assertFalse(modes["audio_transforms"])
                self.assertTrue(modes["audio_transforms.transforms[0]"])

    def test_every_registered_module_still_requires_eval(self):
        for location in ("root", "audio_parent", "late_child"):
            model = model_with_list_audio()
            if location == "root":
                model.training = True
            elif location == "audio_parent":
                model.audio_transforms.training = True
            else:
                model.late_child = torch.nn.Identity()
            with self.subTest(location=location):
                with self.assertRaisesRegex(diag.DiagnosticError, "eval"):
                    diag._require_registered_modules_eval(model)

    def test_invalid_registered_training_state_rejected(self):
        model = model_with_list_audio()
        model.audio_transforms.training = 0
        with self.assertRaisesRegex(diag.DiagnosticError, "training"):
            diag._require_registered_modules_eval(model)

    def test_no_replaceable_discovery_or_eval_invoked(self):
        model = model_with_list_audio()
        with (
            mock.patch.object(model, "modules", side_effect=AssertionError),
            mock.patch.object(model, "named_modules", side_effect=AssertionError),
            mock.patch.object(model, "eval", side_effect=AssertionError),
            mock.patch.object(model, "train", side_effect=AssertionError),
        ):
            diag._require_registered_modules_eval(model)

    def test_registered_cycles_aliases_and_none_terminate(self):
        model = model_with_list_audio()
        model._modules["self"] = model
        model._modules["alias"] = model.audio_transforms
        model._modules["absent"] = None
        diag._require_registered_modules_eval(model)
        model.audio_transforms.training = True
        with self.assertRaisesRegex(diag.DiagnosticError, "eval"):
            diag._require_registered_modules_eval(model)

    def test_worker_accepts_native_modes_without_mutating_them(self):
        model = model_with_list_audio()
        evaluator = fixtures._Task4Evaluator(model_to_load=model)
        with fixtures._task4_hermetic_worker_context(evaluator) as context:
            prepared = diag.prepare_formal40_worker(context, allow_cpu=True)
            self.assertIs(prepared["model"], model)
            self.assertTrue(model.audio_transforms.transforms[0].training)
            self.assertFalse(model.audio_transforms.training)

    def test_list_mode_mutation_rejected_before_prediction(self):
        model = model_with_list_audio()
        evaluator = fixtures._Task4Evaluator(model_to_load=model)
        with fixtures._task4_hermetic_worker_context(evaluator) as context:
            prepared = diag.prepare_formal40_worker(context, allow_cpu=True)
            evaluator.calls.clear()
            model.audio_transforms.transforms[0].training = False
            with diag._prediction_evaluator_context(
                evaluator,
                model=model,
                attestation=prepared["_formal40_worker_attestation"],
            ):
                with self.assertRaises(diag.DiagnosticError):
                    diag.trace_predict_batch(
                        model,
                        torch.ones((2, 2, 4)),
                        torch.ones((2, 2, 4)),
                        torch.tensor([1, 2]),
                        torch.tensor([3, 4]),
                        torch.device("cpu"),
                        autocast_enabled=True,
                        trial_ids=(1, 2),
                    )
            self.assertEqual(evaluator.calls, [])

    def test_list_held_trainable_parameter_still_rejected(self):
        model = model_with_list_audio(torch.nn.Linear(4, 4))
        evaluator = fixtures._Task4Evaluator(model_to_load=model)
        with fixtures._task4_hermetic_worker_context(evaluator) as context:
            with self.assertRaisesRegex(diag.DiagnosticError, "trainable"):
                diag.prepare_formal40_worker(context, allow_cpu=True)

    def test_frozen_audio_source_uses_plain_list_and_not_training(self):
        source = Path("/Users/gigi/projects/auditory_attention/src/audio_transforms.py")
        payload = source.read_bytes()
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "8910af4b94d24852ca6ba582937783cb1866e26f4e2c47c5a5b445842e293085",
        )
        classes = {
            node.name: node
            for node in ast.parse(payload).body
            if isinstance(node, ast.ClassDef)
        }
        compose = classes["AudioCompose"]
        assignment = ast.parse("self.transforms = transforms").body[0]
        self.assertIn(ast.dump(assignment), [ast.dump(n) for n in ast.walk(compose)])
        for name in (
            "AudioToTensor",
            "BinauralCombineWithRandomDBSNRPerExample",
            "BinauralRMSNormalizePerExample",
        ):
            with self.subTest(name=name):
                self.assertFalse(
                    any(
                        isinstance(node, ast.Attribute) and node.attr == "training"
                        for node in ast.walk(classes[name])
                    )
                )


if __name__ == "__main__":
    unittest.main()

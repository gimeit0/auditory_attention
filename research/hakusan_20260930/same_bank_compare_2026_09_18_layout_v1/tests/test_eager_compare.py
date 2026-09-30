"""Disk checkpoint -> original strict loader -> candidate forward -> disk verify.

Real torch operations and v4 scientific helpers, but a tiny synthetic model/bank.
These tests explicitly do NOT establish native A100/real-checkpoint qualification.
"""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd
import torch

CANDIDATE = Path(__file__).resolve().parents[1]
ROOT = CANDIDATE.parent
SPEC = importlib.util.spec_from_file_location(
    "candidate_under_test", CANDIDATE / "eager_compare.py"
)
E = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E)
BASE = E.load_v4(ROOT / "same_bank_eval_2026_08_29_v4/locked_same_bank_eval.py")


class Cache:
    def __init__(self, max_items):
        self.max_items = max_items


def raw(frame, cache, clips, snr_errors=None):
    # Construction independent of peers, length/order and model ID.
    return torch.stack(
        [
            torch.arange(8, dtype=torch.float32).reshape(2, 4) / 10 + int(t) / 100000
            for t in frame.trial_id
        ]
    )


def correct(frame, cache, clips):
    return raw(frame, cache, clips) * 0.2


def role(frame, name, cache, clips):
    return raw(frame, cache, clips) * (0.3 if name == "shuffled_cue" else -0.4)


def bank_fixture():
    rows = []
    for i, trial in enumerate(E.TRIAL_IDS):
        rows.append(
            {
                "trial_id": trial,
                "scene_kind": "clean" if i == 0 else "mixed",
                "control_subset": int(i in (1, 2, 5, 12, 15, 22, 29)),
                "target_speaker": f"00{i % 4}",
                "target_gender": "female",
                "target_norm": "null" if i == 0 else "nan",
                "target_label": i % 800,
                "distractor_count": 0 if i == 0 else 1,
                "snr_bin": -1 if i == 0 else 0,
                "snr_db": np.nan if i == 0 else -3.0,
                "distractor_1_norm": "" if i == 0 else "word",
                "distractor_1_label": (i + 1) % 800,
            }
        )
    return pd.DataFrame(rows)


class CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.snapshot = self.root / "snapshot"
        src = self.snapshot / "src"
        src.mkdir(parents=True)
        E.create_bytes(src / "__init__.py", b"")
        shutil.copyfile(
            CANDIDATE / "tests/fixture_model.py", src / "spatial_attn_lightning.py"
        )
        self.config = self.root / "config.yaml"
        E.create_bytes(self.config, b"compile_model: true\n")
        E.configure_runtime()
        self.manifest = {
            "roots": {"snapshot_files": str(self.snapshot)},
            "inputs": {
                "config": {"path": str(self.config), "sha256": E.sha256(self.config)}
            },
            "models": {},
        }
        with BASE._frozen_import_context(self.snapshot):
            from src.spatial_attn_lightning import BinauralAttentionModule

            for offset, model_id in enumerate(E.MODEL_ORDER):
                torch.manual_seed(100 + offset)
                # Author fixture is uncompiled; original loader must apply its
                # sole approved namespace rewrite to the compiled constructor.
                model = BinauralAttentionModule(
                    {"compile_model": model_id != "author_external"}
                )
                path = self.root / f"{model_id}.ckpt"
                torch.save({"state_dict": model.state_dict()}, path)
                self.manifest["models"][model_id] = {
                    "config_key": "config",
                    "path": str(path),
                    "sha256": E.sha256(path),
                }
        self.models = {}
        for model_id in E.MODEL_ORDER:
            model, report = BASE.strict_load_model(
                self.manifest, model_id, torch.device("cpu")
            )
            self.assertEqual(report["loaded_trainable_numel_ratio"], 1.0)
            self.assertEqual(model.restored, model_id != "author_external")
            self.assertTrue(E.unwrap_eager(model)["known_wrapper_removed"])
            self.models[model_id] = model
        self.bank = bank_fixture()
        self.hashes = dict(
            zip(self.bank.trial_id, BASE._tensor_hashes(raw(self.bank, None, None)))
        )

    def run_pass(self, batch_size=16, **overrides):
        arguments = dict(
            base=BASE,
            bank=self.bank,
            historical_hashes=self.hashes,
            models=self.models,
            device=torch.device("cpu"),
            clips_dir=self.root,
            cache_class=Cache,
            raw_scene_batch=raw,
            correct_cue_batch=correct,
            role_batch=role,
            batch_size=batch_size,
        )
        arguments.update(overrides)
        with contextlib.redirect_stdout(io.StringIO()):
            return E.evaluate_pass(**arguments)

    def test_disk_checkpoint_to_all_controls_to_independent_reload(self):
        results, arrays, details = self.run_pass()
        E.save_pass(self.root, self.bank, results, arrays, details)
        report = E.verify_pass(BASE, self.root)
        self.assertEqual(report["trials"], 32)
        self.assertEqual(report["model_condition_predictions"], 159)
        self.assertEqual(report["numeric_qualification"], "NOT_ESTABLISHED")
        self.assertFalse(report["full_comparison_complete"])
        self.assertEqual(
            set(arrays), {f"{m}__{c}" for m in E.MODEL_ORDER for c in E.CONDITIONS}
        )

    def test_v4_native_predict_cpu_parity(self):
        model = self.models["formal40"]
        scene = raw(self.bank.iloc[:3], None, None)
        cue = correct(self.bank.iloc[:3], None, None)
        labels = torch.tensor([0, 1, 2])
        probes = torch.tensor([1, 2, 3])
        expected = BASE.predict_batch(
            model, scene, cue, labels, probes, torch.device("cpu")
        )
        actual, _ = E.predict(
            BASE, model, scene, cue, labels, probes, torch.device("cpu")
        )
        for key in expected:
            np.testing.assert_array_equal(actual[key], expected[key])

    def test_fixed_batch_repeat_and_one_batch_reports_are_not_auto_qualification(self):
        first, arrays, _ = self.run_pass(16)
        repeat, other, _ = self.run_pass(16)
        pd.testing.assert_frame_equal(first, repeat)
        for key in arrays:
            np.testing.assert_array_equal(arrays[key], other[key])
        singleton, single_arrays, _ = self.run_pass(1)
        self.assertEqual(singleton.trial_id.tolist(), first.trial_id.tolist())
        for key in arrays:
            self.assertEqual(arrays[key].shape, single_arrays[key].shape)

    def test_tail_batch_and_control_indices(self):
        subset = self.bank.iloc[:17].copy()
        results, arrays, details = self.run_pass(bank=subset)
        self.assertEqual(len(results), 17)
        self.assertEqual(arrays["formal40__correct"].shape, (17, 800))
        self.assertEqual(
            len(details["cue_hashes"]["silent"]), int(subset.control_subset.sum())
        )

    def test_scene_hash_mismatch_stops_before_forward(self):
        changed = dict(self.hashes)
        changed[9000] = "a" * 64
        with self.assertRaisesRegex(RuntimeError, "Regenerated scene"):
            self.run_pass(historical_hashes=changed)

    def test_raw_input_mutation_rejected(self):
        def mutate(signal, background):
            signal.add_(1)
            return signal, background

        self.models["formal40"].audio_transforms = mutate
        with self.assertRaisesRegex(RuntimeError, "mutated shared raw"):
            self.run_pass()

    def test_training_and_batch_dependent_batchnorm_rejected(self):
        self.models["formal40"].train()
        with self.assertRaisesRegex(RuntimeError, "Training-mode"):
            self.run_pass()
        self.models["formal40"].eval()
        self.models["formal40"].add_module(
            "bad_bn", torch.nn.BatchNorm1d(3, track_running_stats=False).eval()
        )
        for p in self.models["formal40"].parameters():
            p.requires_grad_(False)
        with self.assertRaisesRegex(RuntimeError, "Batch-dependent BatchNorm"):
            self.run_pass()

    def test_state_content_mutation_without_version_increment_rejected(self):
        model = self.models["formal40"]
        original = model.forward

        def altered(*args):
            model.example_buffer.data.add_(1)
            return original(*args)

        model.forward = altered
        with self.assertRaisesRegex(RuntimeError, "Model state changed"):
            self.run_pass()

    def test_nonfinite_logits_rejected(self):
        model = self.models["formal40"]
        original = model.forward
        model.forward = lambda *args: original(*args) * float("nan")
        with self.assertRaisesRegex(RuntimeError, "Logits are not finite"):
            self.run_pass()

    def test_random_inference_rejected(self):
        model = self.models["formal40"]
        original = model.forward

        def random_forward(*args):
            value = original(*args)
            return value + torch.rand_like(value)

        model.forward = random_forward
        with self.assertRaisesRegex(RuntimeError, "RNG state"):
            self.run_pass()

    def test_runtime_mutation_rejected(self):
        model = self.models["formal40"]
        original = model.forward

        def changed(*args):
            torch.backends.cudnn.benchmark = True
            return original(*args)

        model.forward = changed
        with self.assertRaisesRegex(RuntimeError, "Runtime settings changed"):
            self.run_pass()

    def test_existing_hook_rejected(self):
        handle = self.models["formal40"].model.register_forward_hook(lambda *a: None)
        self.addCleanup(handle.remove)
        with self.assertRaisesRegex(RuntimeError, "Forward hooks"):
            self.run_pass()

    def test_missing_checkpoint_weight_rejected_by_original_strict_loader(self):
        record = self.manifest["models"]["formal40"]
        checkpoint = torch.load(record["path"], weights_only=False)
        checkpoint["state_dict"].pop(next(iter(checkpoint["state_dict"])))
        path = self.root / "missing.ckpt"
        torch.save(checkpoint, path)
        record.update(path=str(path), sha256=E.sha256(path))
        with self.assertRaises(BASE.EvaluationError):
            BASE.strict_load_model(self.manifest, "formal40", torch.device("cpu"))

    def test_metric_corruption_detected_by_logit_recomputation(self):
        results, arrays, details = self.run_pass()
        results.loc[0, "formal40_nll"] += 0.01
        E.save_pass(self.root, self.bank, results, arrays, details)
        with self.assertRaisesRegex(RuntimeError, "Metric does not match"):
            E.verify_pass(BASE, self.root)

    def test_fractional_label_is_not_silently_truncated(self):
        results, arrays, details = self.run_pass()
        results["formal40_pred_label"] = results.formal40_pred_label.astype(float)
        results.loc[0, "formal40_pred_label"] += 0.5
        E.save_pass(self.root, self.bank, results, arrays, details)
        with self.assertRaisesRegex(RuntimeError, "Non-integer"):
            E.verify_pass(BASE, self.root)

    def test_receipt_inventory_recheck_and_corruption(self):
        results, arrays, details = self.run_pass()
        output = self.root / "synthetic-artifacts"
        output.mkdir()
        E.save_pass(output, self.bank, results, arrays, details)
        layout = E.layout_spec("bridge16")
        E.create_bytes(output / "LAYOUT.json", E.layout_bytes(layout))
        layout_sha = E.sha256(output / "LAYOUT.json")
        E.create_json(
            output / "RUN.json",
            {
                "test_scope": "SYNTHETIC_ONLY_NOT_PRODUCTION_EVIDENCE",
                "protocol": E.PROTOCOL,
                "role": E.ROLE,
                "v4_source_sha256": E.V4_SHA,
                "v4_manifest_sha256": E.MANIFEST_SHA,
                "models": {
                    m: {"sha256": BASE.EXPECTED_HASHES[m]} for m in E.MODEL_ORDER
                },
                "trial_ids": E.TRIAL_IDS,
                "layout_id": "bridge16",
                "layout_sha256": layout_sha,
                "batch_size": 16,
                "batches": layout["batches"],
                "historical_scene_hashes": {
                    str(i): self.hashes[i] for i in E.TRIAL_IDS
                },
            },
        )
        E.create_json(output / "LOAD_REPORTS.json", {"scope": "synthetic test fixture"})
        E.create_json(
            output / "RECEIPT.json",
            {
                "protocol": E.PROTOCOL,
                "status": "SMALL_RUN_COMPLETE_NOT_QUALIFIED",
                "files": {p.name: E.sha256(p) for p in output.iterdir()},
            },
        )
        digest = E.sha256(output / "RECEIPT.json")
        self.assertEqual(
            E.verify_receipt(BASE, output, digest, layout_sha)["trials"], 32
        )
        with self.assertRaisesRegex(RuntimeError, "Receipt SHA"):
            E.verify_receipt(BASE, output, "0" * 64, layout_sha)
        E.create_bytes(output / "FAILED.json", b"{}")
        with self.assertRaisesRegex(RuntimeError, "Unexpected files"):
            E.verify_receipt(BASE, output, digest, layout_sha)

    def test_empty_control_cells_cannot_be_filled_with_fabricated_predictions(self):
        results, arrays, details = self.run_pass()
        results.loc[0, "formal40_shuffled_pred_label"] = 2
        E.save_pass(self.root, self.bank, results, arrays, details)
        with self.assertRaises(BASE.EvaluationError):
            E.verify_pass(BASE, self.root)

    def test_logit_nan_and_shape_corruption_rejected(self):
        results, arrays, details = self.run_pass()
        arrays["formal40__correct"][0, 0] = np.nan
        E.save_pass(self.root, self.bank, results, arrays, details)
        with self.assertRaisesRegex(RuntimeError, "Nonfinite archived"):
            E.verify_pass(BASE, self.root)

    def test_frozen_trial_order_and_no_resampling(self):
        selected = E.select_trials(self.bank.sample(frac=1, random_state=2))
        self.assertEqual(tuple(selected.trial_id), E.TRIAL_IDS)
        with self.assertRaises((KeyError, RuntimeError)):
            E.select_trials(self.bank.iloc[:-1])
        with self.assertRaisesRegex(RuntimeError, "Duplicate"):
            E.select_trials(pd.concat([self.bank, self.bank.iloc[:1]]))

    def test_exclusive_artifact_creation(self):
        path = self.root / "exclusive.json"
        E.create_json(path, {"old": True})
        with self.assertRaises(FileExistsError):
            E.create_json(path, {"new": True})
        self.assertEqual(json.loads(path.read_text()), {"old": True})

    def test_production_run_cannot_start_on_local_machine(self):
        with mock.patch.object(E.sys, "platform", "darwin"):
            with self.assertRaisesRegex(RuntimeError, "HAKUSAN Linux"):
                E.run_small(None)


if __name__ == "__main__":
    unittest.main()

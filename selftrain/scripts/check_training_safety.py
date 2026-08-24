"""Fast CPU checks for AMP audit, constraints, rolling saves, and resume rules."""

import pathlib
import tempfile
import types
import unittest
from collections import deque
from unittest import mock

import torch
from pytorch_lightning import LightningModule, Trainer

from src.spatial_attn_lightning import BinauralAttentionModule
from selftrain.data.diotic_attention import DioticAttentionDataset
from src.spatialtrain import (
    RollingStepCheckpoint,
    _validate_resume_checkpoint,
)
from selftrain.scripts.run_integrity import SEMANTIC_INPUTS


class _FakeScaler:
    def __init__(self, scale=65536.0):
        self.scale = float(scale)

    def get_scale(self):
        return self.scale


def _audit_module(window_steps=8):
    module = BinauralAttentionModule.__new__(BinauralAttentionModule)
    LightningModule.__init__(module)
    module.hparas_config = {
        "max_consecutive_amp_overflows": 8,
        "amp_overflow_window_steps": window_steps,
        "max_amp_overflows_per_window": 2,
        "max_total_amp_overflows": 64,
    }
    module.model = torch.nn.Linear(1, 1)
    module.attn_modules = []
    module.constrain_slope = True
    module._amp_overflow_window = deque(maxlen=window_steps)
    module._consecutive_amp_overflows = 0
    module._total_amp_overflows = 0
    module._total_optimizer_attempts = 0
    module._successful_optimizer_steps = 0
    module._amp_epoch_index = -1
    module._amp_epoch_overflows = 0
    module._amp_epoch_optimizer_attempts = 0
    module._amp_epoch_successful_steps = 0
    module._overflow_this_step = False
    module._overflow_scale_before = None
    module._pending_rng_state = None
    scaler = _FakeScaler()
    module._trainer = types.SimpleNamespace(
        current_epoch=0,
        global_step=0,
        precision_plugin=types.SimpleNamespace(scaler=scaler),
    )
    module.log = lambda *args, **kwargs: None
    return module, scaler


class _LightningAmpLoggingHarness(LightningModule):
    """Exercise the AMP audit hook through Lightning's real log collector."""

    _ensure_amp_epoch_state = BinauralAttentionModule._ensure_amp_epoch_state
    _record_optimizer_attempt = BinauralAttentionModule._record_optimizer_attempt
    _log_amp_overflow = BinauralAttentionModule._log_amp_overflow
    on_before_optimizer_step = BinauralAttentionModule.on_before_optimizer_step

    def __init__(self):
        super().__init__()
        self.hparas_config = {
            "max_consecutive_amp_overflows": 8,
            "amp_overflow_window_steps": 8,
            "max_amp_overflows_per_window": 2,
            "max_total_amp_overflows": 64,
        }
        self.model = torch.nn.Linear(1, 1)
        self._amp_overflow_window = deque(maxlen=8)
        self._consecutive_amp_overflows = 0
        self._total_amp_overflows = 0
        self._total_optimizer_attempts = 0
        self._successful_optimizer_steps = 0
        self._amp_epoch_index = -1
        self._amp_epoch_overflows = 0
        self._amp_epoch_optimizer_attempts = 0
        self._amp_epoch_successful_steps = 0
        self._overflow_this_step = False
        self._overflow_scale_before = None

    def on_train_start(self):
        self.trainer.precision_plugin.scaler = _FakeScaler()

    def training_step(self, batch, batch_idx):
        loss = self.model(batch).sum()
        if batch_idx == 1:
            loss = loss * torch.tensor(float("inf"), device=loss.device)
        return loss

    def configure_optimizers(self):
        return torch.optim.SGD(self.model.parameters(), lr=0.01)

    def train_dataloader(self):
        return torch.utils.data.DataLoader(
            torch.ones(2, 1),
            batch_size=1,
        )


class TrainingSafetyChecks(unittest.TestCase):
    def test_readiness_inputs_are_frozen_in_run_snapshot(self):
        self.assertIn(
            "selftrain/artifacts/splits/eval_speakers.txt",
            SEMANTIC_INPUTS,
        )

    def test_attention_constraints_run_after_optimizer_attempt(self):
        module, _ = _audit_module()
        attention = torch.nn.Module()
        attention.bias = torch.nn.Parameter(torch.tensor([1.5, -0.5]))
        attention.slope = torch.nn.Parameter(torch.tensor([-2.0, 3.0]))
        module.attn_modules = [attention]

        class Optimizer:
            def step(self, closure=None):
                if closure is not None:
                    closure()
                with torch.no_grad():
                    attention.bias.add_(0.25)
                    attention.slope.sub_(0.25)

        module.optimizer_step(0, 0, Optimizer(), lambda: None)
        self.assertTrue(torch.equal(attention.bias, torch.tensor([1.0, 0.0])))
        self.assertTrue(torch.equal(attention.slope, torch.tensor([0.0, 2.75])))
        self.assertEqual(module._successful_optimizer_steps, 1)

    def test_amp_overflow_is_skipped_and_scale_is_reduced(self):
        module, scaler = _audit_module()

        class Optimizer:
            def step(self, closure=None):
                closure()
                scaler.scale /= 2.0

        def closure():
            for parameter in module.model.parameters():
                parameter.grad = torch.full_like(parameter, float("inf"))
            module.on_before_optimizer_step(None)

        module.optimizer_step(0, 0, Optimizer(), closure)
        self.assertEqual(module._total_amp_overflows, 1)
        self.assertEqual(module._total_optimizer_attempts, 1)
        self.assertEqual(module._successful_optimizer_steps, 0)
        self.assertEqual(scaler.get_scale(), 32768.0)

    def test_amp_overflow_log_metadata_is_stable_in_lightning(self):
        module = _LightningAmpLoggingHarness()
        trainer = Trainer(
            accelerator="cpu",
            devices=1,
            max_epochs=1,
            limit_train_batches=2,
            logger=False,
            enable_checkpointing=False,
            enable_model_summary=False,
            enable_progress_bar=False,
        )
        trainer.fit(module)
        self.assertEqual(module._total_optimizer_attempts, 2)
        self.assertEqual(module._total_amp_overflows, 1)

    def test_nonconsecutive_overflows_hit_window_limit(self):
        module, _ = _audit_module(window_steps=8)
        for _ in range(2):
            for parameter in module.model.parameters():
                parameter.grad = torch.full_like(parameter, float("inf"))
            module.on_before_optimizer_step(None)
            for parameter in module.model.parameters():
                parameter.grad = torch.zeros_like(parameter)
            module.on_before_optimizer_step(None)

        for parameter in module.model.parameters():
            parameter.grad = torch.full_like(parameter, float("inf"))
        with self.assertRaisesRegex(
            FloatingPointError,
            "rolling window",
        ):
            module.on_before_optimizer_step(None)

    def test_amp_checkpoint_roundtrip_and_old_checkpoint(self):
        source, _ = _audit_module(window_steps=4)
        source._consecutive_amp_overflows = 0
        source._total_amp_overflows = 3
        source._total_optimizer_attempts = 12
        source._successful_optimizer_steps = 9
        source._amp_epoch_index = 2
        source._amp_epoch_overflows = 2
        source._amp_epoch_optimizer_attempts = 5
        source._amp_epoch_successful_steps = 3
        source._amp_overflow_window.extend([1, 0, 1, 0])
        checkpoint = {}
        source.on_save_checkpoint(checkpoint)
        self.assertIn("audattn_rng_state_v1", checkpoint)

        restored, _ = _audit_module(window_steps=4)
        restored.on_load_checkpoint(checkpoint)
        self.assertEqual(restored._total_amp_overflows, 3)
        self.assertEqual(restored._total_optimizer_attempts, 12)
        self.assertEqual(restored._successful_optimizer_steps, 9)
        self.assertEqual(list(restored._amp_overflow_window), [1, 0, 1, 0])

        legacy, _ = _audit_module(window_steps=4)
        legacy.on_load_checkpoint({})
        self.assertEqual(legacy._total_amp_overflows, 0)

    def test_rolling_checkpoint_is_atomic_and_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = pathlib.Path(directory) / "rolling.ckpt"
            callback = RollingStepCheckpoint(destination, 1000)

            class Trainer:
                global_step = 999
                is_global_zero = True

                def save_checkpoint(self, path):
                    pathlib.Path(path).write_text(
                        str(self.global_step),
                        encoding="utf-8",
                    )

            trainer = Trainer()
            callback.on_train_batch_end(trainer, None, None, None, 0)
            self.assertFalse(destination.exists())
            trainer.global_step = 1000
            callback.on_train_batch_end(trainer, None, None, None, 1)
            self.assertFalse(destination.exists())
            callback.on_train_batch_start(trainer, None, None, 2)
            self.assertEqual(destination.read_text(encoding="utf-8"), "1000")
            self.assertFalse((destination.parent / ".rolling.ckpt.tmp").exists())
            trainer.global_step = 2000
            callback.on_train_batch_end(trainer, None, None, None, 2)
            callback.on_train_epoch_end(trainer, None)
            self.assertEqual(destination.read_text(encoding="utf-8"), "2000")

    def test_dataset_rng_is_worker_independent_and_epoch_specific(self):
        dataset = DioticAttentionDataset.__new__(DioticAttentionDataset)
        dataset.mode = "train"
        dataset.seed = 20260721
        dataset.epoch = 3
        first = dataset._rng(17).integers(0, 2**31, size=8)
        torch.manual_seed(999999)
        second = dataset._rng(17).integers(0, 2**31, size=8)
        self.assertTrue((first == second).all())
        dataset.epoch = 4
        next_epoch = dataset._rng(17).integers(0, 2**31, size=8)
        self.assertFalse((first == next_epoch).all())

    def test_checkpoint_modes_are_not_interchangeable(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = pathlib.Path(directory)
            stage_zero = directory / "stage-0.ckpt"
            progress = directory / "rolling.ckpt"
            common = {"state_dict": {}, "epoch": 0, "loops": {}}
            torch.save(
                {
                    **common,
                    "global_step": 0,
                    "optimizer_states": [],
                },
                stage_zero,
            )
            torch.save(
                {
                    **common,
                    "global_step": 1000,
                    "optimizer_states": [{"state": {}}],
                    "lr_schedulers": [],
                    "MixedPrecision": {"scale": 65536.0},
                    "audattn_amp_state_v1": {
                        "total_optimizer_attempts": 1000,
                        "successful_optimizer_steps": 1000,
                        "total_overflows": 0,
                    },
                    "audattn_rng_state_v1": {},
                    "audattn_run_metadata_v1": {
                        "run_id": "test-run",
                        "source_semantic_sha256": "source-hash",
                        "config_sha256": "config-hash",
                    },
                },
                progress,
            )
            checkpoint = torch.load(progress, map_location="cpu")
            checkpoint["audattn_rng_state_v1"] = {
                "python": (),
                "numpy": (),
                "torch_cpu": torch.get_rng_state(),
                "torch_cuda": [],
            }
            torch.save(checkpoint, progress)
            self.assertEqual(
                _validate_resume_checkpoint(stage_zero, "stage-zero"),
                stage_zero.resolve(),
            )
            with mock.patch.dict(
                "os.environ",
                {
                    "AUDATTN_RUN_ID": "test-run",
                    "AUDATTN_SOURCE_SHA256": "source-hash",
                    "AUDATTN_CONFIG_SHA256": "config-hash",
                },
            ):
                self.assertEqual(
                    _validate_resume_checkpoint(progress, "resume"),
                    progress.resolve(),
                )
            with self.assertRaises(ValueError):
                _validate_resume_checkpoint(stage_zero, "resume")
            with self.assertRaises(ValueError):
                _validate_resume_checkpoint(progress, "stage-zero")


if __name__ == "__main__":
    unittest.main(verbosity=2)

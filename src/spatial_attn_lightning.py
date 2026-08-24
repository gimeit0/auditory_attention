import os 
import random
from collections import deque, namedtuple
from typing import List, Tuple, Optional, Union
import numpy as np
import torch
import torchmetrics
from torchmetrics.classification import Accuracy
from pytorch_lightning import LightningModule

import src.audio_transforms as at
import src.audio_attention_transforms as aat
import src.custom_modules as cm
from src.spatial_attn_architecture import  BinauralAuditoryAttentionCNN, BinauralControlCNN
from corpus.binaural_attention_h5 import BinauralAttentionDataset
from selftrain.data.diotic_attention import DioticAttentionDataset


class BinauralAttentionModule(LightningModule):
    def __init__(
        self,
        config: dict,
    ):
        super().__init__()
        # Make config sent to init
        self.config = config
        self.audio_config = config['audio']
        self.corpora_config = config['corpus']
        self.model_config = config['model']
        self.hparas_config = config['hparas']
        self.multi_task = self.corpora_config['task'] == 'word_and_location'
        overflow_window_steps = int(
            self.hparas_config.get("amp_overflow_window_steps", 1000)
        )
        if overflow_window_steps <= 0:
            raise ValueError("amp_overflow_window_steps must be positive")
        self._amp_overflow_window = deque(maxlen=overflow_window_steps)
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
        self._pending_rng_state = None

        self.corpora_name = config.get('corpora_name', False)

        # set dataset as attribute
        self.word_rec_model = False
        dataset_type = self.corpora_config.get(
            "dataset_type", "binaural_h5"
        )
        if dataset_type == "diotic_manifest":
            self.dataset = DioticAttentionDataset
        elif dataset_type == "binaural_h5":
            self.dataset = BinauralAttentionDataset
        else:
            raise ValueError(f"Unsupported corpus.dataset_type: {dataset_type}")
        self.train_val_collate_fn = self._collate_fn
        v2_demean = self.audio_config.get('v2_demean', False)
        if v2_demean:
            print("Using explicit dim specification for demeaning in audio transforms")
        if self.audio_config.get("per_example_leveling", False):
            combine_transform = at.BinauralCombineWithRandomDBSNRPerExample(
                low_snr=config["noise_kwargs"]["low_snr"],
                high_snr=config["noise_kwargs"]["high_snr"],
            )
            normalize_transform = at.BinauralRMSNormalizePerExample(
                rms_level=0.02
            )
        else:
            combine_transform = at.BinauralCombineWithRandomDBSNR(
                low_snr=config['noise_kwargs']['low_snr'],
                high_snr=config['noise_kwargs']['high_snr'],
                v2_demean=v2_demean,
            )
            normalize_transform = (
                at.BinauralRMSNormalizeForegroundAndBackground(
                    rms_level=0.02, v2_demean=v2_demean
                )
            )
        self.audio_transforms = at.AudioCompose([
            at.AudioToTensor(),
            combine_transform,
            normalize_transform,
        ])
        
        if self.audio_config.get('upsample_audio', False):
            self.audio_transforms = at.AudioCompose([
                at.AudioToTensor(),
                at.BinauralCombineWithRandomDBSNR(low_snr=config['noise_kwargs']['low_snr'],
                                                  high_snr=config['noise_kwargs']['high_snr'],
                                                  v2_demean=v2_demean),
                at.BinauralRMSNormalizeForegroundAndBackground(rms_level=0.02, v2_demean=v2_demean), # 20 * np.log10(0.02/20e-6) = 60 dB SPL 
                at.Resample(**self.audio_config['upsample_kwargs'])
            ])

        self.test_step = self._test_step

        # Init Model
        # Get model architecture
        norm_first = self.model_config.get('norm_first', True)
        new_module = self.model_config.get('v08', False)
        control_arch = self.model_config.get('control_arch', False)
        self.use_backbone_arch = self.model_config.get('backbone_arch', False)
        self.backbone_with_ecdf_gains = self.model_config.get('backbone_with_ecdf_gains', False)
        self.backbone_with_learned_gains = self.model_config.get('backbone_with_learned_gains', False)
        
        self.batch_in_dataloader = (self.use_backbone_arch and not (self.backbone_with_ecdf_gains or self.backbone_with_learned_gains))
        # print(f"Batch in dataloader = {self.batch_in_dataloader}")
        self.dataset_batch_size = 1 if self.batch_in_dataloader else self.hparas_config['batch_size']
        self.dataloader_batch_size = self.hparas_config['batch_size'] if self.batch_in_dataloader else 1        

        if control_arch:
            # print("Using BinauralControlCNN")
            self.model = BinauralControlCNN(**self.model_config)
        else:
            # print("Using BinauralAuditoryAttentionCNN")
            self.model = BinauralAuditoryAttentionCNN(**self.model_config)

        # check if torch version 2 or greater - if so, compile model
        getting_acts = self.config.get('getting_acts', False)
        compile_model = self.config.get("compile_model", True)
        if compile_model and not getting_acts and int(torch.__version__.split('.')[0]) >= 2 and not self.multi_task and not self.audio_config.get('upsample_audio', False):
            self.model = torch.compile(self.model, mode="default")

        ## get local rank
        # print(f"Using dataset {self.dataset.__name__}")
        # print(self.model)

        # Add input rep to model or audio transforms
        self.rep_on_gpu = self.audio_config['rep_kwargs']['rep_on_gpu']
        self.coch_gram = cm.AttnAudioInputRepresentation(**self.audio_config)

        # Losses
        self.loss_fn = torch.nn.CrossEntropyLoss()

        # Set up metrics
        if self.multi_task:
            self.train_acc = torch.nn.ModuleDict({'word':Accuracy(task="multiclass", num_classes=config['model']['num_classes']['num_words']), 
                                                  'location':Accuracy(task="multiclass", num_classes=config['model']['num_classes']['num_locs'])})
            self.valid_acc = torch.nn.ModuleDict({'word':Accuracy(task="multiclass", num_classes=config['model']['num_classes']['num_words']),
                                                 'location':Accuracy(task="multiclass", num_classes=config['model']['num_classes']['num_locs'])})
            self.test_acc = torch.nn.ModuleDict({'word':Accuracy(task="multiclass", num_classes=config['model']['num_classes']['num_words']),
                                                 'location':Accuracy(task="multiclass", num_classes=config['model']['num_classes']['num_locs'])})
            self.test_confusion = torch.nn.ModuleDict({'word': Accuracy(task="multiclass", num_classes=config['model']['num_classes']['num_words']),
                                                 'location': Accuracy(task="multiclass", num_classes=config['model']['num_classes']['num_locs'])})
        else:
            task_key = 'num_words' if self.corpora_config['task'] == 'word' else "num_locs"
            self.train_acc = Accuracy(task="multiclass", num_classes=config['model']['num_classes'][task_key]).to(self.device)
            self.valid_acc = Accuracy(task="multiclass", num_classes=config['model']['num_classes'][task_key]).to(self.device)
            self.test_acc = Accuracy(task="multiclass", num_classes=config['model']['num_classes'][task_key]).to(self.device)
            self.test_confusion = Accuracy(task="multiclass", num_classes=config['model']['num_classes'][task_key]).to(self.device)
        self.accuracy = {'train': self.train_acc,
                         'val': self.valid_acc,
                         'test': self.test_acc,
                         'test_confusion': self.test_confusion
                        }

        # Constraints
        self.attn_modules = [module for name, module in  self.model.model_dict.items() if 'attn' in name]
        self.constrain_slope = self.model_config['attn_constraints'].get('slope', False)

    def _step(self, batch, batch_idx, step_type):
        if batch is None:
            print(f"Batch on step {batch_idx} was None")
            return None
        if self.multi_task:
            cue_features, cue_mask_ixs, loc_task_ixs, scene_features, labels = batch
        else:
            cue_features, cue_mask_ixs, scene_features, labels = batch
        
        cue_features, scene_features = self.coch_gram(cue_features, scene_features)

        # self() is self.forward()
        outputs = self(cue_features, scene_features, cue_mask_ixs)
        if self.multi_task:
            word, location = outputs
            word_label = labels[:,0]
            word_loss = self.loss_fn(word, word_label)
            # Take valid examples for location task using loc_task_mask
            location_label = labels[:,1]
            if loc_task_ixs is not None:
                location = location[loc_task_ixs, :]
                location_label = location_label[loc_task_ixs]
            loc_loss = self.loss_fn(location, location_label)
            loss = word_loss + loc_loss
            self.accuracy[step_type]['word'](word, word_label) # word accuracy
            self.accuracy[step_type]['location'](location, location_label) # location accuracy
            self.log(f"{step_type}_word_loss", word_loss.detach(), on_step=True, on_epoch=False, prog_bar=True)
            self.log(f"{step_type}_location_loss", loc_loss.detach(), on_step=True, on_epoch=False, prog_bar=True)
            self.log(f"{step_type}_loss", loss.detach(), on_step=True, on_epoch=False, prog_bar=True)
            self.log(f"{step_type}_word_acc", self.accuracy[step_type]['word'], on_step=False, on_epoch=True, prog_bar=True)
            self.log(f"{step_type}_location_acc", self.accuracy[step_type]['location'], on_step=False, on_epoch=True, prog_bar=True)
        else:
            loss = self.loss_fn(outputs, labels)
            self.accuracy[step_type](outputs, labels)
            self.log(f"{step_type}_loss", loss.detach(), on_step=True, on_epoch=True, prog_bar=True, sync_dist=True)
            self.log(f"{step_type}_acc", self.accuracy[step_type], on_step=False, on_epoch=True, prog_bar=True, sync_dist=True)

        if not torch.isfinite(loss.detach()).all():
            raise FloatingPointError(
                f"Non-finite {step_type} loss at batch_idx={batch_idx}: "
                f"{loss.detach().item()}"
            )

        return loss

    def _ensure_amp_epoch_state(self):
        epoch_index = int(self.current_epoch)
        if self._amp_epoch_index != epoch_index:
            self._amp_epoch_index = epoch_index
            self._amp_epoch_overflows = 0
            self._amp_epoch_optimizer_attempts = 0
            self._amp_epoch_successful_steps = 0

    def _record_optimizer_attempt(self, overflow):
        self._ensure_amp_epoch_state()
        self._total_optimizer_attempts += 1
        self._amp_epoch_optimizer_attempts += 1
        self._amp_overflow_window.append(1 if overflow else 0)
        if overflow:
            self._consecutive_amp_overflows += 1
            self._total_amp_overflows += 1
            self._amp_epoch_overflows += 1
        else:
            self._consecutive_amp_overflows = 0

    def _log_amp_overflow(self, overflow):
        """Log the per-attempt AMP overflow flag with stable metadata."""
        self.log(
            "amp_overflow",
            torch.tensor(
                1.0 if overflow else 0.0,
                device=self.device,
            ),
            prog_bar=False,
            on_step=True,
            on_epoch=False,
        )

    def on_before_optimizer_step(self, _):
        def _get_grad_norm(params):
            """Compute one-device global L2 norm with a single host sync."""
            parameter_norms = []
            for p in params:
                if p.grad is not None:
                    gradient = p.grad.detach().float()
                    parameter_norms.append(
                        torch.linalg.vector_norm(gradient, ord=2)
                    )
            if not parameter_norms:
                return 0.0
            global_norm = torch.linalg.vector_norm(
                torch.stack(parameter_norms), ord=2
            )
            return float(global_norm.item())

        grad_norm = _get_grad_norm(self.model.parameters())
        if not np.isfinite(grad_norm):
            nonfinite_parameters = []
            nan_elements = 0
            inf_elements = 0
            for name, parameter in self.model.named_parameters():
                if parameter.grad is None:
                    continue
                gradient = parameter.grad.detach()
                parameter_nan = int(torch.isnan(gradient).sum().item())
                parameter_inf = int(torch.isinf(gradient).sum().item())
                nan_elements += parameter_nan
                inf_elements += parameter_inf
                if parameter_nan or parameter_inf:
                    nonfinite_parameters.append(
                        f"{name}(nan={parameter_nan}, inf={parameter_inf})"
                    )

            scaler = getattr(
                getattr(self.trainer, "precision_plugin", None),
                "scaler",
                None,
            )
            if scaler is not None and (nan_elements or inf_elements):
                self._record_optimizer_attempt(overflow=True)
                self._overflow_this_step = True
                max_consecutive = int(
                    self.hparas_config.get(
                        "max_consecutive_amp_overflows", 8
                    )
                )
                max_in_window = int(
                    self.hparas_config.get(
                        "max_amp_overflows_per_window", 8
                    )
                )
                max_total = int(
                    self.hparas_config.get("max_total_amp_overflows", 64)
                )
                scale = float(scaler.get_scale())
                self._overflow_scale_before = scale
                window_overflows = sum(self._amp_overflow_window)
                details = ", ".join(nonfinite_parameters[:8])
                print(
                    "AMP gradient overflow detected; GradScaler will skip "
                    "this optimizer step and lower the scale. "
                    f"global_step={self.global_step}, scale={scale}, "
                    f"consecutive={self._consecutive_amp_overflows}, "
                    f"total={self._total_amp_overflows}, "
                    f"window={window_overflows}/"
                    f"{self._amp_overflow_window.maxlen}, "
                    f"nan_elements={nan_elements}, "
                    f"inf_elements={inf_elements}, parameters={details}"
                )
                self._log_amp_overflow(True)
                self.log(
                    "amp_scale",
                    torch.tensor(scale, device=self.device),
                    prog_bar=False,
                    on_step=True,
                    on_epoch=False,
                )
                if self._consecutive_amp_overflows > max_consecutive:
                    raise FloatingPointError(
                        "Too many consecutive AMP gradient overflows: "
                        f"{self._consecutive_amp_overflows} "
                        f"(scale={scale})"
                    )
                if window_overflows > max_in_window:
                    raise FloatingPointError(
                        "Too many AMP gradient overflows in the rolling "
                        f"window: {window_overflows}/"
                        f"{self._amp_overflow_window.maxlen} "
                        f"(allowed={max_in_window}, scale={scale})"
                    )
                if self._total_amp_overflows > max_total:
                    raise FloatingPointError(
                        "Too many total AMP gradient overflows: "
                        f"{self._total_amp_overflows} "
                        f"(allowed={max_total}, scale={scale})"
                    )
                return

            raise FloatingPointError(
                "Non-finite gradient norm that AMP GradScaler cannot "
                f"recover from: norm={grad_norm}, "
                f"nan_elements={nan_elements}, inf_elements={inf_elements}"
            )

        recovered_overflows = self._consecutive_amp_overflows
        self._record_optimizer_attempt(overflow=False)
        scaler = getattr(
            getattr(self.trainer, "precision_plugin", None), "scaler", None
        )
        self._log_amp_overflow(False)
        if scaler is not None and recovered_overflows:
            recovered_scale = float(scaler.get_scale())
            print(
                "AMP gradient recovery confirmed. "
                f"global_step={self.global_step}, scale={recovered_scale}, "
                f"previous_consecutive_overflows={recovered_overflows}, "
                f"grad_norm={grad_norm}"
            )
            self.log(
                "amp_scale",
                torch.tensor(recovered_scale, device=self.device),
                prog_bar=False,
                on_step=True,
                on_epoch=False,
            )
        self.log(
            "grad_norm",
            torch.tensor(grad_norm, device=self.device),
            prog_bar=True,
            on_step=True,
            on_epoch=False,
        )

    @torch.no_grad()
    def _apply_attn_constraints(self):
        for module in self.attn_modules:
            if hasattr(module, "bias") and module.bias is not None:
                module.bias.clamp_(0.0, 1.0)
            if (
                self.constrain_slope
                and hasattr(module, "slope")
                and module.slope is not None
            ):
                module.slope.clamp_(min=0.0)

    def optimizer_step(
        self,
        epoch,
        batch_idx,
        optimizer,
        optimizer_closure=None,
    ):
        # Lightning only calls this at a real optimizer-attempt boundary, not
        # for every gradient-accumulation microbatch. GradScaler performs its
        # skip/backoff inside super().optimizer_step().
        self._overflow_this_step = False
        self._overflow_scale_before = None
        super().optimizer_step(
            epoch,
            batch_idx,
            optimizer,
            optimizer_closure,
        )

        if self._overflow_this_step:
            scaler = getattr(
                getattr(self.trainer, "precision_plugin", None),
                "scaler",
                None,
            )
            if scaler is None:
                raise RuntimeError(
                    "AMP overflow was recorded but GradScaler disappeared"
                )
            scale_after = float(scaler.get_scale())
            if not scale_after < self._overflow_scale_before:
                raise RuntimeError(
                    "GradScaler did not lower its scale after an AMP "
                    "gradient overflow: "
                    f"before={self._overflow_scale_before}, "
                    f"after={scale_after}"
                )
            print(
                "AMP optimizer step safely skipped and scale reduced. "
                f"global_step={self.global_step}, "
                f"scale_before={self._overflow_scale_before}, "
                f"scale_after={scale_after}"
            )
            self.log(
                "amp_scale_after_backoff",
                torch.tensor(scale_after, device=self.device),
                prog_bar=False,
                on_step=True,
                on_epoch=False,
            )
        else:
            self._ensure_amp_epoch_state()
            self._successful_optimizer_steps += 1
            self._amp_epoch_successful_steps += 1

        # Project the attention parameters only after the optimizer attempt.
        # This keeps forward/backward on the same parameter values and ensures
        # validation and checkpoints always observe constrained parameters.
        self._apply_attn_constraints()

    def on_train_epoch_end(self):
        self._ensure_amp_epoch_state()
        scaler = getattr(
            getattr(self.trainer, "precision_plugin", None), "scaler", None
        )
        scale = float(scaler.get_scale()) if scaler is not None else None
        window_overflows = sum(self._amp_overflow_window)
        print(
            "AMP epoch summary: "
            f"epoch={self.current_epoch}, "
            f"epoch_overflows={self._amp_epoch_overflows}, "
            f"epoch_attempts={self._amp_epoch_optimizer_attempts}, "
            f"epoch_successful_steps={self._amp_epoch_successful_steps}, "
            f"total_overflows={self._total_amp_overflows}, "
            f"total_attempts={self._total_optimizer_attempts}, "
            f"total_successful_steps={self._successful_optimizer_steps}, "
            f"window_overflows={window_overflows}/"
            f"{self._amp_overflow_window.maxlen}, scale={scale}"
        )
        self.log(
            "amp_epoch_overflows",
            float(self._amp_epoch_overflows),
            on_step=False,
            on_epoch=True,
        )
        self.log(
            "amp_total_overflows",
            float(self._total_amp_overflows),
            on_step=False,
            on_epoch=True,
        )
        self.log(
            "amp_successful_optimizer_steps",
            float(self._successful_optimizer_steps),
            on_step=False,
            on_epoch=True,
        )

    def on_save_checkpoint(self, checkpoint):
        checkpoint["audattn_amp_state_v1"] = {
            "consecutive_overflows": self._consecutive_amp_overflows,
            "total_overflows": self._total_amp_overflows,
            "total_optimizer_attempts": self._total_optimizer_attempts,
            "successful_optimizer_steps": self._successful_optimizer_steps,
            "epoch_index": self._amp_epoch_index,
            "epoch_overflows": self._amp_epoch_overflows,
            "epoch_optimizer_attempts": self._amp_epoch_optimizer_attempts,
            "epoch_successful_steps": self._amp_epoch_successful_steps,
            "overflow_window": list(self._amp_overflow_window),
        }
        run_metadata = {
            "run_id": os.environ.get("AUDATTN_RUN_ID"),
            "source_semantic_sha256": os.environ.get(
                "AUDATTN_SOURCE_SHA256"
            ),
            "config_sha256": os.environ.get("AUDATTN_CONFIG_SHA256"),
        }
        if any(value is not None for value in run_metadata.values()):
            if not all(value for value in run_metadata.values()):
                raise RuntimeError(
                    "Incomplete AUDATTN run metadata environment: "
                    f"{run_metadata}"
                )
            checkpoint["audattn_run_metadata_v1"] = run_metadata
        checkpoint["audattn_rng_state_v1"] = {
            "python": random.getstate(),
            "numpy": np.random.get_state(),
            "torch_cpu": torch.get_rng_state(),
            "torch_cuda": (
                torch.cuda.get_rng_state_all()
                if torch.cuda.is_available()
                else []
            ),
        }

    def on_load_checkpoint(self, checkpoint):
        state = checkpoint.get("audattn_amp_state_v1")
        if state is not None:
            def _nonnegative_int(name, default=0):
                value = int(state.get(name, default))
                if value < 0:
                    raise ValueError(
                        "Invalid negative AMP checkpoint state "
                        f"{name}={value}"
                    )
                return value

            self._consecutive_amp_overflows = _nonnegative_int(
                "consecutive_overflows"
            )
            self._total_amp_overflows = _nonnegative_int("total_overflows")
            self._total_optimizer_attempts = _nonnegative_int(
                "total_optimizer_attempts"
            )
            self._successful_optimizer_steps = _nonnegative_int(
                "successful_optimizer_steps"
            )
            self._amp_epoch_index = int(state.get("epoch_index", -1))
            self._amp_epoch_overflows = _nonnegative_int("epoch_overflows")
            self._amp_epoch_optimizer_attempts = _nonnegative_int(
                "epoch_optimizer_attempts"
            )
            self._amp_epoch_successful_steps = _nonnegative_int(
                "epoch_successful_steps"
            )
            window = [
                int(value) for value in state.get("overflow_window", [])
            ]
            if any(value not in (0, 1) for value in window):
                raise ValueError("Invalid AMP overflow window in checkpoint")
            self._amp_overflow_window.clear()
            self._amp_overflow_window.extend(
                window[-self._amp_overflow_window.maxlen :]
            )
            if (
                self._successful_optimizer_steps
                + self._total_amp_overflows
                != self._total_optimizer_attempts
            ):
                raise ValueError(
                    "Inconsistent AMP checkpoint accounting: "
                    f"successful={self._successful_optimizer_steps}, "
                    f"overflows={self._total_amp_overflows}, "
                    f"attempts={self._total_optimizer_attempts}"
                )
            if (
                self._amp_epoch_successful_steps
                + self._amp_epoch_overflows
                != self._amp_epoch_optimizer_attempts
            ):
                raise ValueError(
                    "Inconsistent epoch AMP checkpoint accounting: "
                    f"successful={self._amp_epoch_successful_steps}, "
                    f"overflows={self._amp_epoch_overflows}, "
                    f"attempts={self._amp_epoch_optimizer_attempts}"
                )
            if sum(self._amp_overflow_window) > self._total_amp_overflows:
                raise ValueError(
                    "AMP overflow window contains more overflows than the "
                    "checkpoint total"
                )
            trailing_overflows = 0
            for value in reversed(self._amp_overflow_window):
                if value == 0:
                    break
                trailing_overflows += 1
            if trailing_overflows != self._consecutive_amp_overflows:
                raise ValueError(
                    "AMP consecutive-overflow count does not match the "
                    "checkpoint window: "
                    f"consecutive={self._consecutive_amp_overflows}, "
                    f"window_trailing={trailing_overflows}"
                )

        self._pending_rng_state = checkpoint.get("audattn_rng_state_v1")

    def on_train_start(self):
        if self._pending_rng_state is None:
            return
        state = self._pending_rng_state
        random.setstate(state["python"])
        np.random.set_state(state["numpy"])
        torch.set_rng_state(state["torch_cpu"])
        if torch.cuda.is_available() and state.get("torch_cuda"):
            torch.cuda.set_rng_state_all(state["torch_cuda"])
        self._pending_rng_state = None
        print("Restored Python/NumPy/Torch RNG state from checkpoint")

    def configure_optimizers(self):
        # Optimizer
        opt = getattr(torch.optim, self.hparas_config['optimizer'])
        model_params = [{'params': self.model.parameters()}]
        self.optimizer = opt(model_params, lr=self.hparas_config['lr'], eps=self.hparas_config['eps'])       
        if self.hparas_config.get('use_scheduler', False):
            print(f"Using learning rate schedule: {self.hparas_config['scheduler']['type']}")
            if self.hparas_config['scheduler']['type'] == "OneCycleLR":
                # quick hack to get len of training set 
                loader = self.train_dataloader()
                dataset_len = len(self.train_dataset)
                del loader 
                scheduler = torch.optim.lr_scheduler.OneCycleLR(self.optimizer,
                                                                max_lr=self.hparas_config['scheduler']['max_lr'],
                                                                epochs=self.hparas_config['epochs'],
                                                                three_phase=False,
                                                                # verbose=True,
                                                                steps_per_epoch=dataset_len//self.config['ngpus'])

                lr_scheduler = {'scheduler': scheduler, 'interval': 'step'}
            elif self.hparas_config['scheduler']['type'] == "ReduceLROnPlateau":
                scheduler =  torch.optim.lr_scheduler.ReduceLROnPlateau(self.optimizer,
                                                                        mode=self.hparas_config['scheduler']['mode'],
                                                                        patience=self.hparas_config['scheduler']['patience'],
                                                                        factor=self.hparas_config['scheduler']['factor'],
                                                                        )
                lr_scheduler = {'scheduler': scheduler,
                            'monitor': self.config['val_metric'], 
                            'interval': 'epoch',
                            'frequency': 1 
                            }

            return {'optimizer': self.optimizer, 'lr_scheduler': lr_scheduler}

        return [self.optimizer]

    def forward(self, cue: torch.tensor, scene: torch.tensor, cue_mask_ixs: Optional[torch.tensor] = None):
        outputs = self.model(cue, scene, cue_mask_ixs)
        # Outputs here are logits
        return outputs

    def training_step(self, batch, batch_idx):
        return self._step(batch, batch_idx, "train")

    def validation_step(self, batch, batch_idx):
        return self._step(batch, batch_idx, "val")

    def _test_step(self, batch, batch_idx):
        # Not used in model simulations - test loops outside of lightning
        bg_labels = None
        if  self.audioset_bg_test or self.n_test_talkers and not self.matched_cue_level:
            signal, fg_cue, fg_labels = batch
        elif self.get_f0:
            signal, fg_cue, bg_cue, fg_labels, bg_labels, fg_f0, bg_f0 = batch
        else:
            signal, fg_cue, bg_cue, fg_labels, bg_labels = batch
        
        batch_size = len(signal)
        # self() is self.forward()  
        fg_outputs = self(fg_cue, signal) 
        fg_loss = self.loss_fn(fg_outputs, fg_labels)
        # calc foreground talker word accuracy
        if self.get_f0:
            for ix in range(batch_size):
                self.accuracy["test"](fg_outputs[ix].softmax(-1).argmax(-1).view(1,-1), fg_labels[ix].view(1,-1))
                self.log(f"ACC/test_fg_acc_eg_{ix}", self.accuracy["test"], on_step=True, on_epoch=False)

                if not self.audioset_bg_test and not self.n_test_talkers:
                    # log test confusion on tasks that have it 
                    self.accuracy['test_confusion'](fg_outputs[ix].softmax(-1).argmax(-1).view(1,-1), bg_labels[ix].view(1,-1))
                    self.log(f"test_confusion_eg_{ix}", self.accuracy['test_confusion'], on_step=True, on_epoch=False)

                self.log(f"fg_f0_eg_{ix}", fg_f0[ix], on_step=True, on_epoch=False)
                self.log(f"bg_f0_eg_{ix}", bg_f0[ix], on_step=True, on_epoch=False)
                
        else:
            # self.accuracy["test"](fg_outputs, fg_labels)
            self.log(f"ACC/test_fg_acc", self.accuracy["test"], on_step=True, on_epoch=False)

            if bg_labels != None:
                # log test confusion on tasks that have it 
                # self.accuracy['test_confusion'](fg_outputs, bg_labels)
                model_guesses = fg_outputs.log_softmax(-1).argmax(-1).view(1,-1)
                confusion = int(model_guesses in bg_labels)
                self.log(f"test_confusion", confusion, on_step=True, on_epoch=False)

        return fg_loss

    def _extract_labels(self, samples: List):
        # idx=3 is harcoded - sample in samples is list of (cue, foreground, background, label)
        return torch.tensor([sample[3] for sample in samples]).type(torch.LongTensor)

    def get_cue_mask_ixs(self, cue: torch.tensor):
        cue_flat = cue.reshape(cue.shape[0], -1)
        mask_ixs = torch.argwhere(torch.sum(torch.abs(cue_flat), dim=1) == 0).squeeze()
        if self.multi_task:
            # Only use examples in batch with cue for location task 
            loc_task_mask = torch.argwhere(torch.sum(torch.abs(cue_flat), dim=1) != 0).squeeze()
            return mask_ixs, loc_task_mask
        return mask_ixs

    def _extract_features(self, samples: List, sample_ix: Union[int, list]):
        # hardcode none for bg noise here - scenes are pre-mixed
        if self.rep_on_gpu:
            if isinstance(sample_ix, list):
                rep_features = [self.audio_transforms(sample[sample_ix[0]], sample[sample_ix[1]])[0].squeeze() for sample in samples]
            else:
                rep_features = [self.audio_transforms(sample[sample_ix], None)[0].squeeze() for sample in samples]
            features = torch.nn.utils.rnn.pad_sequence(rep_features, batch_first=True)
        else:
            # are cochleagrams & need to transpose from CxFxT -> TxFxC for pad sequence
            if isinstance(sample_ix, list):
                rep_features = [self.audio_transforms(sample[sample_ix[0]], sample[sample_ix[1]])[0].transpose(0,2) for sample in samples]
            else:
                rep_features = [self.audio_transforms(sample[sample_ix], None)[0].transpose(0,2) for sample in samples]
            features = torch.nn.utils.rnn.pad_sequence(rep_features, batch_first=True)
            features = features.transpose(1,3) # back to CxFxT for model
        return features

    def _collate_fn(self, samples: List):
        # samples is a single-element list holding a tuple batches
        samples = samples[0]
        cue_features, _ = self.audio_transforms(samples[0], None)
        if self.hparas_config.get('mask_cues', False):  # default is to not mask cues
            cue_mask_ixs, loc_task_ixs = self.get_cue_mask_ixs(cue_features)
        else:
            cue_mask_ixs, loc_task_ixs = None, None  # loc task ixs are not used if not multi_task
        scene_features, _ = self.audio_transforms(samples[1], samples[2])
        labels = torch.from_numpy(samples[3]).type(torch.LongTensor)
        if self.multi_task:
            return cue_features, cue_mask_ixs, loc_task_ixs, scene_features, labels
        return cue_features, cue_mask_ixs, scene_features, labels

    def test_collate_fn(self, samples: List):
        cue_features = self._extract_features(samples, sample_ix=0)
        cue_mask_ixs = self.get_cue_mask_ixs(cue_features)
        scene_features = self._extract_features(samples, sample_ix=[1,2])
        labels = self._extract_labels(samples)
        return cue_features, cue_mask_ixs, scene_features, labels

    def train_dataloader(self):
        train_config = dict(self.corpora_config)
        train_config["epoch"] = int(self.current_epoch)
        self.train_dataset = self.dataset(**train_config, batch_size=self.dataset_batch_size, mode='train')
        print(f"len training set = {len( self.train_dataset )}")
        dataloader = torch.utils.data.DataLoader(
            self.train_dataset,
            batch_size=self.dataloader_batch_size ,
            num_workers=self.config.get('num_workers', 0),
            collate_fn=self.train_val_collate_fn,
            pin_memory=True,
            # persistent_workers=True,
            shuffle=True if self.use_backbone_arch else False
        )
        return dataloader

    def val_dataloader(self):
        dataset = self.dataset(**self.corpora_config, batch_size=self.dataset_batch_size, mode='val')
        dataloader = torch.utils.data.DataLoader(
            dataset,
            batch_size=self.dataloader_batch_size ,
            num_workers=self.config.get('num_workers', 0),
            collate_fn=self.train_val_collate_fn,
            shuffle=False
        )
        return dataloader

    def test_dataloader(self): # dumy placeholder no longer - fixed
        dataset = self.dataset(**self.corpora_config, mode='test')
        dataloader = torch.utils.data.DataLoader(
            dataset,
            batch_size=self.hparas_config['batch_size'],
            num_workers=self.config.get('num_workers', 0),
            collate_fn=self.test_collate_fn)
        self.test_loader_len = len(dataset)
        print("Test set length = ", self.test_loader_len)
        return dataloader

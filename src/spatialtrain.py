import pathlib
from argparse import ArgumentParser
import os
import yaml
import json
import pickle
import torch
from pytorch_lightning import Trainer, seed_everything
from pytorch_lightning.callbacks import Callback, EarlyStopping, ModelCheckpoint
from src.spatial_attn_lightning import BinauralAttentionModule #probably need to change this to the new name
# get nodename 
import socket

torch.set_float32_matmul_precision('medium')
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True

hostname = socket.gethostname()


class StageZeroCheckpoint(Callback):
    """Save a full Lightning checkpoint before the first optimization step."""

    def __init__(self, checkpoint_path):
        super().__init__()
        self.checkpoint_path = pathlib.Path(checkpoint_path)

    def on_fit_start(self, trainer, pl_module):
        if self.checkpoint_path.exists():
            raise FileExistsError(
                "Refusing to overwrite the random-initialization checkpoint at "
                f"{self.checkpoint_path}. Resume the existing run or move the "
                "old experiment directory before starting a fresh run."
            )
        trainer.save_checkpoint(self.checkpoint_path)
        if trainer.is_global_zero:
            print(
                "Saved random-initialization checkpoint: ",
                self.checkpoint_path,
            )


class RollingStepCheckpoint(Callback):
    """Atomically keep one resumable checkpoint at a fixed step interval."""

    def __init__(self, checkpoint_path, every_n_train_steps):
        super().__init__()
        self.checkpoint_path = pathlib.Path(checkpoint_path)
        self.every_n_train_steps = int(every_n_train_steps)
        if self.every_n_train_steps <= 0:
            raise ValueError("every_n_train_steps must be positive")
        self._last_saved_step = -1
        self._pending_step = None

    def state_dict(self):
        return {
            "last_saved_step": self._last_saved_step,
            "pending_step": self._pending_step,
        }

    def load_state_dict(self, state_dict):
        self._last_saved_step = int(
            state_dict.get("last_saved_step", -1)
        )
        pending_step = state_dict.get("pending_step")
        self._pending_step = (
            None if pending_step is None else int(pending_step)
        )

    def _save_pending_checkpoint(self, trainer):
        if self._pending_step is None:
            return
        if int(getattr(trainer, "world_size", 1)) != 1:
            raise RuntimeError(
                "RollingStepCheckpoint currently supports exactly one "
                "training process; refusing a multi-process checkpoint race"
            )
        step = int(self._pending_step)

        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.checkpoint_path.with_name(
            f".{self.checkpoint_path.name}.tmp"
        )
        previous_last_saved_step = self._last_saved_step
        self._last_saved_step = step
        self._pending_step = None
        try:
            trainer.save_checkpoint(temporary_path)
            os.replace(temporary_path, self.checkpoint_path)
        except BaseException:
            self._last_saved_step = previous_last_saved_step
            self._pending_step = step
            raise
        if trainer.is_global_zero:
            print(
                "Saved atomic rolling checkpoint: "
                f"{self.checkpoint_path} (global_step={step})"
            )

    def on_train_batch_start(self, trainer, pl_module, batch, batch_idx):
        # PL 2.1 increments the previous batch's completed-loop counter only
        # after on_train_batch_end callbacks. Saving here captures the finished
        # optimizer step without creating a checkpoint that would replay it.
        self._save_pending_checkpoint(trainer)

    def on_train_batch_end(
        self,
        trainer,
        pl_module,
        outputs,
        batch,
        batch_idx,
    ):
        step = int(trainer.global_step)
        if (
            step > 0
            and step != self._last_saved_step
            and step % self.every_n_train_steps == 0
        ):
            self._pending_step = step

    def on_train_epoch_end(self, trainer, pl_module):
        # There is no next batch-start hook after the final batch of an epoch.
        self._save_pending_checkpoint(trainer)


def _load_checkpoint_for_validation(checkpoint_path):
    try:
        return torch.load(
            checkpoint_path,
            map_location="cpu",
            weights_only=False,
        )
    except TypeError:
        # PyTorch versions before weights_only was added.
        return torch.load(checkpoint_path, map_location="cpu")


def _validate_resume_checkpoint(checkpoint_path, checkpoint_mode):
    path = pathlib.Path(checkpoint_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Checkpoint does not exist: {path}")
    try:
        checkpoint = _load_checkpoint_for_validation(path)
    except Exception as error:
        raise RuntimeError(f"Checkpoint is not readable: {path}") from error

    required_keys = {"state_dict", "epoch", "global_step", "loops"}
    missing_keys = sorted(required_keys.difference(checkpoint))
    if missing_keys:
        raise ValueError(
            f"Checkpoint {path} is missing required keys: {missing_keys}"
        )

    global_step = int(checkpoint["global_step"])
    epoch = int(checkpoint["epoch"])
    if checkpoint_mode == "stage-zero":
        if global_step != 0:
            raise ValueError(
                "A stage-zero restart requires global_step=0, but "
                f"{path} has global_step={global_step}"
            )
    elif checkpoint_mode == "resume":
        optimizer_states = checkpoint.get("optimizer_states")
        if global_step <= 0:
            raise ValueError(
                "A true resume requires global_step>0. This checkpoint is "
                "a restart point, not a progress checkpoint: "
                f"{path}"
            )
        if not optimizer_states:
            raise ValueError(
                "A true resume requires optimizer state, but none was found "
                f"in {path}"
            )
        if "lr_schedulers" not in checkpoint:
            raise ValueError(
                f"A true resume requires lr_schedulers state: {path}"
            )
        if "audattn_amp_state_v1" not in checkpoint:
            raise ValueError(
                "A true resume requires audattn_amp_state_v1 so overflow "
                f"limits continue across jobs: {path}"
            )
        if "audattn_rng_state_v1" not in checkpoint:
            raise ValueError(
                "A true resume requires audattn_rng_state_v1 so stochastic "
                f"state continues across jobs: {path}"
            )
        amp_state = checkpoint["audattn_amp_state_v1"]
        amp_required = {
            "total_optimizer_attempts",
            "successful_optimizer_steps",
            "total_overflows",
        }
        amp_missing = sorted(amp_required.difference(amp_state))
        if amp_missing:
            raise ValueError(
                "Resume checkpoint has incomplete AMP accounting: "
                f"missing={amp_missing}, path={path}"
            )
        attempts = int(amp_state["total_optimizer_attempts"])
        successful = int(amp_state["successful_optimizer_steps"])
        overflows = int(amp_state["total_overflows"])
        if min(attempts, successful, overflows) < 0:
            raise ValueError(
                f"Resume checkpoint has negative AMP counters: {path}"
            )
        if successful + overflows != attempts:
            raise ValueError(
                "Resume checkpoint has inconsistent AMP accounting: "
                f"successful={successful}, overflows={overflows}, "
                f"attempts={attempts}, path={path}"
            )
        rng_state = checkpoint["audattn_rng_state_v1"]
        rng_required = {"python", "numpy", "torch_cpu", "torch_cuda"}
        rng_missing = sorted(rng_required.difference(rng_state))
        if rng_missing:
            raise ValueError(
                "Resume checkpoint has incomplete RNG state: "
                f"missing={rng_missing}, path={path}"
            )
        scaler_state = checkpoint.get("MixedPrecision")
        if scaler_state is None:
            scaler_state = checkpoint.get("native_amp_scaling_state")
        if not scaler_state:
            raise ValueError(
                "A 16-mixed resume requires saved GradScaler state, but "
                f"none was found in {path}"
            )
        scaler_scale = float(scaler_state.get("scale", 0.0))
        if not scaler_scale > 0 or not torch.isfinite(
            torch.tensor(scaler_scale)
        ):
            raise ValueError(
                f"Resume checkpoint has invalid GradScaler scale: {path}"
            )
        run_metadata = checkpoint.get("audattn_run_metadata_v1")
        expected_run_id = os.environ.get("AUDATTN_RUN_ID")
        expected_source = os.environ.get("AUDATTN_SOURCE_SHA256")
        expected_config = os.environ.get("AUDATTN_CONFIG_SHA256")
        if not all((expected_run_id, expected_source, expected_config)):
            raise RuntimeError(
                "A true resume requires AUDATTN_RUN_ID, "
                "AUDATTN_SOURCE_SHA256, and AUDATTN_CONFIG_SHA256"
            )
        if not run_metadata:
            raise ValueError(f"Resume checkpoint has no run metadata: {path}")
        expected_metadata = {
            "run_id": expected_run_id,
            "source_semantic_sha256": expected_source,
            "config_sha256": expected_config,
        }
        mismatches = {
            key: (run_metadata.get(key), expected)
            for key, expected in expected_metadata.items()
            if expected is not None and run_metadata.get(key) != expected
        }
        if mismatches:
            raise ValueError(
                "Resume checkpoint belongs to a different frozen run: "
                f"{mismatches}"
            )

        def _assert_finite(value, name):
            if isinstance(value, torch.Tensor):
                if value.is_floating_point() and not torch.isfinite(value).all():
                    raise ValueError(
                        f"Non-finite tensor in checkpoint at {name}: {path}"
                    )
            elif isinstance(value, dict):
                for key, item in value.items():
                    _assert_finite(item, f"{name}.{key}")
            elif isinstance(value, (list, tuple)):
                for index, item in enumerate(value):
                    _assert_finite(item, f"{name}[{index}]")

        _assert_finite(checkpoint["state_dict"], "state_dict")
        _assert_finite(optimizer_states, "optimizer_states")
    else:
        raise ValueError(f"Unsupported checkpoint mode: {checkpoint_mode}")

    print(
        "Validated checkpoint: "
        f"path={path}, mode={checkpoint_mode}, epoch={epoch}, "
        f"global_step={global_step}"
    )
    return path


def run_train(args):
    seed_everything(args.random_seed, workers=True)

    if args.config != "":
        config_path = args.config

    else:
        with open(args.config_list, 'rb') as f:
            model_config = pickle.load(f)
        config_path = str(model_config[args.job_id])

    print(config_path)

    if (config_path.endswith(".json")):
        with open(config_path, 'r') as file:
            config = json.load(file)
    elif (config_path.endswith(".yml")) or (config_path.endswith(".yaml")):
        config = yaml.load(open(config_path, 'r'), Loader=yaml.FullLoader)
    else:
        print("config file type not supported")
        return

    config['corpus']['clean_percentage'] = args.clean_percentage
    model_name = config['model_name']

    config['num_workers'] = args.n_jobs
    config['ngpus'] = args.gpus
    if args.gpus > 0:
        config['hparas']['batch_size'] = config['hparas']['batch_size'] // args.gpus

    configured_epochs = int(config['hparas']['epochs'])
    fit_max_epochs = (
        configured_epochs
        if args.fit_max_epochs is None
        else int(args.fit_max_epochs)
    )
    if not 1 <= fit_max_epochs <= configured_epochs:
        raise ValueError(
            "--fit_max_epochs must be between 1 and the frozen config's "
            f"hparas.epochs={configured_epochs}; got {fit_max_epochs}"
        )
    final_checkpoint_path = None
    if args.final_checkpoint_path is not None:
        final_checkpoint_path = pathlib.Path(
            args.final_checkpoint_path
        ).expanduser().resolve()
        if final_checkpoint_path.exists():
            raise FileExistsError(
                "Refusing to overwrite explicit final checkpoint: "
                f"{final_checkpoint_path}"
            )

    config_path = pathlib.Path(config_path)
    checkpoint_dir = args.exp_dir / f"{config_path.stem}/checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    if "saddler" in config_path.stem:
        try:
            from src.saddler_w_gains_lightning import SaddlerBackBoneModule
        except ModuleNotFoundError as error:
            raise ModuleNotFoundError(
                "This checkout does not include src/saddler_w_gains_lightning.py; "
                "use a binaural-attention config or restore that optional module."
            ) from error
        module = SaddlerBackBoneModule
    else:
        module = BinauralAttentionModule

    ckpt_path = None 
    if args.resume_training:
        if 'learned_gains' in config_path.stem and args.ckpt_path == '':
            model = module(config)
            init_ckpt_path = args.init_ckpt_path
            state_dict = torch.load(init_ckpt_path)['state_dict']
            # update state dict so saved weights are loaded correctly
            new_state_dict = {}
            for key, param in state_dict.items():
                new_key = key.replace('_orig_mod.', '_orig_mod.backbone.')
                new_state_dict[key] = param
                new_state_dict[new_key] = param
            # init weights to model
            model.load_state_dict(new_state_dict, strict=False)
            print('Initialized learned gains from checkpoint: ', init_ckpt_path)
        else:
            if args.ckpt_path == '':
                raise ValueError(
                    "--resume_training requires an explicit --ckpt_path. "
                    "Automatic last/ctime checkpoint selection is disabled "
                    "to prevent an accidental stage-0 restart."
                )
            ckpt_path = _validate_resume_checkpoint(
                args.ckpt_path,
                args.checkpoint_mode,
            )
            # Trainer restores model, optimizer, scheduler, epoch, and step.
            model = module(config)
        print('Resuming training from checkpoint: ', ckpt_path)
    else:
        model = module(config)

    callbacks = []

    if (
        config['hparas'].get('save_stage_zero', False)
        and not args.resume_training
    ):
        callbacks.append(
            StageZeroCheckpoint(checkpoint_dir / "stage-0.ckpt")
        )

    checkpoint_every_n_epochs = config['hparas'].get(
        'checkpoint_every_n_epochs', 0
    )
    if checkpoint_every_n_epochs:
        callbacks.append(ModelCheckpoint(
            checkpoint_dir,
            filename="stage-{epoch:02d}-{step}",
            every_n_epochs=checkpoint_every_n_epochs,
            save_top_k=-1,
            save_last=False,
            save_on_train_epoch_end=False,
            verbose=True,
        ))

    checkpoint_every_n_train_steps = config['hparas'].get(
        'checkpoint_every_n_train_steps', 0
    )
    if checkpoint_every_n_train_steps:
        callbacks.append(
            RollingStepCheckpoint(
                checkpoint_dir / "rolling.ckpt",
                checkpoint_every_n_train_steps,
            )
        )

    if isinstance(config['val_metric'], dict):
        for name, value in config['val_metric'].items():
            callbacks.append(ModelCheckpoint(
                checkpoint_dir,
                filename="{epoch}-{step}-best_"+name,
                monitor=value,
                mode="max",
                save_top_k=1,
                save_last=config['hparas'].get('save_last', False),
                # save_weights_only=True,
                verbose=True,
            ))

    else:
        callbacks.append(ModelCheckpoint(
            checkpoint_dir,
            monitor=f"{config['val_metric']}",
            mode="max" if 'acc' in config['val_metric'] else "min",
            save_top_k=1,
            save_last=config['hparas'].get('save_last', False),
            # save_weights_only=True,
            verbose=True,
        ))

    if config['hparas'].get('save_train_checkpoint', True):
        train_checkpoint = ModelCheckpoint(
            checkpoint_dir,
            monitor="train_loss",
            mode="min",
            save_top_k=1,
            # save_weights_only=True,
            verbose=True,
        )
        callbacks.append(train_checkpoint)

    early_stopping = config['hparas'].get('early_stopping')
    if early_stopping:
        callbacks.append(EarlyStopping(
            monitor=early_stopping.get('monitor', config['val_metric']),
            mode=early_stopping.get(
                'mode',
                'max' if 'acc' in config['val_metric'] else 'min',
            ),
            patience=early_stopping.get('patience', 3),
            min_delta=early_stopping.get('min_delta', 0.0),
            verbose=True,
        ))

    accelerator = "gpu" if args.gpus > 0 else "cpu"
    devices = args.gpus if args.gpus > 0 else 1

    trainer = Trainer(
        precision=args.precision,
        # precision=16,# 16 if 'binaural' in args.config else 32,
        default_root_dir=args.exp_dir / config_path.stem,
        max_epochs=fit_max_epochs,
       # log_every_n_steps = 10,
        # detect_anomaly=True,
        benchmark=not config.get('deterministic', False),
        deterministic=config.get('deterministic', False),
        reload_dataloaders_every_n_epochs=1,
        num_nodes=args.num_nodes,
        devices=devices,
        accelerator=accelerator,
        num_sanity_val_steps=config['hparas'].get(
            'num_sanity_val_steps', 2
        ),
        limit_val_batches=config['hparas'].get('limit_val_batches', 1.0),
        # resume_from_checkpoint = ckpt_path,  
        val_check_interval=config['hparas']['valid_step'],
        gradient_clip_val=config['hparas']['gradient_clip_val'],
        gradient_clip_algorithm=config['hparas'].get('gradient_clip_algorithm', 'value'),
        accumulate_grad_batches=config['hparas'].get('accumulate_grad_batches', 1), # default to 1 unless otherwise specified
        profiler=None,
        callbacks=callbacks)

    # add try except for compat with old models 
    # try: 
    #     # this is the right way to re-init in pytorch lighning versions 2.0+
    #     trainer.fit(model,  ckpt_path = ckpt_path if args.resume_training else None)
    # except KeyError as e:
    #     print(e)
    trainer.fit(
        model,
        ckpt_path=ckpt_path if args.resume_training else None,
    )
    if final_checkpoint_path is not None:
        final_checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = final_checkpoint_path.with_name(
            f".{final_checkpoint_path.name}.tmp"
        )
        if temporary_path.exists():
            raise FileExistsError(
                "Explicit final-checkpoint temporary path already exists: "
                f"{temporary_path}"
            )
        try:
            trainer.save_checkpoint(temporary_path)
            os.replace(temporary_path, final_checkpoint_path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
        print(
            "Saved explicit final checkpoint: "
            f"{final_checkpoint_path} (epoch={trainer.current_epoch}, "
            f"global_step={trainer.global_step}, "
            f"fit_max_epochs={fit_max_epochs})"
        )


def cli_main():
    parser = ArgumentParser()
    parser.add_argument('--config', default='', type=str, help='Path to experiment config.')
    parser.add_argument('--config_list', type=str, help='Path to list of config files.')
    parser.add_argument('--job_id', type=int, help='Index into the config list specifying which one to use.')
    parser.add_argument(
        "--exp_dir",
        default=pathlib.Path("./exp"),
        type=pathlib.Path,
        help="Directory to save checkpoints and logs to. (Default: './exp')",
    )
    parser.add_argument(
        "--ckpt_path",
        default='',
        type=str,
        help="Resume training from this checkpoint."
    )
    parser.add_argument(
        "--checkpoint_mode",
        default="resume",
        choices=["stage-zero", "resume"],
        help=(
            "Interpret an explicit checkpoint as either a step-zero restart "
            "or a true optimizer/loop-state resume."
        ),
    )
    parser.add_argument(
        "--num_nodes",
        default=1,
        type=int,
        help="Number of nodes to use for training. (Default: 1)",
    )
    parser.add_argument(
        "--precision",
        default="32-true",
        choices=["32-true", "16-mixed", "bf16-mixed"],
        help="Lightning numerical precision.",
    )
    parser.add_argument(
        "--gpus",
        default=4,
        type=int,
        help="Number of GPUs per node to use for training. (Default: 4)",
    )
    parser.add_argument(
    "--n_jobs",
    default=0,
    type=int,
    help="Number of CPUs for dataloader. (Default: 0)",
    )
    parser.add_argument(
        "--init_ckpt_path",
        default='',
        type=str,
        help="Path to initial checkpoint for model.",
    )
    parser.add_argument('--random_seed', default=0, type=int, help='Random seed for dataset.')
    parser.add_argument(
        '--resume_training',
        action='store_true',
        help='Resume full training state from a checkpoint.',
    )
    parser.add_argument(
        '--fit_max_epochs',
        default=None,
        type=int,
        help=(
            "Optional guarded Trainer max-epoch boundary. It may only lower "
            "the frozen config maximum and is used for staged pilot runs."
        ),
    )
    parser.add_argument(
        '--final_checkpoint_path',
        default=None,
        type=str,
        help=(
            "Write one explicit atomic checkpoint after Trainer.fit returns; "
            "the destination must not already exist."
        ),
    )
    parser.add_argument('--negative_elevs', default=False, help='Use negative elevations in training.')
    parser.add_argument('--clean_percentage', default=0.0, type=float, help='Percentage of clean speech data to use in training.')
    args = parser.parse_args()

    run_train(args)


if __name__ == "__main__":
    cli_main()

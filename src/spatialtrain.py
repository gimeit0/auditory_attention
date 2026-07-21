import pathlib
from argparse import ArgumentParser
import os
import yaml
import json
import pickle
import torch
from pytorch_lightning import Trainer, seed_everything
from pytorch_lightning.callbacks import EarlyStopping, ModelCheckpoint
from src.spatial_attn_lightning import BinauralAttentionModule #probably need to change this to the new name
# get nodename 
import socket

torch.set_float32_matmul_precision('medium')
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True

hostname = socket.gethostname()

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

    config_path = pathlib.Path(config_path)
    checkpoint_dir = args.exp_dir / f"{config_path.stem}/checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    ckpt_paths = sorted(checkpoint_dir.glob("*.ckpt"), key=os.path.getctime)

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
            if args.ckpt_path != '':
                ckpt_path = args.ckpt_path
            elif len(ckpt_paths) != 0:
                ckpt_path = ckpt_paths[-1]
            else:
                raise FileNotFoundError(
                    "--resume_training was requested, but no checkpoint "
                    f"was found in {checkpoint_dir}"
                )
            # Trainer restores model, optimizer, scheduler, epoch, and step.
            model = module(config)
        print('Resuming training from checkpoint: ', ckpt_path)
    else:
        model = module(config)

    callbacks = []

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
        max_epochs=config['hparas']['epochs'],
       # log_every_n_steps = 10,
        # detect_anomaly=True,
        benchmark=True,
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
    parser.add_argument('--negative_elevs', default=False, help='Use negative elevations in training.')
    parser.add_argument('--clean_percentage', default=0.0, type=float, help='Percentage of clean speech data to use in training.')
    args = parser.parse_args()

    run_train(args)


if __name__ == "__main__":
    cli_main()

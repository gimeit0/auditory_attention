#!/bin/bash
# 主实验: 多干扰面板 no_distractor / one / two / four / babble × 5 档 SNR。
# 600 target × (4 条件 × 5 SNR + 1) = 12,600 次前向。Mac CPU 约 23h, GPU 上几分钟到半小时。
#SBATCH -J audattn_multi
#SBATCH -p GPU-1
#SBATCH -N 1
#SBATCH -G 1
#SBATCH -t 24:00:00
#SBATCH -o reproduction/deployment/hakusan/logs/%x_%j.log
#SBATCH -e reproduction/deployment/hakusan/logs/%x_%j.log
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=s2510040@jaist.ac.jp

set -e
source $HOME/miniconda3/etc/profile.d/conda.sh
conda activate $HOME/miniconda3/envs/attn

cd $SLURM_SUBMIT_DIR
export CV_CLIPS=$SLURM_SUBMIT_DIR/cv_clips

echo "==== 节点: $(hostname) | 作业: $SLURM_JOB_ID ===="
python -c "import torch;print('CUDA:', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0))"

python -u -m reproduction.experiment_2_talker_count.scripts.snr_scan_multi \
    --out reproduction/experiment_2_talker_count/results/multi_talker_results.csv

echo "==== 判据: 每行随 SNR 上升 | 同一 SNR 下 one > two > four ≳ babble | 混淆反向 ===="

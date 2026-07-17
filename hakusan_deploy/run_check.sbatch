#!/bin/bash
# 闸门作业: GPU 等价性校验。失败 -> 非零退出 -> 挂在后面的作业被 SLURM 取消。
# QOS 限制单作业 CPU 数, 因此不写 -c(用默认 1 核)。
#SBATCH -J audattn_check
#SBATCH -p GPU-1
#SBATCH -N 1
#SBATCH -G 1
#SBATCH -t 01:00:00
#SBATCH -o hakusan_deploy/logs/%x_%j.log
#SBATCH -e hakusan_deploy/logs/%x_%j.log
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=s2510040@jaist.ac.jp

set -e
source $HOME/miniconda3/etc/profile.d/conda.sh
conda activate $HOME/miniconda3/envs/attn

cd $SLURM_SUBMIT_DIR
export CV_CLIPS=$SLURM_SUBMIT_DIR/cv_clips

echo "==== 节点: $(hostname) | 作业: $SLURM_JOB_ID ===="
nvidia-smi
python -u hakusan_deploy/check_hakusan.py

#!/bin/bash
# 交叉验证: 在 GPU 上复跑「同性单干扰」SNR 扫描, 结果应复现 Mac 上的 [26,35,46,55,63,88]%。
# 这是信任锚点——对上了才说明 GPU 管线可信。Mac 上跑了 6.5 小时, GPU 上几分钟。
#SBATCH -J audattn_repro
#SBATCH -p GPU-1
#SBATCH -N 1
#SBATCH -G 1
#SBATCH -t 08:00:00
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

python -u -m reproduction.experiment_1_gender.scripts.snr_scan \
    --dist_col same_dist_path \
    --out reproduction/experiment_1_gender/results/snr_scan_results_gpu.csv

echo "==== 判据: 6 档准确率应接近 Mac 的 [26, 35, 46, 55, 63, 88]% ===="

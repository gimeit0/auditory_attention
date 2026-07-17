#!/bin/bash
# 通用 GPU 作业模板。改最后的 python 命令, 然后: sbatch hakusan_deploy/run_gpu.sbatch
# 分区: GPU-1 = A40 ; 换 A100 用 -p GPU-1A
#SBATCH -J audattn
#SBATCH -p GPU-1
#SBATCH -N 1
#SBATCH -G 1
# 不写 -c: QOS 限制单作业 CPU 数, 写了会被拒
#SBATCH -o hakusan_deploy/logs/%x_%j.log
#SBATCH -e hakusan_deploy/logs/%x_%j.log
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=s2510040@jaist.ac.jp

source $HOME/miniconda3/etc/profile.d/conda.sh
conda activate $HOME/miniconda3/envs/attn

cd $SLURM_SUBMIT_DIR
export CV_CLIPS=$SLURM_SUBMIT_DIR/cv_clips        # 上传的 CV clips 子集

python -c "import torch;print('CUDA:', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no gpu')"

# ====== 在这里放实际命令 ======
# 例1: GPU 上复跑同性单干扰 SNR 扫描(Mac 上跑了 6.5h, GPU 几分钟)
#   python -u snr_scan.py --dist_col same_dist_path --out snr_scan_results.csv
# 例2: 异性
#   python -u snr_scan.py --dist_col diff_dist_path --out snr_scan_results_diff.csv
# 例3(待实现): 多干扰面板
#   python -u snr_scan_multi.py --conditions one,two,four,babble --out multi_talker_results.csv
echo "把上面的示例命令换成你要跑的任务"

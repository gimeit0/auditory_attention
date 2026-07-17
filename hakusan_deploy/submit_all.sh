#!/bin/bash
# 在【超算登录节点】的仓库根目录跑: bash hakusan_deploy/submit_all.sh
#
# 一次提交三个作业, 用 afterok 串成依赖链, 断网也照跑:
#     check  (闸门: CUDA + 权重 + demo about/above)
#       └─ afterok ─> repro (交叉验证: 同性单干扰扫描, 应复现 [26,35,46,55,63,88]%)
#                       └─ afterok ─> multi (主实验: 多干扰面板)
# 任一环节失败 -> 后面的作业不会跑(状态 DependencyNeverSatisfied), 不会烧掉 GPU 时间。
set -e

cd "$(dirname "$0")/.."          # 仓库根目录
mkdir -p hakusan_deploy/logs     # SLURM 不会自动建日志目录, 少了这步作业会秒挂

CHECK=$(sbatch --parsable hakusan_deploy/run_check.sbatch)
REPRO=$(sbatch --parsable --dependency=afterok:${CHECK} hakusan_deploy/run_repro.sbatch)
MULTI=$(sbatch --parsable --dependency=afterok:${REPRO} hakusan_deploy/run_multi.sbatch)

cat <<EOF

==== 已提交(依赖链) ====
  ${CHECK}  audattn_check   闸门: CUDA + 权重 + demo
  ${REPRO}  audattn_repro   交叉验证(依赖 ${CHECK})
  ${MULTI}  audattn_multi   多干扰面板(依赖 ${REPRO})

看状态:   squeue -u \$USER
看日志:   ls -lt hakusan_deploy/logs/ | head
          cat hakusan_deploy/logs/audattn_check_${CHECK}.log
产出:     snr_scan_results_gpu.csv   (交叉验证)
          multi_talker_results.csv   (主实验)
全部取消: scancel ${CHECK} ${REPRO} ${MULTI}
EOF

#!/bin/bash
# 在【本地 Mac】运行: 把 复现脚本 + checkpoint + demo + 用到的 CV clips 传到 HAKUSAN。
# 前提: 能 SSH 到 hakusan1(校网/VPN 内)。超算上的 conda 环境和官方仓库【已经建好】, 不用再传 src/config。
#
# 用法:  bash hakusan_deploy/upload_to_hakusan.sh
set -e

HAKUSAN_USER="s2510040"
HAKUSAN_HOST="hakusan1"
# 超算上官方仓库的位置(交接文档确认)
REMOTE_DIR="/home/${HAKUSAN_USER}/selective_listening_repro/code/auditory_attention"

LOCAL_DIR="/Users/gigi/projects/auditory_attention"
CV_CLIPS="/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en/clips"
LIST="${LOCAL_DIR}/hakusan_deploy/clips_list.txt"

cd "${LOCAL_DIR}"

echo "==== [1/4] 生成 clips 清单 ===="
python hakusan_deploy/make_clip_list.py --out "${LIST}"

echo
echo "==== [2/4] 传复现脚本 + 样本表 + 干扰池 + 部署套件 ===="
rsync -avz --progress \
  align_words.py build_pairs.py build_anchor_first.py build_distractor_pool.py \
  add_diff_distractor.py slice_stimuli.py snr_scan.py snr_scan_multi.py validate_model.py \
  run_demo_m1.py plot_fig2a.py plot_fig2b.py plot_fig2e.py \
  samples_expanded.csv distractor_pool.csv \
  hakusan_deploy \
  "${HAKUSAN_USER}@${HAKUSAN_HOST}:${REMOTE_DIR}/"

echo
echo "==== [3/4] 传用到的 CV clips (只传清单里的, 非 79GB 全量) ===="
rsync -avz --progress --files-from="${LIST}" \
  "${CV_CLIPS}/" \
  "${HAKUSAN_USER}@${HAKUSAN_HOST}:${REMOTE_DIR}/cv_clips/"

echo
echo "==== [4/4] 传 checkpoint(~754MB) + demo_stimuli ===="
rsync -avz --progress \
  attn_cue_models demo_stimuli \
  "${HAKUSAN_USER}@${HAKUSAN_HOST}:${REMOTE_DIR}/"

cat <<'EOF'

==== 完成 ====
在超算上跑之前, 先设一个环境变量指向上传的 clips(脚本会读它):
    export CV_CLIPS=$HOME/selective_listening_repro/code/auditory_attention/cv_clips
(已写进 run_gpu.sbatch, 批处理作业里不用手动设。)

下一步: GPU 节点上跑 demo 校验
    salloc -p GPU-1 -c 8 -G 1
    conda activate /home/s2510040/miniconda3/envs/attn
    cd ~/selective_listening_repro/code/auditory_attention
    python hakusan_deploy/check_hakusan.py       # 期望 about / above -> PASS
EOF

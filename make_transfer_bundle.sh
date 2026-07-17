#!/bin/bash
# 把「在 3070 笔记本上跑多话者实验」需要的全部东西, 集中到一个文件夹, 便于拷贝(U盘/网盘/scp)。
# 用法(Mac 仓库根目录):  bash make_transfer_bundle.sh
set -e

SRC="/Users/gigi/projects/auditory_attention"
CV="/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en/clips"
OUT="${SRC}/transfer_3070"

cd "${SRC}"
rm -rf "${OUT}"
mkdir -p "${OUT}/cv_clips"

echo "==== [1/5] 代码 ===="
mkdir -p "${OUT}/src" "${OUT}/config"
cp -R src/* "${OUT}/src/"
cp -R config/* "${OUT}/config/"
cp align_words.py slice_stimuli.py snr_scan.py snr_scan_multi.py \
   build_anchor_first.py build_distractor_pool.py add_diff_distractor.py \
   validate_model.py plot_fig2a.py plot_fig2b.py plot_fig2e.py "${OUT}/"
find "${OUT}/src" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo "==== [2/5] chcochleagram(纯 Python, 直接拷包) ===="
CHCOCH=$(python -c "import chcochleagram,os;print(os.path.dirname(chcochleagram.__file__))")
cp -R "${CHCOCH}" "${OUT}/chcochleagram"
find "${OUT}/chcochleagram" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo "==== [3/5] 样本表 + 干扰池 + 词表 ===="
cp samples_expanded.csv distractor_pool.csv cv_800_word_label_to_int_dict.pkl "${OUT}/"

echo "==== [4/5] checkpoint(719MB) + demo_stimuli ===="
cp -R attn_cue_models demo_stimuli "${OUT}/"

echo "==== [5/5] CV clips(2819 条, 约 120MB) ===="
n=0
while IFS= read -r f; do
  cp "${CV}/${f}" "${OUT}/cv_clips/" && n=$((n+1))
done < hakusan_deploy/clips_list.txt
echo "  拷贝了 ${n} 条"

cp 多话者复现_3070说明.md "${OUT}/" 2>/dev/null || true

echo
echo "==== 完成 ===="
du -sh "${OUT}"
echo "把整个 ${OUT} 文件夹拷到 Windows 笔记本, 然后照 多话者复现_3070说明.md 做。"

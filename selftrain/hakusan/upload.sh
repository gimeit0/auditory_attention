#!/bin/bash
# Run on the local Mac. Upload the Tier-0 code, manifests, and only the Common
# Voice clips referenced by the leak-free train/validation candidate manifests.
set -e

HAKUSAN_USER="s2510040"
HAKUSAN_HOST="hakusan1"
REMOTE_DIR="/home/${HAKUSAN_USER}/selective_listening_repro/code/auditory_attention"
LOCAL_DIR="/Users/gigi/projects/auditory_attention"
CV_DIR="/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en"
LIST="${LOCAL_DIR}/selftrain/hakusan/selftrain_clips_list.txt"

cd "${LOCAL_DIR}"

python -m selftrain.hakusan.make_clip_list --out "${LIST}"

ssh "${HAKUSAN_USER}@${HAKUSAN_HOST}" \
  "mkdir -p '${REMOTE_DIR}/cv_train/clips' '${REMOTE_DIR}/selftrain/artifacts' '${REMOTE_DIR}/selftrain/hakusan/logs'"

rsync -avR --info=progress2 \
  align_words.py \
  cv_800_word_label_to_int_dict.pkl \
  selftrain/__init__.py \
  selftrain/data/__init__.py \
  selftrain/data/diotic_attention.py \
  selftrain/scripts/__init__.py \
  selftrain/scripts/prepare_splits.py \
  selftrain/scripts/build_anchor_catalog.py \
  selftrain/scripts/check_readiness.py \
  selftrain/scripts/check_dataset.py \
  selftrain/configs/smoke.yaml \
  selftrain/configs/full.yaml \
  selftrain/hakusan/__init__.py \
  selftrain/hakusan/make_clip_list.py \
  selftrain/hakusan/run_alignment.sbatch \
  selftrain/hakusan/run_training.sbatch \
  selftrain/docs/训练模型_设计方案.md \
  src/audio_transforms.py \
  src/spatial_attn_lightning.py \
  src/spatialtrain.py \
  src/time_domain_cochleagram.py \
  "${HAKUSAN_USER}@${HAKUSAN_HOST}:${REMOTE_DIR}/"

rsync -av --info=progress2 \
  selftrain/artifacts/ \
  "${HAKUSAN_USER}@${HAKUSAN_HOST}:${REMOTE_DIR}/selftrain/artifacts/"

rsync -av --partial --info=progress2 --files-from="${LIST}" \
  "${CV_DIR}/" \
  "${HAKUSAN_USER}@${HAKUSAN_HOST}:${REMOTE_DIR}/cv_train/"

echo "Upload complete."
echo "Next: ssh ${HAKUSAN_USER}@${HAKUSAN_HOST}"
echo "Then: cd ${REMOTE_DIR}"
echo "Then: sbatch selftrain/hakusan/run_alignment.sbatch"

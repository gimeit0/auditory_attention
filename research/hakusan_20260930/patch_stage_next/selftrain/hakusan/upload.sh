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
  "mkdir -p '${REMOTE_DIR}/cv_train/clips' '${REMOTE_DIR}/selftrain/artifacts/splits' '${REMOTE_DIR}/selftrain/hakusan/logs'"

rsync -avR --progress \
  align_words.py \
  cv_800_word_label_to_int_dict.pkl \
  selftrain/__init__.py \
  selftrain/data/__init__.py \
  selftrain/data/anchor_index.py \
  selftrain/data/diotic_attention.py \
  selftrain/scripts/__init__.py \
  selftrain/scripts/prepare_splits.py \
  selftrain/scripts/build_anchor_catalog.py \
  selftrain/scripts/check_readiness.py \
  selftrain/scripts/check_dataset.py \
  selftrain/scripts/check_diag_stage.py \
  selftrain/scripts/build_cue_control_manifest.py \
  selftrain/scripts/eval_cue_controls.py \
  selftrain/scripts/check_training_safety.py \
  selftrain/scripts/check_training_phase.py \
  selftrain/scripts/check_cue_control_release.py \
  selftrain/scripts/finalize_training_phase.py \
  selftrain/scripts/full_started.py \
  selftrain/scripts/build_full_pilot_eval_bank.py \
  selftrain/scripts/eval_full_pilot.py \
  selftrain/scripts/pilot_release.py \
  selftrain/scripts/run_integrity.py \
  selftrain/scripts/test_run_integrity.py \
  selftrain/scripts/test_training_phase.py \
  selftrain/scripts/test_cue_control_release.py \
  selftrain/scripts/test_finalize_training_phase.py \
  selftrain/scripts/test_full_started.py \
  selftrain/scripts/test_full_pilot_eval.py \
  selftrain/scripts/test_pilot_release.py \
  selftrain/configs/smoke.yaml \
  selftrain/configs/full.yaml \
  selftrain/configs/diag_clean.yaml \
  selftrain/configs/diag_1dist_p10db.yaml \
  selftrain/configs/diag_1dist_0db.yaml \
  selftrain/configs/diag_1dist_0db_20ep.yaml \
  selftrain/hakusan/__init__.py \
  selftrain/hakusan/make_clip_list.py \
  selftrain/hakusan/fork_resume_checkpoint.py \
  selftrain/hakusan/checkpoint_reference.py \
  selftrain/hakusan/test_fork_resume_checkpoint.py \
  selftrain/hakusan/test_checkpoint_reference.py \
  selftrain/hakusan/run_alignment.sbatch \
  selftrain/hakusan/run_preflight.sbatch \
  selftrain/hakusan/run_numerics_preflight.sbatch \
  selftrain/hakusan/run_training.sbatch \
  selftrain/hakusan/run_full_pilot_eval.sbatch \
  selftrain/hakusan/run_diag.sbatch \
  selftrain/hakusan/run_diag_1dist_p10db.sbatch \
  selftrain/hakusan/run_diag_1dist_0db.sbatch \
  selftrain/hakusan/run_diag_1dist_0db_20ep.sbatch \
  selftrain/hakusan/run_cue_controls_551219.sbatch \
  selftrain/hakusan/submit_training.sh \
  selftrain/docs/训练模型_设计方案.md \
  selftrain/full_scale_task2_2026-07-23/README.md \
  selftrain/full_scale_task2_2026-07-23/experiment_manifest.yaml \
  selftrain/full_scale_task2_2026-07-23/docs/说明文档_2026-07-23.md \
  selftrain/full_scale_task2_2026-07-23/docs/全量实验方案书_2026-07-23.md \
  selftrain/full_scale_task2_2026-07-23/docs/HAKUSAN运行说明_2026-07-23.md \
  selftrain/full_scale_task2_2026-07-23/records/运行记录模板.md \
  selftrain/full_scale_task2_2026-07-23/results/.gitkeep \
  src/audio_transforms.py \
  src/audio_attention_transforms.py \
  src/custom_modules.py \
  src/spatial_attn_architecture.py \
  src/spatial_attn_lightning.py \
  src/spatialtrain.py \
  src/time_domain_cochleagram.py \
  src/layers/conv2d_same.py \
  src/layers/padding.py \
  corpus/binaural_attention_h5.py \
  "${HAKUSAN_USER}@${HAKUSAN_HOST}:${REMOTE_DIR}/"

# Generated anchors are authoritative on HAKUSAN once alignment has started.
# Upload only split definitions so stale local JSONL files cannot overwrite
# resumable remote alignment progress.
rsync -av --progress \
  selftrain/artifacts/splits/ \
  "${HAKUSAN_USER}@${HAKUSAN_HOST}:${REMOTE_DIR}/selftrain/artifacts/splits/"

rsync -av --partial --progress --files-from="${LIST}" \
  "${CV_DIR}/" \
  "${HAKUSAN_USER}@${HAKUSAN_HOST}:${REMOTE_DIR}/cv_train/"

echo "Upload complete."
echo "Next: ssh ${HAKUSAN_USER}@${HAKUSAN_HOST}"
echo "Then: cd ${REMOTE_DIR}"
echo "Then: run local/import checks and submit run_numerics_preflight.sbatch"

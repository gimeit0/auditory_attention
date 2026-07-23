"""
任务 B: 词级筛选 + 切片。把 alignments.json 里的 target 锚点切成 2.5s 片段刺激。

样本定义(已与用户确认):
  - 一个 trial = (一个 pair, 该 pair 的 target 录音上的一个锚点)。
    target 录音必须有锚点(要报的中间词);若一条 target 录音有多个锚点,每个锚点各成一个 trial。
  - cue 不要求有表内锚点: 只是指示目标说话人。取 cue 录音【中心 2.5s】,
    要求其中心词 != target 锚点词(论文约束 3: cue/target 中间词不同)。
  - distractor(same/diff)也不要求锚点: 取【中心 2.5s】(论文背景是随机裁剪,这里用
    中心裁剪保证确定性、避开边界静音)。Task C 再做混音/SNR/RMS 归一。

切片规格(与 demo_stimuli 完全一致):
  - 44100 Hz, 2.5s = 110250 样本。模型 config 里 center_crop:True 会内部再取中间 2s,
    所以这里只产 2.5s(就是喂模型的格式),不手切 2s。
  - 锚点的 1.25s 余量约束(任务 A)已保证 target 的 2.5s 窗口落在录音内。
  - 本步【不做】RMS 归一/混音(留给 Task C)。

输出:
  - eval_stimuli/<trial_id>/{target,cue,same_dist,diff_dist}.wav  (2.5s @ 44100, 原始幅度)
  - eval_manifest.csv  每行一个 trial,记录词/label/来源/切片中心等

用法:
    python slice_stimuli.py
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
import soundfile as sf
import torch
import torchaudio

SR = 44100
SEG_S = 2.5
SEG_N = int(SR * SEG_S)          # 110250
HALF_N = SEG_N // 2              # 55125


def load_44k(mp3_path):
    """解码 mp3 -> 单声道 float32 -> 重采样到 44100。返回 np.float32 [N]。"""
    w, sr = sf.read(mp3_path, dtype="float32")
    if w.ndim == 2:
        w = w.mean(axis=1)
    wav = torch.from_numpy(w).unsqueeze(0)
    wav44 = torchaudio.functional.resample(wav, sr, SR)
    return wav44.squeeze(0).numpy()


def slice_centered(wav, center_s):
    """以 center_s(秒)为中心切 2.5s。返回 None 表示越界。"""
    c = int(round(center_s * SR))
    start = c - HALF_N
    end = start + SEG_N
    if start < 0 or end > len(wav):
        return None
    return wav[start:end]


def slice_middle(wav):
    """中心裁剪 2.5s(用于 cue/distractor)。返回 None 表示录音不足 2.5s。"""
    if len(wav) < SEG_N:
        return None
    start = (len(wav) - SEG_N) // 2
    return wav[start:start + SEG_N]


def middle_word(align_entry):
    """录音中心 dur/2 处跨越的已对齐词的 norm;找不到返回 None。"""
    if not align_entry or "words" not in align_entry:
        return None
    mid = align_entry["duration_s"] / 2.0
    for w in align_entry["words"]:
        if w["aligned"] and w["start_s"] <= mid < w["end_s"]:
            return w["norm"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pairs", default="reproduction/experiment_1_gender/archive/pairs_test.csv"
    )
    ap.add_argument(
        "--align", default="reproduction/experiment_1_gender/archive/alignments.json"
    )
    ap.add_argument("--cv_dir", default="/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en")
    ap.add_argument(
        "--out_dir", default="reproduction/experiment_1_gender/archive/eval_stimuli"
    )
    ap.add_argument(
        "--manifest", default="reproduction/experiment_1_gender/archive/eval_manifest.csv"
    )
    args = ap.parse_args()

    clips_dir = os.path.join(args.cv_dir, "clips")
    with open(args.align) as f:
        align = json.load(f)
    pairs = pd.read_csv(args.pairs, dtype=str, keep_default_na=False)
    os.makedirs(args.out_dir, exist_ok=True)

    rows = []
    n_trials = 0
    skip_cue_short = skip_cue_collision = skip_dist_short = 0
    wav_cache = {}

    def get_wav(path):
        if path not in wav_cache:
            wav_cache[path] = load_44k(os.path.join(clips_dir, path))
        return wav_cache[path]

    for pi, r in pairs.iterrows():
        tp = r["target_path"]
        tgt_anchors = align.get(tp, {}).get("anchor_candidates", [])
        if not tgt_anchors:
            continue

        # cue: 中心 2.5s + 中心词(用于 != target 词检查)
        cue_entry = align.get(r["cue_path"], {})
        cue_mid_word = middle_word(cue_entry)
        cue_wav = get_wav(r["cue_path"])
        cue_seg = slice_middle(cue_wav)

        # distractor 中心 2.5s
        sd_seg = slice_middle(get_wav(r["same_dist_path"]))
        dd_seg = slice_middle(get_wav(r["diff_dist_path"]))

        if cue_seg is None:
            skip_cue_short += 1
            continue
        if sd_seg is None or dd_seg is None:
            skip_dist_short += 1
            continue

        tgt_wav = get_wav(tp)
        for ai, a in enumerate(tgt_anchors):
            if cue_mid_word is not None and cue_mid_word == a["norm"]:
                skip_cue_collision += 1
                continue
            tgt_seg = slice_centered(tgt_wav, a["anchor_center_s"])
            if tgt_seg is None:
                continue  # 理论上不会(余量约束已保证),保险起见

            trial_id = f"trial_{pi:03d}_{ai}"
            tdir = os.path.join(args.out_dir, trial_id)
            os.makedirs(tdir, exist_ok=True)
            sf.write(os.path.join(tdir, "target.wav"), tgt_seg, SR)
            sf.write(os.path.join(tdir, "cue.wav"), cue_seg, SR)
            sf.write(os.path.join(tdir, "same_dist.wav"), sd_seg, SR)
            sf.write(os.path.join(tdir, "diff_dist.wav"), dd_seg, SR)

            rows.append({
                "trial_id": trial_id,
                "target_gender": r["target_gender"],
                "target_word": a["word"],
                "target_norm": a["norm"],
                "target_label": a["label"],
                "target_center_s": a["anchor_center_s"],
                "target_path": tp,
                "target_sentence": r["target_sentence"],
                "cue_path": r["cue_path"],
                "cue_mid_word": cue_mid_word,
                "same_dist_path": r["same_dist_path"],
                "same_dist_sentence": r["same_dist_sentence"],
                "diff_dist_path": r["diff_dist_path"],
                "diff_dist_sentence": r["diff_dist_sentence"],
            })
            n_trials += 1

    out_df = pd.DataFrame(rows)
    out_df.to_csv(args.manifest, index=False)

    # ---- 自检 ----
    print(f"=== 自检 ===")
    print(f"生成 trial 数:            {n_trials}")
    print(f"涉及 target 录音数:       {out_df['target_path'].nunique() if n_trials else 0}")
    print(f"跳过(cue 不足 2.5s):      {skip_cue_short} 个 pair")
    print(f"跳过(distractor<2.5s):    {skip_dist_short} 个 pair")
    print(f"跳过(cue 词==target 词):  {skip_cue_collision} 个锚点")
    if n_trials:
        print(f"target 性别分布:          {out_df['target_gender'].value_counts().to_dict()}")
        print(f"target 词去重数:          {out_df['target_norm'].nunique()}")
        # 校验切片长度
        import glob
        sample = glob.glob(os.path.join(args.out_dir, '*', 'target.wav'))[0]
        w, sr = sf.read(sample)
        print(f"切片校验({os.path.basename(os.path.dirname(sample))}/target.wav): "
              f"{len(w)} 样本 @ {sr} = {len(w)/sr:.3f}s (应为 110250 @ 44100 = 2.500s)")
    print(f"\n已写出: {args.manifest} + {args.out_dir}/<trial_id>/*.wav")


if __name__ == "__main__":
    main()

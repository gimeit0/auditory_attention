"""
双耳分听决定性验证 —— 同一说话人条件(会议要求的真实条件)。

demo 单例(dichotic_probe.py)有混淆:cue 说话人 ≠ 目标耳内容说话人,gain 谱不匹配会产生
伪影(女声 cue 施到男声内容 -> 报出无关词 football)。真实双耳分听是【左右耳同一说话人】,
不存在该混淆。本脚本用同说话人多录音直接测:

  某说话人有录音 A(中间词 W_A)、B(中间词 W_B),W_A≠W_B,均在 800 词表。
  左耳 = A(切在其中间词), 右耳 = B, cue = 同说话人第三条录音(切中段)。
  说话人处处相同 => cue 只能靠【耳朵位置】区分目标。
    cue 放左耳 -> 期望报 W_A ; cue 放右耳 -> 期望报 W_B
  左右分配再互换一次,抵消耳偏。

判据:预测==被 cue 那只耳的中间词 = 命中(跟随耳朵)。
     预测==对侧耳的中间词      = 耳混淆(路由失败的主要错误类型)。
若命中率显著高于耳混淆率 => 单耳 cue 能路由目标耳,双耳分听方案可行。

用法: PYTHONPATH=. python reproduction/dichotic_probe_samespeaker.py [--speakers 30]
"""
import scipy.signal
if not hasattr(scipy.signal, "hann"):
    scipy.signal.hann = scipy.signal.windows.hann

import sys
import argparse
import pickle
from pathlib import Path


def _find_repo(start):
    """向上找 repo 根(含 src/ 与 cv_800_word_label_to_int_dict.pkl),不依赖脚本所在深度。"""
    for cand in [start.resolve(), *start.resolve().parents]:
        if (cand / "cv_800_word_label_to_int_dict.pkl").exists() and (cand / "src").is_dir():
            return cand
    raise SystemExit("找不到 repo 根(需含 src/ 与 cv_800_word_label_to_int_dict.pkl)")


REPO = _find_repo(Path(__file__))
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd
import torch
import yaml

_torch_orig_load = torch.load
def _torch_load_full(*a, **k):
    k["weights_only"] = False
    return _torch_orig_load(*a, **k)
torch.load = _torch_load_full

from src.spatial_attn_lightning import BinauralAttentionModule
from slice_stimuli import load_44k, slice_centered, slice_middle

DEVICE = "cpu"
RMS_LEVEL = 0.02
import os
CV_CLIPS = os.environ.get("CV_CLIPS", "/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en/clips")


def rms_norm(wav, level=RMS_LEVEL):
    wav = wav - wav.mean()
    r = np.sqrt((wav ** 2).mean())
    return wav * level / r if r > 0 else wav


def dichotic_mix(left_wav, right_wav):
    n = min(len(left_wav), len(right_wav))
    st = np.stack([rms_norm(left_wav[:n]), rms_norm(right_wav[:n])], axis=0)
    return torch.from_numpy(st).unsqueeze(0).float(), n


def cue_in_ear(cue_wav, ear, n):
    """Place a cue in one ear and preserve the model's global RMS=0.02 rule.

    A one-ear signal whose active channel has RMS 0.02 has global binaural RMS
    0.02/sqrt(2).  The published preprocessing normalizes over both binaural
    channels, so the active channel must be sqrt(2) louder here.
    """
    st = np.zeros((2, n), dtype=np.float32)
    st[ear] = rms_norm(cue_wav[:n])
    st = st - st.mean()
    global_rms = np.sqrt((st ** 2).mean())
    if global_rms > 0:
        st = st * RMS_LEVEL / global_rms
    return torch.from_numpy(st).unsqueeze(0).float()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speakers", type=int, default=30)
    ap.add_argument("--samples", default=REPO / "reproduction/experiment_1_gender/data/samples_expanded.csv")
    args = ap.parse_args()

    cfg = yaml.load(open(REPO / "config/binaural_attn/word_task_v10_main_feature_gain_config.yaml"),
                    Loader=yaml.FullLoader)
    ckpt = sorted((REPO / "attn_cue_models/word_task_v10_main_feature_gain_config/checkpoints").glob("*.ckpt"))[0]
    print(f"checkpoint: {ckpt.name}")
    model = BinauralAttentionModule.load_from_checkpoint(
        checkpoint_path=str(ckpt), config=cfg, strict=False).eval().to(DEVICE)
    coch = model.coch_gram.to(DEVICE)

    with open(REPO / "cv_800_word_label_to_int_dict.pkl", "rb") as f:
        word_to_ix = pickle.load(f)
    ix_to_word = {v: k for k, v in word_to_ix.items()}

    df = pd.read_csv(args.samples, dtype=str, keep_default_na=False)

    wav_cache = {}
    def get_wav(p):
        if p not in wav_cache:
            wav_cache[p] = load_44k(f"{CV_CLIPS}/{p}")
        return wav_cache[p]

    def predict_cg(cue_t, mix_cg):
        cue_cg, _ = coch(cue_t.to(DEVICE), None)
        with torch.no_grad():
            ix = model(cue_cg, mix_cg).softmax(-1).argmax(dim=1).item()
        return ix_to_word[ix]

    hit = 0        # 预测 == 被cue耳的词
    ear_conf = 0   # 预测 == 对侧耳的词
    other = 0      # 都不是
    right_hits = 0 # 右耳被cue且命中(看右耳优势/偏)
    right_trials = 0
    n_trials = 0
    done_speakers = 0

    for spk, sub in df.groupby("target_speaker"):
        # 取两条中间词不同的录音
        sub = sub.drop_duplicates("target_path")
        rows = []
        seen_words = set()
        for _, r in sub.iterrows():
            if r["target_norm"] not in seen_words:
                rows.append(r); seen_words.add(r["target_norm"])
            if len(rows) == 2:
                break
        if len(rows) < 2:
            continue
        rA, rB = rows[0], rows[1]
        # cue: 同说话人第三条录音,且不等于 A/B 的录音
        cue_path = rA["cue_path"]
        if cue_path in (rA["target_path"], rB["target_path"]):
            cue_path = rB["cue_path"]
        if cue_path in (rA["target_path"], rB["target_path"]):
            continue

        wA = slice_centered(get_wav(rA["target_path"]), float(rA["target_center_s"]))
        wB = slice_centered(get_wav(rB["target_path"]), float(rB["target_center_s"]))
        wcue = slice_middle(get_wav(cue_path))
        if wA is None or wB is None or wcue is None:
            continue
        WA, WB = rA["target_norm"], rB["target_norm"]

        # 两种左右分配 × cue 两只耳
        for left_wav, right_wav, WL, WR in [(wA, wB, WA, WB), (wB, wA, WB, WA)]:
            mix, n = dichotic_mix(left_wav, right_wav)
            mix_cg, _ = coch(mix.to(DEVICE), None)   # 同混音只算一次
            for cue_ear, cued_word, other_word in [(0, WL, WR), (1, WR, WL)]:
                pred = predict_cg(cue_in_ear(wcue, cue_ear, n), mix_cg)
                n_trials += 1
                if pred == cued_word:
                    hit += 1
                    if cue_ear == 1:
                        right_hits += 1
                elif pred == other_word:
                    ear_conf += 1
                else:
                    other += 1
                if cue_ear == 1:
                    right_trials += 1

        done_speakers += 1
        if done_speakers >= args.speakers:
            break

    print(f"\n=== 双耳分听决定性验证(同说话人, {done_speakers} 说话人, {n_trials} trials)===")
    print(f"命中(跟随被cue耳)   : {hit}/{n_trials} = {hit/n_trials:.1%}")
    print(f"耳混淆(报成对侧耳)  : {ear_conf}/{n_trials} = {ear_conf/n_trials:.1%}")
    print(f"其他(两耳词都不是)  : {other}/{n_trials} = {other/n_trials:.1%}")
    print(f"随机基线(2选1中间词): ~50% (仅两耳词之间); 全词表随机 0.1%")
    if right_trials:
        left_trials = n_trials - right_trials
        left_hits = hit - right_hits
        print(f"右耳命中率 {right_hits}/{right_trials}={right_hits/right_trials:.1%}  "
              f"vs 左耳 {left_hits}/{left_trials}={left_hits/left_trials:.1%}  (看是否有耳偏)")
    print()
    if hit > ear_conf * 1.5 and hit / n_trials > 0.6:
        print("=> 命中显著高于耳混淆: 单耳 cue 能路由目标耳,双耳分听方案可行,可进入正式建集。")
    elif ear_conf >= hit:
        print("=> 耳混淆 >= 命中: 单耳 cue 未能路由耳朵,方案需重新设计(改 cue 喂法)。")
    else:
        print("=> 命中偏高但不压倒: 方案大概率可行,建议扩大样本 / 微调再确认。")


if __name__ == "__main__":
    main()

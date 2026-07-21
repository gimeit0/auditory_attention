"""
Fig 2a: speech-in-noise 中间词识别准确率 vs SNR(within-item,每点 600 样本)。

设计(已与用户确认):
  - 6 档 SNR: -9/-6/-3/0/+3/+inf dB。inf=无干扰(纯 target)。
  - same-sex 单干扰(Fig 2a 的那条线),diotic(单声道复制到左右)。
  - cue + mixture 都 RMS 归一到 0.02。
  - within-item: 同一批 600 样本(同一 target+cue+distractor),在 6 档 SNR 下各重混一次,
    每档都对全部 600 样本跑 checkpoint。消除 item 差异。

混音口径完全复用仓库 transforms(与 run_demo_m1.py 一致):
  CombineWithRandomDBSNR(low=high=snr) -> RMSNormalize(0.02) -> DuplicateChannel -> Unsqueeze
  foreground=target(signal), background=distractor(noise)。SNR 越高 distractor 越弱。
  inf 档: background=None -> 只剩 target,再归一/diotic。

切片复用 slice_stimuli(target 以 anchor 中心切 2.5s;cue/distractor 中心裁剪 2.5s)。

评分:
  - exact   = 预测词 == target 锚点词("中间词识别准确率",主指标)
  - lenient = 预测词 ∈ target 句中所有表内词(论文宽松口径,参考)

输出: 每档 6 个准确率数字 + snr_scan_results.csv(每样本每档预测,供画图)。

用法:
    python snr_scan.py --samples samples_expanded.csv --out snr_scan_results.csv
"""
import scipy.signal
if not hasattr(scipy.signal, "hann"):
    scipy.signal.hann = scipy.signal.windows.hann

import argparse
import pickle
from pathlib import Path

import pandas as pd
import torch
import yaml

_torch_orig_load = torch.load
def _torch_load_full(*a, **k):
    k["weights_only"] = False
    return _torch_orig_load(*a, **k)
torch.load = _torch_load_full

from src.spatial_attn_lightning import BinauralAttentionModule
import src.audio_transforms as at
from align_words import normalize_token
from slice_stimuli import load_44k, slice_centered, slice_middle, SR

import os

# Mac 上无 CUDA -> cpu;HAKUSAN GPU 节点上自动切 cuda
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
REPO = Path(__file__).resolve().parents[3]
EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
SNRS = [-9, -6, -3, 0, 3, "inf"]            # 从低到高;inf 最易
# 超算上用 CV_CLIPS 环境变量指到上传的 clips 子集目录
CV_CLIPS = os.environ.get(
    "CV_CLIPS", "/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en/clips")


def build_model():
    cfg = yaml.load(open(REPO / "config/binaural_attn/word_task_v10_main_feature_gain_config.yaml"),
                    Loader=yaml.FullLoader)
    ckpt = sorted((REPO / "attn_cue_models/word_task_v10_main_feature_gain_config/checkpoints").glob("*.ckpt"))[0]
    print(f"checkpoint: {ckpt.name}")
    model = BinauralAttentionModule.load_from_checkpoint(
        checkpoint_path=str(ckpt), config=cfg, strict=False).eval().to(DEVICE)
    return model, model.coch_gram.to(DEVICE)


def compose(snr):
    """snr 为数值 -> 固定 SNR 混音;snr=None -> 不混(inf/clean 或 cue)。"""
    snr_val = 0 if snr is None else snr
    return at.AudioCompose([
        at.AudioToTensor(),
        at.CombineWithRandomDBSNR(low_snr=snr_val, high_snr=snr_val),
        at.RMSNormalizeForegroundAndBackground(rms_level=0.02),
        at.DuplicateChannel(),
        at.UnsqueezeAudio(dim=0),
    ])


def to_dev(x):
    return x.to(DEVICE).float()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=EXPERIMENT_DIR / "data/samples_expanded.csv")
    ap.add_argument("--out", default=EXPERIMENT_DIR / "results/snr_scan_results.csv")
    ap.add_argument("--word_table", default="cv_800_word_label_to_int_dict.pkl")
    ap.add_argument("--dist_col", default="same_dist_path",
                    help="用哪一列做 distractor: same_dist_path(同性) 或 diff_dist_path(异性)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    with open(REPO / args.word_table, "rb") as f:
        word_to_ix = pickle.load(f)
    ix_to_word = {v: k for k, v in word_to_ix.items()}
    word_set = set(word_to_ix)

    model, coch = build_model()
    composers = {s: compose(None if s == "inf" else s) for s in SNRS}
    cue_compose = compose(None)

    df = pd.read_csv(args.samples, dtype=str, keep_default_na=False)
    if args.limit:
        df = df.iloc[:args.limit]
    n = len(df)
    print(f"样本数: {n} | SNR 档: {SNRS}")

    # 解码缓存(同一录音可能在多个样本里复用)
    wav_cache = {}
    def get_wav(path):
        if path not in wav_cache:
            wav_cache[path] = load_44k(f"{CV_CLIPS}/{path}")
        return wav_cache[path]

    rows = []
    correct_exact = {s: 0 for s in SNRS}
    correct_lenient = {s: 0 for s in SNRS}

    for i, (_, r) in enumerate(df.iterrows()):
        tgt = slice_centered(get_wav(r["target_path"]), float(r["target_center_s"]))
        cue = slice_middle(get_wav(r["cue_path"]))
        dist = slice_middle(get_wav(r[args.dist_col]))
        if tgt is None or cue is None or dist is None:
            continue  # 理论上不会(构建时已保证)

        # cue cochleagram 每样本算一次,跨 6 档复用
        cue_in, _ = cue_compose(cue, None)
        cue_cg, _ = coch(to_dev(cue_in), None)

        # target 句中表内词(lenient 评分用)
        in_table = set()
        for w in r["target_sentence"].split():
            for s in normalize_token(w):
                if s in word_set:
                    in_table.add(s)

        rec = {"trial_id": r["trial_id"], "target_norm": r["target_norm"]}
        for snr in SNRS:
            bg = None if snr == "inf" else dist
            mix, _ = composers[snr](tgt, bg)
            mix_cg, _ = coch(to_dev(mix), None)
            with torch.no_grad():
                pred_ix = model(cue_cg, mix_cg).softmax(-1).argmax(dim=1).item()
            pred = ix_to_word[pred_ix]
            is_exact = (pred == r["target_norm"])
            is_lenient = (pred in in_table)
            correct_exact[snr] += is_exact
            correct_lenient[snr] += is_lenient
            rec[f"pred_{snr}"] = pred
            rec[f"exact_{snr}"] = int(is_exact)
            rec[f"lenient_{snr}"] = int(is_lenient)
        rows.append(rec)

        if (i + 1) % 50 == 0 or i + 1 == n:
            print(f"  {i+1}/{n}")

    out_df = pd.DataFrame(rows)
    out_df.to_csv(args.out, index=False)
    m = len(out_df)

    print(f"\n=== Fig 2a: 中间词识别准确率 vs SNR (within-item, n={m}) ===")
    print(f"{'SNR(dB)':>8} | {'exact':>8} | {'lenient':>8}")
    for snr in SNRS:
        lab = "inf" if snr == "inf" else f"{snr:+d}"
        print(f"{lab:>8} | {correct_exact[snr]/m:>7.1%} | {correct_lenient[snr]/m:>7.1%}")
    # 单调性自检(exact)
    accs = [correct_exact[s] / m for s in SNRS]
    mono = all(accs[i] <= accs[i+1] + 1e-9 for i in range(len(accs)-1))
    print(f"\n趋势(exact 随 SNR): {'单调上升 ✓' if mono else '非严格单调(看整体方向)'}  "
          f"序列={[round(a,3) for a in accs]}")
    print(f"\n已写出: {args.out}")


if __name__ == "__main__":
    main()

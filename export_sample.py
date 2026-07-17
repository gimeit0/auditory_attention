"""
导出一个样本在 6 档 SNR 下的混音(各一个 wav),外加 cue 和纯目标作参照。
用和 snr_scan.py 完全相同的处理(切片->按SNR缩放干扰->相加->RMS归一0.02->diotic),
仅对所有导出文件施加【同一个增益】提到可听音量(不改变档间/档内相对响度,SNR不变)。

用法:
    python export_sample.py                 # 默认第0个样本, 同性干扰
    python export_sample.py --trial t0005 --dist diff
"""
import argparse
import os

import numpy as np
import pandas as pd
import soundfile as sf

import src.audio_transforms as at
from slice_stimuli import load_44k, slice_centered, slice_middle, SR

SNRS = [-9, -6, -3, 0, 3, "inf"]
CV_CLIPS = "/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en/clips"


def compose(snr):
    """与 snr_scan.py 一致: 固定 SNR 混音 -> RMS归一0.02 -> diotic。"""
    snr_val = 0 if snr == "inf" else snr
    return at.AudioCompose([
        at.AudioToTensor(),
        at.CombineWithRandomDBSNR(low_snr=snr_val, high_snr=snr_val),
        at.RMSNormalizeForegroundAndBackground(rms_level=0.02),
        at.DuplicateChannel(),
        at.UnsqueezeAudio(dim=0),
    ])


def to_mono(x):
    """compose 输出 [1,2,N] -> 单声道 numpy [N](diotic 两声道相同,取其一)。"""
    return x[0, 0].numpy().astype("float32")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="samples_expanded.csv")
    ap.add_argument("--trial", default=None, help="trial_id, 默认第0行")
    ap.add_argument("--dist", choices=["same", "diff"], default="same",
                    help="用同性(same)还是异性(diff)干扰")
    ap.add_argument("--out_dir", default="export_audio")
    args = ap.parse_args()

    df = pd.read_csv(args.samples, dtype=str, keep_default_na=False)
    row = df[df["trial_id"] == args.trial].iloc[0] if args.trial else df.iloc[0]
    dist_col = "same_dist_path" if args.dist == "same" else "diff_dist_path"
    dist_sent = "same_dist_sentence" if args.dist == "same" else "diff_dist_sentence"

    outdir = os.path.join(args.out_dir, f"{row['trial_id']}_{args.dist}")
    os.makedirs(outdir, exist_ok=True)

    # 切片(与推理同)
    tgt = slice_centered(load_44k(f"{CV_CLIPS}/{row['target_path']}"), float(row["target_center_s"]))
    cue = slice_middle(load_44k(f"{CV_CLIPS}/{row['cue_path']}"))
    dist = slice_middle(load_44k(f"{CV_CLIPS}/{row[dist_col]}"))

    # === 演示用归一化: 固定 target 电平, 按 SNR 缩放 distractor ===
    # (模型真正输入用的是"混音级 RMS 归一到0.02"; 那种方式下 target 随SNR变响、
    #  distractor 绝对音量几乎不变, 听感上不直观。这里为了让"干扰音量随SNR明显变化"
    #  改成固定target、缩放distractor —— SNR(target/distractor 比值)完全不变。)
    def dm(x):
        return x - np.mean(x)

    def rms(x):
        r = np.sqrt(np.mean(x ** 2))
        return r if r > 0 else 1.0

    LVL = 0.05
    t = dm(tgt); t = t * (LVL / rms(t))      # target 固定电平(所有档一致)
    d = dm(dist); d = d * (LVL / rms(d))     # distractor 先归一到同电平
    c = dm(cue); c = c * (LVL / rms(c))      # cue 固定电平

    signals = {"cue": c}
    for snr in SNRS:
        if snr == "inf":
            mix = t.copy()                   # 无干扰
        else:
            mix = t + d * (10.0 ** (-snr / 20.0))   # 干扰按 SNR 缩放, target 不变
        lab = "inf" if snr == "inf" else f"{snr:+d}dB"
        signals[f"mix_{lab}"] = mix
    signals["target_clean"] = t.copy()

    # 统一增益: 用全体峰值归到 0.9(保持所有相对响度, 仅整体放大到可听)
    peak = max(np.abs(s).max() for s in signals.values())
    gain = 0.9 / peak if peak > 0 else 1.0

    for name, s in signals.items():
        sf.write(os.path.join(outdir, f"{name}.wav"), s * gain, SR)

    print(f"=== 导出样本 {row['trial_id']} ({args.dist}-sex 干扰) ===")
    print(f"目标中间词: {row['target_norm']}")
    print(f"目标句   : {row['target_sentence']}")
    print(f"干扰句   : {row[dist_sent]}")
    print(f"统一增益 : x{gain:.1f} (仅提音量, 不改 SNR)")
    print(f"\n已导出到 {outdir}/ :")
    print("  cue.wav            (目标说话人提示音)")
    for snr in SNRS:
        lab = "inf" if snr == "inf" else f"{snr:+d}dB"
        note = "  <- 纯目标,无干扰" if snr == "inf" else ""
        print(f"  mix_{lab}.wav{' '*(8-len(lab))} (SNR={lab} 混音){note}")
    print("  target_clean.wav   (=mix_inf, 纯目标参照)")


if __name__ == "__main__":
    main()

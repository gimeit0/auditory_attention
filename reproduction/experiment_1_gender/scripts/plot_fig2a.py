"""
画 Fig 2a 复现图: 中间词识别准确率 vs SNR (exact)。
从 snr_scan_results.csv 直接重算每档准确率,风格尽量贴近论文 Fig 2a,便于并排对比。

用法:
    python plot_fig2a.py --results snr_scan_results.csv --out fig2a_reproduction.png
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

EXPERIMENT_DIR = Path(__file__).resolve().parents[1]

# 中文标题字体(macOS)
plt.rcParams["font.sans-serif"] = ["PingFang SC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

SNRS = ["-9", "-6", "-3", "0", "3", "inf"]
XLABELS = ["-9", "-6", "-3", "0", "+3", "+inf"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=EXPERIMENT_DIR / "results/snr_scan_results.csv")
    ap.add_argument("--out", default=EXPERIMENT_DIR / "figures/fig2a_reproduction.png")
    args = ap.parse_args()

    df = pd.read_csv(args.results)
    n = len(df)
    accs, ses = [], []
    for s in SNRS:
        p = df[f"exact_{s}"].mean()
        accs.append(p)
        ses.append(np.sqrt(p * (1 - p) / n))   # 二项标准误
    accs, ses = np.array(accs), np.array(ses)

    x = np.arange(len(SNRS))                    # 6 个等距类别位置
    fig, ax = plt.subplots(figsize=(6.0, 5.0), dpi=150)

    # 主线 + 数据点 + 误差棒(论文风格: 实线、圆点、细误差棒)
    ax.errorbar(x, accs, yerr=ses, color="#1f3b73", lw=2, marker="o",
                ms=8, mfc="#1f3b73", mec="white", mew=1.2, capsize=3,
                ecolor="#1f3b73", zorder=3)

    # 每个点标注数值
    for xi, a in zip(x, accs):
        ax.annotate(f"{a*100:.0f}%", (xi, a), textcoords="offset points",
                    xytext=(0, 10), ha="center", fontsize=9, color="#1f3b73")

    # inf 档单独标在最右: 在 +3 与 +inf 之间画一条竖虚线分隔
    ax.axvline(x=4.5, color="0.6", ls="--", lw=1, zorder=1)
    ax.text(5, 0.04, "No distractor", ha="center", va="bottom", fontsize=8, color="0.4")

    # 随机基线(1/800)
    ax.axhline(y=1/800, color="0.7", ls=":", lw=1, zorder=1)
    ax.text(0.02, 1/800 + 0.015, "Chance level (1/800)", fontsize=7.5, color="0.5",
            transform=ax.get_yaxis_transform())

    ax.set_xticks(x)
    ax.set_xticklabels(XLABELS)
    ax.set_xlabel("SNR (dB)", fontsize=11)
    ax.set_ylabel("Middle-word recognition accuracy", fontsize=11)
    ax.set_ylim(0, 1.0)
    ax.set_yticks(np.arange(0, 1.01, 0.2))
    ax.set_xlim(-0.4, 5.4)
    ax.grid(axis="y", color="0.9", lw=0.8)
    ax.set_axisbelow(True)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)

    ax.set_title("Reproduction of Fig 2a: Middle-word recognition accuracy vs SNR\n"
                 "(same-sex talker distractor, diotic, N=599)",
                 fontsize=10.5, pad=12)

    fig.tight_layout()
    fig.savefig(args.out, bbox_inches="tight")
    print(f"已写出: {args.out}")
    print("每档准确率(exact):")
    for lab, a, se in zip(XLABELS, accs, ses):
        print(f"  {lab:>5} dB: {a:.1%}  (±{se:.1%})")


if __name__ == "__main__":
    main()

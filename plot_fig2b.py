"""
画 Fig 2b 复现图: 同性 vs 异性 distractor 两条线 (中间词识别准确率 vs SNR, exact)。
从 snr_scan_results.csv(同性) 和 snr_scan_results_diff.csv(异性) 直接重算每档准确率。

用法:
    python plot_fig2b.py
"""
import argparse

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SNRS = ["-9", "-6", "-3", "0", "3", "inf"]
XLABELS = ["-9", "-6", "-3", "0", "+3", "+inf"]


def accs_ses(path):
    df = pd.read_csv(path)
    n = len(df)
    a = np.array([df[f"exact_{s}"].mean() for s in SNRS])
    se = np.sqrt(a * (1 - a) / n)
    return a, se, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--same", default="snr_scan_results.csv")
    ap.add_argument("--diff", default="snr_scan_results_diff.csv")
    ap.add_argument("--out", default="fig2b_reproduction_en.png")
    args = ap.parse_args()

    same_a, same_se, n_same = accs_ses(args.same)
    diff_a, diff_se, n_diff = accs_ses(args.diff)
    x = np.arange(len(SNRS))
    xf = x[:5]   # 有限档 -9..+3 连线; inf 档单独画、不连线(与论文 Fig 2b 一致)

    fig, ax = plt.subplots(figsize=(6.2, 5.0), dpi=150)

    # 异性(更易) = 暖色;同性(更难) = 冷色,贴近论文配色习惯。仅连有限档
    ax.errorbar(xf, diff_a[:5], yerr=diff_se[:5], color="#c0392b", lw=2, marker="s",
                ms=7, mfc="#c0392b", mec="white", mew=1.1, capsize=3,
                ecolor="#c0392b", zorder=3, label="Different-sex distractor")
    ax.errorbar(xf, same_a[:5], yerr=same_se[:5], color="#1f3b73", lw=2, marker="o",
                ms=8, mfc="#1f3b73", mec="white", mew=1.2, capsize=3,
                ecolor="#1f3b73", zorder=3, label="Same-sex distractor")

    # +inf(无干扰): 单独一个黑点, 不与两条线相连(论文 Fig 2b 也是一个独立点)
    inf_acc = (same_a[5] + diff_a[5]) / 2
    ax.errorbar([5], [inf_acc], yerr=[same_se[5]], fmt="o", ms=8, color="black",
                mfc="black", mec="white", mew=1.2, capsize=3, ecolor="black",
                zorder=4, label="No distractor")

    # inf 档分隔虚线 + 标注
    ax.axvline(x=4.5, color="0.6", ls="--", lw=1, zorder=1)
    ax.text(5, 0.04, "No distractor", ha="center", va="bottom", fontsize=8, color="0.4")
    # 随机基线
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
    ax.legend(loc="upper left", frameon=False, fontsize=9.5)

    ax.set_title("Reproduction of Fig 2b: Same-sex vs different-sex talker distractor\n"
                 f"(diotic, N={n_same} / {n_diff})", fontsize=10.5, pad=12)
    # 显式标注误差棒口径(与论文 Fig 2 一致: s.e.m.)
    fig.text(0.99, 0.005, "Error bars: ± 1 SEM (binomial)", ha="right",
             fontsize=8, color="0.45")

    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(args.out, bbox_inches="tight")
    print(f"已写出: {args.out}")
    print(f"误差棒 = ± 1 SEM,  SEM = sqrt(p(1-p)/n)\n")
    # 同性 vs 异性: 误差棒是否重叠 + 差异显著性(差/差的SE)
    print(f"{'SNR':>6} | {'same':>7} | {'diff':>7} | {'Δ':>7} | {'误差棒重叠?':>9} | {'Δ/SE(Δ)':>8}")
    for i, lab in enumerate(XLABELS):
        s, d = same_a[i], diff_a[i]
        se_diff = np.sqrt(same_se[i]**2 + diff_se[i]**2)   # 两独立比例之差的SE
        # 误差棒重叠 = diff 下沿 <= same 上沿 (此处 diff>same)
        overlap = (d - diff_se[i]) <= (s + same_se[i])
        z = (d - s) / se_diff if se_diff > 0 else float("inf")
        print(f"{lab:>6} | {s:>6.1%} | {d:>6.1%} | {(d-s)*100:>+5.1f}pp | "
              f"{'重叠' if overlap else '不重叠':>9} | {z:>7.1f}σ")


if __name__ == "__main__":
    main()

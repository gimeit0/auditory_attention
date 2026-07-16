"""
Fig 2e 复现: distractor confusion vs SNR, 按 same-sex / different-sex 分两条线。

confusion(论文口径): 应答(预测)词出现在 distractor 句的转写里 = 把目标词听成了干扰说话人的词。
纯后处理,不跑模型:
  - 预测词: snr_scan_results.csv(同性) / snr_scan_results_diff.csv(异性) 的 pred_<snr> 列
  - distractor 句: samples_expanded.csv 的 same_dist_sentence / diff_dist_sentence
  - distractor 句按 align_words.normalize_token 规范化成词集合,判 pred ∈ 该集合

预期趋势(论文 Fig 2e):
  - SNR 降低 -> confusion 增多
  - same-sex 的 confusion 高于 different-sex
  - inf 档无干扰 -> confusion 落到地板(只剩偶然命中)

另报一个更严格的 intrusion 变体: pred ∈ distractor 且 pred != target(排除与目标词巧合重合)。

用法:
    python plot_fig2e.py
"""
import argparse

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from align_words import normalize_token

SNRS = ["-9", "-6", "-3", "0", "3", "inf"]
XLABELS = ["-9", "-6", "-3", "0", "+3", "+inf"]


def dist_wordset(sentence):
    """distractor 句 -> 规范化词集合。"""
    s = set()
    for w in str(sentence).split():
        for t in normalize_token(w):
            s.add(t)
    return s


def confusion_curve(results_csv, manifest, dist_sent_col):
    """返回 (raw_rate[6], strict_rate[6], n)。
    raw    = pred ∈ distractor 词集
    strict = pred ∈ distractor 词集 且 pred != target_norm
    """
    res = pd.read_csv(results_csv)
    # trial_id -> distractor 词集
    dset = {r["trial_id"]: dist_wordset(r[dist_sent_col]) for _, r in manifest.iterrows()}
    n = len(res)
    raw, strict = [], []
    for s in SNRS:
        rc = sc = 0
        for _, row in res.iterrows():
            words = dset.get(row["trial_id"], set())
            pred = row[f"pred_{s}"]
            hit = pred in words
            rc += hit
            sc += hit and (pred != row["target_norm"])
        raw.append(rc / n)
        strict.append(sc / n)
    return np.array(raw), np.array(strict), n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--same", default="snr_scan_results.csv")
    ap.add_argument("--diff", default="snr_scan_results_diff.csv")
    ap.add_argument("--manifest", default="samples_expanded.csv")
    ap.add_argument("--out", default="fig2e_reproduction_en.png")
    args = ap.parse_args()

    man = pd.read_csv(args.manifest, dtype=str, keep_default_na=False)
    same_raw, same_str, n_same = confusion_curve(args.same, man, "same_dist_sentence")
    diff_raw, diff_str, n_diff = confusion_curve(args.diff, man, "diff_dist_sentence")

    x = np.arange(len(SNRS))
    fig, ax = plt.subplots(figsize=(6.2, 5.0), dpi=150)

    def se(p, n):
        return np.sqrt(p * (1 - p) / n)

    ax.errorbar(x, same_raw, yerr=se(same_raw, n_same), color="#1f3b73", lw=2, marker="o",
                ms=8, mfc="#1f3b73", mec="white", mew=1.2, capsize=3, ecolor="#1f3b73",
                zorder=3, label="Same-sex distractor")
    ax.errorbar(x, diff_raw, yerr=se(diff_raw, n_diff), color="#c0392b", lw=2, marker="s",
                ms=7, mfc="#c0392b", mec="white", mew=1.1, capsize=3, ecolor="#c0392b",
                zorder=3, label="Different-sex distractor")

    ax.axvline(x=4.5, color="0.6", ls="--", lw=1, zorder=1)
    ax.text(5, 0.04, "No distractor", ha="center", va="bottom", fontsize=8, color="0.4")

    ax.set_xticks(x)
    ax.set_xticklabels(XLABELS)
    ax.set_xlabel("SNR (dB)", fontsize=11)
    ax.set_ylabel("Confusion rate (response = distractor word)", fontsize=11)
    # y 轴固定 0~1.0,与 Fig 2b / 论文 Fig 2e 统一,便于并排对比(数据本身不变)
    ax.set_ylim(0, 1.0)
    ax.set_yticks(np.arange(0, 1.01, 0.2))
    ax.set_xlim(-0.4, 5.4)
    ax.grid(axis="y", color="0.9", lw=0.8)
    ax.set_axisbelow(True)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    ax.legend(loc="upper right", frameon=False, fontsize=9.5)
    ax.set_title("Reproduction of Fig 2e: Distractor confusions vs SNR\n"
                 f"(same-sex vs different-sex, diotic, N={n_same} / {n_diff})",
                 fontsize=10.5, pad=12)
    # 显式标注误差棒口径(与 Fig 2b 同一种: s.e.m.)
    fig.text(0.99, 0.005, "Error bars: ± 1 SEM (binomial)", ha="right",
             fontsize=8, color="0.45")

    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(args.out, bbox_inches="tight")
    print(f"已写出: {args.out}\n")
    print(f"{'SNR':>6} | {'same(raw)':>9} {'same(strict)':>12} | {'diff(raw)':>9} {'diff(strict)':>12}")
    for i, lab in enumerate(XLABELS):
        print(f"{lab:>6} | {same_raw[i]:>8.1%} {same_str[i]:>11.1%} | {diff_raw[i]:>8.1%} {diff_str[i]:>11.1%}")
    print("\n趋势预期: SNR降->confusion升; same-sex > different-sex; inf档落地板。")


if __name__ == "__main__":
    main()

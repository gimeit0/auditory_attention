"""
干扰数量面板作图 —— 配色/版式对齐论文 Fig 2a(准确率) / 2d(混淆)。
左: Prop. target word vs SNR (one/two/four/babble + no-distractor)
右: Prop. distractor word (conf_sent, 论文口径) vs SNR
论文粉->紫渐变: one=浅粉, two=品红, four=深洋红, babble=深紫; no-distractor=黑点。
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import rcParams

CSV = "/Users/gigi/论文/主课题/多话者复现实验 结果/multi_talker_results.csv"
OUT = "/Users/gigi/论文/主课题/多话者复现实验 结果/fig_multi_talker_reproduction.png"

# ---- 论文配色(取自 Fig 2 的粉->紫渐变) ----
C = {
    "one_same":    "#F0A5C0",   # One-talker  浅粉
    "two_talker":  "#DB4D96",   # Two-talker  品红
    "four_talker": "#9C2E6D",   # Four-talker 深洋红
    "babble":      "#5D2E7C",   # Babble      深紫
}
LABEL = {"one_same": "One-talker", "two_talker": "Two-talker",
         "four_talker": "Four-talker", "babble": "Babble"}
ORDER = ["one_same", "two_talker", "four_talker", "babble"]
SNRS = [-9.0, -6.0, -3.0, 0.0, 3.0]
X = list(range(5))                # 有限档位置 0..4
X_INF = 5                         # +inf 单独位置

rcParams.update({"font.size": 12, "font.family": "sans-serif",
                 "axes.linewidth": 1.1, "svg.fonttype": "none"})


def agg(d, cond, col):
    m, se = [], []
    for s in SNRS:
        sub = d[(d.condition == cond) & (d.snr == s)][col]
        m.append(sub.mean() * 100)
        se.append(sub.std(ddof=1) / np.sqrt(len(sub)) * 100)
    return np.array(m), np.array(se)


def style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_xticks(X + [X_INF])
    ax.set_xticklabels(["-9", "-6", "-3", "0", "3", "inf"])
    ax.set_xlabel("SNR (dB)")
    ax.set_ylim(-0.02, 1.0)
    ax.set_yticks(np.arange(0, 1.01, 0.2))
    ax.set_xlim(-0.5, 5.5)


def draw(ax, d, col, ylabel, with_nodist):
    for cond in ORDER:
        m, se = agg(d, cond, col)
        m, se = m / 100, se / 100
        ax.plot(X, m, "-o", color=C[cond], ms=6, lw=2.2,
                mec="white", mew=0.8, label=LABEL[cond], zorder=3)
        ax.fill_between(X, m - se, m + se, color=C[cond], alpha=0.25, lw=0, zorder=2)
    if with_nodist:
        nod = d[d.condition == "no_distractor"][col].mean()
        ax.plot([X_INF], [nod], "o", color="black", ms=7, zorder=4,
                label="No distractor")
    ax.set_ylabel(ylabel)
    style(ax)


d = pd.read_csv(CSV)
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 4.4))

# --- 面板 a: 准确率 (对应论文 Fig 2a 的 model 面板) ---
draw(ax1, d, "is_exact", "Prop. target word", with_nodist=True)
ax1.set_title("Feature-gain model", fontsize=12)
ax1.text(0.0, 0.93, "N = 600", fontsize=11, va="bottom", transform=ax1.transData)
ax1.text(-0.16, 1.06, "a", fontsize=17, fontweight="bold",
         transform=ax1.transAxes, va="top")

# --- 面板 d: 混淆 (对应论文 Fig 2d 的 model 面板) ---
draw(ax2, d, "conf_sent", "Prop. distractor word", with_nodist=False)
ax2.set_title("Feature-gain model", fontsize=12)
ax2.text(-0.16, 1.06, "d", fontsize=17, fontweight="bold",
         transform=ax2.transAxes, va="top")

# 图例(论文顺序: No distractor 在最上), 放准确率面板内
h1, l1 = ax1.get_legend_handles_labels()
idx = l1.index("No distractor")
order = [idx] + [i for i in range(len(l1)) if i != idx]
ax1.legend([h1[i] for i in order], [l1[i] for i in order],
           frameon=False, fontsize=10, loc="upper left",
           bbox_to_anchor=(0.02, 0.98), handletextpad=0.5, labelspacing=0.35)

fig.suptitle("Experiment 1: Number of distractors", fontsize=14, y=1.0)
fig.tight_layout()
fig.savefig(OUT, dpi=200, bbox_inches="tight")
print("saved:", OUT)

"""
多干扰面板(干扰数量)：no_distractor / one_talker / two_talker / four_talker / babble × 5 档 SNR。

设计(见《干扰数量面板_复现计划书》+《计划评审》)：
  - within-item: 同一批 600 target(samples_expanded.csv), 每种条件 × 每档 SNR 各重混一次。
  - 干扰来自 distractor_pool.csv —— **每条干扰都带表内锚点词**, 以该词为中心切 2.5s,
    与 target 的切法完全对称。这样「模型把干扰词说出来」在原理上是可能的,
    混淆率才有可比量级(旧的随机干扰是 Fig 2e 低估 4-5 倍的根因)。
  - 嵌套抽样: 每个 target 用固定种子抽 8 个互不相同、且 != target 说话人的干扰,
      one=d1 | two=d1,d2 | four=d1..d4 | babble=d1..d8
    嵌套 => two-talker 就是 one-talker 再加一个人, 条件间差异只来自「人数」。
  - SNR 定义 = **target-to-total-masker**: N 个干扰先各自 RMS 对齐、求和成一个总掩蔽信号,
    再整体缩放到目标 SNR。=> one/two/four 在同一 SNR 下**总干扰能量相同**,
    差异只来自信息掩蔽(可混淆的人越多), 正是本实验要考察的变量。
    (N=1 时与已完成的 2a/2b 完全等价。)
  - 混音口径复用仓库 transforms, 与 snr_scan.py 一致:
      CombineWithRandomDBSNR(low=high=snr) -> RMSNormalize(0.02) -> DuplicateChannel -> Unsqueeze
  - no_distractor = +inf 单点(干扰置零), 所有条件在此收敛到同一水平。

评分:
  - exact       : 预测词 == target 锚点词(主指标, 准确率面板)
  - conf_anchor : 预测词 ∈ {本 trial 各干扰的锚点词}(严格混淆; 干扰带锚点后才有意义)
  - conf_sent   : 预测词 ∈ {本 trial 各干扰句的全部表内词}(论文宽松口径, 与 Fig 2e 可比)

算力: 600 × (4 条件 × 5 SNR + 1) = 12,600 次前向。Mac CPU 约 23 小时 -> **必须上 GPU**。

用法(超算 GPU 节点):
    export CV_CLIPS=$PWD/cv_clips
    python -u -m reproduction.experiment_2_talker_count.scripts.snr_scan_multi
调试(本地小样本):
    python -u -m reproduction.experiment_2_talker_count.scripts.snr_scan_multi --limit 5 --out /tmp/multi_smoke.csv
"""
import scipy.signal
if not hasattr(scipy.signal, "hann"):
    scipy.signal.hann = scipy.signal.windows.hann

import argparse
import os
import pickle
import random
from pathlib import Path

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
import src.audio_transforms as at
from align_words import normalize_token
from slice_stimuli import load_44k, slice_centered, SR

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
REPO = Path(__file__).resolve().parents[3]
EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_1_DIR = REPO / "reproduction/experiment_1_gender"
CV_CLIPS = os.environ.get(
    "CV_CLIPS", "/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en/clips")

SNRS = [-9, -6, -3, 0, 3]                       # 含干扰条件的 5 档
CONDITIONS = {"one_talker": 1, "two_talker": 2, "four_talker": 4, "babble": 8}
N_DRAW = 8                                       # 每个 target 抽 8 个干扰(嵌套用)


def build_model():
    cfg = yaml.load(open(REPO / "config/binaural_attn/word_task_v10_main_feature_gain_config.yaml"),
                    Loader=yaml.FullLoader)
    ckpt = sorted((REPO / "attn_cue_models/word_task_v10_main_feature_gain_config"
                          "/checkpoints").glob("*.ckpt"))[0]
    print(f"checkpoint: {ckpt.name} | device: {DEVICE}")
    model = BinauralAttentionModule.load_from_checkpoint(
        checkpoint_path=str(ckpt), config=cfg, strict=False).eval().to(DEVICE)
    return model, model.coch_gram.to(DEVICE)


def composer(snr):
    """snr=None -> 无干扰(background 传 None)。其余与 snr_scan.py 完全一致。"""
    return at.AudioCompose([
        at.AudioToTensor(),
        at.CombineWithRandomDBSNR(low_snr=(0 if snr is None else snr),
                                  high_snr=(0 if snr is None else snr)),
        at.RMSNormalizeForegroundAndBackground(rms_level=0.02),
        at.DuplicateChannel(),
        at.UnsqueezeAudio(dim=0),
    ])


def rms(x):
    return float(np.sqrt(np.mean(x ** 2)) + 1e-12)


def make_masker(slices):
    """N 个干扰片段各自 RMS 对齐后求和 -> 单一总掩蔽信号。
    只定形状不定电平: 后面 CombineWithRandomDBSNR 会按 SNR 整体缩放它。"""
    ref = rms(slices[0])
    return np.sum([s * (ref / rms(s)) for s in slices], axis=0).astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=EXPERIMENT_1_DIR / "data/samples_expanded.csv")
    ap.add_argument("--pool", default=EXPERIMENT_DIR / "data/distractor_pool.csv")
    ap.add_argument("--out", default=EXPERIMENT_DIR / "results/multi_talker_results.csv")
    ap.add_argument("--limit", type=int, default=0, help=">0 时只跑前 N 个 target(调试)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    smp = pd.read_csv(args.samples)
    if args.limit:
        smp = smp.head(args.limit)
    pool = pd.read_csv(args.pool).to_dict("records")
    with open(REPO / "cv_800_word_label_to_int_dict.pkl", "rb") as f:
        word2ix = pickle.load(f)
    ix2w = {v: k for k, v in word2ix.items()}

    print(f"target: {len(smp)} | 干扰池: {len(pool)} 条 / "
          f"{len(set(p['speaker'] for p in pool))} 个说话人")

    model, coch = build_model()
    comps = {snr: composer(snr) for snr in SNRS}
    comps[None] = composer(None)

    def to_dev(x):
        return x.to(DEVICE).float()

    rows = []
    n_skip = 0
    for i, r in enumerate(smp.to_dict("records")):
        # ---- 切 cue / target ----
        try:
            cue_w = load_44k(os.path.join(CV_CLIPS, r["cue_path"]))
            tgt_w = load_44k(os.path.join(CV_CLIPS, r["target_path"]))
        except Exception as e:
            n_skip += 1
            continue
        from slice_stimuli import slice_middle
        cue = slice_middle(cue_w)
        tgt = slice_centered(tgt_w, r["target_center_s"])
        if cue is None or tgt is None:
            n_skip += 1
            continue

        # ---- 抽 8 个干扰(固定种子, 与 SNR/条件无关 => within-item 干净) ----
        rng = random.Random(args.seed * 100003 + i)
        cand = [p for p in pool if p["speaker"] != r["target_speaker"]]
        drawn = rng.sample(cand, N_DRAW)
        dslices, dinfo = [], []
        for p in drawn:
            try:
                s = slice_centered(load_44k(os.path.join(CV_CLIPS, p["path"])),
                                   p["dist_center_s"])
            except Exception:
                s = None
            if s is None:
                continue
            dslices.append(s)
            dinfo.append(p)
        if len(dslices) < N_DRAW:
            n_skip += 1
            continue

        cue_cg, _ = coch(to_dev(comps[None](cue, None)[0]), None)

        # ---- no_distractor(+inf 单点) ----
        mix, _ = comps[None](tgt, None)
        with torch.no_grad():
            mix_cg, _ = coch(to_dev(mix), None)
            pred = ix2w[model(cue_cg, mix_cg).softmax(-1).argmax(1).item()]
        rows.append(dict(trial_id=r["trial_id"], condition="no_distractor", snr="inf",
                         pred=pred, is_exact=int(pred == r["target_norm"]),
                         conf_anchor=0, conf_sent=0))

        # ---- 4 种干扰条件 × 5 档 SNR ----
        for cond, n in CONDITIONS.items():
            sub = dslices[:n]
            info = dinfo[:n]
            masker = make_masker(sub)
            anchors = {p["dist_norm"] for p in info}
            sent_words = set()
            for p in info:
                sent_words |= {w for tok in str(p["sentence"]).split()
                               for w in normalize_token(tok) if w in word2ix}
            for snr in SNRS:
                mix, _ = comps[snr](tgt, masker)
                with torch.no_grad():
                    mix_cg, _ = coch(to_dev(mix), None)
                    pred = ix2w[model(cue_cg, mix_cg).softmax(-1).argmax(1).item()]
                tw = r["target_norm"]
                rows.append(dict(
                    trial_id=r["trial_id"], condition=cond, snr=snr, pred=pred,
                    is_exact=int(pred == tw),
                    conf_anchor=int(pred in anchors and pred != tw),
                    conf_sent=int(pred in sent_words and pred != tw)))

        if (i + 1) % 25 == 0:
            done = pd.DataFrame(rows)
            acc = done[done.condition == "one_talker"].is_exact.mean()
            print(f"  [{i+1}/{len(smp)}] one_talker 平均准确率 {acc:.3f} | 跳过 {n_skip}")

    out = pd.DataFrame(rows)
    out.to_csv(args.out, index=False)

    print(f"\n===== 结果 (跳过 {n_skip} 个 target) =====")
    print("\n-- 准确率 (prop. target word) --")
    piv = out[out.condition != "no_distractor"].pivot_table(
        index="condition", columns="snr", values="is_exact", aggfunc="mean")
    piv = piv.reindex(["one_talker", "two_talker", "four_talker", "babble"])
    print((piv * 100).round(1).to_string())
    nod = out[out.condition == "no_distractor"].is_exact.mean()
    print(f"no_distractor (+inf): {nod*100:.1f}%")

    print("\n-- 混淆率 conf_anchor (预测=某个干扰的锚点词) --")
    pa = out[out.condition != "no_distractor"].pivot_table(
        index="condition", columns="snr", values="conf_anchor", aggfunc="mean")
    print((pa.reindex(["one_talker", "two_talker", "four_talker", "babble"]) * 100).round(1).to_string())

    print("\n-- 混淆率 conf_sent (预测 ∈ 干扰句表内词, 与 Fig 2e 同口径) --")
    ps = out[out.condition != "no_distractor"].pivot_table(
        index="condition", columns="snr", values="conf_sent", aggfunc="mean")
    print((ps.reindex(["one_talker", "two_talker", "four_talker", "babble"]) * 100).round(1).to_string())

    print(f"\n判据: 每行随 SNR 上升 | 同一 SNR 下 one > two > four ≳ babble | 混淆反向")
    print(f"写出: {args.out}  ({len(out)} 行)")


if __name__ == "__main__":
    main()

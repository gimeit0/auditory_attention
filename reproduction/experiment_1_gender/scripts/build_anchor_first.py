"""
锚点优先配对: 从 CV v9 扩到 ~600 个有效 target 样本(供 Fig 2a 用)。

与旧 build_pairs.py(先随机配对、后筛锚点,产出率低)不同:这里【先对齐、后配对】。
  - 对每个候选目标说话人的若干录音做 forced alignment(复用 align_words.py),
    只把"有合格锚点(在800词表内、前后各≥1.25s、词长<2s)"的录音当 target。
  - 每个 target 锚点 = 1 个样本(一条录音有多个锚点就产多个样本,中心词不同)。
  - cue: 同一目标说话人的另一条录音(中心 2.5s),要求其中心词 != 该样本的 target 词。
  - distractor: same-sex(Fig 2a 单干扰那条线)、不同说话人、时长≥2.5s。
    Fig 2a 只看准确率,不需要 distractor 的转写/对齐,只需能切 2.5s。

输出:
  - samples_expanded.csv  每行一个 target 样本,自带 target_center_s/label/cue/distractor,
    切片阶段无需再查 alignment。
  - 打印产出统计: 实际样本数 / 处理(对齐)录音数 / 0锚点率 / 性别均衡 / 目标词去重数。

用法:
    python build_anchor_first.py --n_targets 600 --out samples_expanded.csv --seed 0
"""

import argparse
import json
import os
import pickle
import random
import sys
from pathlib import Path

import pandas as pd
import soundfile as sf
import torchaudio

from align_words import load_audio_16k, process_clip

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT_DIR = Path(__file__).resolve().parents[1]

CUE_DUR_MIN = 2.5
DIST_DUR_MIN = 2.5
ALIGN_CAP_PER_SPK = 4    # 每个目标说话人最多对齐几条录音(控成本、且够凑 cue)
SAMPLE_CAP_PER_SPK = 6   # 每个目标说话人最多产几个样本(分散说话人多样性、防偏斜)


def middle_word(words, duration_s):
    """录音中心 dur/2 处跨越的已对齐词的 norm;找不到返回 None。"""
    mid = duration_s / 2.0
    for w in words:
        if w["aligned"] and w["start_s"] <= mid < w["end_s"]:
            return w["norm"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cv_dir", default="/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en")
    ap.add_argument("--n_targets", type=int, default=600)
    ap.add_argument("--out", default=EXPERIMENT_DIR / "data/samples_expanded.csv")
    ap.add_argument(
        "--align_out", default=EXPERIMENT_DIR / "data/alignments_expanded.json"
    )
    ap.add_argument(
        "--word_table", default=PROJECT_ROOT / "cv_800_word_label_to_int_dict.pkl"
    )
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    random.seed(args.seed)
    clips_dir = os.path.join(args.cv_dir, "clips")
    tsv = os.path.join(args.cv_dir, "validated.tsv")
    with open(args.word_table, "rb") as f:
        word2ix = pickle.load(f)

    print(f"读取 {tsv} ...")
    df = pd.read_csv(tsv, sep="\t", dtype=str, keep_default_na=False)
    df = df[df["gender"].isin(["male", "female"])].copy()
    # 剔除性别标注不一致的说话人(同 build_pairs)
    nun = df.groupby("client_id")["gender"].nunique()
    df = df[df["client_id"].isin(nun[nun == 1].index)].copy()
    # 保留 >=2 条录音的说话人(target+cue 需同人两条)
    cnt = df["client_id"].value_counts()
    df = df[df["client_id"].isin(cnt[cnt >= 2].index)].copy()
    spk_gender = df.groupby("client_id")["gender"].first().to_dict()
    rows_by_spk = {c: g.to_dict("records") for c, g in df.groupby("client_id")}
    print(f"  可用说话人: {len(rows_by_spk):,} | 录音: {len(df):,}")

    # distractor 池(按性别);只存 path/sentence/speaker,时长用 sf.info 现查
    recs_by_gender = {"male": [], "female": []}
    for r in df.to_dict("records"):
        recs_by_gender[r["gender"]].append(r)

    # 目标说话人列表,按性别交替以保证 target 性别均衡
    male_spk = [s for s in rows_by_spk if spk_gender[s] == "male"]
    female_spk = [s for s in rows_by_spk if spk_gender[s] == "female"]
    random.shuffle(male_spk)
    random.shuffle(female_spk)
    spk_order = []
    for i in range(max(len(male_spk), len(female_spk))):
        if i < len(female_spk):
            spk_order.append(female_spk[i])
        if i < len(male_spk):
            spk_order.append(male_spk[i])

    print("加载 MMS_FA 对齐器 ...")
    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model()
    tokenizer = bundle.get_tokenizer()
    aligner = bundle.get_aligner()

    def pick_distractor(gender, exclude_spk):
        pool = recs_by_gender[gender]
        for _ in range(10):
            d = random.choice(pool)
            if d["client_id"] == exclude_spk:
                continue
            try:
                if sf.info(os.path.join(clips_dir, d["path"])).duration >= DIST_DUR_MIN:
                    return d
            except Exception:
                continue
        return None

    samples = []
    align_store = {}
    n_processed = n_zero_anchor = 0
    skip_no_cue = skip_no_dist = 0
    gender_count = {"male": 0, "female": 0}
    quota = {"male": args.n_targets // 2, "female": args.n_targets - args.n_targets // 2}

    for cid in spk_order:
        if len(samples) >= args.n_targets:
            break
        g = spk_gender[cid]
        if gender_count[g] >= quota[g]:   # 该性别配额已满,跳过此说话人
            continue
        recs = rows_by_spk[cid][:]
        random.shuffle(recs)
        n_from_spk = 0

        # 对齐该说话人最多 ALIGN_CAP_PER_SPK 条录音
        aligned = []
        for rec in recs[:ALIGN_CAP_PER_SPK]:
            try:
                wav16, dur = load_audio_16k(os.path.join(clips_dir, rec["path"]))
                words, anchors, _, _ = process_clip(
                    model, tokenizer, aligner, wav16, dur, rec["sentence"], word2ix)
            except Exception:
                continue
            n_processed += 1
            if not anchors:
                n_zero_anchor += 1
            aligned.append({
                "path": rec["path"], "sentence": rec["sentence"], "dur": dur,
                "words": words, "anchors": anchors,
                "mid_word": middle_word(words, dur),
            })
            align_store[rec["path"]] = {
                "duration_s": round(dur, 3), "words": words, "anchor_candidates": anchors,
            }

        # 该说话人里每条有锚点的录音 -> target;另一条 -> cue
        for t in aligned:
            if not t["anchors"]:
                continue
            for a in t["anchors"]:
                if len(samples) >= args.n_targets:
                    break
                if gender_count[g] >= quota[g] or n_from_spk >= SAMPLE_CAP_PER_SPK:
                    break
                # cue: 另一条录音、≥2.5s、中心词 != 该样本 target 词
                cue = None
                for c in aligned:
                    if c["path"] == t["path"]:
                        continue
                    if c["dur"] < CUE_DUR_MIN:
                        continue
                    if c["mid_word"] == a["norm"]:
                        continue
                    cue = c
                    break
                if cue is None:
                    skip_no_cue += 1
                    continue
                dist = pick_distractor(g, exclude_spk=cid)
                if dist is None:
                    skip_no_dist += 1
                    continue
                samples.append({
                    "trial_id": f"t{len(samples):04d}",
                    "target_gender": g,
                    "target_word": a["word"],
                    "target_norm": a["norm"],
                    "target_label": a["label"],
                    "target_center_s": a["anchor_center_s"],
                    "target_path": t["path"],
                    "target_sentence": t["sentence"],
                    "target_speaker": cid,
                    "cue_path": cue["path"],
                    "cue_mid_word": cue["mid_word"],
                    "cue_speaker": cid,
                    "same_dist_path": dist["path"],
                    "same_dist_sentence": dist["sentence"],
                    "same_dist_speaker": dist["client_id"],
                })
                gender_count[g] += 1
                n_from_spk += 1

        if len(samples) and len(samples) % 100 < 2:
            print(f"  已收集 {len(samples)} 样本 | 已对齐 {n_processed} 录音")

    out_df = pd.DataFrame(samples)
    out_df.to_csv(args.out, index=False)
    with open(args.align_out, "w") as f:
        json.dump(align_store, f, ensure_ascii=False)

    # ---- 产出统计 ----
    print(f"\n=== 产出统计 ===")
    print(f"有效 target 样本数:        {len(out_df)}")
    print(f"处理(对齐)录音数:          {n_processed}")
    print(f"其中 0 锚点录音:           {n_zero_anchor} ({n_zero_anchor/n_processed:.1%})" if n_processed else "")
    print(f"涉及目标说话人数:          {out_df['target_speaker'].nunique() if len(out_df) else 0}")
    print(f"涉及 target 录音数:        {out_df['target_path'].nunique() if len(out_df) else 0}")
    print(f"target 性别均衡:           {gender_count}")
    print(f"target 词去重数:           {out_df['target_norm'].nunique() if len(out_df) else 0} / 800")
    print(f"跳过(无合格 cue):          {skip_no_cue}")
    print(f"跳过(无合格 distractor):   {skip_no_dist}")
    print(f"\n已写出: {args.out} + {args.align_out}")


if __name__ == "__main__":
    main()

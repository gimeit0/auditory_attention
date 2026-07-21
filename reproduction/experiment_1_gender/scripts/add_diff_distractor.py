"""
给 samples_expanded.csv 的每个样本加一个【异性 distractor】(Fig 2b 的另一条线)。

within-item 设计: target/cue/锚点完全不变,只多挑一个异性、不同说话人、≥2.5s 的干扰,
这样同性 vs 异性两条线用的是同一批 target,可直接对比。

用法:
    python add_diff_distractor.py --samples samples_expanded.csv --seed 0
"""
import argparse
import os
import random
from pathlib import Path

import pandas as pd
import soundfile as sf

EXPERIMENT_DIR = Path(__file__).resolve().parents[1]

DIST_DUR_MIN = 2.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--samples", default=EXPERIMENT_DIR / "data/samples_expanded.csv"
    )
    ap.add_argument("--cv_dir", default="/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    random.seed(args.seed)
    clips_dir = os.path.join(args.cv_dir, "clips")

    df = pd.read_csv(args.samples, dtype=str, keep_default_na=False)

    # 重建与 build_anchor_first 一致的干扰池
    tsv = os.path.join(args.cv_dir, "validated.tsv")
    pool = pd.read_csv(tsv, sep="\t", dtype=str, keep_default_na=False)
    pool = pool[pool["gender"].isin(["male", "female"])].copy()
    nun = pool.groupby("client_id")["gender"].nunique()
    pool = pool[pool["client_id"].isin(nun[nun == 1].index)].copy()
    recs_by_gender = {"male": [], "female": []}
    for r in pool.to_dict("records"):
        recs_by_gender[r["gender"]].append(r)

    def pick_diff(target_gender, exclude_spk):
        opp = "female" if target_gender == "male" else "male"
        for _ in range(12):
            d = random.choice(recs_by_gender[opp])
            if d["client_id"] == exclude_spk:
                continue
            try:
                if sf.info(os.path.join(clips_dir, d["path"])).duration >= DIST_DUR_MIN:
                    return d
            except Exception:
                continue
        return None

    paths, sents, spks = [], [], []
    n_fail = 0
    for _, row in df.iterrows():
        d = pick_diff(row["target_gender"], row["target_speaker"])
        if d is None:
            n_fail += 1
            paths.append(""); sents.append(""); spks.append("")
        else:
            paths.append(d["path"]); sents.append(d["sentence"]); spks.append(d["client_id"])
    df["diff_dist_path"] = paths
    df["diff_dist_sentence"] = sents
    df["diff_dist_speaker"] = spks
    df.to_csv(args.samples, index=False)

    # 自检
    ok = (df["diff_dist_path"] != "").sum()
    print(f"=== 自检 ===")
    print(f"成功分配异性 distractor: {ok}/{len(df)} (失败 {n_fail})")
    # 验证性别确为异性、说话人不同
    opp_ok = 0
    for _, r in df.iterrows():
        if not r["diff_dist_speaker"]:
            continue
        dg = next((rec["gender"] for rec in recs_by_gender["male"] + recs_by_gender["female"]
                   if rec["client_id"] == r["diff_dist_speaker"]), None)
        if dg and dg != r["target_gender"] and r["diff_dist_speaker"] != r["target_speaker"]:
            opp_ok += 1
    print(f"异性且异人校验通过:      {opp_ok}/{ok} (应=成功数)")
    print(f"已更新: {args.samples} (+ diff_dist_path/sentence/speaker)")


if __name__ == "__main__":
    main()

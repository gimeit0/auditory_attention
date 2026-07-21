"""
算出「上传到 HAKUSAN 需要哪些 Common Voice clips」, 写成 rsync --files-from 用的清单。

来源两处:
  samples_expanded.csv  -> target / cue / same_dist / diff_dist  (单干扰实验, 已完成的 2a/2b/2e)
  distractor_pool.csv   -> 多干扰面板(two/four-talker + babble)的带锚点干扰池

只传用到的 clips(约 100-150 MB), 不传 79GB 全量语料。

用法(仓库根目录):
    python reproduction/deployment/hakusan/make_clip_list.py
"""
import argparse
import os
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
EXP1 = REPO / "reproduction/experiment_1_gender"
EXP2 = REPO / "reproduction/experiment_2_talker_count"
DEPLOY = REPO / "reproduction/deployment/hakusan"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=EXP1 / "data/samples_expanded.csv")
    ap.add_argument("--pool", default=EXP2 / "data/distractor_pool.csv")
    ap.add_argument("--cv_clips",
                    default="/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en/clips")
    ap.add_argument("--out", default=DEPLOY / "clips_list.txt")
    args = ap.parse_args()

    clips = set()

    smp = pd.read_csv(args.samples)
    for c in ["target_path", "cue_path", "same_dist_path", "diff_dist_path"]:
        clips |= set(smp[c].dropna().astype(str))
    n_smp = len(clips)
    print(f"samples_expanded.csv : {n_smp} 条 clips")

    if os.path.exists(args.pool):
        pool = pd.read_csv(args.pool)
        before = len(clips)
        clips |= set(pool["path"].dropna().astype(str))
        print(f"distractor_pool.csv  : {len(pool)} 条 (新增 {len(clips)-before} 条不重复)")
    else:
        print(f"⚠️ 找不到 {args.pool} —— 多干扰面板的干扰池还没建, 先跑 build_distractor_pool.py")

    clips = sorted(clips)
    total = miss = 0
    for f in clips:
        p = os.path.join(args.cv_clips, f)
        if os.path.exists(p):
            total += os.path.getsize(p)
        else:
            miss += 1

    with open(args.out, "w") as fh:
        fh.write("\n".join(clips) + "\n")

    print(f"\n合计 clips  : {len(clips)}")
    print(f"合计大小    : {total/1e6:.1f} MB" + (f"  | ⚠️ 缺失 {miss} 条" if miss else ""))
    print(f"清单写出    : {args.out}")


if __name__ == "__main__":
    main()

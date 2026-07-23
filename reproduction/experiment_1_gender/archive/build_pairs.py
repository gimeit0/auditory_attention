"""
Step 1: 从 Common Voice 9.0 英语构建「配对清单」(还不做对齐/混音)。

这一版做什么:
  - 读 validated.tsv
  - 只保留 gender 为 male/female 的录音(CV 很多行 gender 为空,无法做 sex 配对)
  - 按 client_id 分组,保留名下 >=2 条录音的说话人(才凑得出 cue+target)
  - 把说话人切成 speaker-disjoint 的两堆(默认全部进 eval;留了 train 接口)
  - 为每个 target 配:
        cue              = 同一 client_id、不同录音
        same-sex dist    = 不同 client_id、与 target 同性别
        different-sex dist = 不同 client_id、与 target 不同性别
  - 输出一张 CSV,每行是一组 (cue, target, same_dist, diff_dist)

这一版【还没做】、留给后续(forced alignment 之后)的:
  - 「中间词限定在 800 词表内」: 需要词级时间戳才知道每条录音的"中间词"。
    脚本里用 --word_table 预留了接口,但默认不启用(USE_WORD_FILTER=False)。
  - 实际切词、混音、喂模型: 后续步骤单独做。

用法(在你本地 audattn 环境里):
    python build_pairs.py \
        --cv_dir "/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en" \
        --out pairs_eval.csv \
        --n_targets 500 \
        --seed 0

先用小数目验证逻辑(比如 --n_targets 50),看 CSV 对不对,再放大。
"""

import argparse
import os
import random
import sys

import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cv_dir", required=True,
                    help="CV 英语根目录,内含 validated.tsv 和 clips/")
    ap.add_argument("--out", default="pairs_eval.csv", help="输出 CSV 路径")
    ap.add_argument("--n_targets", type=int, default=500,
                    help="要生成多少组配对(target 数量)")
    ap.add_argument("--eval_speaker_frac", type=float, default=1.0,
                    help="多少比例的说话人划进 eval(其余留作 train,默认全进 eval)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--word_table", default=None,
                    help="(预留)800 词表 pkl 路径;本版默认不启用词级筛选")
    args = ap.parse_args()

    random.seed(args.seed)

    tsv = os.path.join(args.cv_dir, "validated.tsv")
    clips_dir = os.path.join(args.cv_dir, "clips")
    if not os.path.exists(tsv):
        sys.exit(f"找不到 {tsv} — 检查 --cv_dir 是否正确")

    print(f"读取 {tsv} ...")
    # CV 的 tsv 是 tab 分隔;字段当字符串读,避免 client_id 被当数字
    df = pd.read_csv(tsv, sep="\t", dtype=str, keep_default_na=False)
    print(f"  总行数: {len(df):,}")

    # --- 1) 只保留有性别标注的 male/female ---
    df = df[df["gender"].isin(["male", "female"])].copy()
    print(f"  有性别标注(male/female): {len(df):,}")

    # --- 1b) 剔除性别标注不一致的说话人 ---
    # CV 里极少数 client_id 在不同录音被标了不同性别(数据噪声),
    # 这种人会破坏 same/different-sex 配对,直接丢掉。
    nunique_g = df.groupby("client_id")["gender"].nunique()
    consistent = nunique_g[nunique_g == 1].index
    n_dropped = df["client_id"].nunique() - len(consistent)
    df = df[df["client_id"].isin(consistent)].copy()
    print(f"  剔除性别标注不一致的说话人: {n_dropped:,}")

    # --- 2) 按 client_id 分组,保留 >=2 条录音的说话人 ---
    counts = df["client_id"].value_counts()
    multi_speakers = counts[counts >= 2].index
    df = df[df["client_id"].isin(multi_speakers)].copy()
    speakers = sorted(df["client_id"].unique())
    print(f"  >=2 条录音的说话人数: {len(speakers):,}")
    if len(speakers) < 4:
        sys.exit("可用说话人太少,无法配对。检查数据或放宽筛选条件。")

    # 每个说话人的性别(此时每人只有一种性别,干净)
    spk_gender = df.groupby("client_id")["gender"].first().to_dict()

    # --- 3) speaker-disjoint 切分: 把说话人分成 eval / train 两堆 ---
    random.shuffle(speakers)
    n_eval = int(len(speakers) * args.eval_speaker_frac)
    eval_speakers = set(speakers[:n_eval])
    # train_speakers = set(speakers[n_eval:])  # 本版只用 eval
    eval_df = df[df["client_id"].isin(eval_speakers)].copy()

    # 按性别把"可做 distractor 的说话人池"建好(用于异人配对)
    male_speakers = [s for s in eval_speakers if spk_gender[s] == "male"]
    female_speakers = [s for s in eval_speakers if spk_gender[s] == "female"]
    print(f"  eval 说话人: {len(eval_speakers):,} "
          f"(男 {len(male_speakers):,} / 女 {len(female_speakers):,})")
    if len(male_speakers) < 2 or len(female_speakers) < 2:
        sys.exit("某一性别的说话人太少,无法做 same/different-sex 配对。")

    # 把每个说话人的录音行,按 client_id 收成 list,方便随机取
    rows_by_spk = {cid: g.to_dict("records")
                   for cid, g in eval_df.groupby("client_id")}

    def pick_distractor_clip(spk_pool, exclude_spk):
        """从 spk_pool 里随机挑一个不等于 exclude_spk 的说话人,再随机取其一条录音。"""
        candidates = [s for s in spk_pool if s != exclude_spk]
        if not candidates:
            return None
        ds = random.choice(candidates)
        return random.choice(rows_by_spk[ds])

    # --- 4) 为每个 target 配 cue / same-dist / diff-dist ---
    # 性别平衡: target 男女各占一半(论文 Experiment 1 是 sex-balanced 的)。
    # CV 男声远多于女声,所以分别建男/女 target 候选队列,交替取。
    male_targets = [s for s in eval_speakers if spk_gender[s] == "male"]
    female_targets = [s for s in eval_speakers if spk_gender[s] == "female"]
    random.shuffle(male_targets)
    random.shuffle(female_targets)

    n_each = args.n_targets // 2
    # 受限于较少的那个性别的可用人数
    n_each = min(n_each, len(male_targets), len(female_targets))
    if n_each * 2 < args.n_targets:
        print(f"  注意: 受女声说话人数限制,实际只能生成 {n_each*2} 组(男女各 {n_each})")
    # 交替排列,保证均衡
    eval_speaker_list = []
    for i in range(n_each):
        eval_speaker_list.append(male_targets[i])
        eval_speaker_list.append(female_targets[i])

    out_rows = []
    for cid in eval_speaker_list:
        if len(out_rows) >= args.n_targets:
            break
        clips = rows_by_spk[cid]
        if len(clips) < 2:
            continue
        g = spk_gender[cid]

        # cue 和 target: 同一说话人的两条不同录音
        target_row, cue_row = random.sample(clips, 2)

        # same-sex distractor: 同性别、不同说话人
        same_pool = male_speakers if g == "male" else female_speakers
        same_dist = pick_distractor_clip(same_pool, exclude_spk=cid)

        # different-sex distractor: 不同性别
        diff_pool = female_speakers if g == "male" else male_speakers
        diff_dist = pick_distractor_clip(diff_pool, exclude_spk=cid)

        if same_dist is None or diff_dist is None:
            continue

        out_rows.append({
            "target_client_id": cid,
            "target_gender": g,
            "target_path": target_row["path"],
            "target_sentence": target_row["sentence"],
            "cue_client_id": cid,                      # 同人
            "cue_path": cue_row["path"],
            "cue_sentence": cue_row["sentence"],
            "same_dist_client_id": same_dist["client_id"],
            "same_dist_gender": same_dist["gender"],
            "same_dist_path": same_dist["path"],
            "same_dist_sentence": same_dist["sentence"],
            "diff_dist_client_id": diff_dist["client_id"],
            "diff_dist_gender": diff_dist["gender"],
            "diff_dist_path": diff_dist["path"],
            "diff_dist_sentence": diff_dist["sentence"],
        })

    out_df = pd.DataFrame(out_rows)
    out_df.to_csv(args.out, index=False)

    # --- 自检打印 ---
    print(f"\n生成配对组数: {len(out_df)}")
    if len(out_df):
        same_ok = (out_df["target_gender"] == out_df["same_dist_gender"]).mean()
        diff_ok = (out_df["target_gender"] != out_df["diff_dist_gender"]).mean()
        cue_same_spk = (out_df["target_client_id"] == out_df["cue_client_id"]).mean()
        dist_diff_spk = ((out_df["target_client_id"] != out_df["same_dist_client_id"]) &
                         (out_df["target_client_id"] != out_df["diff_dist_client_id"])).mean()
        print(f"  cue 与 target 同人比例:        {cue_same_spk:.1%} (应为 100%)")
        print(f"  distractor 与 target 异人比例: {dist_diff_spk:.1%} (应为 100%)")
        print(f"  same-sex distractor 同性别:    {same_ok:.1%} (应为 100%)")
        print(f"  diff-sex distractor 异性别:    {diff_ok:.1%} (应为 100%)")
        print(f"  target 性别分布: {out_df['target_gender'].value_counts().to_dict()}")
    print(f"\n已写出: {args.out}")
    print("提示: clips 音频在", clips_dir, "(path 列是文件名,拼到这个目录下即可读取)")


if __name__ == "__main__":
    main()

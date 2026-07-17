"""
建「带锚点的干扰池」——供多干扰面板(one/two/four-talker + babble)抽样用。

为什么要重建池:
  现有 samples_expanded.csv 里的 1200 条干扰是随机抽的, 中间词多半不在 800 词表内,
  导致模型「即使听到干扰词也无法输出它」, 混淆率被系统性低估 4-5 倍(Fig 2e 的已知缺陷)。
  这里改为: 每条干扰录音也必须含一个「表内锚点词」, 并以该词为中心切 2.5s——
  与 target 的切法完全对称, 混淆率才有可比量级。

约束(与 target 侧一致, 复用 align_words.find_anchor_candidates):
  - 锚点词 ∈ 800 词表; 词长 < 2.0s; 前后各留 ≥1.25s (=> 录音时长必然 ≥2.5s)
  - 说话人有性别标注、且该说话人性别标注一致
  - 说话人 ∉ target/cue 说话人集合 (speaker-disjoint, 保证干扰不是目标本人)
  - 每个说话人只取 1 条录音 => 池内说话人互不相同, 抽 12 个不重复干扰毫无压力
  - 性别均衡(男女各半), 以便日后复用做 same/diff-sex 对比

输出 distractor_pool.csv, 每行一条干扰录音:
  path, speaker, gender, duration_s, sentence,
  dist_word(原词), dist_norm(规范化), dist_label(词表 int), dist_center_s(切片中心)

用法:
    python build_distractor_pool.py --n 1200                 # 全量(男女各 600)
    python build_distractor_pool.py --n 20 --align_cap 200   # 冒烟测试/计时
"""
import argparse
import os
import pickle
import random
import time

import pandas as pd
import soundfile as sf
import torch
import torchaudio

from align_words import load_audio_16k, process_clip


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cv_dir", default="/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en")
    ap.add_argument("--samples", default="samples_expanded.csv",
                    help="已有样本表, 用于取出 target/cue 说话人以排除")
    ap.add_argument("--word_table", default="cv_800_word_label_to_int_dict.pkl")
    ap.add_argument("--out", default="distractor_pool.csv")
    ap.add_argument("--n", type=int, default=1200, help="池大小(说话人数), 男女各半")
    ap.add_argument("--align_cap", type=int, default=0,
                    help=">0 时最多对齐这么多条录音就停(调试用)")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    random.seed(args.seed)
    clips_dir = os.path.join(args.cv_dir, "clips")
    with open(args.word_table, "rb") as f:
        word2ix = pickle.load(f)

    # ---- 排除已用作 target/cue 的说话人 ----
    smp = pd.read_csv(args.samples)
    excl = set(smp["target_speaker"]) | set(smp["cue_speaker"])
    print(f"排除的 target/cue 说话人: {len(excl)}")

    print("读取 validated.tsv ...")
    df = pd.read_csv(os.path.join(args.cv_dir, "validated.tsv"),
                     sep="\t", dtype=str, keep_default_na=False)
    df = df[df["gender"].isin(["male", "female"])].copy()
    nun = df.groupby("client_id")["gender"].nunique()          # 性别标注一致
    df = df[df["client_id"].isin(nun[nun == 1].index)].copy()
    df = df[~df["client_id"].isin(excl)].copy()                # speaker-disjoint
    spk_gender = df.groupby("client_id")["gender"].first().to_dict()
    rows_by_spk = {c: g.to_dict("records") for c, g in df.groupby("client_id")}
    print(f"  候选说话人: {len(rows_by_spk):,} | 候选录音: {len(df):,}")

    # 男女交替遍历说话人, 保证性别均衡
    male = [s for s in rows_by_spk if spk_gender[s] == "male"]
    female = [s for s in rows_by_spk if spk_gender[s] == "female"]
    random.shuffle(male)
    random.shuffle(female)
    order = []
    for i in range(max(len(male), len(female))):
        if i < len(female):
            order.append(female[i])
        if i < len(male):
            order.append(male[i])

    print("加载 MMS_FA 对齐器 ...")
    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model()
    tokenizer = bundle.get_tokenizer()
    aligner = bundle.get_aligner()

    quota = {"male": args.n // 2, "female": args.n - args.n // 2}
    got = {"male": 0, "female": 0}
    pool, n_aligned, n_no_anchor = [], 0, 0
    t0 = time.time()

    for cid in order:
        if len(pool) >= args.n:
            break
        g = spk_gender[cid]
        if got[g] >= quota[g]:
            continue

        recs = rows_by_spk[cid][:]
        random.shuffle(recs)
        for rec in recs[:3]:            # 每人最多试 3 条, 找到一条带锚点的就收
            if args.align_cap and n_aligned >= args.align_cap:
                break
            path = os.path.join(clips_dir, rec["path"])
            try:
                wav16, dur = load_audio_16k(path)
                if dur < 2.5:            # 不可能有合法锚点, 省掉一次对齐
                    continue
                _, anchors, _, _ = process_clip(
                    model, tokenizer, aligner, wav16, dur, rec["sentence"], word2ix)
            except Exception:
                continue
            n_aligned += 1
            if not anchors:
                n_no_anchor += 1
                continue
            # 取最靠近录音中点的锚点: 切片离边界最远, 最稳
            a = min(anchors, key=lambda x: abs(x["anchor_center_s"] - dur / 2))
            pool.append({
                "path": rec["path"], "speaker": cid, "gender": g,
                "duration_s": round(dur, 3), "sentence": rec["sentence"],
                "dist_word": a["word"], "dist_norm": a["norm"],
                "dist_label": a["label"], "dist_center_s": a["anchor_center_s"],
            })
            got[g] += 1
            break                        # 该说话人只收 1 条

        if args.align_cap and n_aligned >= args.align_cap:
            break
        if len(pool) and len(pool) % 100 == 0 and len(pool) != getattr(main, "_last", -1):
            main._last = len(pool)
            el = time.time() - t0
            print(f"  已收 {len(pool)}/{args.n} | 对齐 {n_aligned} 条 | "
                  f"{el/60:.1f} min | {el/max(n_aligned,1):.2f} s/条")

    out = pd.DataFrame(pool)
    out.to_csv(args.out, index=False)
    el = time.time() - t0

    print("\n===== 自检 =====")
    print(f"池大小              : {len(out)}  (目标 {args.n})")
    print(f"性别分布            : {out['gender'].value_counts().to_dict()}")
    print(f"说话人是否互不相同  : {out['speaker'].nunique() == len(out)}")
    print(f"与 target/cue 说话人重叠: {len(set(out['speaker']) & excl)}  (应为 0)")
    print(f"锚点词种类          : {out['dist_norm'].nunique()} 个不同词")
    print(f"时长中位数          : {out['duration_s'].median():.2f} s (最短 {out['duration_s'].min():.2f})")
    print(f"对齐录音数          : {n_aligned} | 无锚点被弃: {n_no_anchor} "
          f"(锚点率 {100*(1-n_no_anchor/max(n_aligned,1)):.1f}%)")
    print(f"耗时                : {el/60:.1f} min ({el/max(n_aligned,1):.2f} s/条)")
    print(f"写出                : {args.out}")


if __name__ == "__main__":
    main()

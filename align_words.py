"""
任务 A: Forced Alignment —— 对配对清单里用到的每条 CV 录音做词级对齐,
并按论文口径标出"中间词锚点候选"。

做什么:
  - 读 build_pairs.py 输出的配对 CSV(默认 pairs_test.csv)
  - 收集所有用到的录音(target/cue/same_dist/diff_dist 四组 path+sentence),去重
  - 用 torchaudio MMS_FA(Wav2Vec2FABundle)对每条录音的完整 transcript 做强制对齐,
    得到每个词的 (word, start_s, end_s)
  - 文本规范化复刻论文 src/get_swc_binaural_manifest_transcripts.py 的 convert_transcript,
    但【保留撇号】(详见 normalize_token 注释)
  - 标"中间词锚点候选": 论文不是取整段中点,而是"以目标词为中心切 2.5s,目标词落在
    中间 2s 的 1s 处"。等价判定: 目标词在 800 词表内、词长<2s、前后各留够 1.25s。

设计要点 / 已确认:
  - 对齐只为拿到【秒级时间戳】,与模型 44.1k 的采样率解耦。MMS_FA 要 16k 单声道,
    CV 是 48k mp3 -> soundfile 解码 + torchaudio.functional.resample 到 16k(仅供对齐)。
  - CPU 运行(M1 无 CUDA;沿用 CLAUDE.md 第 6 节)。
  - MMS_FA 字符集含撇号(char 25),can't/don't 这类带撇号词可直接对齐,
    无需单独的"对齐用字符串"。

规范化规则(逐 token,复刻 convert_transcript 但保留撇号):
  - 转小写
  - re.sub(r"[^a-z0-9' ]+", "", text)  保留 a-z 0-9 撇号 空格,去掉其余(连字符也删)
  - 纯数字 token 用 num2words 转英文词,按连字符/空格拆成多个词
  词表(800 词)里有 16 个带撇号缩写(can't/don't/that's/...),保留撇号才能匹配上;
  词表里没有带连字符或含数字的词,所以连字符删除、含数字词判为不可对齐,都不影响匹配。

用法:
    python align_words.py --pairs pairs_test.csv --out alignments.json
    # 先小样本: --limit 20 只处理前 20 条唯一录音

输出: 一个 JSON,key 是录音文件名,value 见 main() 里的组装结构。
"""

import argparse
import json
import os
import pickle
import re
import sys

import pandas as pd
import soundfile as sf
import torch
import torchaudio
from num2words import num2words

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"   # 超算 GPU 节点自动切 cuda

# MMS_FA 能对齐的字符集: a-z 和撇号(字典里 char 25)。
# 注: 字典 index 0 是 '-',即 CTC blank,送进 aligner 会报错,所以连字符不算可对齐字符。
MMS_OK = set("abcdefghijklmnopqrstuvwxyz'")


def normalize_token(raw):
    """复刻论文 convert_transcript 的逐 token 规则(但保留撇号),返回该原始词的
    norm 子词列表(0..N 个)。
      - 小写 -> 去掉非 [a-z0-9' 空格] 字符(连字符被删,撇号保留)
      - 纯数字 -> num2words 展开,按连字符/空格拆成多个单词
      - 含数字的混合词(如 '3d'/'mp3')原样返回,后续因含数字判为不可对齐
    """
    clean = re.sub(r"[^a-z0-9' ]+", "", raw.lower())   # 保留撇号 '
    if clean == "":
        return []
    if clean.isdigit():
        # 源码是 num2words(token).split('-'); >=100 会带空格(one hundred),
        # 这里把连字符和空格都当分隔,保证每个 norm 是单词、可直接喂对齐器。
        return num2words(clean).replace("-", " ").split()
    return [clean]


def normalize_sentence(sentence):
    """把整句拆词并规范化,保留 provenance(每个 norm 词来自哪个原始词)。
    返回:
      norm_words: [{orig_idx, word(原始词), norm}]  展平后的 norm 子词
      unaligned:  [{orig_idx, word, reason}]         规范化后变空的原始词
      modified:   [{orig_idx, word, norm}]           字母数字内容被改写的(主要是数字展开)
    """
    raw_words = sentence.split()
    norm_words, unaligned, modified = [], [], []
    for oi, raw in enumerate(raw_words):
        subs = normalize_token(raw)
        if not subs:
            unaligned.append({"orig_idx": oi, "word": raw, "reason": "normalized_empty"})
            continue
        # 只在"字母数字内容"真的变了时记 modified(避免去尾点这类把每个句尾词都标上)
        low_alnum = re.sub(r"[^a-z0-9']", "", raw.lower())
        if "".join(subs) != low_alnum:
            modified.append({"orig_idx": oi, "word": raw, "norm": " ".join(subs)})
        for s in subs:
            norm_words.append({"orig_idx": oi, "word": raw, "norm": s})
    return norm_words, unaligned, modified


def find_anchor_candidates(words, duration_s, word2ix):
    """论文口径的中间词锚点候选。words 是已对齐的 norm 词列表。
    合法条件(全部满足):
      - norm 在 800 词表内
      - 词时长 (end-start) < 2.0s
      - start - 1.25 >= 0        (前面够 1.25s)
      - end   + 1.25 <= duration (后面够 1.25s)
    """
    out = []
    for w in words:
        if not w["aligned"]:
            continue
        nm = w["norm"]
        if nm not in word2ix:
            continue
        if not (w["end_s"] - w["start_s"] < 2.0):
            continue
        if w["start_s"] - 1.25 < 0:
            continue
        if w["end_s"] + 1.25 > duration_s:
            continue
        out.append({
            "idx": w["idx"],
            "word": w["word"],
            "norm": nm,
            "label": word2ix[nm],
            "anchor_center_s": round((w["start_s"] + w["end_s"]) / 2, 3),
            "start_s": w["start_s"],
            "end_s": w["end_s"],
        })
    return out


def collect_clips(pairs_df):
    """从配对 CSV 收集所有用到的 (path, sentence),按 path 去重。"""
    groups = [
        ("target_path", "target_sentence"),
        ("cue_path", "cue_sentence"),
        ("same_dist_path", "same_dist_sentence"),
        ("diff_dist_path", "diff_dist_sentence"),
    ]
    seen = {}
    for pcol, scol in groups:
        for path, sent in zip(pairs_df[pcol], pairs_df[scol]):
            if path not in seen:
                seen[path] = sent
    return seen


def load_audio_16k(mp3_path):
    """解码 mp3 -> 单声道 float32 -> 重采样到 16k。返回 (wav16 [1,N], dur_s)。"""
    w, sr = sf.read(mp3_path, dtype="float32")
    if w.ndim == 2:
        w = w.mean(axis=1)
    wav = torch.from_numpy(w).unsqueeze(0)
    wav16 = torchaudio.functional.resample(wav, sr, 16000)
    return wav16, wav16.shape[1] / 16000.0


def process_clip(model, tokenizer, aligner, wav16, dur_s, sentence, word2ix):
    """规范化 -> 对齐 -> 算锚点。返回 (words, anchors, unaligned, modified)。"""
    norm_words, unaligned, modified = normalize_sentence(sentence)

    words = []
    transcript = []       # 喂对齐器的 norm 词
    transcript_pos = []   # transcript[i] 对应 words 里的下标
    for i, nw in enumerate(norm_words):
        words.append({
            "idx": i, "word": nw["word"], "norm": nw["norm"],
            "start_s": None, "end_s": None, "aligned": False,
        })
        nm = nw["norm"]
        tokenizable = nm and all(c in MMS_OK for c in nm) and any(c.isalpha() for c in nm)
        if tokenizable:
            transcript_pos.append(i)
            transcript.append(nm)
        else:
            unaligned.append({"idx": i, "word": nw["word"], "norm": nm, "reason": "untokenizable"})

    if transcript:
        with torch.inference_mode():
            emission, _ = model(wav16.to(DEVICE))
        token_spans = aligner(emission[0], tokenizer(transcript))
        ratio = wav16.shape[1] / emission.shape[1] / 16000.0
        for ti, sp in enumerate(token_spans):
            wi = transcript_pos[ti]
            words[wi]["start_s"] = round(sp[0].start * ratio, 3)
            words[wi]["end_s"] = round(sp[-1].end * ratio, 3)
            words[wi]["aligned"] = True

    anchors = find_anchor_candidates(words, dur_s, word2ix)
    return words, anchors, unaligned, modified


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="pairs_test.csv", help="build_pairs.py 输出的配对 CSV")
    ap.add_argument("--cv_dir",
                    default="/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en",
                    help="CV 英语根目录(内含 clips/)")
    ap.add_argument("--out", default="alignments.json", help="输出 JSON 路径")
    ap.add_argument("--word_table", default="cv_800_word_label_to_int_dict.pkl",
                    help="800 词表 pkl(word -> 分类标签号)")
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 条唯一录音(调试用)")
    args = ap.parse_args()

    clips_dir = os.path.join(args.cv_dir, "clips")
    if not os.path.exists(args.pairs):
        sys.exit(f"找不到配对 CSV: {args.pairs}")
    with open(args.word_table, "rb") as f:
        word2ix = pickle.load(f)

    pairs_df = pd.read_csv(args.pairs, dtype=str, keep_default_na=False)
    clips = collect_clips(pairs_df)
    items = list(clips.items())
    if args.limit:
        items = items[:args.limit]
    print(f"配对组数: {len(pairs_df)} | 唯一录音数(去重后): {len(clips)}"
          f"{' | 本次只处理 ' + str(len(items)) if args.limit else ''}"
          f" | 词表大小: {len(word2ix)}")

    print("加载 MMS_FA 对齐器(首次会下载 ~1.2GB 模型,之后走缓存)...")
    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model().to(DEVICE)
    tokenizer = bundle.get_tokenizer()
    aligner = bundle.get_aligner()

    results = {}
    n_ok = n_fail = 0
    n_unaligned = n_modified = 0
    n_zero_cand = 0
    cand_counts = []
    cand_word_freq = {}
    fails = []

    for k, (fname, sentence) in enumerate(items):
        mp3_path = os.path.join(clips_dir, fname)
        try:
            wav16, dur_s = load_audio_16k(mp3_path)
            words, anchors, unaligned, modified = process_clip(
                model, tokenizer, aligner, wav16, dur_s, sentence, word2ix)
            results[fname] = {
                "sentence": sentence,
                "duration_s": round(dur_s, 3),
                "words": words,
                "anchor_candidates": anchors,
                "unaligned_tokens": unaligned,
                "modified_tokens": modified,
            }
            n_ok += 1
            n_unaligned += len(unaligned)
            n_modified += len(modified)
            cand_counts.append(len(anchors))
            if not anchors:
                n_zero_cand += 1
            for a in anchors:
                cand_word_freq[a["norm"]] = cand_word_freq.get(a["norm"], 0) + 1
        except Exception as e:
            n_fail += 1
            fails.append((fname, type(e).__name__, str(e)))
            results[fname] = {"sentence": sentence, "error": f"{type(e).__name__}: {e}"}

        if (k + 1) % 20 == 0 or k + 1 == len(items):
            print(f"  进度 {k+1}/{len(items)} | ok={n_ok} fail={n_fail}")

    with open(args.out, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # ---- 自检打印 ----
    total_cand = sum(cand_counts)
    print(f"\n=== 自检 ===")
    print(f"成功处理录音:          {n_ok}/{len(items)}")
    print(f"失败录音:              {n_fail}")
    print(f"不可对齐 token 总数:    {n_unaligned}(已记录在各录音 unaligned_tokens)")
    print(f"被规范化改写 token 总数: {n_modified}(已记录在 modified_tokens)")
    print(f"锚点候选总数:          {total_cand}")
    print(f"平均每条录音候选数:     {total_cand / n_ok:.2f}" if n_ok else "  (无成功录音)")
    print(f"0 候选的录音数:        {n_zero_cand}/{n_ok}(该录音没有可用目标词)")
    if cand_word_freq:
        top = sorted(cand_word_freq.items(), key=lambda x: -x[1])[:10]
        print(f"候选词命中分布(全部 ∈ 800 词表;top10 词频): {top}")
    if fails:
        print("\n失败样例(前 5):")
        for fn, et, msg in fails[:5]:
            print(f"  {fn}: {et}: {msg[:80]}")
    print(f"\n已写出: {args.out}")


if __name__ == "__main__":
    main()

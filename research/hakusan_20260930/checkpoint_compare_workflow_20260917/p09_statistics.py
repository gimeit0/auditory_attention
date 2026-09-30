"""P09: statistics and report from the accepted P08 full-run archive.

Read-only. Reads the frozen results through the pinned v3 reader (which re-verifies
the receipt, layout, declarations and the full-run inventory), then applies the
original v4 ``summarize_results(..., full_run=True)`` semantics unchanged: fixed
strata, target_speaker cluster bootstrap with the original seed rules, paired
differences per stratum, and cue-control summaries. Adds the approved P06-4 margin
upper bounds and the P06-5 error-budget check. No GPU, no SSH, no thresholds changed.
"""

import argparse
import csv
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V3_REVIEW = ROOT / "same_bank_compare_2026_09_19_full_v3/review_layouts.py"
FULL_LAYOUT_SHA = "c6aee22c91e0198b65a5c5d10537353cf490f37a4279ccc3f2e0d27204c0a469"
ENVELOPE_NLL = 2e-3  # P06-3, approved 2026-09-19
MAIN_PAIR = "formal40_vs_author_external"
PAIR_LABELS = {
    "formal40_vs_author_external": "formal40 − author（主表）",
    "formal40_vs_valbest33": "formal40 − valbest33（补充）",
    "valbest33_vs_author_external": "valbest33 − author（补充）",
}
STRATA_LABELS = {
    "overall": "全部 10,000", "mixed": "mixed 9,000", "clean": "clean 1,000",
    **{f"distractors_{k}": f"干扰数 {k}" for k in range(1, 5)},
    **{f"snr_bin_{k}": f"SNR 段 {k}（{-10 + 4 * k}~{-6 + 4 * k} dB）" for k in range(5)},
    "target_gender_female": "目标女声", "target_gender_male": "目标男声",
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(ok, message):
    if not ok:
        raise ValueError(message)


def compute(archive_dir, receipt_sha, repetitions=None):
    """Return the statistics record. ``repetitions`` is for synthetic tests only."""
    R = load("p09_review", V3_REVIEW)
    candidate, base = R.load_core()
    if repetitions is not None:
        base.BOOTSTRAP_REPETITIONS = int(repetitions)
    archive_dir = Path(archive_dir).absolute()
    archive = R.read_archive(candidate, base, archive_dir, receipt_sha, FULL_LAYOUT_SHA)
    run = archive["run"]
    require(run["layout_id"] == "full10k", "P09 requires the accepted full10k archive")
    results = archive["results"]
    summary = base.summarize_results(results, full_run=True)
    require(summary["bootstrap"]["performed"] is True, "Bootstrap must run for the full result")
    strata = R.margin_strata(candidate, archive)
    bounds = {
        m: strata["by_model_condition"][f"{m}__correct"]["within_envelope_fraction"]
        for m in candidate.MODEL_ORDER
    }
    budget = {}
    for pair, record in summary["paired_model_differences"].items():
        for name, s in record["strata"].items():
            ci = s["cross_entropy_improvement_b_minus_a_positive_favors_a"][
                "target_speaker_cluster_bootstrap_95ci"
            ]
            half = (ci[1] - ci[0]) / 2.0
            budget[f"{pair}/{name}"] = {
                "ci_half_width": half,
                "envelope_nll": ENVELOPE_NLL,
                "numeric_perturbation_negligible": ENVELOPE_NLL < half / 10.0,
            }
    return {
        "status": "P09_STATISTICS_COMPUTED",
        "computed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "role": candidate.ROLE,
        "source": {
            "archive": str(archive_dir),
            "job_id": run["job_id"],
            "receipt_sha256": receipt_sha,
            "results_csv_sha256": sha256(archive_dir / "results.csv"),
            "logits_npz_sha256": sha256(archive_dir / "logits.npz"),
            "candidate_sha256": run["candidate_sha256"],
            "v4_source_sha256": run["v4_source_sha256"],
            "predictions": archive["verification"]["model_condition_predictions"],
        },
        "v4_summary": summary,
        "p06_4_accuracy_uncertainty_upper_bound": bounds,
        "margin_strata": strata,
        "p06_5_error_budget": budget,
        "limitations": [
            "Reused validation/pilot bank audit; not an independent test set; no generalisation claim.",
            "author_external is a system-level external reference with its own native preprocessing.",
            "Accuracy differences carry the P06-4 numeric upper bound per model; NLL differences are checked against the P06-3 envelope (P06-5).",
            "The primary checkpoint (formal40) and the secondary (valbest33) were fixed before this evaluation and are not re-selected on these results.",
        ],
    }


def _ci(record):
    ci = record["target_speaker_cluster_bootstrap_95ci"]
    return f"{record['mean']:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]"


def render_markdown(stats):
    s = stats["v4_summary"]
    models = s["models"]
    lines = [
        "# P09 三模型比较统计（Job 728520 正式产物）",
        "",
        f"计算时间 {stats['computed_utc']}；研究身份 `{stats['role']}`；来源 results.csv SHA `{stats['source']['results_csv_sha256'][:16]}…`，logits SHA `{stats['source']['logits_npz_sha256'][:16]}…`，{stats['source']['predictions']} 条模型—条件预测。",
        f"bootstrap：单位 {s['bootstrap']['unit']}，{s['bootstrap']['repetitions']} 次，seed {s['bootstrap']['seed']}（原 v4 规则，分层偏移），分位数 {s['bootstrap']['quantile_method']}。",
        "",
        "## 1. 主结果：正确 cue 下的 Accuracy 与交叉熵（NLL）",
        "",
        "| 模型 | 角色 | Accuracy 全部 | mixed | clean | NLL 全部 | mixed | clean | P06-4 Accuracy 数值不确定性上界 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for m in ("formal40", "author_external", "valbest33"):
        st = models[m]["strata"]
        b = stats["p06_4_accuracy_uncertainty_upper_bound"][m]
        lines.append(
            f"| {m} | {models[m]['role']} | {st['overall']['accuracy']:.4f} | {st['mixed']['accuracy']:.4f} | {st['clean']['accuracy']:.4f} | {st['overall']['cross_entropy']:.4f} | {st['mixed']['cross_entropy']:.4f} | {st['clean']['cross_entropy']:.4f} | ±{b * 100:.2f} 个百分点 |"
        )
    lines += ["", "## 2. 配对差值与 95% 置信区间（target_speaker 成簇 bootstrap）", ""]
    for pair, label in PAIR_LABELS.items():
        rec = s["paired_model_differences"][pair]
        lines += [
            f"### {label}",
            "",
            "| 分层 | n | Accuracy 差（a−b，正值利于 a）[95% CI] | 交叉熵改善（b−a，正值利于 a）[95% CI] | P06-5 数值扰动可忽略 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for name in ("overall", "mixed", "clean", *[f"distractors_{k}" for k in range(1, 5)],
                     *[f"snr_bin_{k}" for k in range(5)], "target_gender_female", "target_gender_male"):
            if name not in rec["strata"]:
                continue
            r = rec["strata"][name]
            bud = stats["p06_5_error_budget"][f"{pair}/{name}"]
            lines.append(
                f"| {STRATA_LABELS.get(name, name)} | {r['trials']} | {_ci(r['accuracy_difference_a_minus_b_positive_favors_a'])} | {_ci(r['cross_entropy_improvement_b_minus_a_positive_favors_a'])} | {'是' if bud['numeric_perturbation_negligible'] else '否（CI 半宽 ' + format(bud['ci_half_width'], '.2e') + '）'} |"
            )
        lines.append("")
    lines += [
        "## 3. 干扰数 × SNR 段细胞（主表 formal40 − author，交叉熵改善 [95% CI]）",
        "",
        "| 干扰数 \\ SNR 段 | " + " | ".join(f"段 {k}" for k in range(5)) + " |",
        "| --- | " + " | ".join("---" for _ in range(5)) + " |",
    ]
    main = s["paired_model_differences"][MAIN_PAIR]["strata"]
    for count in range(1, 5):
        cells = []
        for k in range(5):
            key = f"distractors_{count}__snr_bin_{k}"
            cells.append(_ci(main[key]["cross_entropy_improvement_b_minus_a_positive_favors_a"]) if key in main else "—")
        lines.append(f"| {count} | " + " | ".join(cells) + " |")
    lines += ["", "## 4. Cue controls（2,000 条 control 子集）", "",
              "| 模型 | correct Acc | shuffled Acc | silent Acc | distractor Acc | correct−shuffled [CI] | correct−silent [CI] | correct−distractor [CI] | distractor cue 下 probe 概率变化 [CI] |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for m in ("formal40", "author_external", "valbest33"):
        c = models[m]["cue_controls"]
        lines.append(
            f"| {m} | {c['correct_accuracy']:.4f} | {c['shuffled_accuracy']:.4f} | {c['silent_accuracy']:.4f} | {c['distractor_accuracy']:.4f} | {_ci(c['correct_minus_shuffled'])} | {_ci(c['correct_minus_silent'])} | {_ci(c['correct_minus_distractor'])} | {_ci(c['distractor_cue_p_probe_delta'])} |"
        )
    lines += ["", "## 5. 数值资格、数据复用与预处理差异（独立说明）", ""]
    for item in stats["limitations"]:
        lines.append(f"- {item}")
    lines += [
        f"- P06-3 包络 NLL {ENVELOPE_NLL:g}：全量两次运行（728378/728520）48,000 条预测逐位一致；批形状扰动不进入本表。",
        "- P06-4 上界 = correct cue 中 top1−top2 logit margin ≤ 4e-3 的比例；本表 Accuracy 差值应与该上界并列解读。",
        "- P06-5：交叉熵差的 CI 半宽 ≥ 10× 包络时记“可忽略”。",
        "",
    ]
    return "\n".join(lines)


def write_outputs(stats, output):
    output = Path(output).absolute()
    output.mkdir(mode=0o700)
    payload = (json.dumps(stats, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with (output / "STATISTICS.json").open("xb") as h:
        h.write(payload)
    with (output / "REPORT.md").open("x", encoding="utf-8") as h:
        h.write(render_markdown(stats))
    with (output / "paired_strata.csv").open("x", newline="") as h:
        w = csv.writer(h)
        w.writerow(["pair", "stratum", "trials", "metric", "mean", "ci_low", "ci_high", "unique_target_speakers"])
        for pair, record in stats["v4_summary"]["paired_model_differences"].items():
            for name, r in record["strata"].items():
                for metric in ("accuracy_difference_a_minus_b_positive_favors_a", "cross_entropy_improvement_b_minus_a_positive_favors_a"):
                    v = r[metric]
                    w.writerow([pair, name, r["trials"], metric, v["mean"], *v["target_speaker_cluster_bootstrap_95ci"], v["unique_target_speakers"]])
    return {"statistics_sha256": hashlib.sha256(payload).hexdigest(), "output": str(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stats = compute(args.archive, args.receipt_sha256)
    print(json.dumps(write_outputs(stats, args.output), indent=2))


if __name__ == "__main__":
    main()

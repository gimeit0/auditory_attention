"""Offline review of Job725677; adds signed NLL summaries without changing gates."""

import argparse
import csv
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
REVIEW_SHA = "49076fd6d9436ba2af2179cdb376836e263e72079197c0a4fa618c6f6c06fd95"
RELEASE_SHA = "d534169c3f437df0d6b7434f2187a870b62ee4bc186d59886f73c1bd71f31747"
COMPLETE_SHA = "ee3826ef1865b0d723e1960fb4e5a4341d19c7df335e1c940268d50af95c2d7d"
RECEIPTS = {
    "s1": "58f1fc6953c4732955efcadcbf7adbf543738936672639d929d0ef5359f00027",
    "repeat16": "695b789f8436f2fe4b9c87c2667274846982fef13e75a0e633eeb44339f693d8",
    "batch1": "d099a1571c8a3a0375c26fefc74ad94ea3835092224d726c897189a5d3fbbd74",
}
BASELINE = (
    PROJECT
    / "docs/superpowers/evidence/eager-small-production-20260917/collect-724808-8lr7w3yd/archive/attempts/slurm-724808"
)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def signed_difference(left, right):
    """LEFT minus RIGHT; descriptive population SD, not a standard error."""
    a, b = np.asarray(left, dtype=np.float64), np.asarray(right, dtype=np.float64)
    require(
        a.ndim == b.ndim == 1 and a.shape == b.shape,
        "One-dimensional paired arrays required",
    )
    require(np.isfinite(a).all() and np.isfinite(b).all(), "Nonfinite NLL")
    d = a - b
    require(np.isfinite(d).all(), "Nonfinite difference")
    return {
        "direction": "left_nll_minus_right_nll",
        "count": int(d.size),
        "std_ddof": 0,
        "mean": float(d.mean()) if d.size else None,
        "std": float(d.std(ddof=0)) if d.size else None,
        "max_abs": float(np.abs(d).max()) if d.size else None,
        "positive_count": int((d > 0).sum()),
        "negative_count": int((d < 0).sum()),
        "zero_count": int((d == 0).sum()),
    }


def verify_collection(folder):
    report = read(folder / "RESULT.json")
    require(
        report["action"] == "collect" and report["rc"] == 0 and report["result"]["ok"],
        "Collection failed",
    )
    require(report["release_sha256"] == RELEASE_SHA, "Wrong collected release")
    result = report["result"]["result"]
    root = folder / "archive"
    actual = set()
    for p in root.rglob("*"):
        require(not p.is_symlink(), "Archive symlink")
        if p.is_file():
            actual.add(str(p.relative_to(root)))
    require(actual == set(result["files"]), "Collection inventory differs")
    for name, item in result["files"].items():
        p = Path(name)
        require(not p.is_absolute() and ".." not in p.parts, "Unsafe path")
        require(sha(root / p) == item["sha256"], "Collected file changed: " + name)
    require(sha(root / "RELEASE.json") == RELEASE_SHA, "Release changed")
    release = read(root / "RELEASE.json")
    for name, digest in release["files"].items():
        require(
            Path(name).name == name and sha(root / "tools" / name) == digest,
            "Frozen source changed",
        )
    require(
        sha(root / "state/COMPLETE.json") == COMPLETE_SHA,
        "External terminal hash differs",
    )
    terminal = read(root / "state/COMPLETE.json")
    require(
        terminal["status"] == "S2A_EXECUTION_COMPLETE_NOT_QUALIFIED"
        and terminal["job_id"] == "725677"
        and terminal["release_sha256"] == RELEASE_SHA
        and terminal["baseline_receipt_sha256"] == RECEIPTS["s1"],
        "Terminal identity differs",
    )
    query = result["query"]
    row = query["accounting"]["stdout"].strip().split("|")
    require(
        query["accounting"]["rc"] == 0
        and len(row) == 9
        and row[:4] == ["725677", "COMPLETED", "0:0", "00:03:30"]
        and row[4:6] == ["2026-09-18T08:25:14", "2026-09-18T08:28:44"]
        and row[8] == "spcc-a100g02",
        "Independent Slurm terminal differs",
    )
    expected = {
        "billing": "8",
        "cpu": "8",
        "gres/gpu:nvidia_a100": "1",
        "mem": "64G",
        "node": "1",
    }
    for text in row[6:8]:
        require(
            dict(item.split("=", 1) for item in text.split(",")) == expected,
            "Slurm resources differ",
        )
    require(not (root / "state/FAILED.json").exists(), "Failure marker present")
    require(query["COMPLETE.json"]["sha256"] == COMPLETE_SHA, "Query terminal differs")
    return (
        root,
        terminal,
        {
            "files": len(actual),
            "collection_record_sha256": sha(folder / "RESULT.json"),
            "accounting": row,
            "terminal_sha256": COMPLETE_SHA,
        },
    )


def supplement(candidate, left, right, report, comparison):
    rows = []
    for condition in candidate.CONDITIONS:
        mask = (
            np.ones(len(left["bank"]), dtype=bool)
            if condition == "correct"
            else left["bank"].control_subset.to_numpy(dtype=int) == 1
        )
        ids = left["bank"].loc[mask, "trial_id"].to_numpy(dtype=int)
        for model in candidate.MODEL_ORDER:
            key = model + "__" + condition
            prefix = model if condition == "correct" else model + "_" + condition
            a = left["results"].loc[mask, prefix + "_nll"].to_numpy(dtype=float)
            b = right["results"].loc[mask, prefix + "_nll"].to_numpy(dtype=float)
            values = signed_difference(a, b)
            report["by_model_condition"][key]["nll_signed_diff_left_minus_right"] = (
                values
            )
            old = report["by_model_condition"][key]
            require(
                np.isclose(values["mean"], -old["mean_nll_change"], atol=1e-15, rtol=0),
                "Mean sign differs",
            )
            require(values["max_abs"] == old["nll_abs_diff"]["maximum"], "Max differs")
            for trial, x, y in zip(ids, a, b, strict=True):
                rows.append(
                    {
                        "comparison": comparison,
                        "model": model,
                        "condition": condition,
                        "trial_id": int(trial),
                        "left_nll": float(x),
                        "right_nll": float(y),
                        "left_minus_right": float(x - y),
                    }
                )
    report["signed_nll_note"] = (
        "Signed supplement is LEFT minus RIGHT (batch16 minus batch1 for batch-size); original mean_nll_change remains RIGHT minus LEFT. std uses ddof=0, descriptive only. No automatic acceptance."
    )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(
        not args.output.exists() and not args.output.is_symlink(),
        "Output already exists",
    )
    require(sha(HERE / "review_runs.py") == REVIEW_SHA, "Original reader changed")
    spec = importlib.util.spec_from_file_location(
        "pinned_s2_reader", HERE / "review_runs.py"
    )
    review = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(review)
    root, terminal, verification = verify_collection(args.collection)
    candidate, base = review.load_core()
    parent = root / "attempts/slurm-725677"
    archives = {"s1": review.read_archive(candidate, base, BASELINE, RECEIPTS["s1"])}
    require(
        [r["stage"] for r in terminal["children"]] == ["repeat16", "batch1"],
        "Wrong stages",
    )
    for item in terminal["children"]:
        stage = item["stage"]
        require(item["receipt_sha256"] == RECEIPTS[stage], "External receipt differs")
        a = review.read_archive(candidate, base, parent / stage, RECEIPTS[stage])
        run = a["run"]
        process = read(parent / (stage + "_PROCESS.json"))
        ended = read(parent / (stage + "_EXIT.json"))
        require(
            ended["rc"] == 0
            and ended["pid"] == process["pid"] == item["pid"] == run["pid"]
            and run["job_id"] == "725677"
            and run["environment"]["hostname"] == row_host(verification)
            and run["batch_size"] == item["batch_size"] == process["batch_size"]
            and run["started_utc"] == item["started_utc"],
            "Process identity differs",
        )
        require(
            a["verification"]["model_condition_predictions"] == 159,
            "Prediction count differs",
        )
        archives[stage] = a
    require(
        terminal["children"][0]["pid"] != terminal["children"][1]["pid"], "Same process"
    )
    require(
        dt.datetime.fromisoformat(read(parent / "repeat16_EXIT.json")["ended_utc"])
        <= dt.datetime.fromisoformat(
            read(parent / "batch1_PROCESS.json")["started_utc"]
        ),
        "Not sequential",
    )
    reports, rows = {}, []
    for name, kind, lkey, rkey in [
        ("cold_repeat", "cold-repeat", "s1", "repeat16"),
        ("batch16_vs_1", "batch-size", "repeat16", "batch1"),
        ("s1_vs_batch1", "batch-size", "s1", "batch1"),
    ]:
        report = review.compare_archives(
            candidate, base, archives[lkey], archives[rkey], kind
        )
        rows += supplement(candidate, archives[lkey], archives[rkey], report, name)
        reports[name] = report
    args.output.mkdir(mode=0o700)

    def save(name, value):
        with (args.output / name).open("x") as f:
            json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
            f.write("\n")

    for name, report in reports.items():
        save(name + ".json", report)
    with (args.output / "paired_nll_differences.csv").open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    save(
        "INDEPENDENT_REVIEW.json",
        dict(
            verification,
            status="ARTIFACTS_RECOMPUTED_AND_NUMERIC_DIFFERENCES_RECORDED",
            job_id="725677",
            scope="original32, seven control trials; three fixed models; not full10k",
            scientific_qualification="NOT_DECIDED",
            full_run_authorized=False,
            receipt_sha256=RECEIPTS,
            verifier_sha256=REVIEW_SHA,
            supplement_sha256=sha(__file__),
            created_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
            runs={k: v["verification"] for k, v in archives.items()},
            report_sha256={p.name: sha(p) for p in args.output.iterdir()},
        ),
    )
    print("INDEPENDENT_REVIEW=" + str(args.output))
    for name, report in reports.items():
        print(name, json.dumps(report["legacy_v4_result_table_canary_1e_6"]))


def row_host(verification):
    return verification["accounting"][8]


if __name__ == "__main__":
    main()

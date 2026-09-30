"""Single model or independent verifier worker. No submission/retry commands."""

import argparse
import csv
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import runpy
import sys
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("p05b_sequence", HERE / "sequence.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


def model(args):
    batch = 1 if args.stage == "cold1" else 16
    with tempfile.TemporaryDirectory(
        prefix="p05b-" + args.stage + "-", dir="/tmp"
    ) as scratch:
        # Separate Python process and scratch for every checkpoint-loading unit.
        # Eager candidate creates its own per-process cache directories underneath.
        print(
            json.dumps({"stage": args.stage, "pid": os.getpid(), "scratch": scratch}),
            flush=True,
        )
        candidate = HERE / "eager_compare.py"
        sys.argv = [
            str(candidate),
            "run-layout",
            "--output",
            str(args.parent / args.stage),
            "--scratch-parent",
            scratch,
            "--expected-candidate-sha256",
            S.PINNED["same_bank_compare_2026_09_18_layout_v1/eager_compare.py"],
            "--confirm",
            "same_bank_eager_fp32_layout_20260918_v1",
            "--layout",
            args.stage,
            "--expected-layout-sha256",
            S.LAYOUT_SHAS[args.stage],
            "--batch-size",
            str(batch),
        ]
        runpy.run_path(str(candidate), run_name="__main__")


def summarize_reports(stage, model_pid, receipt_sha, reports):
    expected_names = {
        "bridge16": {"repeat"},
        "cold1": {"repeat", "vs_bridge16"},
        "peers16": {"vs_bridge16", "vs_cold1"},
        "tail17": {"vs_bridge16", "vs_cold1"},
    }
    S.require(
        stage in expected_names and set(reports) == expected_names[stage],
        "Incomplete comparison reports",
    )
    expected_groups = {
        f"{m}__{c}"
        for m in ("formal40", "author_external", "valbest33")
        for c in ("correct", "shuffled", "silent", "distractor")
    }
    for report in reports.values():
        S.require(
            set(report["by_model_condition"]) == expected_groups,
            "Incomplete model/condition report",
        )
        S.require(
            report["status"] == "NUMERIC_SENSITIVITY_RECORDED"
            and report["full_run_authorized"] is False,
            "Unexpected comparison status",
        )
    fixed = stage in ("bridge16", "cold1")
    repeat = reports["repeat"] if fixed else None
    return {
        "stage": stage,
        "status": "RECOMPUTED_NOT_QUALIFIED",
        "model_pid": model_pid,
        "receipt_sha256": receipt_sha,
        "artifact_verified": True,
        "full_run_authorized": False,
        "fixed_configuration_logits_equal": all(
            v["logits_bitwise_equal"] for v in repeat["by_model_condition"].values()
        )
        if fixed
        else None,
        "repeat_result_table_canary": repeat["legacy_v4_result_table_canary_1e_6"][
            "status"
        ]
        if fixed
        else None,
        "comparison_names": list(reports),
        "scientific_qualification": "NOT_DECIDED",
    }


def verify(args, contract):
    R = S.load_module(HERE / "review_layouts.py", "p05b_worker_review")
    candidate, base = R.load_core()
    current = R.read_archive(
        candidate,
        base,
        args.parent / args.stage,
        args.receipt_sha256,
        S.LAYOUT_SHAS[args.stage],
    )
    process = S.read(args.parent / f"{args.stage}.model.PROCESS.json")
    exit_record = S.read(args.parent / f"{args.stage}.model.EXIT.json")
    run = current["run"]
    S.require(
        exit_record["rc"] == 0 and exit_record["interrupted"] is False,
        "Model execution not complete",
    )
    S.require(
        run["pid"] == process["pid"] == exit_record["pid"]
        and run["job_id"] == contract["job_id"]
        and run["environment"]["hostname"] == platform.node(),
        "Actual model identity differs",
    )
    reports = {}
    if args.stage in S.BASELINES:
        directory, digest = S.BASELINES[args.stage]
        baseline = R.read_baseline(S.BASELINE_ROOT / directory, digest)
        reports["repeat"] = R.compare_archives(
            candidate,
            base,
            baseline,
            current,
            "bridge" if args.stage == "bridge16" else "cold-repeat",
        )
    if args.stage != "bridge16":
        for name in ("bridge16",) if args.stage == "cold1" else ("bridge16", "cold1"):
            previous = S.read(args.parent / f"{name}.review.json")
            S.check_gate(previous, name)
            archive = R.read_archive(
                candidate,
                base,
                args.parent / name,
                previous["receipt_sha256"],
                S.LAYOUT_SHAS[name],
            )
            kind = {"cold1": "batch-size", "peers16": "peers", "tail17": "tail"}[
                args.stage
            ]
            reports["vs_" + name] = R.compare_archives(
                candidate, base, archive, current, kind
            )
    for name, report in reports.items():
        candidate.create_json(
            args.parent / f"{args.stage}.{name}.comparison.json", report
        )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=(
            "comparison",
            "trial_id",
            "model",
            "condition",
            "left_nll",
            "right_nll",
            "diff",
        ),
    )
    writer.writeheader()
    for name, report in reports.items():
        writer.writerows(
            dict(row, comparison=name) for row in report["paired_nll_rows"]
        )
    candidate.create_bytes(
        args.parent / f"{args.stage}.paired_nll.csv", stream.getvalue().encode()
    )
    summary = summarize_reports(args.stage, run["pid"], args.receipt_sha256, reports)
    S.write(args.parent / f"{args.stage}.review.json", summary)
    # Keep a repeat DIFF report durable before terminating the qualification batch.
    S.check_gate(summary, args.stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("model", "verify"))
    parser.add_argument("--stage", choices=S.STAGES, required=True)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--receipt-sha256")
    args = parser.parse_args()
    contract, _ = S.native_context(args.contract, args.contract_sha256)
    S.require(
        args.parent.absolute()
        == S.REMOTE_ROOT / "attempts" / ("slurm-" + contract["job_id"]),
        "Wrong attempt directory",
    )
    S.safe(args.parent, directory=True)
    S.safe(args.parent / f"{args.stage}.{args.operation}.INTENT.json")
    if args.operation == "model":
        S.require(args.receipt_sha256 is None, "No receipt expected before execution")
        model(args)
    else:
        S.require(
            args.receipt_sha256 is not None, "External model receipt SHA required"
        )
        verify(args, contract)
    S.check_contract(args.contract, args.contract_sha256)


if __name__ == "__main__":
    main()

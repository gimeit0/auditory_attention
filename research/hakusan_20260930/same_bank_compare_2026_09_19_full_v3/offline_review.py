"""One-command P08full offline recomputation. No SSH, models, or GPU execution.

Recomputes every declared comparison from archived logits, checks the saved
worker summaries against that recomputation, and aggregates P07 cost records.
"""

import argparse
import csv
import datetime as dt
import importlib.util
import io
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("p08full_offline_control", HERE / "control.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
S = M.S


def accounting(path, expected, release_sha, job):
    S.require(S.sha(path) == expected, "External accounting evidence SHA differs")
    record = S.read(path)
    S.require(
        record["rc"] == 0
        and record["action"] == "status"
        and record["release_sha256"] == release_sha
        and record["response"]["ok"] is True,
        "Successful bound status evidence required",
    )
    result = record["response"]["result"]
    value = result["accounting"]
    S.require(result["job_id"] == job and value["rc"] == 0, "Accounting job differs")
    rows = [r.split("|") for r in value["stdout"].strip().splitlines()]
    S.require(len(rows) == 1 and len(rows[0]) == 5 and rows[0][0] == job, "Accounting row differs")
    return rows[0]


def checked_terminal(source, expected):
    before = S.inventory(source)
    names = [n for n in ("COMPLETE.json", "FAILED.json") if n in before["files"]]
    S.require(len(names) == 1, "Exactly one terminal record required")
    name = names[0]
    S.require(S.sha(source / name) == expected, "External terminal SHA differs")
    terminal = S.read(source / name)
    body = {
        "directories": before["directories"],
        "files": {n: r for n, r in before["files"].items() if n != name},
    }
    S.require(
        terminal["protocol"] == S.PROTOCOL
        and terminal["full_run_authorized"] is False
        and terminal["inventory"] == body,
        "Terminal inventory/protocol differs",
    )
    wanted = "EXECUTION_FAILED" if name == "FAILED.json" else "EXECUTION_COMPLETE_NOT_QUALIFIED"
    S.require(terminal["status"] == wanted, "Terminal status differs")
    return terminal, before


def stage_seconds(log_path):
    """Parse STAGE_SECONDS lines of a model stdout log into a cost summary."""
    timings = {}
    for line in S.safe(log_path).read_text(errors="replace").splitlines():
        match = re.fullmatch(r"STAGE_SECONDS=([^:]+):([0-9.]+)", line.strip())
        if match:
            timings[match.group(1)] = float(match.group(2))
    forward = {k: v for k, v in timings.items() if k.startswith("forward/")}
    by_condition, by_model = {}, {}
    for key, value in forward.items():
        _, _, condition, model_id = key.split("/")
        by_condition[condition] = by_condition.get(condition, 0.0) + value
        by_model[model_id] = by_model.get(model_id, 0.0) + value
    return {
        "runtime": timings.get("runtime"),
        "verify_frozen_inputs": timings.get("verify_frozen_inputs"),
        "strict_load": {
            k.split("/")[1]: v for k, v in timings.items() if k.startswith("strict_load/")
        },
        "shared_scene_and_prediction": timings.get("shared_scene_and_prediction"),
        "save_and_independent_reload": timings.get("save_and_independent_reload"),
        "postcheck_frozen_inputs": timings.get("postcheck_frozen_inputs"),
        "forward_total": sum(forward.values()),
        "forward_calls": len(forward),
        "forward_by_condition": by_condition,
        "forward_by_model": by_model,
    }


def recompute(source, terminal_sha, release_file, release_sha, job,
              baseline_root, status_file, status_sha, output):
    source = S.safe(source, directory=True)
    release = M.decode(M.C.read(release_file), release_sha)
    for name, digest in release["files"].items():
        S.require(S.sha(S.PROJECT / name) == digest, "Review package changed: " + name)
    terminal, before = checked_terminal(source, terminal_sha)
    expected_contract = M.digest(S.wire(M.contract(release, job)))
    S.require(
        terminal["provenance"]["job_id"] == job
        and terminal["provenance"]["contract_sha256"] == expected_contract,
        "Terminal contract/job differs",
    )
    row = accounting(status_file, status_sha, release_sha, job)
    output = Path(output).absolute()
    S.safe(output.parent, directory=True)
    S.require(
        not output.is_relative_to(source)
        and not output.is_relative_to(Path(baseline_root).absolute()),
        "Output must not modify source trees",
    )
    output.mkdir(mode=0o700)
    S.write(
        output / "START.json",
        dict(source=str(source), terminal_sha256=terminal_sha, release_sha256=release_sha,
             accounting_sha256=status_sha, job_id=job),
    )
    try:
        if terminal["status"] == "EXECUTION_FAILED":
            S.require(row[1] not in ("PENDING", "RUNNING", "COMPLETING"), "Accounting not terminal")
            result = dict(status="FAILED_RUN_RECORDED_NO_NUMERIC_QUALIFICATION", full_run_authorized=False,
                          job_id=job, terminal_status=terminal["status"], accounting=row)
        else:
            S.require(row[1:3] == ["COMPLETED", "0:0"], "Successful terminal accounting required")
            result = compare_all(source, baseline_root, terminal, job, output, row[4])
            result["accounting"] = row
        S.require(S.inventory(source) == before, "Source changed during review")
        S.write(output / "REPORT.json", result)
        return result
    except Exception as error:
        S.write(output / "REVIEW_FAILED.json",
                dict(status="REVIEW_FAILED", error=str(error), full_run_authorized=False))
        raise


def compare_all(source, baseline_root, terminal, job, output, node=None):
    R = S.load_module(HERE / "review_layouts.py", "p08full_offline_reader")
    W = S.load_module(HERE / "sequence_worker.py", "p08full_offline_summary")
    candidate, base = R.load_core()
    children = terminal["children"]
    S.require([c["stage"] for c in children] == list(S.STAGES), "Missing/duplicate/reordered stage")
    archives, reports, summaries, pids, cost = {}, {}, {}, [], {}
    previous_end = None
    for child in children:
        stage = child["stage"]
        archive = R.read_archive(candidate, base, source / stage, child["receipt_sha256"], S.LAYOUT_SHAS[stage])
        run = archive["run"]
        if node is not None:
            S.require(run["environment"]["hostname"] == node, "Accounting node differs from model environment")
        for operation in ("model", "verify"):
            name = stage + "." + operation
            process = S.read(source / (name + ".PROCESS.json"))
            exit_record = S.read(source / (name + ".EXIT.json"))
            S.require(process["pid"] == exit_record["pid"] and exit_record["rc"] == 0
                      and exit_record["interrupted"] is False, "Process failed or identity changed")
            start = dt.datetime.fromisoformat(process["started_utc"])
            end = dt.datetime.fromisoformat(exit_record["ended_utc"])
            S.require(start.tzinfo is not None and end.tzinfo is not None and end >= start
                      and (previous_end is None or start >= previous_end), "Processes not sequential")
            previous_end = end
            if operation == "model":
                S.require(run["pid"] == process["pid"] == child["model_pid"] and run["job_id"] == job,
                          "Model/job identity differs")
                pids.append(run["pid"])
                cost[stage] = {
                    "process_wall_seconds": (end - start).total_seconds(),
                    "stage_seconds": stage_seconds(source / (name + ".stdout.log")),
                    "profile": S.read(source / stage / "PROFILE.json"),
                }
        archives[stage] = archive
        paired = {}
        for name, (left_name, kind) in S.COMPARISONS[stage].items():
            if left_name == "baseline":
                directory, digest = S.BASELINES[stage]
                left = R.read_baseline(Path(baseline_root) / directory, digest, S.BASELINE_LAYOUT_SHAS[stage])
            else:
                left = archives[left_name]
            paired[name] = R.compare_archives(candidate, base, left, archive, kind)
        summary = W.summarize_reports(stage, run["pid"], child["receipt_sha256"], paired,
                                      R.margin_strata(candidate, archive))
        S.require(S.sha(source / (stage + ".review.json")) == child["review_sha256"], "Saved review SHA differs")
        S.require(S.read(source / (stage + ".review.json")) == summary,
                  "Saved summary differs from independent recomputation")
        # Fixed-configuration repeat mismatch remains a hard stop, no tolerance changes.
        S.check_gate(summary, stage)
        summaries[stage] = summary
        for name, report in paired.items():
            key = stage + "." + name
            reports[key] = report
            S.write(output / (key + ".json"), report)
    S.require(len(set(pids)) == len(S.STAGES), "Distinct model processes required")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=["comparison", "trial_id", "model", "condition", "left_nll", "right_nll", "diff"])
    writer.writeheader()
    for name, report in reports.items():
        writer.writerows(dict(row, comparison=name) for row in report["paired_nll_rows"])
    M.C.write(output / "paired_nll.csv", stream.getvalue().encode())
    exceeded = [s for s, v in summaries.items() if v["envelope"] and any(
        not e["within_envelope"] for e in v["envelope"].values())]
    predictions = {s: a["verification"]["model_condition_predictions"] for s, a in archives.items()}
    return dict(status="P08FULL_OFFLINE_RECOMPUTED_NOT_QUALIFIED", job_id=job, summaries=summaries,
                predictions=predictions,
                comparisons=list(reports), paired_rows=sum(len(r["paired_nll_rows"]) for r in reports.values()),
                envelope_exceeded_stages=exceeded, cost=cost,
                full_run_authorized=False, scientific_qualification="NOT_DECIDED",
                limitation="Full frozen 10k bank in original order plus in-job 32-trial self-check; reused validation bank audit, not an independent test set; statistics (P09) are not computed here.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "release-file", "baseline-root", "status-file", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("terminal-sha256", "release-sha256", "job-id", "status-sha256"):
        parser.add_argument("--" + name, required=True)
    a = parser.parse_args()
    result = recompute(a.source, a.terminal_sha256, a.release_file, a.release_sha256,
                       a.job_id, a.baseline_root, a.status_file, a.status_sha256, a.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

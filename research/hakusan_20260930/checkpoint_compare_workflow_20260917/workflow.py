#!/usr/bin/env python3
"""Local-only workflow entry; records real test logs. Cannot submit any job."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "same_bank_compare_2026_09_17_eager_v1"
V4 = ROOT / "same_bank_eval_2026_08_29_v4"
PLAN = ROOT / "2026-09-17_checkpoint对比_可执行详细计划与进度.md"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory():
    files = {}
    for line in (PACKAGE / "candidate-files.sha256").read_text().splitlines():
        expected, name = line.split(maxsplit=1)
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe candidate manifest entry")
        path = PACKAGE / relative
        if path.is_symlink() or digest(path) != expected:
            raise ValueError(f"Candidate changed: {name}")
        files[str(path.relative_to(ROOT))] = expected
    for name, expected in {
        "locked_same_bank_eval.py": "31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4",
        "run_locked_same_bank_eval.sbatch": "b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495",
    }.items():
        path = V4 / name
        if path.is_symlink() or digest(path) != expected:
            raise ValueError(f"Original v4 changed: {name}")
        files[str(path.relative_to(ROOT))] = expected
    for path in (Path(__file__), Path(__file__).with_name("review_runs.py")):
        files[str(path.relative_to(ROOT))] = digest(path)
    for path in sorted(Path(__file__).parent.joinpath("tests").glob("test_*.py")):
        files[str(path.relative_to(ROOT))] = digest(path)
    return files


def save(path, payload):
    with path.open("xb") as handle:
        handle.write(payload)


def local_check():
    before = inventory()
    evidence = ROOT / "docs/superpowers/evidence/eager-local-execution-20260917"
    evidence.mkdir(mode=0o700, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = Path(tempfile.mkdtemp(prefix=stamp + "-", dir=evidence))
    commands = [
        (
            "candidate_tests",
            [
                sys.executable,
                "-B",
                "-m",
                "unittest",
                "discover",
                "-s",
                str(PACKAGE / "tests"),
                "-v",
            ],
        ),
        (
            "original_v4_tests",
            [
                sys.executable,
                "-B",
                "-m",
                "unittest",
                "discover",
                "-s",
                str(V4),
                "-p",
                "test_locked_same_bank_eval.py",
                "-v",
            ],
        ),
        (
            "workflow_tests",
            [
                sys.executable,
                "-B",
                "-m",
                "unittest",
                "discover",
                "-s",
                str(Path(__file__).parent / "tests"),
                "-v",
            ],
        ),
        (
            "candidate_help",
            [sys.executable, "-I", "-B", str(PACKAGE / "eager_compare.py"), "--help"],
        ),
        (
            "review_help",
            [
                sys.executable,
                "-I",
                "-B",
                str(Path(__file__).with_name("review_runs.py")),
                "--help",
            ],
        ),
    ]
    report = {
        "status": "LOCAL_CHECKS_RUNNING",
        "python": platform.python_version(),
        "executable": sys.executable,
        "platform": platform.platform(),
        "sources": before,
        "steps": [],
        "jobs_submitted": 0,
        "production_model_loaded": False,
        "native_gpu_qualification": False,
    }
    print(f"LOCAL_EVIDENCE={output}", flush=True)
    for name, command in commands:
        print(f"LOCAL_CHECK_BEGIN={name}", flush=True)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=120,
                check=False,
            )
            payload, rc = completed.stdout, completed.returncode
        except subprocess.TimeoutExpired as error:
            payload, rc = (
                (error.stdout or b"") + b"\nLOCAL_CHECK_TIMEOUT_120_SECONDS\n",
                124,
            )
        logfile = output / f"{name}.log"
        save(logfile, payload)
        tests_run = None
        minimum_tests = {
            "candidate_tests": 21,
            "original_v4_tests": 56,
            "workflow_tests": 12,
        }
        if name in minimum_tests:
            matches = re.findall(rb"Ran (\d+) tests? in", payload)
            tests_run = int(matches[-1]) if matches else 0
            if tests_run < minimum_tests[name]:
                rc = 2
        report["steps"].append(
            {
                "name": name,
                "command": command,
                "returncode": rc,
                "elapsed_seconds": time.monotonic() - started,
                "log": logfile.name,
                "log_sha256": digest(logfile),
                "tests_run": tests_run,
            }
        )
        print(payload.decode("utf-8", errors="replace"), end="", flush=True)
        if rc:
            report["status"] = "LOCAL_CHECKS_FAILED"
            break
    else:
        if inventory() != before:
            report["status"] = "LOCAL_SOURCES_CHANGED_DURING_CHECK"
        else:
            report["status"] = "LOCAL_CHECKS_PASS"
    save(
        output / "REPORT.json",
        (json.dumps(report, indent=2, sort_keys=True) + "\n").encode(),
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(output / "REPORT.json"),
                "report_sha256": digest(output / "REPORT.json"),
                "jobs_submitted": 0,
            }
        ),
        flush=True,
    )
    return 0 if report["status"] == "LOCAL_CHECKS_PASS" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("local-check", "plan"))
    args = parser.parse_args()
    if args.action == "plan":
        print(PLAN.read_text())
        return 0
    return local_check()


if __name__ == "__main__":
    raise SystemExit(main())

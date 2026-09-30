"""Allocated-node wrapper. Preserve full errors; never initialize Torch early."""

import faulthandler
import importlib.util
import json
import os
from pathlib import Path
import runpy
import signal
import sys
import tempfile
import traceback


def main():
    here = Path(__file__).absolute().parent
    spec = importlib.util.spec_from_file_location(
        "small_launch_control", here / "remote_control.py"
    )
    c = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(c)
    digest = sys.argv[1]
    c.require(
        sys.flags.isolated and sys.dont_write_bytecode and sys.platform == "linux",
        "Use native Python -I -B",
    )
    c.require(
        os.environ.get("CUBLAS_WORKSPACE_CONFIG") == ":4096:8",
        "CUBLAS must be set before Python",
    )
    c.require(os.environ.get("HOME") == "/home/s2510040", "HOME must remain original")
    release = c.checked(digest)
    receipt = json.loads(c.read(c.ROOT / "state/SUBMISSION.json"))
    job = os.environ.get("SLURM_JOB_ID")
    c.require(
        job == receipt["job_id"] and receipt["release_sha256"] == digest,
        "Wrong job/release",
    )
    c.require((c.ROOT / "state/RELEASE_INTENT.json").is_file(), "No authorized release")
    info = c.command(["/usr/bin/scontrol", "-o", "show", "job", job])
    c.validate_job(c.successful(info), release, job, held=False)
    c.require(
        os.environ.get("SLURM_CPUS_PER_TASK") == "8"
        and os.environ.get("SLURM_NTASKS") == "1",
        "Task allocation differs",
    )
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",")
    c.require(
        len(visible) == 1 and bool(visible[0].strip()), "Expected one visible GPU"
    )
    c.write(
        c.ROOT / "state/LAUNCH.json",
        c.wire(
            {
                "job_id": job,
                "pid": os.getpid(),
                "time_utc": c.now(),
                "release_sha256": digest,
                "allocation": info,
                "environment": {
                    k: os.environ.get(k)
                    for k in (
                        "HOME",
                        "CUBLAS_WORKSPACE_CONFIG",
                        "CUDA_VISIBLE_DEVICES",
                        "SLURM_CPUS_PER_TASK",
                        "SLURM_NTASKS",
                    )
                },
            }
        ),
    )
    faulthandler.enable()
    faulthandler.dump_traceback_later(300, repeat=True)

    def terminated(signum, frame):
        faulthandler.dump_traceback()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminated)
    with tempfile.TemporaryDirectory(
        prefix="eager-s1-" + job + "-", dir="/tmp"
    ) as scratch:
        print("ALLOCATED_SCRATCH=" + scratch, flush=True)
        sys.argv = [
            str(here / "eager_compare.py"),
            "run-small",
            "--output",
            str(c.ROOT / "attempts" / ("slurm-" + job)),
            "--scratch-parent",
            scratch,
            "--expected-candidate-sha256",
            c.CANDIDATE_SHA,
            "--confirm",
            "same_bank_eager_fp32_small_20260917_v1",
            "--batch-size",
            "16",
        ]
        runpy.run_path(sys.argv[0], run_name="__main__")
    faulthandler.cancel_dump_traceback_later()
    c.checked(digest)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc()
        raise SystemExit(2)

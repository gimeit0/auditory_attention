"""Two independent native model processes; first failure stops the sequence."""

import argparse
import faulthandler
import importlib.util
import json
import os
from pathlib import Path
import platform
import runpy
import signal
import subprocess
import sys
import tempfile
import time
import traceback

HERE = Path(__file__).absolute().parent
spec = importlib.util.spec_from_file_location(
    "s2_runtime_control", HERE / "control_s2.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
c = m.c


def run_children(parent, argv_for, verify, timeout=1740):
    """Actual OS processes; durable intent before each spawn; no restart path."""
    deadline = time.monotonic() + timeout
    records = []
    for stage, batch in m.STAGES:
        remaining = deadline - time.monotonic()
        c.require(remaining > 0, "Total parent budget exhausted")
        argv = argv_for(stage)
        c.write(
            parent / (stage + "_INTENT.json"),
            c.wire({"stage": stage, "batch": batch, "argv": argv, "time_utc": c.now()}),
        )
        process = subprocess.Popen(argv)
        identity = {
            "stage": stage,
            "batch_size": batch,
            "pid": process.pid,
            "argv": argv,
            "started_utc": c.now(),
        }
        try:
            c.write(parent / (stage + "_PROCESS.json"), c.wire(identity))
            rc = process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except BaseException:
            # Only terminate this wrapper's own child, never other user processes/jobs.
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        c.write(
            parent / (stage + "_EXIT.json"),
            c.wire(dict(identity, rc=rc, ended_utc=c.now())),
        )
        c.require(rc == 0, "Child failed: " + stage + " rc=" + str(rc))
        record = verify(stage, batch, identity)
        records.append(record)
    return records


def allocation(digest):
    c.require(
        sys.flags.isolated and sys.dont_write_bytecode and sys.platform == "linux",
        "Native Python -I -B required",
    )
    c.require(
        os.environ.get("HOME") == "/home/s2510040"
        and os.environ.get("CUBLAS_WORKSPACE_CONFIG") == ":4096:8",
        "Launch environment differs",
    )
    release = m.checked(digest)
    job = os.environ.get("SLURM_JOB_ID")
    receipt = m.submission(release, digest)
    c.require(job == receipt["job_id"], "Wrong allocation identity")
    intent = json.loads(c.read(m.ROOT / "state/RELEASE_INTENT.json"))
    c.require(
        intent["job_id"] == job and intent["release_sha256"] == digest,
        "No matching release intent",
    )
    info = c.command(["/usr/bin/scontrol", "-o", "show", "job", job])
    m.validate_job(c.successful(info), release, job, False)
    c.require(
        os.environ.get("SLURM_CPUS_PER_TASK") == "8"
        and os.environ.get("SLURM_NTASKS") == "1",
        "Wrong task allocation",
    )
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",")
    c.require(
        len(visible) == 1 and bool(visible[0].strip()), "One visible GPU required"
    )
    return release, job, info


def child(digest, stage):
    allocation(digest)
    batch = dict(m.STAGES)[stage]
    parent = m.ROOT / "attempts" / ("slurm-" + os.environ["SLURM_JOB_ID"])
    c.safe(parent, directory=True)
    c.require(
        os.path.lexists(parent / (stage + "_INTENT.json")), "No parent launch intent"
    )
    faulthandler.enable()
    faulthandler.dump_traceback_later(300, repeat=True)

    def terminated(signum, frame):
        faulthandler.dump_traceback()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminated)
    with tempfile.TemporaryDirectory(
        prefix="eager-s2a-" + stage + "-", dir="/tmp"
    ) as scratch:
        print(
            "MODEL_PROCESS="
            + json.dumps({"stage": stage, "pid": os.getpid(), "scratch": scratch}),
            flush=True,
        )
        sys.argv = [
            str(HERE / "eager_compare.py"),
            "run-small",
            "--output",
            str(parent / stage),
            "--scratch-parent",
            scratch,
            "--expected-candidate-sha256",
            c.CANDIDATE_SHA,
            "--confirm",
            "same_bank_eager_fp32_small_20260917_v1",
            "--batch-size",
            str(batch),
        ]
        runpy.run_path(sys.argv[0], run_name="__main__")
    faulthandler.cancel_dump_traceback_later()
    m.checked(digest)


def verify_child(parent, stage, batch, identity, baseline_run, job):
    output = parent / stage
    receipt_raw = c.read(output / "RECEIPT.json")
    receipt = json.loads(receipt_raw)
    c.require(
        receipt["status"] == "SMALL_RUN_COMPLETE_NOT_QUALIFIED"
        and receipt["verification"]["model_condition_predictions"] == 159,
        "Child receipt incomplete",
    )
    for name, digest in receipt["files"].items():
        c.require(
            Path(name).name == name and c.sha(c.read(output / name)) == digest,
            "Child artifact differs",
        )
    run = json.loads(c.read(output / "RUN.json"))
    for field in (
        "candidate_sha256",
        "v4_source_sha256",
        "v4_manifest_sha256",
        "models",
        "trial_ids",
        "historical_scene_hashes",
        "runtime",
        "amp",
        "compiled_forward",
        "tail_policy",
        "model_order",
        "protocol",
        "role",
    ):
        c.require(
            run[field] == baseline_run[field],
            "Child baseline declaration differs: " + field,
        )
    for field in ("python", "torch", "cuda", "cudnn", "device"):
        c.require(
            run["environment"][field] == baseline_run["environment"][field],
            "Child native environment differs",
        )
    c.require(
        run["batch_size"] == batch
        and run["job_id"] == job
        and run["pid"] == identity["pid"]
        and run["environment"]["hostname"] == platform.node(),
        "Child process/batch identity differs",
    )
    return {
        "stage": stage,
        "batch_size": batch,
        "pid": identity["pid"],
        "started_utc": run["started_utc"],
        "receipt_sha256": c.sha(receipt_raw),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("digest")
    parser.add_argument("--child", choices=[s for s, _ in m.STAGES])
    args = parser.parse_args()
    if args.child:
        child(args.digest, args.child)
        return
    release, job, info = allocation(args.digest)
    baseline_run = m.baseline()
    parent = m.ROOT / "attempts" / ("slurm-" + job)
    parent.mkdir(mode=0o700)  # Exclusive; scheduler requeue is disabled as well.
    c.write(
        m.ROOT / "state/LAUNCH.json",
        c.wire(
            {
                "job_id": job,
                "pid": os.getpid(),
                "allocation": info,
                "release_sha256": args.digest,
                "time_utc": c.now(),
            }
        ),
    )
    try:
        # A short separate process checks device/version without initializing CUDA in either model child.
        probe_code = 'import json,platform,torch;print(json.dumps({"python":platform.python_version(),"torch":torch.__version__,"cuda":torch.version.cuda,"cudnn":torch.backends.cudnn.version(),"device":torch.cuda.get_device_name(0)}))'
        probe = c.command([c.PYTHON, "-I", "-B", "-c", probe_code], timeout=60)
        c.write(parent / "DEVICE_PROBE.json", c.wire(probe))
        environment = json.loads(c.successful(probe))
        c.require(
            environment == {k: baseline_run["environment"][k] for k in environment}
            and set(environment) == {"python", "torch", "cuda", "cudnn", "device"},
            "Device/version differs from S1",
        )

        def argv_for(stage):
            m.checked(args.digest)
            return [
                c.PYTHON,
                "-I",
                "-B",
                "-u",
                str(HERE / "launch_s2.py"),
                args.digest,
                "--child",
                stage,
            ]

        def verify(stage, batch, identity):
            return verify_child(parent, stage, batch, identity, baseline_run, job)

        records = run_children(parent, argv_for, verify, timeout=1680)
        m.checked(args.digest)
        m.baseline()
        record = {
            "status": "S2A_EXECUTION_COMPLETE_NOT_QUALIFIED",
            "job_id": job,
            "release_sha256": args.digest,
            "baseline_receipt_sha256": m.BASELINE_SHA,
            "children": records,
            "numeric_comparison": "PENDING_INDEPENDENT_REVIEW",
            "full_comparison_complete": False,
        }
        c.write(m.ROOT / "state/COMPLETE.json", c.wire(record))
        print(json.dumps(record), flush=True)
    except BaseException as error:
        c.write(
            m.ROOT / "state/FAILED.json",
            c.wire(
                {
                    "status": "EXECUTION_FAILED",
                    "job_id": job,
                    "error": str(error),
                    "traceback": traceback.format_exc(),
                }
            ),
        )
        raise


if __name__ == "__main__":
    main()

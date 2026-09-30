"""Bounded four-process coordinator and local, read-only-source collection.

No sbatch/scontrol mutation, SSH, retries, requeue, or automatic qualification.
Native execution requires a separately approved, externally hashed contract.
"""

import argparse
import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import stat
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
STAGES = ("bridge16", "conf256", "conf32rep16", "conf32b1")
PROTOCOL = "p07conf_sequence_20260919_v2"
CANDIDATE_PROTOCOL = "same_bank_eager_fp32_confirm_20260919_v2"
PREFIX = "same_bank_compare_2026_09_19_confirm_v2/"
REMOTE_ROOT = Path("/home/s2510040/audattn_external_eval_ops/eager_p07conf_20260919_v2")
PYTHON = "/home/s2510040/miniconda3/envs/attn/bin/python"
# Bridge baseline: Job 726428 bridge16 (P05b), read through the pinned v1 reader.
BASELINE_ROOT = Path(
    "/home/s2510040/audattn_external_eval_ops/eager_p05b_20260918_v1/attempts/slurm-726428"
)
BASELINES = {
    "bridge16": (
        "bridge16",
        "5758f06d2930cf333870176cb8b67e284ebefb15b5f10e0814a82644fdfa5492",
    ),
}
BASELINE_LAYOUT_SHAS = {
    "bridge16": "a5d966886f165239da4ed6daaf2501e0df403c859d24ea9e7706b678da0b25b1",
}
LAYOUT_SHAS = {
    "bridge16": "68717fd4315650d18d3d9f820962ba1ae18b06d631230a3ae9ca928f7fb52514",
    "conf256": "d42a6900d4393bcda34d88dfe4ae8ff49e7725a3c793ddf168e8658f913b9ffb",
    "conf32rep16": "5a3bc8a2dbd9ed673e71d00489d44962d85d7707a806632ff1bed291977a078a",
    "conf32b1": "56821226444687f1cdd2b009e8c135904aaff67f554dbd9f824ac47441f4f759",
}
SELECTION_RECORD_SHA = "d727691355aea3f7721b65ce8d64baafb13c24abd6687b18dc4d5b7fd2c1b35c"
STAGE_BATCH = {"conf32b1": 1}
# Declared comparisons per stage: name -> (left source, kind). "baseline" reads
# BASELINES through the pinned v1 reader; other names are earlier stages.
COMPARISONS = {
    "bridge16": {"repeat": ("baseline", "bridge")},
    "conf256": {},
    "conf32rep16": {"vs_conf256": ("conf256", "subset-repeat")},
    "conf32b1": {
        "vs_conf256": ("conf256", "subset-batch-size"),
        "vs_conf32rep16": ("conf32rep16", "subset-batch-size"),
    },
}
# Fixed-configuration repeats that must be bitwise identical (P06-1).
GATED = {"bridge16": "repeat", "conf32rep16": "vs_conf256"}
LIMITS = {
    "jobs": 1,
    "gpus": 1,
    "gpu_type": "nvidia_a100",
    "cpus": 8,
    "memory_mib": 65536,
    "wall_seconds": 1800,
    "coordinator_seconds": 1680,
    "model_processes": 4,
    "automatic_retry": False,
}
PINNED = {
    PREFIX + "eager_compare.py": "3fb3e57098861e4eef7ed0b92fcfe837be4613eefca72d775a7364146d2d2f5e",
    PREFIX + "review_layouts.py": "149bfa15033af8c3349f51d63da358e28e01363d28d4d9030bac47ddea40ffe8",
    "same_bank_compare_2026_09_18_layout_v1/eager_compare.py": "8a191e7afc5a7e382b26039fb409041910bc250e7b9b84b8a483244d7c3042ed",
    "same_bank_compare_2026_09_18_layout_v1/review_layouts.py": "a2648549402e3e56b2b670078557ded09b1dbc1015fa00320073088cc65eed23",
    "same_bank_compare_2026_09_17_eager_v1/eager_compare.py": "d6f8380de33acee4dd448cd3135eab556a935e32d86598e422e3ace1d29bc3d4",
    "checkpoint_compare_workflow_20260917/review_runs.py": "49076fd6d9436ba2af2179cdb376836e263e72079197c0a4fa618c6f6c06fd95",
    "same_bank_eval_2026_08_29_v4/locked_same_bank_eval.py": "31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4",
    "checkpoint_compare_workflow_20260917/submission/remote_control.py": "d0fb9e2c295765c0aea835490d9ef78c01126d8e9a73b9541bc53c3ca665e503",
    PREFIX + "layouts/confirmation_256.json": SELECTION_RECORD_SHA,
    **{f"{PREFIX}layouts/{k}.json": v for k, v in LAYOUT_SHAS.items()},
}
OWN_FILES = {PREFIX + n for n in ("sequence.py", "sequence_worker.py", "run_layouts.sbatch")}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def safe(path, directory=False):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        require(not part.is_symlink(), f"Symlink rejected: {part}")
    mode = path.stat().st_mode
    require(
        stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode),
        f"Wrong file type: {path}",
    )
    return path


def sha(path):
    digest = hashlib.sha256()
    with safe(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wire(value):
    return (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()


def write(path, value):
    path = Path(path)
    safe(path.parent, directory=True)
    with path.open("xb") as handle:
        handle.write(wire(value))
        handle.flush()
        os.fsync(handle.fileno())


def read(path):
    return json.loads(safe(path).read_text())


def inventory(root):
    root = safe(root, directory=True)
    files, directories, total = {}, [], 0
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "Symlink in artifact tree")
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            safe(path, directory=True)
            directories.append(relative)
        else:
            safe(path)
            size = path.stat().st_size
            total += size
            require(
                size <= 64 * 1024**2 and total <= 256 * 1024**2,
                "Artifact budget exceeded",
            )
            require(len(files) < 1000, "Artifact count exceeded")
            files[relative] = {"sha256": sha(path), "size": size}
    return {"files": files, "directories": directories}


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("Total coordinator deadline exhausted")
    return seconds


def terminate_group(process):
    # Each owned child starts a fresh session. Never signal another job/group.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=2)


@contextlib.contextmanager
def interrupt_guard():
    def stop(signum, frame):
        raise InterruptedError(f"Coordinator interrupted by signal {signum}")

    old = {s: signal.signal(s, stop) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        yield
    finally:
        for s, handler in old.items():
            signal.signal(s, handler)


def step(parent, name, argv, deadline):
    require(
        isinstance(argv, list) and argv and all(isinstance(x, str) for x in argv),
        "Invalid argv",
    )
    remaining(deadline)
    write(parent / f"{name}.INTENT.json", {"argv": argv, "started_utc": now()})
    with (
        (parent / f"{name}.stdout.log").open("xb") as out,
        (parent / f"{name}.stderr.log").open("xb") as err,
    ):
        process = subprocess.Popen(argv, stdout=out, stderr=err, start_new_session=True)
        identity = {"pid": process.pid, "argv": argv, "started_utc": now()}
        try:
            write(parent / f"{name}.PROCESS.json", identity)
            rc = process.wait(timeout=remaining(deadline))
        except BaseException as error:
            terminate_group(process)
            write(
                parent / f"{name}.EXIT.json",
                dict(
                    identity,
                    rc=process.returncode,
                    ended_utc=now(),
                    exception_type=type(error).__name__,
                    interrupted=True,
                ),
            )
            raise
    write(
        parent / f"{name}.EXIT.json",
        dict(identity, rc=rc, ended_utc=now(), interrupted=False),
    )
    require(rc == 0, f"Child {name} failed rc={rc}")
    remaining(deadline)
    return identity


def check_gate(report, stage):
    require(
        report["stage"] == stage and report["status"] == "RECOMPUTED_NOT_QUALIFIED",
        "Wrong review status",
    )
    require(report["full_run_authorized"] is False, "Unexpected full-run approval")
    require(report["artifact_verified"] is True, "Artifacts not verified")
    if stage in GATED:
        require(
            report["fixed_configuration_logits_equal"] is True,
            f"Fixed-configuration repeat differs: {stage}; stop for review",
        )
        require(
            report["repeat_result_table_canary"] == "PASS",
            "Repeat result-table canary differs",
        )
    else:
        require(
            report["fixed_configuration_logits_equal"] is None,
            "Wrong layout gate semantics",
        )


def execute_sequence(parent, argv_for, provenance, timeout=1680):
    """Local-testable engine. CLI calls it only after native contract validation.

    Model and verifier are separately bounded OS processes. A verifier failure,
    repeat DIFF, interrupt or timeout prevents all later model launches.
    """
    require(
        type(timeout) in (int, float)
        and math.isfinite(timeout)
        and 0 < timeout <= 1680,
        "Invalid timeout",
    )
    parent = Path(parent).absolute()
    safe(parent.parent, directory=True)
    parent.mkdir(mode=0o700)  # No restart, overwrite, or in-place retry.
    deadline = time.monotonic() + timeout
    records = []
    with interrupt_guard():
        try:
            write(
                parent / "START.json",
                {"protocol": PROTOCOL, "started_utc": now(), "provenance": provenance},
            )
            for stage in STAGES:
                model = step(
                    parent, stage + ".model", argv_for(stage, "model"), deadline
                )
                step(parent, stage + ".verify", argv_for(stage, "verify"), deadline)
                report = read(parent / f"{stage}.review.json")
                check_gate(report, stage)
                require(
                    report["model_pid"] == model["pid"],
                    "Model PID does not match spawn record",
                )
                records.append(
                    {
                        "stage": stage,
                        "model_pid": model["pid"],
                        "receipt_sha256": report["receipt_sha256"],
                        "review_sha256": sha(parent / f"{stage}.review.json"),
                    }
                )
                remaining(deadline)
            require(
                len({r["model_pid"] for r in records}) == len(STAGES),
                "Distinct model processes required",
            )
            terminal = {
                "protocol": PROTOCOL,
                "status": "EXECUTION_COMPLETE_NOT_QUALIFIED",
                "children": records,
                "provenance": provenance,
                "ended_utc": now(),
                "full_run_authorized": False,
                "inventory": inventory(parent),
            }
            remaining(deadline)
            write(parent / "COMPLETE.json", terminal)
            return terminal
        except BaseException as error:
            # Preserve all partial artifacts; never manufacture COMPLETE on failure.
            try:
                partial_inventory = inventory(parent)
                inventory_error = None
            except Exception as inventory_exception:
                partial_inventory = None
                inventory_error = str(inventory_exception)
            terminal = {
                "protocol": PROTOCOL,
                "status": "EXECUTION_FAILED",
                "children": records,
                "provenance": provenance,
                "ended_utc": now(),
                "error_type": type(error).__name__,
                "error": str(error),
                "full_run_authorized": False,
                "inventory": partial_inventory,
                "inventory_error": inventory_error,
            }
            write(parent / "FAILED.json", terminal)
            raise


def collect(source, terminal_sha, destination):
    """Copy a terminal artifact tree into a NEW local directory; no SSH/retry."""
    source = safe(source, directory=True)
    candidates = [
        p for p in (source / "COMPLETE.json", source / "FAILED.json") if p.exists()
    ]
    require(len(candidates) == 1, "Exactly one terminal marker required")
    terminal_path = candidates[0]
    require(sha(terminal_path) == terminal_sha, "External terminal SHA mismatch")
    terminal = read(terminal_path)
    expected_status = (
        "EXECUTION_FAILED"
        if terminal_path.name == "FAILED.json"
        else "EXECUTION_COMPLETE_NOT_QUALIFIED"
    )
    require(
        terminal["protocol"] == PROTOCOL
        and terminal["status"] == expected_status
        and terminal["full_run_authorized"] is False,
        "Wrong terminal declaration",
    )
    expected = terminal["inventory"]
    actual = inventory(source)
    actual["files"].pop(terminal_path.name)
    require(actual == expected, "Terminal inventory differs from source")
    destination = Path(destination).absolute()
    safe(destination.parent, directory=True)
    require(
        not destination.is_relative_to(source), "Collection cannot be inside source"
    )
    destination.mkdir(mode=0o700)
    write(
        destination / "COLLECTION_STARTED.json",
        {"source": str(source), "terminal_sha256": terminal_sha},
    )
    archive = destination / "archive"
    archive.mkdir(mode=0o700)
    for relative in expected["directories"]:
        (archive / relative).mkdir(mode=0o700)
    files = dict(expected["files"])
    files[terminal_path.name] = {
        "sha256": terminal_sha,
        "size": terminal_path.stat().st_size,
    }
    for relative, record in files.items():
        origin = safe(source / relative)
        require(sha(origin) == record["sha256"], "Source changed during collection")
        with origin.open("rb") as inp, (archive / relative).open("xb") as out:
            for chunk in iter(lambda: inp.read(1024 * 1024), b""):
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        require(sha(archive / relative) == record["sha256"], "Copy hash mismatch")
    require(
        inventory(source) == inventory(archive), "Source changed or copy incomplete"
    )
    record = {
        "status": "COLLECTED_NOT_QUALIFIED",
        "terminal_status": terminal["status"],
        "terminal_sha256": terminal_sha,
        "files": files,
        "full_run_authorized": False,
    }
    write(destination / "COLLECTION.json", record)
    return record


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, safe(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_contract(path, digest):
    require(sha(path) == digest, "External contract SHA mismatch")
    contract = read(path)
    require(
        contract["status"] == "USER_APPROVED_FOR_ALLOCATED_JOB"
        and contract["protocol"] == PROTOCOL,
        "No matching explicit authorization",
    )
    require(wire(contract["limits"]) == wire(LIMITS), "Budget differs")
    require(
        contract["stages"] == list(STAGES)
        and re.fullmatch(r"[a-f0-9]{32}", contract["nonce"]),
        "Execution scope differs",
    )
    require(
        type(contract["job_id"]) is str
        and re.fullmatch(r"[1-9][0-9]*", contract["job_id"]),
        "Invalid job ID",
    )
    require(
        set(contract["files"]) == set(PINNED) | OWN_FILES, "Bundle inventory differs"
    )
    for name, expected in contract["files"].items():
        require(
            re.fullmatch(r"[a-f0-9]{64}", expected) and sha(PROJECT / name) == expected,
            "Bundle SHA mismatch: " + name,
        )
        if name in PINNED:
            require(expected == PINNED[name], "Scientific dependency differs")
    require(
        contract["baseline_receipts"] == {k: v[1] for k, v in BASELINES.items()},
        "Baseline binding differs",
    )
    return contract


def validate_allocation(common, raw, contract):
    fields = common.fields(raw)
    expected = {
        "JobId": contract["job_id"],
        "JobName": "audattn_eager_p07conf",
        "Partition": "GPU-1A",
        "Account": "student",
        "NumCPUs": "8",
        "NumTasks": "1",
        "CPUs/Task": "8",
        "TimeLimit": "00:30:00",
        "JobState": "RUNNING",
        "Requeue": "0",
        "Restarts": "0",
        "WorkDir": str(REMOTE_ROOT),
        "Command": str(HERE / "run_layouts.sbatch"),
        "Comment": "p07conf-" + contract["nonce"],
    }
    for key, value in expected.items():
        require(fields.get(key) == value, "Allocation differs: " + key)
    require(
        fields.get("UserId", "").startswith("s2510040(")
        and fields.get("NumNodes") in ("1", "1-1"),
        "Owner/node differs",
    )
    common.check_tres(fields.get("ReqTRES", ""))
    common.check_tres(fields.get("AllocTRES", ""))
    return fields


def native_context(contract_path, digest):
    require(
        sys.platform == "linux" and sys.flags.isolated and sys.dont_write_bytecode,
        "Native Linux python -I -B required",
    )
    require(
        platform.python_version() == "3.11.5"
        and str(Path(sys.executable).resolve()) == str(Path(PYTHON).resolve()),
        "Wrong native Python",
    )
    contract = check_contract(contract_path, digest)
    require(os.environ.get("SLURM_JOB_ID") == contract["job_id"], "Wrong allocated job")
    require(
        os.environ.get("CUBLAS_WORKSPACE_CONFIG") == ":4096:8"
        and os.environ.get("SLURM_CPUS_PER_TASK") == "8"
        and os.environ.get("SLURM_NTASKS") == "1",
        "Wrong launch environment",
    )
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",")
    require(len(visible) == 1 and bool(visible[0].strip()), "One visible GPU required")
    common = load_module(
        PROJECT / "checkpoint_compare_workflow_20260917/submission/remote_control.py",
        "allocation_common",
    )
    result = subprocess.run(
        ["/usr/bin/scontrol", "-o", "show", "job", contract["job_id"]],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    validate_allocation(common, result.stdout, contract)
    return contract, result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Allocated job only; no submission")
    run.add_argument("--contract", type=Path, required=True)
    run.add_argument("--contract-sha256", required=True)
    get = commands.add_parser(
        "collect", help="Local terminal source copy; no remote transport"
    )
    get.add_argument("--source", type=Path, required=True)
    get.add_argument("--terminal-sha256", required=True)
    get.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "collect":
        print(json.dumps(collect(args.source, args.terminal_sha256, args.destination)))
        return
    contract, allocation = native_context(args.contract, args.contract_sha256)
    parent = REMOTE_ROOT / "attempts" / ("slurm-" + contract["job_id"])

    def argv_for(stage, operation):
        check_contract(args.contract, args.contract_sha256)
        argv = [
            PYTHON,
            "-I",
            "-B",
            "-u",
            str(HERE / "sequence_worker.py"),
            operation,
            "--stage",
            stage,
            "--parent",
            str(parent),
            "--contract",
            str(args.contract.absolute()),
            "--contract-sha256",
            args.contract_sha256,
        ]
        if operation == "verify":
            argv += ["--receipt-sha256", sha(parent / stage / "RECEIPT.json")]
        return argv

    execute_sequence(
        parent,
        argv_for,
        {
            "contract_sha256": args.contract_sha256,
            "job_id": contract["job_id"],
            "allocation": allocation,
        },
    )
    print(
        json.dumps(
            {
                "status": "EXECUTION_COMPLETE_NOT_QUALIFIED",
                "terminal_sha256": sha(parent / "COMPLETE.json"),
            }
        )
    )


if __name__ == "__main__":
    main()

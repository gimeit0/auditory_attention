"""Fixed S2a operations: one held job, two model processes, no repair/retry."""

import base64
import importlib.util
import json
import os
from pathlib import Path
import re

COMMON_SHA = "d0fb9e2c295765c0aea835490d9ef78c01126d8e9a73b9541bc53c3ca665e503"
if "common" not in globals():
    here = Path(__file__).resolve().parent
    path = here / "s1_control.py"
    if not path.exists():
        path = here.parent / "submission/remote_control.py"
    import hashlib

    if hashlib.sha256(path.read_bytes()).hexdigest() != COMMON_SHA:
        raise RuntimeError("Common helper SHA differs")
    spec = importlib.util.spec_from_file_location("s2_common", path)
    common = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common)
c = common

ROOT = Path("/home/s2510040/audattn_external_eval_ops/eager_s2a_20260918_v1")
PROTOCOL = "same_bank_eager_s2a_20260918_v1"
JOB_NAME = "audattn_eager_s2a"
BASELINE = c.ROOT / "attempts/slurm-724808"
BASELINE_SHA = "58f1fc6953c4732955efcadcbf7adbf543738936672639d929d0ef5359f00027"
STAGES = (("repeat16", 16), ("batch1", 1))
LIMITS = {
    "gpus": 1,
    "gpu_type": "nvidia_a100",
    "cpus": 8,
    "memory_mib": 65536,
    "seconds": 1800,
    "jobs": 1,
    "trials": 32,
    "batch_sizes": [16, 1],
    "model_processes": 2,
    "automatic_retry": False,
}
FILES = {
    "eager_compare.py",
    "s1_control.py",
    "control_s2.py",
    "launch_s2.py",
    "run_s2.sbatch",
    "AUTHORIZATION.json",
}


def decode(raw, digest):
    c.require(c.sha(raw) == digest, "Release SHA differs")
    release = json.loads(raw)
    c.require(
        release["protocol"] == PROTOCOL
        and release["limits"] == LIMITS
        and set(release["files"]) == FILES
        and release["files"]["eager_compare.py"] == c.CANDIDATE_SHA
        and release["files"]["s1_control.py"] == COMMON_SHA
        and release["baseline_receipt_sha256"] == BASELINE_SHA
        and re.fullmatch(r"[a-f0-9]{32}", release["nonce"]),
        "Release scope differs",
    )
    return release


def checked(digest):
    release = decode(c.read(ROOT / "RELEASE.json"), digest)
    for name, sha in release["files"].items():
        c.require(
            c.sha(c.read(ROOT / "tools" / name)) == sha, "Package changed: " + name
        )
    auth = json.loads(c.read(ROOT / "tools/AUTHORIZATION.json"))
    c.require(
        auth["limits"] == LIMITS
        and auth["status"] == "USER_APPROVED"
        and auth["conditional_release"] is True
        and auth["resource_repair_authorized"] is False,
        "Authorization differs",
    )
    return release


def baseline():
    raw = c.read(BASELINE / "RECEIPT.json")
    c.require(c.sha(raw) == BASELINE_SHA, "S1 baseline receipt changed")
    receipt = json.loads(raw)
    c.require(receipt["status"] == "SMALL_RUN_COMPLETE_NOT_QUALIFIED", "S1 incomplete")
    for name, digest in receipt["files"].items():
        c.require(Path(name).name == name, "Invalid S1 artifact name")
        c.require(c.sha(c.read(BASELINE / name)) == digest, "S1 artifact changed")
    return json.loads(c.read(BASELINE / "RUN.json"))


def preflight(execute=c.command):
    # Reuse unchanged native user/version/input/partition/node/disk checks.
    report = c.preflight(execute, queue_empty=True)
    before = baseline()
    accounting = execute(
        [
            "/usr/bin/sacct",
            "-j",
            "724808",
            "-X",
            "-n",
            "-P",
            "--format=JobIDRaw,State,ExitCode",
        ]
    )
    c.require(
        c.successful(accounting).strip() == "724808|COMPLETED|0:0",
        "S1 terminal differs",
    )
    return {
        "baseline_preflight": report,
        "baseline_environment": before["environment"],
        "baseline_accounting": accounting,
        "target_root": str(ROOT),
    }


def batch_argv(release, digest, test=False):
    return [
        "/usr/bin/sbatch",
        "--test-only" if test else "--hold",
        "--parsable",
        "--export=NONE",
        "--no-requeue",
        "--partition=GPU-1A",
        "--account=student",
        "--nodes=1",
        "--ntasks=1",
        "--cpus-per-task=8",
        "--threads-per-core=1",
        "--mem=65536M",
        "--time=00:30:00",
        "--gpus=nvidia_a100:1",
        "--gpus-per-node=nvidia_a100:1",
        "--job-name=" + JOB_NAME,
        "--comment=eager-s2a-" + release["nonce"],
        "--chdir=" + str(ROOT),
        "--input=/dev/null",
        "--output=" + str(ROOT / "logs/s2a_%j.log"),
        "--error=" + str(ROOT / "logs/s2a_%j.log"),
        str(ROOT / "tools/run_s2.sbatch"),
        digest,
    ]


def validate_job(raw, release, job, held):
    f = c.fields(raw)
    expected = {
        "JobId": job,
        "JobName": JOB_NAME,
        "Partition": "GPU-1A",
        "Account": "student",
        "NumCPUs": "8",
        "NumTasks": "1",
        "CPUs/Task": "8",
        "TimeLimit": "00:30:00",
        "Requeue": "0",
        "Restarts": "0",
        "WorkDir": str(ROOT),
        "Command": str(ROOT / "tools/run_s2.sbatch"),
        "Comment": "eager-s2a-" + release["nonce"],
        "TresPerNode": "gres/gpu:nvidia_a100:1",
        "TresPerJob": "gres/gpu:nvidia_a100:1",
    }
    for key, value in expected.items():
        c.require(
            f.get(key) == value, "Scheduler mismatch: " + key + "=" + str(f.get(key))
        )
    c.require(
        f.get("UserId", "").startswith("s2510040(")
        and f.get("NumNodes") in ("1", "1-1"),
        "Owner/node differs",
    )
    c.check_tres(f.get("ReqTRES", ""))
    if held:
        c.require(
            f.get("JobState") == "PENDING"
            and f.get("Reason") == "JobHeldUser"
            and f.get("Priority") == "0"
            and f.get("RunTime") == "00:00:00"
            and f.get("AllocTRES") in (None, "", "(null)"),
            "Not never-run held job",
        )
    else:
        c.require(f.get("JobState") == "RUNNING", "Not running")
        c.check_tres(f.get("AllocTRES", ""))
    return f


def submission(release, digest):
    receipt = json.loads(c.read(ROOT / "state/SUBMISSION.json"))
    c.require(
        receipt["nonce"] == release["nonce"]
        and receipt["release_sha256"] == digest
        and re.fullmatch(r"[1-9][0-9]*", receipt["job_id"]),
        "Submission identity differs",
    )
    return receipt


def query(release, digest, execute=c.command):
    receipt = submission(release, digest)
    job = receipt["job_id"]
    result = {
        "status": "READ_ONLY",
        "submission": receipt,
        "queue": execute(
            ["/usr/bin/squeue", "-h", "-u", "s2510040", "-o", "%A|%T|%j|%k"]
        ),
        "job": execute(["/usr/bin/scontrol", "-o", "show", "job", job]),
        "accounting": execute(
            [
                "/usr/bin/sacct",
                "-j",
                job,
                "-X",
                "-n",
                "-P",
                "--format=JobIDRaw,State,ExitCode,Elapsed,Start,End,ReqTRES%200,AllocTRES%200,NodeList",
            ]
        ),
    }
    c.successful(result["queue"])
    c.successful(result["accounting"])
    for name in ("LAUNCH.json", "COMPLETE.json", "FAILED.json"):
        path = ROOT / "state" / name
        if path.exists():
            raw = c.read(path)
            result[name] = {"sha256": c.sha(raw), "record": json.loads(raw)}
    return result


def remote(spec, execute=c.command):
    os.umask(0o077)
    action, digest = spec["action"], spec["release_sha256"]
    if action in ("preflight", "deploy"):
        c.require(not os.path.lexists(ROOT), "New root already exists")
        before = preflight(execute)
        if action == "preflight":
            return dict(status="PREFLIGHT_PASS_NO_JOB", **before)
        raw = base64.b64decode(spec["release"], validate=True)
        release = decode(raw, digest)
        c.require(set(spec["files"]) == FILES, "Upload inventory differs")
        files = {
            n: base64.b64decode(b, validate=True) for n, b in spec["files"].items()
        }
        c.require(
            all(c.sha(files[n]) == h for n, h in release["files"].items()),
            "Upload digest differs",
        )
        c.safe(ROOT.parent, directory=True)
        ROOT.mkdir(mode=0o700)
        for name in ("tools", "logs", "state", "attempts"):
            (ROOT / name).mkdir(mode=0o700)
        c.write(ROOT / "RELEASE.json", raw)
        for name, value in files.items():
            c.write(ROOT / "tools" / name, value)
        checked(digest)
        c.write(ROOT / "state/DEPLOY.json", c.wire(before))
        return {"status": "DEPLOYED_NO_JOB"}
    release = checked(digest)
    if action == "test-only":
        c.require(
            not os.path.lexists(ROOT / "state/SUBMIT_INTENT.json"), "Already submitted"
        )
        before = preflight(execute)
        help_result = execute(
            [c.PYTHON, "-I", "-B", str(ROOT / "tools/launch_s2.py"), "--help"]
        )
        c.successful(help_result)
        result = execute(batch_argv(release, digest, test=True))
        c.write(
            ROOT / "state/TEST_ONLY.json",
            c.wire(
                {
                    "release_sha256": digest,
                    "before": before,
                    "help": help_result,
                    "result": result,
                }
            ),
        )
        c.successful(result)
        return {"status": "TEST_ONLY_PASS_NO_JOB", "result": result}
    if action == "submit":
        c.require(
            not os.path.lexists(ROOT / "state/SUBMIT_INTENT.json")
            and not any((ROOT / "attempts").iterdir()),
            "Submission already attempted",
        )
        test = json.loads(c.read(ROOT / "state/TEST_ONLY.json"))
        c.require(
            test["release_sha256"] == digest
            and test["result"]["rc"] == 0
            and test["result"]["argv"] == batch_argv(release, digest, test=True),
            "No matching test-only",
        )
        before = preflight(execute)
        argv = batch_argv(release, digest)
        c.write(
            ROOT / "state/SUBMIT_INTENT.json",
            c.wire(
                {
                    "release_sha256": digest,
                    "nonce": release["nonce"],
                    "before": before,
                    "argv": argv,
                }
            ),
        )
        response = execute(argv)
        c.write(ROOT / "state/SBATCH_RESPONSE.json", c.wire(response))
        c.require(
            response["rc"] == 0
            and re.fullmatch(
                r"[1-9][0-9]*(?:;[A-Za-z0-9_.-]+)?\n?", response["stdout"]
            ),
            "SUBMISSION_UNKNOWN: query only, never repeat",
        )
        job = response["stdout"].strip().split(";")[0]
        receipt = {
            "status": "SUBMITTED_HELD",
            "job_id": job,
            "nonce": release["nonce"],
            "release_sha256": digest,
            "automatic_retry": False,
        }
        c.write(ROOT / "state/SUBMISSION.json", c.wire(receipt))
        info = execute(["/usr/bin/scontrol", "-o", "show", "job", job])
        c.write(ROOT / "state/HELD_QUERY.json", c.wire(info))
        try:
            validate_job(c.successful(info), release, job, True)
        except RuntimeError as error:
            return dict(receipt, status="HELD_RESOURCE_MISMATCH", reason=str(error))
        return receipt
    if action == "release":
        job = submission(release, digest)["job_id"]
        c.require(
            not os.path.lexists(ROOT / "state/RELEASE_INTENT.json"),
            "Release already attempted",
        )
        info = execute(["/usr/bin/scontrol", "-o", "show", "job", job])
        f = validate_job(c.successful(info), release, job, True)
        accounting = execute(
            [
                "/usr/bin/sacct",
                "-j",
                job,
                "-X",
                "-n",
                "-P",
                "--format=JobIDRaw,State,ReqTRES%256,AllocTRES%256,Elapsed",
            ]
        )
        row = c.successful(accounting).strip().split("|")
        c.require(
            len(row) == 5
            and row[:2] == [job, "PENDING"]
            and row[3:] == ["", "00:00:00"]
            and c.tres(row[2]) == c.tres(f["ReqTRES"]),
            "Accounting differs",
        )
        spool = execute(["/usr/bin/scontrol", "write", "batch_script", job, "-"])
        c.require(
            c.sha(c.successful(spool).encode()) == release["files"]["run_s2.sbatch"],
            "Submitted script differs",
        )
        checked(digest)
        baseline()
        c.write(
            ROOT / "state/RELEASE_INTENT.json",
            c.wire(
                {
                    "job_id": job,
                    "release_sha256": digest,
                    "before": info,
                    "accounting": accounting,
                    "spool": spool,
                }
            ),
        )
        response = execute(["/usr/bin/scontrol", "release", job])
        c.write(ROOT / "state/RELEASE_RESPONSE.json", c.wire(response))
        c.successful(response)
        return {"status": "RELEASED_ONCE", "job_id": job}
    if action in ("status", "collect"):
        result = query(release, digest, execute)
        if action == "status":
            return result
        rows = result["accounting"]["stdout"].strip().splitlines()
        c.require(
            len(rows) == 1
            and rows[0].split("|")[1]
            in (
                "COMPLETED",
                "FAILED",
                "TIMEOUT",
                "CANCELLED",
                "OUT_OF_MEMORY",
                "NODE_FAIL",
            ),
            "Not confirmed terminal",
        )
        files = {}
        for path in sorted(ROOT.rglob("*")):
            c.require(not path.is_symlink(), "Symlink in evidence")
            if path.is_file():
                files[str(path.relative_to(ROOT))] = c.read(path)
        c.require(sum(map(len, files.values())) <= 64 * 1024**2, "Collection too large")
        c.require(
            all(c.read(ROOT / n) == b for n, b in files.items()),
            "Artifacts changed during collection",
        )
        return {
            "status": "TERMINAL_EVIDENCE",
            "query": result,
            "files": {
                n: {"sha256": c.sha(b), "base64": base64.b64encode(b).decode()}
                for n, b in files.items()
            },
        }
    raise RuntimeError("Unknown action")

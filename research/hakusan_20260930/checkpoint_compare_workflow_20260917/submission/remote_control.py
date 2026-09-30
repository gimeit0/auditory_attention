"""Fixed single small-run deployment/control. No retry, repair, or requeue."""

import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

ROOT = Path("/home/s2510040/audattn_external_eval_ops/eager_small_20260917_v1")
PYTHON = "/home/s2510040/miniconda3/envs/attn/bin/python"
V4 = Path("/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4")
CANDIDATE_SHA = "d6f8380de33acee4dd448cd3135eab556a935e32d86598e422e3ace1d29bc3d4"
FIXED_INPUTS = {
    "input_freeze.json": "1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5",
    "state/evaluation.lock": "63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710",
    "tools/locked_same_bank_eval.py": "31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4",
    "tools/run_locked_same_bank_eval.sbatch": "b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495",
}
FILES = {
    "eager_compare.py",
    "remote_control.py",
    "launch_small.py",
    "run_small.sbatch",
    "AUTHORIZATION.json",
}
LIMITS = {
    "gpus": 1,
    "gpu_type": "nvidia_a100",
    "cpus": 8,
    "memory_mib": 65536,
    "seconds": 1800,
    "jobs": 1,
    "batch_size": 16,
    "trials": 32,
    "automatic_retry": False,
}
JOB_NAME = "audattn_eager_s1"


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def safe(path, directory=False):
    path = Path(path)
    require(
        path.is_absolute() and ".." not in path.parts,
        "Absolute unaliased path required",
    )
    require(
        not any(p.is_symlink() for p in (path, *path.parents)), "Symlink path rejected"
    )
    info = path.stat()
    require(
        (stat.S_ISDIR if directory else stat.S_ISREG)(info.st_mode), "Wrong file type"
    )
    require(info.st_uid == os.getuid(), "Wrong owner")
    return path


def read(path, maximum=32 * 1024**2):
    path = safe(path)
    require(path.stat().st_size <= maximum, "File exceeds collection bound")
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        raw = handle.read(maximum + 1)
        after = os.fstat(handle.fileno())

    def identity(s):
        return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)

    require(
        len(raw) == before.st_size
        and identity(before) == identity(after) == identity(path.stat()),
        "File changed during read",
    )
    return raw


def write(path, raw):
    safe(path.parent, directory=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def command(argv, timeout=30):
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("SBATCH_", "SLURM_")):
            env.pop(key)
    env.update(PATH="/usr/bin:/bin", LC_ALL="C")
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, env=env
        )
        return {
            "argv": argv,
            "rc": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired as error:
        return {
            "argv": argv,
            "rc": 124,
            "stdout": (error.stdout or b"").decode(errors="replace"),
            "stderr": "TIMEOUT: state uncertain; never retry a mutation",
        }


def successful(result):
    require(result["rc"] == 0, "Command failed: " + json.dumps(result))
    return result["stdout"]


def fields(raw):
    matches = list(re.finditer(r"(?:^|\s)([A-Za-z][A-Za-z0-9_/:]*)=", raw))
    return {
        m[1]: raw[
            m.end() : matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        ].strip()
        for i, m in enumerate(matches)
    }


def tres(raw):
    return dict(item.split("=", 1) for item in raw.split(",") if "=" in item)


def check_tres(raw):
    values = tres(raw)
    require(
        values.get("cpu") == "8"
        and values.get("node") == "1"
        and values.get("mem") in ("64G", "65536M"),
        "CPU/node/memory budget mismatch",
    )
    gpu = {k: v for k, v in values.items() if k.startswith("gres/gpu")}
    require(
        gpu.get("gres/gpu:nvidia_a100") == "1"
        and set(gpu) <= {"gres/gpu", "gres/gpu:nvidia_a100"}
        and all(v == "1" for v in gpu.values()),
        "Expected exactly one typed A100; no repair or release",
    )


def validate_job(raw, release, job, held):
    f = fields(raw)
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
        "Command": str(ROOT / "tools/run_small.sbatch"),
        "Comment": "eager-s1-" + release["nonce"],
    }
    for k, v in expected.items():
        require(f.get(k) == v, "Scheduler mismatch " + k + ": " + str(f.get(k)))
    require(f.get("UserId", "").startswith("s2510040("), "Wrong job owner")
    require(f.get("NumNodes") in ("1", "1-1"), "Wrong node count")
    check_tres(f.get("ReqTRES", ""))
    require(
        f.get("TresPerNode") == "gres/gpu:nvidia_a100:1",
        "GPU request is not typed A100",
    )
    if held:
        require(
            f.get("JobState") == "PENDING"
            and f.get("Reason") == "JobHeldUser"
            and f.get("Priority") == "0",
            "Not the original user-held job",
        )
        require(
            f.get("AllocTRES") in (None, "", "(null)"),
            "Held job unexpectedly allocated",
        )
    else:
        require(f.get("JobState") == "RUNNING", "Allocation not running")
        check_tres(f.get("AllocTRES", ""))
    return f


def decode_release(raw, expected):
    require(sha(raw) == expected, "Release SHA mismatch")
    release = json.loads(raw)
    require(
        set(release["files"]) == FILES and release["limits"] == LIMITS,
        "Release scope changed",
    )
    require(release["files"]["eager_compare.py"] == CANDIDATE_SHA, "Candidate changed")
    require(re.fullmatch("[a-f0-9]{32}", release["nonce"]) is not None, "Invalid nonce")
    return release


def checked(expected):
    safe(ROOT, directory=True)
    release = decode_release(read(ROOT / "RELEASE.json"), expected)
    active_files = dict(release["files"])
    repair_path = ROOT / "state/CONTROL_REPAIR.json"
    if repair_path.exists() or repair_path.is_symlink():
        repair = json.loads(read(repair_path))
        require(
            expected
            == "e513fb99de9e731d867c194414a466ee40be5a0bf32bd8cb77cdcc2e62509927"
            and repair["base_release_sha256"] == expected
            and repair["job_id"] == "724808"
            and repair["nonce"] == release["nonce"]
            and repair["changed_files"] == ["remote_control.py"]
            and repair["limits"] == LIMITS
            and repair["release_authorized"] is False,
            "Wrong same-job control amendment",
        )
        archive = ROOT / "repairs/job724808/original"
        require(
            read(archive / "RELEASE.json") == read(ROOT / "RELEASE.json"),
            "Original release archive differs",
        )
        for name, digest in release["files"].items():
            require(
                sha(read(archive / name)) == digest,
                "Original package archive differs: " + name,
            )
        require(
            re.fullmatch("[a-f0-9]{64}", repair["controller_sha256"]) is not None,
            "Invalid repaired controller SHA",
        )
        active_files["remote_control.py"] = repair["controller_sha256"]
        for name, digest in repair["original_journals"].items():
            require(
                name
                in (
                    "SUBMISSION.json",
                    "SUBMIT_INTENT.json",
                    "SBATCH_RESPONSE.json",
                    "TEST_ONLY.json",
                ),
                "Unexpected original journal",
            )
            require(
                sha(read(ROOT / "state" / name)) == digest,
                "Original journal changed: " + name,
            )
        require(
            set(repair["original_journals"])
            == {
                "SUBMISSION.json",
                "SUBMIT_INTENT.json",
                "SBATCH_RESPONSE.json",
                "TEST_ONLY.json",
            },
            "Original journal binding incomplete",
        )
        if "SLURM_JOB_ID" in os.environ:
            require(
                os.environ["SLURM_JOB_ID"] == "724808",
                "Amendment is only for Job724808",
            )
    for name, digest in active_files.items():
        require(sha(read(ROOT / "tools" / name)) == digest, "Package changed: " + name)
    auth = json.loads(read(ROOT / "tools/AUTHORIZATION.json"))
    require(
        auth["limits"] == LIMITS
        and auth["status"] == "USER_APPROVED"
        and auth["models"] == ["formal40", "author_external", "valbest33"],
        "Authorization mismatch",
    )
    return release


def preflight(execute=command, queue_empty=True):
    require(
        os.uname().sysname == "Linux" and os.environ.get("USER") == "s2510040",
        "HAKUSAN user required",
    )
    hashes = {n: sha(read(V4 / n)) for n in FIXED_INPUTS}
    require(hashes == FIXED_INPUTS, "Original v4 evidence changed")
    queue = execute(["/usr/bin/squeue", "-h", "-u", "s2510040", "-o", "%A|%T|%j|%k"])
    output = successful(queue)
    if queue_empty:
        require(
            not output.strip(), "Account queue not empty; inspect before submission"
        )
    partition = execute(["/usr/bin/scontrol", "-o", "show", "partition", "GPU-1A"])
    p = fields(successful(partition))
    require(
        p.get("State") == "UP" and p.get("DefaultTime") != "00:00:00",
        "Partition unavailable",
    )
    nodes = execute(["/usr/bin/sinfo", "-p", "GPU-1A", "-N", "-h", "-o", "%N|%t|%G|%m"])
    require("gpu:nvidia_a100:" in successful(nodes), "A100 resource not present")
    version = execute(
        [PYTHON, "-I", "-B", "-c", "import sys;print(sys.version.split()[0])"]
    )
    require(successful(version).strip() == "3.11.5", "Native Python differs")
    disk = execute(["/bin/df", "-Pk", str(ROOT.parent)])
    successful(disk)
    return {
        "time_utc": now(),
        "queue": queue,
        "partition": partition,
        "nodes": nodes,
        "python": version,
        "disk": disk,
        "v4_sha256": hashes,
        "root_exists": ROOT.exists(),
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
        "--gres=gpu:nvidia_a100:1",
        "--job-name=" + JOB_NAME,
        "--comment=eager-s1-" + release["nonce"],
        "--chdir=" + str(ROOT),
        "--input=/dev/null",
        "--output=" + str(ROOT / "logs/small_%j.log"),
        "--error=" + str(ROOT / "logs/small_%j.log"),
        str(ROOT / "tools/run_small.sbatch"),
        digest,
    ]


def submit(release, digest, execute=command):
    require(
        not (ROOT / "state/SUBMIT_INTENT.json").exists()
        and not any((ROOT / "attempts").iterdir()),
        "Submission already attempted; status only",
    )
    test = json.loads(read(ROOT / "state/TEST_ONLY.json"))
    require(
        test["release_sha256"] == digest and test["result"]["rc"] == 0,
        "Matching test-only success required",
    )
    before = preflight(execute)
    argv = batch_argv(release, digest)
    write(
        ROOT / "state/SUBMIT_INTENT.json",
        wire(
            {
                "release_sha256": digest,
                "nonce": release["nonce"],
                "argv": argv,
                "time_utc": now(),
                "preflight": before,
            }
        ),
    )
    response = execute(argv)
    write(ROOT / "state/SBATCH_RESPONSE.json", wire(response))
    require(
        response["rc"] == 0
        and re.fullmatch(r"[1-9][0-9]*(?:;[A-Za-z0-9_.-]+)?\n?", response["stdout"])
        is not None,
        "SUBMISSION_UNKNOWN: query only; never resubmit",
    )
    job = response["stdout"].strip().split(";")[0]
    receipt = {
        "job_id": job,
        "nonce": release["nonce"],
        "release_sha256": digest,
        "status": "SUBMITTED_HELD",
        "automatic_retry": False,
    }
    write(ROOT / "state/SUBMISSION.json", wire(receipt))
    info = execute(["/usr/bin/scontrol", "-o", "show", "job", job])
    write(ROOT / "state/HELD_QUERY.json", wire(info))
    try:
        validate_job(successful(info), release, job, held=True)
    except RuntimeError as error:
        return dict(receipt, status="HELD_RESOURCE_MISMATCH", reason=str(error))
    return receipt


def release_job(release, digest, execute=command):
    require(
        not (ROOT / "state/CONTROL_REPAIR.json").exists(),
        "Control repair does not authorize release; use separately approved release operation",
    )
    receipt = json.loads(read(ROOT / "state/SUBMISSION.json"))
    require(
        receipt["release_sha256"] == digest and receipt["nonce"] == release["nonce"],
        "Wrong submission identity",
    )
    job = receipt["job_id"]
    info = execute(["/usr/bin/scontrol", "-o", "show", "job", job])
    validate_job(successful(info), release, job, held=True)
    checked(digest)
    write(
        ROOT / "state/RELEASE_INTENT.json",
        wire({"job_id": job, "before": info, "release_sha256": digest}),
    )
    response = execute(["/usr/bin/scontrol", "release", job])
    write(ROOT / "state/RELEASE_RESPONSE.json", wire(response))
    successful(response)
    return {"status": "RELEASED_ONCE", "job_id": job}


def query(release, execute=command):
    queue = execute(["/usr/bin/squeue", "-h", "-u", "s2510040", "-o", "%A|%T|%j|%k"])
    successful(queue)
    receipt = (
        json.loads(read(ROOT / "state/SUBMISSION.json"))
        if (ROOT / "state/SUBMISSION.json").exists()
        else None
    )
    result = {
        "status": "READ_ONLY",
        "queue": queue,
        "submission": receipt,
        "intent_exists": (ROOT / "state/SUBMIT_INTENT.json").exists(),
    }
    if receipt:
        require(receipt["nonce"] == release["nonce"], "Receipt identity changed")
        job = receipt["job_id"]
        result["job"] = execute(["/usr/bin/scontrol", "-o", "show", "job", job])
        result["accounting"] = execute(
            [
                "/usr/bin/sacct",
                "-j",
                job,
                "-X",
                "-n",
                "-P",
                "--format=JobIDRaw,State,ExitCode,Elapsed,Start,End,ReqTRES%200,AllocTRES%200,NodeList",
            ]
        )
        for p in (ROOT / "attempts" / ("slurm-" + job)).glob("*.json"):
            if p.name in ("RECEIPT.json", "FAILED.json"):
                result[p.name] = {"sha256": sha(read(p)), "record": json.loads(read(p))}
    return result


def remote(spec):
    os.umask(0o077)
    action, digest = spec["action"], spec["release_sha256"]
    if action == "preflight":
        require(not ROOT.exists() and not ROOT.is_symlink(), "New root already exists")
        return dict(status="READ_ONLY_PREFLIGHT", **preflight())
    if action == "deploy":
        before = preflight()
        require(not ROOT.exists() and not ROOT.is_symlink(), "New root already exists")
        safe(ROOT.parent, directory=True)
        raw = base64.b64decode(spec["release"], validate=True)
        release = decode_release(raw, digest)
        require(set(spec["files"]) == FILES, "Upload inventory mismatch")
        data = {n: base64.b64decode(b, validate=True) for n, b in spec["files"].items()}
        require(
            all(sha(data[n]) == h for n, h in release["files"].items()),
            "Upload digest mismatch",
        )
        ROOT.mkdir(mode=0o700)
        for name in ("tools", "logs", "state", "attempts"):
            (ROOT / name).mkdir(mode=0o700)
        for name, value in data.items():
            write(ROOT / "tools" / name, value)
        write(ROOT / "RELEASE.json", raw)
        checked(digest)
        write(ROOT / "state/DEPLOY.json", wire(before))
        return {"status": "PACKAGE_DEPLOYED_NO_JOB", "release_sha256": digest}
    release = checked(digest)
    if action == "test-only":
        before = preflight()
        require(
            not (ROOT / "state/SUBMIT_INTENT.json").exists(),
            "Already attempted submission",
        )
        help_result = command(
            [PYTHON, "-I", "-B", str(ROOT / "tools/eager_compare.py"), "--help"]
        )
        successful(help_result)
        result = command(batch_argv(release, digest, test=True))
        record = {
            "release_sha256": digest,
            "preflight": before,
            "candidate_help": help_result,
            "result": result,
        }
        write(ROOT / "state/TEST_ONLY.json", wire(record))
        successful(result)
        return {
            "status": "SCHEDULER_TEST_PASS_NO_JOB",
            "test_sha256": sha(wire(record)),
            "result": result,
        }
    if action == "submit":
        return submit(release, digest)
    if action == "release":
        return release_job(release, digest)
    if action == "status":
        return query(release)
    if action == "collect":
        status = query(release)
        require(status["submission"] is not None, "No job receipt")
        rows = successful(status["accounting"]).strip().splitlines()
        job = status["submission"]["job_id"]
        require(
            len(rows) == 1
            and rows[0].split("|")[0] == job
            and rows[0].split("|")[1]
            in (
                "COMPLETED",
                "FAILED",
                "TIMEOUT",
                "CANCELLED",
                "OUT_OF_MEMORY",
                "NODE_FAIL",
            ),
            "Job not confirmed terminal",
        )
        files = {}
        for path in sorted(ROOT.rglob("*")):
            if path.is_symlink():
                raise RuntimeError("Symlink in evidence")
            if path.is_file():
                files[str(path.relative_to(ROOT))] = read(path)
        require(
            sum(map(len, files.values())) <= 64 * 1024**2,
            "Evidence exceeds bounded collection",
        )
        require(
            all(read(ROOT / n) == raw for n, raw in files.items()),
            "Evidence changed during collection",
        )
        return {
            "status": "TERMINAL_EVIDENCE",
            "query": status,
            "files": {
                n: {"sha256": sha(raw), "base64": base64.b64encode(raw).decode()}
                for n, raw in files.items()
            },
        }
    raise RuntimeError("Unknown action")

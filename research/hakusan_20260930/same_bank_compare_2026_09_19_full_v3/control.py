"""P08full controller library (approved full 10k run). No CLI, SSH, implicit approval, repair, or retry.

Transport must externally pin this source and pass an explicit release digest.
All scheduler mutations are preceded by exclusive durable intent records.
"""

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "p05b_control_sequence", HERE / "sequence.py"
)
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)
COMMON = "checkpoint_compare_workflow_20260917/submission/remote_control.py"
S.require(S.sha(S.PROJECT / COMMON) == S.PINNED[COMMON], "Common source differs")
C = S.load_module(S.PROJECT / COMMON, "p05b_common")
ROOT = S.REMOTE_ROOT
PREFIX = "same_bank_compare_2026_09_19_full_v3/"
FILES = (
    set(S.PINNED)
    | S.OWN_FILES
    | {
        PREFIX + "control.py",
        PREFIX + "launch_approved.py",
        PREFIX + "offline_review.py",
    }
)
PROTOCOL = "p08full_held_delivery_20260919_v3"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def record(path, value):
    # The shared writer fsyncs both file and parent directory.
    C.write(path, S.wire(value))


def decode(raw, expected):
    S.require(digest(raw) == expected, "Release digest differs")
    r = json.loads(raw)
    S.require(
        r["protocol"] == PROTOCOL and r["status"] == "EXPLICITLY_APPROVED",
        "Approval required",
    )
    S.require(S.wire(r["limits"]) == S.wire(S.LIMITS), "Budget differs")
    S.require(
        r["stages"] == list(S.STAGES) and re.fullmatch(r"[a-f0-9]{32}", r["nonce"]),
        "Scope differs",
    )
    S.require(
        r["baseline_receipts"] == {k: v[1] for k, v in S.BASELINES.items()},
        "Baseline differs",
    )
    S.require(set(r["files"]) == FILES, "Package inventory differs")
    S.require(
        all(re.fullmatch(r"[a-f0-9]{64}", h) for h in r["files"].values()),
        "Invalid digest",
    )
    S.require(all(r["files"][n] == h for n, h in S.PINNED.items()), "Science changed")
    auth = r["authorization"]
    S.require(
        auth["single_held_submission"] is True
        and auth["conditional_release"] is True
        and auth["resource_repair"] is False
        and auth["automatic_retry"] is False
        and isinstance(auth["user_approval_record"], str)
        and bool(auth["user_approval_record"].strip()),
        "Explicit scoped approval missing",
    )
    return r


def checked(expected):
    r = decode(C.read(ROOT / "RELEASE.json"), expected)
    for name, sha in r["files"].items():
        S.require(
            digest(C.read(ROOT / "package" / name)) == sha,
            "Published source changed: " + name,
        )
    return r


def inputs():
    for name, sha in C.FIXED_INPUTS.items():
        S.require(digest(C.read(C.V4 / name)) == sha, "Original input changed")
    for stage, (folder, expected) in S.BASELINES.items():
        parent = S.BASELINE_ROOT / folder
        raw = C.read(parent / "RECEIPT.json")
        S.require(digest(raw) == expected, "Baseline receipt changed: " + stage)
        receipt = json.loads(raw)
        S.require(
            receipt["status"] == "SMALL_RUN_COMPLETE_NOT_QUALIFIED",
            "Baseline incomplete",
        )
        for name, sha in receipt["files"].items():
            S.require(Path(name).name == name, "Unsafe baseline filename")
            S.require(
                digest(C.read(parent / name, maximum=S.ARTIFACT_FILE_LIMIT)) == sha,
                "Baseline artifact changed",
            )


def queue_empty(execute):
    q = execute(["/usr/bin/squeue", "-h", "-u", "s2510040", "-o", "%A|%T|%j|%k"])
    S.require(not C.successful(q).strip(), "User queue is not empty; inspect first")


def publish(raw, expected, encoded):
    r = decode(raw, expected)
    S.require(set(encoded) == FILES, "Upload inventory differs")
    data = {n: base64.b64decode(b, validate=True) for n, b in encoded.items()}
    S.require(sum(map(len, data.values())) <= 8 * 1024**2, "Package too large")
    S.require(
        all(digest(data[n]) == h for n, h in r["files"].items()), "Upload differs"
    )
    C.safe(ROOT.parent, directory=True)
    S.require(not os.path.lexists(ROOT), "Root exists; no overwrite")
    ROOT.mkdir(mode=0o700)
    for name in ("package", "state", "logs", "attempts"):
        (ROOT / name).mkdir(mode=0o700)
    C.write(ROOT / "RELEASE.json", raw)
    for name, content in data.items():
        target = ROOT / "package" / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        C.write(target, content)
    checked(expected)
    record(
        ROOT / "state/PUBLISHED.json",
        {"release_sha256": expected, "status": "PUBLISHED_NO_JOB"},
    )


def batch_argv(r, expected, test=False):
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
        "--time=03:00:00",
        "--gres=gpu:nvidia_a100:1",
        "--job-name=audattn_eager_p08full",
        "--comment=p08full-" + r["nonce"],
        "--chdir=" + str(ROOT),
        "--input=/dev/null",
        "--output=" + str(ROOT / "logs/p05b_%j.log"),
        "--error=" + str(ROOT / "logs/p05b_%j.log"),
        str(ROOT / "package" / PREFIX / "run_layouts.sbatch"),
        "--release",
        expected,
    ]


def test_only(expected, execute=C.command):
    r = checked(expected)
    S.require(
        not os.path.lexists(ROOT / "state/SUBMIT_INTENT.json"),
        "Submission already attempted",
    )
    inputs()
    queue_empty(execute)
    argv = batch_argv(r, expected, True)
    record(ROOT / "state/TEST_INTENT.json", {"release_sha256": expected, "argv": argv})
    result = execute(argv)
    record(
        ROOT / "state/TEST_ONLY.json", {"release_sha256": expected, "result": result}
    )
    C.successful(result)
    return {"status": "TEST_ONLY_PASS_NO_JOB"}


def submit(expected, execute=C.command):
    r = checked(expected)
    t = S.read(ROOT / "state/TEST_ONLY.json")
    S.require(
        t["release_sha256"] == expected
        and t["result"]["rc"] == 0
        and t["result"]["argv"] == batch_argv(r, expected, True),
        "Matching test-only required",
    )
    S.require(not any((ROOT / "attempts").iterdir()), "Attempt exists")
    inputs()
    queue_empty(execute)
    argv = batch_argv(r, expected)
    record(
        ROOT / "state/SUBMIT_INTENT.json",
        {"release_sha256": expected, "nonce": r["nonce"], "argv": argv},
    )
    response = execute(argv)
    record(ROOT / "state/SBATCH_RESPONSE.json", response)
    S.require(
        response["rc"] == 0
        and re.fullmatch(r"[1-9][0-9]*(?:;[A-Za-z0-9_.-]+)?\n?", response["stdout"]),
        "SUBMISSION_UNKNOWN: inspect only, never repeat",
    )
    job = response["stdout"].strip().split(";")[0]
    record(
        ROOT / "state/SUBMISSION.json",
        {"job_id": job, "release_sha256": expected, "nonce": r["nonce"]},
    )
    return {"status": "SUBMITTED_HELD_NOT_RELEASED", "job_id": job}


def submission(r, expected):
    record = S.read(ROOT / "state/SUBMISSION.json")
    intent = S.read(ROOT / "state/SUBMIT_INTENT.json")
    response = S.read(ROOT / "state/SBATCH_RESPONSE.json")
    S.require(
        record["release_sha256"] == expected
        and record["nonce"] == r["nonce"]
        and re.fullmatch(r"[1-9][0-9]*", record["job_id"]),
        "Submission binding differs",
    )
    S.require(
        intent
        == {
            "release_sha256": expected,
            "nonce": r["nonce"],
            "argv": batch_argv(r, expected),
        },
        "Intent differs",
    )
    S.require(
        response["rc"] == 0
        and response["argv"] == intent["argv"]
        and response["stdout"].strip().split(";")[0] == record["job_id"],
        "Response differs",
    )
    return record["job_id"]


def held(r, expected, execute):
    job = submission(r, expected)
    raw = C.successful(execute(["/usr/bin/scontrol", "-o", "show", "job", job]))
    fields = C.fields(raw)
    exact = {
        "JobId": job,
        "JobName": "audattn_eager_p08full",
        "Partition": "GPU-1A",
        "Account": "student",
        "NumCPUs": "8",
        "NumTasks": "1",
        "CPUs/Task": "8",
        "TimeLimit": "03:00:00",
        "Requeue": "0",
        "Restarts": "0",
        "WorkDir": str(ROOT),
        "Command": str(ROOT / "package" / PREFIX / "run_layouts.sbatch"),
        "Comment": "p08full-" + r["nonce"],
        "JobState": "PENDING",
        "Reason": "JobHeldUser",
        "Priority": "0",
        "RunTime": "00:00:00",
    }
    S.require(
        all(fields.get(k) == v for k, v in exact.items()),
        "Held identity/budget differs",
    )
    S.require(
        fields.get("UserId", "").startswith("s2510040(")
        and fields.get("NumNodes") in ("1", "1-1")
        and fields.get("AllocTRES") in (None, "", "(null)")
        and fields.get("NodeList") in (None, "", "(null)"),
        "Job already allocated or wrong owner",
    )
    C.check_tres(fields.get("ReqTRES", ""))
    spool = C.successful(
        execute(["/usr/bin/scontrol", "write", "batch_script", job, "-"])
    )
    S.require(
        digest(spool.encode()) == r["files"][PREFIX + "run_layouts.sbatch"],
        "Spool differs",
    )
    accounting = C.successful(
        execute(
            [
                "/usr/bin/sacct",
                "-j",
                job,
                "-X",
                "-n",
                "-P",
                "--format=JobIDRaw,State,ExitCode,Elapsed,Start,End",
            ]
        )
    )
    rows = [line.split("|") for line in accounting.strip().splitlines()]
    S.require(
        len(rows) == 1
        and rows[0][:4] == [job, "PENDING", "0:0", "00:00:00"]
        and len(rows[0]) == 6
        and all(x in ("", "Unknown") for x in rows[0][4:]),
        "Accounting not never-run held",
    )
    S.require(not any((ROOT / "attempts").iterdir()), "Attempt exists")
    return job, raw


def contract(r, job):
    return {
        "status": "USER_APPROVED_FOR_ALLOCATED_JOB",
        "protocol": S.PROTOCOL,
        "job_id": job,
        "nonce": r["nonce"],
        "limits": r["limits"],
        "stages": r["stages"],
        "baseline_receipts": r["baseline_receipts"],
        "files": {n: r["files"][n] for n in set(S.PINNED) | S.OWN_FILES},
    }


def release(expected, execute=C.command):
    r = checked(expected)
    inputs()
    job, snapshot = held(r, expected, execute)
    S.require(
        not os.path.lexists(ROOT / "state/RELEASE_INTENT.json"),
        "Release already attempted; query only",
    )
    value = contract(r, job)
    path = ROOT / "state/CONTRACT.json"
    record(path, value)
    argv = ["/usr/bin/scontrol", "release", job]
    record(
        ROOT / "state/RELEASE_INTENT.json",
        {
            "job_id": job,
            "release_sha256": expected,
            "contract_sha256": S.sha(path),
            "held_snapshot": snapshot,
            "argv": argv,
        },
    )
    response = execute(argv)
    record(ROOT / "state/RELEASE_RESPONSE.json", response)
    C.successful(response)
    return {"status": "RELEASE_REQUEST_ACCEPTED_QUERY_NEXT", "job_id": job}


def launch_contract(expected, job):
    r = checked(expected)
    S.require(submission(r, expected) == job, "Wrong allocated job")
    value = contract(r, job)
    path = ROOT / "state/CONTRACT.json"
    S.require(S.read(path) == value, "Job contract differs")
    intent = S.read(ROOT / "state/RELEASE_INTENT.json")
    S.require(
        intent["release_sha256"] == expected
        and intent["job_id"] == job
        and intent["contract_sha256"] == S.sha(path)
        and intent["argv"] == ["/usr/bin/scontrol", "release", job],
        "Release intent differs",
    )
    return path, S.sha(path)


def export_attempt(expected, terminal_sha):
    r = checked(expected)
    job = submission(r, expected)
    parent = ROOT / "attempts" / ("slurm-" + job)
    inventory = S.inventory(parent)
    markers = [n for n in ("COMPLETE.json", "FAILED.json") if n in inventory["files"]]
    S.require(len(markers) == 1, "Exactly one terminal required")
    marker = markers[0]
    S.require(S.sha(parent / marker) == terminal_sha, "Terminal SHA differs")
    terminal = S.read(parent / marker)
    contract_path, contract_sha = launch_contract(expected, job)
    S.require(
        terminal["provenance"]["job_id"] == job
        and terminal["provenance"]["contract_sha256"] == contract_sha,
        "Terminal job binding differs",
    )
    S.require(
        terminal["status"]
        == (
            "EXECUTION_FAILED"
            if marker == "FAILED.json"
            else "EXECUTION_COMPLETE_NOT_QUALIFIED"
        ),
        "Terminal status differs",
    )
    body = {
        "directories": inventory["directories"],
        "files": {n: v for n, v in inventory["files"].items() if n != marker},
    }
    S.require(
        terminal["inventory"] == body
        and terminal["protocol"] == S.PROTOCOL
        and terminal["full_run_authorized"] is False,
        "Terminal inventory differs",
    )
    files = {
        n: {
            "base64": base64.b64encode(
                C.read(parent / n, maximum=S.ARTIFACT_FILE_LIMIT)
            ).decode(),
            **record,
        }
        for n, record in inventory["files"].items()
    }
    S.require(S.inventory(parent) == inventory, "Source changed while exporting")
    return {
        "job_id": job,
        "release_sha256": expected,
        "terminal_sha256": terminal_sha,
        "inventory": inventory,
        "files": files,
        "full_run_authorized": False,
    }


def import_attempt(payload, expected, job, terminal_sha, destination):
    """Unpack bounded untrusted wire data, then use the independent collector."""
    S.require(
        payload["release_sha256"] == expected
        and payload["job_id"] == job
        and payload["terminal_sha256"] == terminal_sha
        and payload["full_run_authorized"] is False,
        "Collection identity differs",
    )
    inv = payload["inventory"]
    S.require(
        set(payload["files"]) == set(inv["files"]) and len(inv["files"]) <= 1000,
        "Transfer inventory differs",
    )
    dirs = inv["directories"]
    S.require(
        len(dirs) <= 1000 and len(set(dirs)) == len(dirs), "Invalid directory inventory"
    )
    for n in list(inv["files"]) + dirs:
        p = Path(n)
        S.require(
            n
            and not p.is_absolute()
            and ".." not in p.parts
            and p.as_posix() == n
            and n != ".",
            "Unsafe transfer path",
        )
    data = {}
    total = 0
    for n, rec in payload["files"].items():
        S.require(
            type(rec["size"]) is int
            and 0 <= rec["size"] <= S.ARTIFACT_FILE_LIMIT
            and len(rec["base64"]) <= 350 * 1024**2,
            "Oversized transfer",
        )
        raw = base64.b64decode(rec["base64"], validate=True)
        total += len(raw)
        S.require(
            total <= S.ARTIFACT_TOTAL_LIMIT
            and len(raw) == rec["size"]
            and digest(raw) == rec["sha256"]
            and inv["files"][n] == {"size": len(raw), "sha256": digest(raw)},
            "Transfer digest differs",
        )
        data[n] = raw
    destination = Path(destination).absolute()
    C.safe(destination.parent, directory=True)
    destination.mkdir(mode=0o700)
    received = destination / "received"
    received.mkdir(mode=0o700)
    for n in sorted(dirs, key=lambda x: (len(Path(x).parts), x)):
        (received / n).mkdir(mode=0o700)
    for n, raw in data.items():
        C.write(received / n, raw)
    S.require(S.inventory(received) == inv, "Received inventory differs")
    markers = [
        received / n
        for n in ("COMPLETE.json", "FAILED.json")
        if (received / n).exists()
    ]
    S.require(
        len(markers) == 1 and S.read(markers[0])["provenance"]["job_id"] == job,
        "Received job differs",
    )
    return S.collect(received, terminal_sha, destination / "verified")


def preflight(execute=C.command):
    """Short read-only native checks; no checkpoint loading or submission."""
    import pwd

    S.require(
        sys.platform == "linux"
        and platform.python_version() == "3.11.5"
        and pwd.getpwuid(os.getuid()).pw_name == "s2510040",
        "Wrong native account/Python",
    )
    S.require(
        Path(sys.executable).resolve() == Path(S.PYTHON).resolve(),
        "Wrong native executable",
    )
    C.safe(ROOT.parent, directory=True)
    inputs()
    queue_empty(execute)
    commands = {
        "version": ["/usr/bin/scontrol", "--version"],
        "partition": ["/usr/bin/scontrol", "-o", "show", "partition", "GPU-1A"],
        "nodes": ["/usr/bin/sinfo", "-p", "GPU-1A", "-N", "-h", "-o", "%N|%G|%m|%t"],
        "disk": ["/bin/df", "-Pk", str(ROOT.parent)],
        "baseline_accounting": [
            "/usr/bin/sacct",
            "-j",
            "728280",
            "-X",
            "-n",
            "-P",
            "--format=JobIDRaw,State,ExitCode",
        ],
    }
    reports = {k: execute(argv) for k, argv in commands.items()}
    for result in reports.values():
        C.successful(result)
    S.require(
        reports["baseline_accounting"]["stdout"].strip() == "728280|COMPLETED|0:0",
        "Baseline accounting differs",
    )
    S.require(
        "nvidia_a100" in reports["nodes"]["stdout"], "A100 not visible in partition"
    )
    return {
        "status": "READ_ONLY_PREFLIGHT_REVIEW_REQUIRED",
        "reports": reports,
        "root_exists": os.path.lexists(ROOT),
        "jobs_submitted": 0,
    }


def status(expected, execute=C.command):
    """Also works after lost submission response; never reconstructs a receipt."""
    r = checked(expected)
    queue = execute(["/usr/bin/squeue", "-h", "-u", "s2510040", "-o", "%A|%T|%j|%k"])
    C.successful(queue)
    journal = {}
    for name in (
        "SUBMIT_INTENT.json",
        "SBATCH_RESPONSE.json",
        "SUBMISSION.json",
        "CONTRACT.json",
        "RELEASE_INTENT.json",
        "RELEASE_RESPONSE.json",
    ):
        path = ROOT / "state" / name
        if os.path.lexists(path):
            journal[name] = {"sha256": S.sha(path), "record": S.read(path)}
    if "SUBMISSION.json" not in journal:
        # Bounded time window supplied by frozen release, not an all-history query.
        S.require(
            re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", r["accounting_since"]),
            "Invalid accounting window",
        )
        accounting = execute(
            [
                "/usr/bin/sacct",
                "-u",
                "s2510040",
                "-S",
                r["accounting_since"],
                "-X",
                "-n",
                "-P",
                "--name=audattn_eager_p08full",
                "--format=JobIDRaw,State,ExitCode,Submit,Comment%100",
            ]
        )
        C.successful(accounting)
        return {
            "status": "SUBMISSION_UNKNOWN_QUERY_ONLY"
            if "SUBMIT_INTENT.json" in journal
            else "NOT_SUBMITTED",
            "nonce": r["nonce"],
            "queue": queue,
            "accounting": accounting,
            "journal": journal,
        }
    job = submission(r, expected)
    accounting = execute(
        [
            "/usr/bin/sacct",
            "-j",
            job,
            "-X",
            "-n",
            "-P",
            "--format=JobIDRaw,State,ExitCode,Elapsed,NodeList",
        ]
    )
    C.successful(accounting)
    terminal = {}
    for name in ("COMPLETE.json", "FAILED.json"):
        path = ROOT / "attempts" / ("slurm-" + job) / name
        if os.path.lexists(path):
            terminal[name] = {
                "sha256": S.sha(path),
                "status": S.read(path).get("status"),
            }
    return {
        "status": "QUERY_ONLY_NOT_VERIFIED",
        "job_id": job,
        "queue": queue,
        "accounting": accounting,
        "journal": journal,
        "terminal": terminal,
        "job": execute(["/usr/bin/scontrol", "-o", "show", "job", job]),
    }

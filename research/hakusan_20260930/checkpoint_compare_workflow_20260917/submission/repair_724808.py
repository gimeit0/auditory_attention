"""Same held job: inspect, archive/replace one controller, update GPU, verify.

No submission, release, cancellation, requeue, model loading, or automatic retry.
Original release digest remains the immutable base; a separate amendment binds
the one changed operational controller and preserved original package.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types

HERE = Path(__file__).resolve().parent if "__file__" in globals() else None
BASE_SHA = "e513fb99de9e731d867c194414a466ee40be5a0bf32bd8cb77cdcc2e62509927"
OLD_SHA = "fc8617224ba852e3d57fc68ee9ac07b64e38a46289a1fd00018cbbfc2f66d037"
JOB = "724808"
GPU = "gres/gpu:nvidia_a100:1"
UPDATE = [
    "/usr/bin/scontrol",
    "update",
    "JobId=" + JOB,
    "TresPerJob=" + GPU,
    "TresPerNode=" + GPU,
]
JOURNALS = (
    "SUBMISSION.json",
    "SUBMIT_INTENT.json",
    "SBATCH_RESPONSE.json",
    "TEST_ONLY.json",
)


def loaded(raw, name, path):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), vars(module))
    return module


def bind_submission(c, release):
    require = c.require
    records = {n: json.loads(c.read(c.ROOT / "state" / n)) for n in JOURNALS}
    receipt, intent, response, test = (records[n] for n in JOURNALS)
    require(
        receipt
        == {
            "automatic_retry": False,
            "job_id": JOB,
            "nonce": release["nonce"],
            "release_sha256": BASE_SHA,
            "status": "SUBMITTED_HELD",
        },
        "Original submission mismatch",
    )
    require(
        intent["release_sha256"] == BASE_SHA
        and intent["nonce"] == release["nonce"]
        and intent["argv"] == c.batch_argv(release, BASE_SHA),
        "Original intent mismatch",
    )
    require(
        response["rc"] == 0
        and response["stdout"].strip() == JOB
        and response["argv"] == intent["argv"],
        "Original sbatch response mismatch",
    )
    require(
        test["release_sha256"] == BASE_SHA
        and test["result"]["rc"] == 0
        and test["result"]["argv"] == c.batch_argv(release, BASE_SHA, test=True),
        "Original test mismatch",
    )
    for name in ("RELEASE_INTENT.json", "RELEASE_RESPONSE.json", "LAUNCH.json"):
        require(
            not os.path.lexists(c.ROOT / "state" / name),
            "Release or execution already attempted",
        )
    require(
        not any((c.ROOT / "attempts").iterdir()), "Execution artifacts already exist"
    )
    return {n: c.sha(c.read(c.ROOT / "state" / n)) for n in JOURNALS}


def snapshot(c, execute):
    return {
        "job": execute(["/usr/bin/scontrol", "-o", "show", "job", JOB]),
        "accounting": execute(
            [
                "/usr/bin/sacct",
                "-j",
                JOB,
                "-X",
                "-n",
                "-P",
                "--format=JobIDRaw,State,ReqTRES%256,AllocTRES%256,Elapsed",
            ]
        ),
        "queue": execute(
            ["/usr/bin/squeue", "-h", "-u", "s2510040", "-o", "%A|%T|%j|%k"]
        ),
        "batch_script": execute(
            ["/usr/bin/scontrol", "write", "batch_script", JOB, "-"]
        ),
        "version": execute(["/usr/bin/scontrol", "--version"]),
    }


def validate_snapshot(c, release, snap, corrected=False):
    for result in snap.values():
        c.successful(result)
    c.require(
        snap["version"]["stdout"].strip() == "slurm 25.05.5", "Slurm version changed"
    )
    c.require(
        snap["queue"]["stdout"].strip()
        == JOB + "|PENDING|" + c.JOB_NAME + "|eager-s1-" + release["nonce"],
        "Queue/nonce differs",
    )
    c.require(
        c.sha(snap["batch_script"]["stdout"].encode())
        == release["files"]["run_small.sbatch"],
        "Submitted batch script differs from original",
    )
    raw = snap["job"]["stdout"]
    f = c.fields(raw)
    req = c.tres(f.get("ReqTRES", ""))
    if not corrected:
        c.require(
            req
            == {
                "cpu": "8",
                "mem": "64G",
                "node": "1",
                "billing": "8",
                "gres/gpu:h100-20c": "1",
            }
            and f.get("TresPerNode") == "gres/gpu:1"
            and not f.get("TresPerJob"),
            "Not exact original GPU mismatch",
        )
        # Only to validate non-GPU fields before repair. Never saved as real A100 evidence.
        view = raw.replace("gres/gpu:h100-20c=1", "gres/gpu:nvidia_a100=1").replace(
            "TresPerNode=gres/gpu:1", "TresPerNode=" + GPU
        )
        c.validate_job(view, release, JOB, held=True)
    else:
        c.validate_job(raw, release, JOB, held=True)
        c.require(f.get("TresPerJob") == GPU, "Typed total GPU request absent")
    c.require(
        f.get("RunTime") == "00:00:00" and f.get("NodeList") in ("", "(null)"),
        "Job previously executed or allocated",
    )
    lines = [
        s.split("|") for s in snap["accounting"]["stdout"].splitlines() if s.strip()
    ]
    c.require(len(lines) == 1 and len(lines[0]) == 5, "One accounting record required")
    job, state, requested, allocated, elapsed = lines[0]
    c.require(
        job == JOB
        and state == "PENDING"
        and allocated == ""
        and elapsed == "00:00:00"
        and c.tres(requested) == req,
        "Independent accounting differs",
    )
    return f


def amendment(c, release, controller_sha, repair_sha, journals):
    return {
        "job_id": JOB,
        "nonce": release["nonce"],
        "base_release_sha256": BASE_SHA,
        "controller_sha256": controller_sha,
        "repair_tool_sha256": repair_sha,
        "changed_files": ["remote_control.py"],
        "original_journals": journals,
        "limits": c.LIMITS,
        "release_authorized": False,
        "authorization": {
            "user_reply": "好的",
            "scope": "Correct same held Job724808 controller and A100 request; preserve original package; no new job and no direct release.",
        },
    }


def install(c, spec, release, execute):
    # Original files must still match the old release before any write.
    for name, digest in release["files"].items():
        c.require(
            c.sha(c.read(c.ROOT / "tools" / name)) == digest, "Original package drift"
        )
    c.require(
        c.sha(c.read(c.ROOT / "tools/remote_control.py")) == OLD_SHA,
        "Unexpected original controller",
    )
    journals = bind_submission(c, release)
    before = snapshot(c, execute)
    validate_snapshot(c, release, before)
    code = base64.b64decode(spec["controller"], validate=True)
    c.require(c.sha(code) == spec["controller_sha256"], "Candidate controller drift")
    record = amendment(c, release, c.sha(code), spec["repair_sha256"], journals)
    repairs = c.ROOT / "repairs"
    if not repairs.exists():
        repairs.mkdir(mode=0o700)
    c.safe(repairs, directory=True)
    target = repairs / "job724808"
    target.mkdir(mode=0o700)  # Exclusive boundary: cannot retry this operation.
    original = target / "original"
    original.mkdir(mode=0o700)
    c.write(
        target / "INSTALL_INTENT.json",
        c.wire({"time_utc": c.now(), "before": before, "amendment": record}),
    )
    c.write(original / "RELEASE.json", c.read(c.ROOT / "RELEASE.json"))
    for name, digest in release["files"].items():
        raw = c.read(c.ROOT / "tools" / name)
        c.require(c.sha(raw) == digest, "Original file changed before archive")
        c.write(original / name, raw)
        c.require(c.sha(c.read(original / name)) == digest, "Original archive mismatch")
    staged = target / "new_remote_control.py"
    c.write(staged, code)
    c.write(target / "REPAIR_AUTHORIZATION.json", c.wire(record["authorization"]))
    # Recheck held state immediately before publishing the amendment/one-file replacement.
    validate_snapshot(c, release, snapshot(c, execute))
    bind_submission(c, release)
    c.require(
        c.sha(c.read(c.ROOT / "tools/remote_control.py")) == OLD_SHA,
        "Controller changed before replacement",
    )
    c.write(c.ROOT / "state/CONTROL_REPAIR.json", c.wire(record))
    os.replace(staged, c.ROOT / "tools/remote_control.py")
    fd = os.open(c.ROOT / "tools", os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    # Import actual installed file, not merely the local proposal.
    live = loaded(
        c.read(c.ROOT / "tools/remote_control.py"),
        "live_repaired_control",
        c.ROOT / "tools/remote_control.py",
    )
    # Tests may redirect ROOT; production uses the same canonical fixed path.
    c.require(live.ROOT == c.ROOT, "Installed root differs")
    live.checked(BASE_SHA)
    after = snapshot(c, execute)
    validate_snapshot(live, release, after)
    result = {
        "status": "CONTROL_REPAIRED_STILL_HELD",
        "job_id": JOB,
        "controller_sha256": c.sha(code),
        "amendment_sha256": c.sha(c.wire(record)),
        "original_controller_sha256": OLD_SHA,
        "release_sha256": BASE_SHA,
        "after": after,
        "jobs_submitted": 0,
        "release_performed": False,
    }
    c.write(target / "INSTALL_COMPLETE.json", c.wire(result))
    return result


def update_gpu(c, spec, release, execute):
    c.checked(BASE_SHA)
    bind_submission(c, release)
    repair = json.loads(c.read(c.ROOT / "state/CONTROL_REPAIR.json"))
    c.require(
        repair["controller_sha256"] == spec["controller_sha256"]
        and repair["repair_tool_sha256"] == spec["repair_sha256"],
        "Repair binding differs",
    )
    complete = json.loads(c.read(c.ROOT / "repairs/job724808/INSTALL_COMPLETE.json"))
    c.require(
        complete["status"] == "CONTROL_REPAIRED_STILL_HELD"
        and complete["amendment_sha256"] == c.sha(c.wire(repair)),
        "Installed repair not verified",
    )
    before = snapshot(c, execute)
    f_before = validate_snapshot(c, release, before)
    folder = c.ROOT / "repairs/job724808"
    c.write(
        folder / "GPU_UPDATE_INTENT.json",
        c.wire(
            {
                "job_id": JOB,
                "argv": UPDATE,
                "before": before,
                "time_utc": c.now(),
                "amendment_sha256": c.sha(c.wire(repair)),
            }
        ),
    )
    response = execute(UPDATE)
    c.write(folder / "GPU_UPDATE_RESPONSE.json", c.wire(response))
    after = snapshot(c, execute)
    c.write(folder / "GPU_UPDATE_READBACK.json", c.wire(after))
    c.successful(response)
    f_after = validate_snapshot(c, release, after, corrected=True)
    # Besides exactly the GPU request, preserve all scheduling/budget/identity fields.
    for name in (
        "JobId",
        "JobName",
        "UserId",
        "Comment",
        "Partition",
        "Account",
        "QOS",
        "NumCPUs",
        "NumTasks",
        "CPUs/Task",
        "TimeLimit",
        "Requeue",
        "Restarts",
        "Command",
        "WorkDir",
        "StdIn",
        "StdOut",
        "StdErr",
        "MinMemoryNode",
        "Priority",
        "Reason",
        "JobState",
    ):
        c.require(
            f_before.get(name) == f_after.get(name),
            "Unexpected update side effect: " + name,
        )
    c.checked(BASE_SHA)
    result = {
        "status": "A100_CORRECTED_STILL_HELD",
        "job_id": JOB,
        "after": after,
        "controller_sha256": spec["controller_sha256"],
        "jobs_submitted": 0,
        "release_performed": False,
        "automatic_retry": False,
    }
    c.write(folder / "GPU_UPDATED.json", c.wire(result))
    return result


def remote(c, spec):
    os.umask(0o077)
    release = c.decode_release(c.read(c.ROOT / "RELEASE.json"), BASE_SHA)
    bind_submission(c, release)
    if spec["action"] == "install":
        return install(c, spec, release, c.command)
    if spec["action"] == "update-gpu":
        return update_gpu(c, spec, release, c.command)
    if spec["action"] == "inspect":
        snap = snapshot(c, c.command)
        corrected = "gres/gpu:nvidia_a100=1" in snap["job"]["stdout"]
        validate_snapshot(c, release, snap, corrected=corrected)
        c.checked(BASE_SHA)
        installed = c.ROOT / "state/CONTROL_REPAIR.json"
        return {
            "status": "VERIFIED_STILL_HELD",
            "snapshot": snap,
            "control_amendment": json.loads(c.read(installed))
            if installed.exists()
            else None,
            "jobs_submitted": 0,
            "release_performed": False,
        }
    raise RuntimeError("Action not authorized")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "install", "update-gpu"))
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--expected-controller-sha256", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    source, controller = (
        Path(__file__).read_bytes(),
        (HERE / "remote_control.py").read_bytes(),
    )
    if (
        hashlib.sha256(source).hexdigest() != args.expected_source_sha256
        or hashlib.sha256(controller).hexdigest() != args.expected_controller_sha256
    ):
        raise RuntimeError("Reviewed repair/controller sources changed")
    c = loaded(controller, "reviewed_repair_control", HERE / "remote_control.py")
    project = HERE.parents[1]
    evidence = project / "docs/superpowers/evidence/eager-small-production-20260917"
    socket = project / ".hakusan-control/master.sock"
    master = subprocess.run(
        ["ssh", "-S", str(socket), "-O", "check", "s2510040@hakusan1"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    c.require(master.returncode == 0, "SSH master unavailable: " + master.stderr)
    folder = Path(tempfile.mkdtemp(prefix="repair-" + args.action + "-", dir=evidence))
    print("REPAIR_EVIDENCE=" + str(folder), flush=True)
    spec = {
        "action": args.action,
        "controller_sha256": args.expected_controller_sha256,
        "repair_sha256": args.expected_source_sha256,
        "controller": base64.b64encode(controller).decode(),
    }
    if args.action != "inspect":
        c.write(
            evidence / ("LOCAL_REPAIR_" + args.action + "_INTENT.json"),
            c.wire(
                {
                    "evidence": str(folder),
                    "action": args.action,
                    "controller_sha256": args.expected_controller_sha256,
                    "repair_sha256": args.expected_source_sha256,
                    "job_id": JOB,
                    "time_utc": c.now(),
                    "no_release": True,
                }
            ),
        )
    code = "import base64,hashlib,types,json,traceback\n"
    for name, raw in (("c", controller), ("r", source)):
        code += (
            "raw=base64.b64decode("
            + repr(base64.b64encode(raw).decode())
            + ",validate=True)\n"
        )
        code += "assert hashlib.sha256(raw).hexdigest()==" + repr(c.sha(raw)) + "\n"
        code += (
            name
            + "=types.ModuleType("
            + repr("repair_" + name)
            + ');exec(compile(raw,"<pinned-repair>","exec"),vars('
            + name
            + "))\n"
        )
    code += (
        'try:\n result={"ok":True,"result":r.remote(c,'
        + repr(spec)
        + ')}\nexcept Exception as e:\n traceback.print_exc();result={"ok":False,"error":str(e)}\n'
    )
    code += 'print("REPAIR_RESULT="+json.dumps(result),flush=True)\nraise SystemExit(0 if result["ok"] else 2)\n'
    request = code.encode("ascii")
    c.write(folder / "request.py", request)
    argv = [
        "ssh",
        "-S",
        str(socket),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=12",
        "-o",
        "ProxyCommand=false",
        "s2510040@hakusan1",
        c.PYTHON,
        "-I",
        "-B",
        "-",
    ]
    with (
        (folder / "stdout.log").open("xb") as out,
        (folder / "stderr.log").open("xb") as err,
    ):
        try:
            rc = subprocess.run(
                argv, input=request, stdout=out, stderr=err, timeout=240
            ).returncode
        except subprocess.TimeoutExpired:
            rc = 124
    stdout, stderr = c.read(folder / "stdout.log"), c.read(folder / "stderr.log")
    lines = [
        line.split(b"=", 1)[1]
        for line in stdout.splitlines()
        if line.startswith(b"REPAIR_RESULT=")
    ]
    result = json.loads(lines[0]) if len(lines) == 1 else None
    c.write(
        folder / "RESULT.json",
        c.wire(
            {
                "job_id": JOB,
                "action": args.action,
                "rc": rc,
                "controller_sha256": args.expected_controller_sha256,
                "repair_sha256": args.expected_source_sha256,
                "request_sha256": c.sha(request),
                "stdout_sha256": c.sha(stdout),
                "stderr_sha256": c.sha(stderr),
                "result": result,
            }
        ),
    )
    print(
        json.dumps(result, indent=2) if result else stderr.decode(errors="replace"),
        flush=True,
    )
    print("REPAIR_RC=" + str(rc), flush=True)
    return 0 if rc == 0 and result and result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())

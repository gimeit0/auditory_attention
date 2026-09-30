"""Explicitly approved release of repaired Job724808, or read-only status.

No submission, resource change, cancellation, reconnect, or automatic retry.
The frozen package and repair sources are not modified.
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

JOB = "724808"
CONTROL_SHA = "d0fb9e2c295765c0aea835490d9ef78c01126d8e9a73b9541bc53c3ca665e503"
REPAIR_SHA = "5a365141361327b8b3f4526dff86a47d83126a49f784b64bca02609a5b2c3625"
AMENDMENT_SHA = "5e17eeea9e88102d8f2c6c5926c1a0f58190f0ec3e873f48990835be784dd163"
RELEASE_ARGV = ["/usr/bin/scontrol", "release", JOB]


def remote(c, r, action, source_sha, execute):
    os.umask(0o077)
    c.require(
        c.sha(c.read(c.ROOT / "tools/remote_control.py")) == CONTROL_SHA,
        "Installed controller differs",
    )
    c.require(
        c.sha(c.read(c.ROOT / "state/CONTROL_REPAIR.json")) == AMENDMENT_SHA,
        "Repair amendment differs",
    )
    release = c.checked(r.BASE_SHA)
    receipt = json.loads(c.read(c.ROOT / "state/SUBMISSION.json"))
    c.require(
        receipt["job_id"] == JOB
        and receipt["nonce"] == release["nonce"]
        and receipt["release_sha256"] == r.BASE_SHA,
        "Submission differs",
    )
    if action == "status":
        result = c.query(release, execute)
        c.successful(result["accounting"])
        # scontrol may no longer retain a finished job; retain its rc and sacct.
        for name in ("RELEASE_INTENT.json", "RELEASE_RESPONSE.json", "LAUNCH.json"):
            path = c.ROOT / "state" / name
            if path.exists():
                raw = c.read(path)
                result[name] = {"sha256": c.sha(raw), "record": json.loads(raw)}
        return result
    c.require(action == "release-once", "Unsupported action")
    r.bind_submission(c, release)  # Requires never released/launched, empty attempts.
    update = json.loads(c.read(c.ROOT / "repairs/job724808/GPU_UPDATED.json"))
    c.require(
        update["status"] == "A100_CORRECTED_STILL_HELD"
        and update["job_id"] == JOB
        and update["controller_sha256"] == CONTROL_SHA
        and update["release_performed"] is False,
        "GPU repair unverified",
    )
    r.validate_snapshot(c, release, update["after"], corrected=True)
    c.require(
        {n: c.sha(c.read(c.V4 / n)) for n in c.FIXED_INPUTS} == c.FIXED_INPUTS,
        "Original science evidence changed",
    )
    before = r.snapshot(c, execute)
    r.validate_snapshot(c, release, before, corrected=True)
    c.checked(r.BASE_SHA)
    r.bind_submission(c, release)
    intent = {
        "job_id": JOB,
        "release_sha256": r.BASE_SHA,
        "amendment_sha256": AMENDMENT_SHA,
        "source_sha256": source_sha,
        "time_utc": c.now(),
        "nonce": release["nonce"],
        "argv": RELEASE_ARGV,
        "authorization": {
            "user_reply": "好的",
            "scope": "Release the same repaired Job724808 for original32 batch16 three-model small verification; not the full checkpoint comparison.",
            "limits": c.LIMITS,
            "automatic_retry": False,
            "new_jobs": 0,
        },
        "before": before,
    }
    # Exclusive durable intent is the no-retry boundary, even on an RPC timeout.
    c.write(c.ROOT / "state/RELEASE_INTENT.json", c.wire(intent))
    response = execute(RELEASE_ARGV)
    c.write(c.ROOT / "state/RELEASE_RESPONSE.json", c.wire(response))
    c.successful(response)
    return {
        "status": "RELEASED_ONCE",
        "job_id": JOB,
        "jobs_submitted": 0,
        "automatic_retry": False,
        "response": response,
        "release_intent_sha256": c.sha(c.wire(intent)),
        "after": c.query(release, execute),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "release-once"))
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--confirm-release-job")
    args = parser.parse_args()
    if args.action == "release-once" and args.confirm_release_job != JOB:
        parser.error("release-once requires --confirm-release-job 724808")
    os.umask(0o077)
    here = Path(__file__).resolve().parent
    raws = {
        "c": (here / "remote_control.py").read_bytes(),
        "r": (here / "repair_724808.py").read_bytes(),
        "u": Path(__file__).read_bytes(),
    }
    for name, expected in (
        ("c", CONTROL_SHA),
        ("r", REPAIR_SHA),
        ("u", args.expected_source_sha256),
    ):
        if hashlib.sha256(raws[name]).hexdigest() != expected:
            raise RuntimeError("Reviewed source changed: " + name)
    c = types.ModuleType("local_release_control")
    exec(compile(raws["c"], "<pinned-control>", "exec"), vars(c))
    project = here.parents[1]
    evidence = project / "docs/superpowers/evidence/eager-small-production-20260917"
    socket = project / ".hakusan-control/master.sock"
    master = subprocess.run(
        ["ssh", "-S", str(socket), "-O", "check", "s2510040@hakusan1"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    c.require(master.returncode == 0, "SSH master unavailable: " + master.stderr)
    folder = Path(
        tempfile.mkdtemp(prefix="job724808-" + args.action + "-", dir=evidence)
    )
    print("ACTION_EVIDENCE=" + str(folder), flush=True)
    if args.action == "release-once":
        c.write(
            evidence / "LOCAL_RELEASE_724808_INTENT.json",
            c.wire(
                {
                    "job_id": JOB,
                    "action": args.action,
                    "time_utc": c.now(),
                    "source_sha256": args.expected_source_sha256,
                    "evidence": str(folder),
                    "user_reply": "好的",
                    "automatic_retry": False,
                }
            ),
        )
    code = "import base64,hashlib,types,json,traceback\n"
    for name, raw in raws.items():
        code += (
            "raw=base64.b64decode("
            + repr(base64.b64encode(raw).decode())
            + ",validate=True)\n"
        )
        code += "assert hashlib.sha256(raw).hexdigest()==" + repr(c.sha(raw)) + "\n"
        code += (
            name
            + "=types.ModuleType("
            + repr("release_" + name)
            + ");exec(compile(raw,'<pinned-release>','exec'),vars("
            + name
            + "))\n"
        )
    code += (
        "try:\n result={'ok':True,'result':u.remote(c,r,"
        + repr(args.action)
        + ","
        + repr(args.expected_source_sha256)
        + ",c.command)}\n"
    )
    code += "except Exception as e:\n traceback.print_exc();result={'ok':False,'error':str(e)}\n"
    code += "print('JOB_ACTION_RESULT='+json.dumps(result),flush=True)\nraise SystemExit(0 if result['ok'] else 2)\n"
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
        s.split(b"=", 1)[1]
        for s in stdout.splitlines()
        if s.startswith(b"JOB_ACTION_RESULT=")
    ]
    result = json.loads(lines[0]) if len(lines) == 1 else None
    c.write(
        folder / "RESULT.json",
        c.wire(
            {
                "job_id": JOB,
                "action": args.action,
                "time_utc": c.now(),
                "rc": rc,
                "source_sha256": args.expected_source_sha256,
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
    print("ACTION_RC=" + str(rc), flush=True)
    return 0 if rc == 0 and result and result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())

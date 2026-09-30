"""Explicit local S2a actions via an existing SSH connection. No auto retry."""

import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
EVIDENCE = PROJECT / "docs/superpowers/evidence/eager-s2a-production-20260918"
SOCKET = PROJECT / ".hakusan-control/master.sock"
spec = importlib.util.spec_from_file_location("s2_ship_control", HERE / "control_s2.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
c = m.c


def prepare():
    c.require(not os.path.lexists(EVIDENCE), "Existing package must not be replaced")
    data = {
        n: c.read(HERE / n) for n in ("control_s2.py", "launch_s2.py", "run_s2.sbatch")
    }
    data["s1_control.py"] = c.read(HERE.parent / "submission/remote_control.py")
    data["eager_compare.py"] = c.read(
        PROJECT / "same_bank_compare_2026_09_17_eager_v1/eager_compare.py"
    )
    c.require(
        c.sha(data["s1_control.py"]) == m.COMMON_SHA
        and c.sha(data["eager_compare.py"]) == c.CANDIDATE_SHA,
        "Reviewed helper/candidate changed",
    )
    data["AUTHORIZATION.json"] = c.wire(
        {
            "status": "USER_APPROVED",
            "user_reply": "好的",
            "recorded_utc": c.now(),
            "scope": "One new A100 job, 8 CPUs, 64 GiB, total 30 minutes. Two sequential independent model processes: original32 batch16 repeat then batch1; three unchanged checkpoints and controls. No automatic retry, no full run.",
            "limits": m.LIMITS,
            "conditional_release": True,
            "release_condition": "Held request, actual budget, identity and saved script must match. Stop held on mismatch.",
            "resource_repair_authorized": False,
        }
    )
    release = {
        "protocol": m.PROTOCOL,
        "nonce": uuid.uuid4().hex,
        "limits": m.LIMITS,
        "baseline_receipt_sha256": m.BASELINE_SHA,
        "files": {n: c.sha(b) for n, b in data.items()},
    }
    raw = c.wire(release)
    m.decode(raw, c.sha(raw))
    EVIDENCE.mkdir(mode=0o700)
    (EVIDENCE / "package").mkdir(mode=0o700)
    for name, value in data.items():
        c.write(EVIDENCE / "package" / name, value)
    c.write(EVIDENCE / "package/RELEASE.json", raw)
    c.write(
        EVIDENCE / "LOCAL_PACKAGE.json",
        c.wire(
            {
                "release_sha256": c.sha(raw),
                "ship_sha256": c.sha(c.read(__file__)),
                "remote_root": str(m.ROOT),
            }
        ),
    )
    print(
        json.dumps(
            {
                "status": "LOCAL_PACKAGE_ONLY",
                "release_sha256": c.sha(raw),
                "evidence": str(EVIDENCE),
            }
        )
    )


def package():
    record = json.loads(c.read(EVIDENCE / "LOCAL_PACKAGE.json"))
    c.require(
        record["ship_sha256"] == c.sha(c.read(__file__)), "Shipping source changed"
    )
    raw = c.read(EVIDENCE / "package/RELEASE.json")
    release = m.decode(raw, record["release_sha256"])
    files = {n: c.read(EVIDENCE / "package" / n) for n in m.FILES}
    c.require(
        all(c.sha(files[n]) == h for n, h in release["files"].items()),
        "Frozen package differs",
    )
    for name in ("control_s2.py", "launch_s2.py", "run_s2.sbatch"):
        c.require(c.read(HERE / name) == files[name], "Active source differs: " + name)
    return raw, files, record["release_sha256"]


def payload(action, raw, files, digest):
    spec = {"action": action, "release_sha256": digest}
    if action == "deploy":
        spec.update(
            release=base64.b64encode(raw).decode(),
            files={n: base64.b64encode(b).decode() for n, b in files.items()},
        )
    code = "import base64,hashlib,types,json,traceback\n"
    for var, name in (("common", "s1_control.py"), ("m", "control_s2.py")):
        data = files[name]
        code += (
            "raw=base64.b64decode("
            + repr(base64.b64encode(data).decode())
            + ",validate=True)\n"
        )
        code += "assert hashlib.sha256(raw).hexdigest()==" + repr(c.sha(data)) + "\n"
        code += var + "=types.ModuleType(" + repr("s2_" + var) + ")\n"
        if var == "m":
            code += "m.common=common\n"
        code += "exec(compile(raw,'<pinned-s2a>','exec'),vars(" + var + "))\n"
    code += "try:\n result={'ok':True,'result':m.remote(" + repr(spec) + ")}\n"
    code += "except Exception as e:\n traceback.print_exc();result={'ok':False,'error':str(e)}\n"
    code += "print('S2_ACTION_RESULT='+json.dumps(result),flush=True)\nraise SystemExit(0 if result['ok'] else 2)\n"
    return code.encode("ascii")


def act(action):
    raw, files, digest = package()
    master = subprocess.run(
        ["ssh", "-S", str(SOCKET), "-O", "check", "s2510040@hakusan1"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    c.require(
        master.returncode == 0,
        "SSH master unavailable; authenticate in terminal: " + master.stderr,
    )
    folder = Path(tempfile.mkdtemp(prefix=action + "-", dir=EVIDENCE))
    print("ACTION_EVIDENCE=" + str(folder), flush=True)
    if action in ("deploy", "test-only", "submit", "release"):
        c.write(
            EVIDENCE / ("LOCAL_" + action + "_INTENT.json"),
            c.wire(
                {
                    "action": action,
                    "time_utc": c.now(),
                    "release_sha256": digest,
                    "evidence": str(folder),
                    "automatic_retry": False,
                }
            ),
        )
    request = payload(action, raw, files, digest)
    c.write(folder / "request.py", request)
    argv = [
        "ssh",
        "-S",
        str(SOCKET),
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
    stdout, stderr = (
        c.read(folder / "stdout.log", maximum=100 * 1024**2),
        c.read(folder / "stderr.log"),
    )
    lines = [
        line.split(b"=", 1)[1]
        for line in stdout.splitlines()
        if line.startswith(b"S2_ACTION_RESULT=")
    ]
    result = json.loads(lines[0]) if len(lines) == 1 else None
    c.write(
        folder / "RESULT.json",
        c.wire(
            {
                "action": action,
                "time_utc": c.now(),
                "rc": rc,
                "release_sha256": digest,
                "request_sha256": c.sha(request),
                "stdout_sha256": c.sha(stdout),
                "stderr_sha256": c.sha(stderr),
                "result": result,
            }
        ),
    )
    if action == "collect" and rc == 0 and result and result.get("ok"):
        archive = folder / "archive"
        archive.mkdir(mode=0o700)
        for name, item in result["result"]["files"].items():
            relative = Path(name)
            c.require(
                not relative.is_absolute() and ".." not in relative.parts,
                "Unsafe collection path",
            )
            value = base64.b64decode(item["base64"], validate=True)
            c.require(c.sha(value) == item["sha256"], "Transfer digest differs")
            target = archive / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            c.write(target, value)
            c.require(c.sha(c.read(target)) == item["sha256"], "Local copy differs")
        print("COLLECTED_ARCHIVE=" + str(archive))
    else:
        print(
            json.dumps(result, indent=2) if result else stderr.decode(errors="replace"),
            flush=True,
        )
    print("ACTION_RC=" + str(rc), flush=True)
    return 0 if rc == 0 and result and result.get("ok") else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "prepare",
            "preflight",
            "deploy",
            "test-only",
            "submit",
            "release",
            "status",
            "collect",
        ),
    )
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == "prepare":
        prepare()
        return 0
    return act(args.action)


if __name__ == "__main__":
    raise SystemExit(main())

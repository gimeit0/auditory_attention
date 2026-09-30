"""Short explicit actions over existing SSH; no automatic auth/retry/submission."""

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
EVIDENCE = PROJECT / "docs/superpowers/evidence/eager-small-production-20260917"
SOCKET = PROJECT / ".hakusan-control/master.sock"
spec = importlib.util.spec_from_file_location(
    "small_ship_control", HERE / "remote_control.py"
)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def prepare():
    c.require(
        not EVIDENCE.exists(), "Package/evidence already exists; never replace it"
    )
    candidate = PROJECT / "same_bank_compare_2026_09_17_eager_v1/eager_compare.py"
    c.require(c.sha(c.read(candidate)) == c.CANDIDATE_SHA, "Candidate changed")
    auth = {
        "status": "USER_APPROVED",
        "user_reply": "开始吧",
        "approval_context": "Following explicit request: one A100, 8 CPU, 64 GiB, at most 30 minutes, one batch16 pass on original32, three fixed checkpoints and controls, no automatic retry. Conditional held release only if resources match. No resource repair, no full comparison.",
        "recorded_utc": c.now(),
        "limits": c.LIMITS,
        "models": ["formal40", "author_external", "valbest33"],
    }
    data = {
        n: c.read(HERE / n)
        for n in ("remote_control.py", "launch_small.py", "run_small.sbatch")
    }
    data.update(
        {"eager_compare.py": c.read(candidate), "AUTHORIZATION.json": c.wire(auth)}
    )
    release = {
        "nonce": uuid.uuid4().hex,
        "limits": c.LIMITS,
        "files": {n: c.sha(raw) for n, raw in data.items()},
        "protocol": "same_bank_eager_fp32_small_20260917_v1",
    }
    EVIDENCE.mkdir(mode=0o700)
    (EVIDENCE / "package").mkdir(mode=0o700)
    for name, raw in data.items():
        c.write(EVIDENCE / "package" / name, raw)
    c.write(EVIDENCE / "package/RELEASE.json", c.wire(release))
    c.write(
        EVIDENCE / "LOCAL_PACKAGE.json",
        c.wire(
            {
                "release_sha256": c.sha(c.wire(release)),
                "ship_sha256": c.sha(c.read(__file__)),
                "remote_root": str(c.ROOT),
            }
        ),
    )
    print(
        json.dumps(
            {
                "status": "LOCAL_PACKAGE_READY_NO_JOB",
                "evidence": str(EVIDENCE),
                "release_sha256": c.sha(c.wire(release)),
            }
        )
    )


def package():
    record = json.loads(c.read(EVIDENCE / "LOCAL_PACKAGE.json"))
    c.require(
        record["ship_sha256"] == c.sha(c.read(__file__)),
        "Shipping code changed after preparation",
    )
    raw = c.read(EVIDENCE / "package/RELEASE.json")
    release = c.decode_release(raw, record["release_sha256"])
    data = {n: c.read(EVIDENCE / "package" / n) for n in c.FILES}
    c.require(
        all(c.sha(data[n]) == h for n, h in release["files"].items()),
        "Local frozen package changed",
    )
    c.require(
        data["remote_control.py"] == c.read(HERE / "remote_control.py"),
        "Controller source drift",
    )
    return raw, data, record["release_sha256"]


def payload(action, raw, data, digest):
    spec = {"action": action, "release_sha256": digest}
    if action == "deploy":
        spec.update(
            release=base64.b64encode(raw).decode(),
            files={n: base64.b64encode(b).decode() for n, b in data.items()},
        )
    code = "import base64,hashlib,types,json,traceback\n"
    code += (
        "raw=base64.b64decode("
        + repr(base64.b64encode(data["remote_control.py"]).decode())
        + ",validate=True)\n"
    )
    code += (
        "assert hashlib.sha256(raw).hexdigest()=="
        + repr(c.sha(data["remote_control.py"]))
        + "\n"
    )
    code += 'm=types.ModuleType("small_remote_control");exec(compile(raw,"<pinned-small-control>","exec"),vars(m))\n'
    code += 'try:\n result={"ok":True,"result":m.remote(' + repr(spec) + ")}\n"
    code += 'except Exception as e:\n traceback.print_exc();result={"ok":False,"error":str(e)}\n'
    code += 'print("SMALL_ACTION_RESULT="+json.dumps(result),flush=True)\nraise SystemExit(0 if result["ok"] else 2)\n'
    return code.encode("ascii")


def act(action):
    raw, data, digest = package()
    checked = subprocess.run(
        ["ssh", "-S", str(SOCKET), "-O", "check", "s2510040@hakusan1"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    c.require(
        checked.returncode == 0,
        "Existing SSH master unavailable: "
        + checked.stderr
        + "; use connection script in your terminal",
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
    request = payload(action, raw, data, digest)
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
    # File-backed output: full errors/collection retained without truncating lines.
    with (
        (folder / "stdout.log").open("xb") as stdout,
        (folder / "stderr.log").open("xb") as stderr,
    ):
        try:
            result = subprocess.run(
                argv, input=request, stdout=stdout, stderr=stderr, timeout=240
            )
            rc = result.returncode
        except subprocess.TimeoutExpired:
            rc = 124
    stdout = c.read(folder / "stdout.log", maximum=100 * 1024**2)
    stderr = c.read(folder / "stderr.log", maximum=8 * 1024**2)
    lines = [
        s.split(b"=", 1)[1]
        for s in stdout.splitlines()
        if s.startswith(b"SMALL_ACTION_RESULT=")
    ]
    parsed = json.loads(lines[0]) if len(lines) == 1 else None
    record = {
        "action": action,
        "release_sha256": digest,
        "rc": rc,
        "stdout_sha256": c.sha(stdout),
        "stderr_sha256": c.sha(stderr),
        "request_sha256": c.sha(request),
        "result": parsed,
        "time_utc": c.now(),
        "automatic_retry": False,
    }
    c.write(folder / "RESULT.json", c.wire(record))
    if parsed and parsed.get("ok") and action == "collect":
        archive = folder / "archive"
        archive.mkdir(mode=0o700)
        for name, item in parsed["result"]["files"].items():
            relative = Path(name)
            c.require(
                not relative.is_absolute() and ".." not in relative.parts,
                "Unsafe archive path",
            )
            value = base64.b64decode(item["base64"], validate=True)
            c.require(c.sha(value) == item["sha256"], "Downloaded SHA mismatch")
            destination = archive / relative
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            c.write(destination, value)
        print("COLLECTED_ARCHIVE=" + str(archive))
        print(
            json.dumps(
                {
                    "status": "DOWNLOADED_NOT_YET_SCIENTIFICALLY_VERIFIED",
                    "files": len(parsed["result"]["files"]),
                }
            )
        )
    elif parsed:
        print(json.dumps(parsed, indent=2), flush=True)
    else:
        print(stderr.decode(errors="replace")[-5000:])
    print("ACTION_RC=" + str(rc), flush=True)
    if rc or not parsed or not parsed.get("ok"):
        print(
            "STOP: inspect saved evidence; never retry submit/release automatically.",
            flush=True,
        )
        return 2
    return 0


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

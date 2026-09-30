"""Explicit P05b transport. Local freeze requires an external approval record.

No password input, automatic reconnection/retry, resource correction or full run.
Remote calls use the already-authenticated shared SSH master only.
"""

import argparse
import base64
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import uuid

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("p05b_ship_control", HERE / "control.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
ROOT = M.S.PROJECT
MUTATIONS = {"publish", "test-only", "submit", "release"}


def freeze(destination, authorization, authorization_sha):
    """Never creates approval from 'continue'; requires an independently supplied file."""
    raw = M.C.read(authorization)
    M.S.require(
        M.digest(raw) == authorization_sha, "External authorization SHA differs"
    )
    auth = json.loads(raw)
    M.S.require(
        auth["status"] == "USER_APPROVED_P05B"
        and auth["limits"] == M.S.LIMITS
        and auth["stages"] == list(M.S.STAGES),
        "Explicit P05b approval required",
    )
    data = {n: M.C.read(ROOT / n) for n in M.FILES}
    release = dict(
        protocol=M.PROTOCOL,
        status="EXPLICITLY_APPROVED",
        limits=M.S.LIMITS,
        stages=list(M.S.STAGES),
        nonce=uuid.uuid4().hex,
        accounting_since=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT00:00:00"),
        baseline_receipts={k: v[1] for k, v in M.S.BASELINES.items()},
        files={n: M.digest(b) for n, b in data.items()},
        authorization=auth["authorization"],
        authorization_sha256=authorization_sha,
    )
    wire = M.S.wire(release)
    digest = M.digest(wire)
    M.decode(wire, digest)
    destination = Path(destination).absolute()
    M.C.safe(destination.parent, directory=True)
    destination.mkdir(mode=0o700)
    M.C.write(destination / "AUTHORIZATION.json", raw)
    M.C.write(destination / "RELEASE.json", wire)
    for name, value in data.items():
        path = destination / "package" / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        M.C.write(path, value)
    M.record(
        destination / "LOCAL.json",
        dict(release_sha256=digest, transport_sha256=M.S.sha(__file__)),
    )
    return {"status": "LOCAL_FROZEN_NO_REMOTE_ACTION", "release_sha256": digest}


def package(folder, expected):
    folder = M.C.safe(Path(folder).absolute(), directory=True)
    raw = M.C.read(folder / "RELEASE.json")
    r = M.decode(raw, expected)
    local = M.S.read(folder / "LOCAL.json")
    M.S.require(
        local == {"release_sha256": expected, "transport_sha256": M.S.sha(__file__)},
        "Transport or package binding changed",
    )
    M.S.require(
        M.digest(M.C.read(folder / "AUTHORIZATION.json")) == r["authorization_sha256"],
        "Authorization record changed",
    )
    files = {n: M.C.read(folder / "package" / n) for n in M.FILES}
    for name, content in files.items():
        M.S.require(
            M.digest(content) == r["files"][name] and M.C.read(ROOT / name) == content,
            "Frozen/active source changed: " + name,
        )
    return raw, files


BOOTSTRAP = r"""
import base64, hashlib, importlib.util, json, os, pathlib, pwd, sys, tempfile, traceback
assert sys.platform == "linux" and pwd.getpwuid(os.getuid()).pw_name == "s2510040"
assert sys.version.split()[0] == "3.11.5" and sys.flags.isolated and sys.dont_write_bytecode
os.umask(0o077)
with tempfile.TemporaryDirectory(prefix="p05b-transport-") as scratch:
    root = pathlib.Path(scratch)
    for name, item in REQUEST["files"].items():
        relative = pathlib.PurePosixPath(name)
        assert not relative.is_absolute() and ".." not in relative.parts
        raw = base64.b64decode(item["data"], validate=True)
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
    path = root / "same_bank_compare_2026_09_18_layout_v1/control.py"
    spec = importlib.util.spec_from_file_location("p05b_remote_control", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    action, digest = REQUEST["action"], REQUEST["release_sha256"]
    try:
        if action == "preflight":
            value = m.preflight()
        elif action == "publish":
            m.preflight()
            m.publish(base64.b64decode(REQUEST["release"], validate=True), digest,
                      {n: item["data"] for n, item in REQUEST["files"].items()})
            value = {"status": "PUBLISHED_NO_JOB"}
        elif action == "collect":
            value = m.export_attempt(digest, REQUEST["terminal_sha256"])
        else:
            value = {"test-only": m.test_only, "submit": m.submit, "release": m.release, "status": m.status}[action](digest)
        response = {"ok": True, "result": value}
    except Exception as error:
        traceback.print_exc()
        response = {"ok": False, "error": str(error)}
print("P05B_RESULT=" + json.dumps(response), flush=True)
raise SystemExit(0 if response["ok"] else 2)
"""


def request(action, raw, files, expected, terminal_sha=None):
    M.S.require(
        action in MUTATIONS | {"preflight", "status", "collect"}, "Invalid action"
    )
    r = M.decode(raw, expected)
    M.S.require(
        set(files) == M.FILES
        and all(M.digest(files[n]) == h for n, h in r["files"].items()),
        "Payload differs",
    )
    value = dict(
        action=action,
        release_sha256=expected,
        release=base64.b64encode(raw).decode(),
        files={
            n: {"data": base64.b64encode(b).decode(), "sha256": M.digest(b)}
            for n, b in files.items()
        },
        terminal_sha256=terminal_sha,
    )
    return ("REQUEST=" + repr(value) + "\n" + BOOTSTRAP).encode()


def result_from(stdout):
    lines = [
        line.split(b"=", 1)[1]
        for line in stdout.splitlines()
        if line.startswith(b"P05B_RESULT=")
    ]
    M.S.require(
        len(lines) == 1, "Missing/duplicate response; query only, never repeat mutation"
    )
    return json.loads(lines[0])


def act(folder, action, expected, terminal_sha=None, job=None, execute=subprocess.run):
    folder = Path(folder).absolute()
    raw, files = package(folder, expected)
    if action == "collect":
        M.S.require(terminal_sha and job, "External terminal SHA and job ID required")
    socket = ROOT / ".hakusan-control/master.sock"
    info = socket.lstat()
    M.S.require(
        stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid(),
        "No owned shared master",
    )
    check = execute(
        ["ssh", "-S", str(socket), "-O", "check", "s2510040@hakusan1"],
        capture_output=True,
        timeout=10,
    )
    M.S.require(
        check.returncode == 0,
        "Authenticate using existing helper; no automatic reconnect",
    )
    evidence = Path(tempfile.mkdtemp(prefix=action + "-", dir=folder))
    payload = request(action, raw, files, expected, terminal_sha)
    M.C.write(evidence / "request.py", payload)
    if action in MUTATIONS:
        M.record(
            folder / ("LOCAL_" + action + "_INTENT.json"),
            dict(
                action=action,
                release_sha256=expected,
                request_sha256=M.digest(payload),
                evidence=str(evidence),
                time_utc=M.C.now(),
            ),
        )
    argv = [
        "ssh",
        "-S",
        str(socket),
        "-o",
        "BatchMode=yes",
        "-o",
        "ProxyCommand=false",
        "-o",
        "ConnectTimeout=12",
        "-o",
        "ConnectionAttempts=1",
        "s2510040@hakusan1",
        M.S.PYTHON,
        "-I",
        "-B",
        "-",
    ]
    with (
        (evidence / "stdout.log").open("xb") as out,
        (evidence / "stderr.log").open("xb") as err,
    ):
        try:
            rc = execute(
                argv, input=payload, stdout=out, stderr=err, timeout=240
            ).returncode
        except subprocess.TimeoutExpired:
            rc = 124
        except OSError as error:
            err.write(str(error).encode())
            rc = 255
    stdout = M.C.read(evidence / "stdout.log", maximum=400 * 1024**2)
    try:
        response = result_from(stdout)
    except (ValueError, KeyError):
        response = None
    M.record(
        evidence / "RESULT.json",
        dict(
            rc=rc,
            action=action,
            release_sha256=expected,
            stdout_sha256=M.digest(stdout),
            stderr_sha256=M.S.sha(evidence / "stderr.log"),
            response=response
            if action != "collect"
            else {"ok": bool(response and response.get("ok"))},
        ),
    )
    M.S.require(
        rc == 0 and response and response.get("ok"),
        "Remote action failed/uncertain; evidence=" + str(evidence),
    )
    if action == "collect":
        value = M.import_attempt(
            response["result"], expected, job, terminal_sha, evidence / "collected"
        )
    else:
        value = response["result"]
    return {"evidence": str(evidence), "result": value}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    freeze_parser = commands.add_parser(
        "freeze", help="Local only; explicit approval file required"
    )
    freeze_parser.add_argument("--folder", type=Path, required=True)
    freeze_parser.add_argument("--authorization", type=Path, required=True)
    freeze_parser.add_argument("--authorization-sha256", required=True)
    for action in sorted(MUTATIONS | {"preflight", "status", "collect"}):
        p = commands.add_parser(action)
        p.add_argument("--folder", type=Path, required=True)
        p.add_argument("--release-sha256", required=True)
        if action == "collect":
            p.add_argument("--terminal-sha256", required=True)
            p.add_argument("--job-id", required=True)
    args = parser.parse_args()
    if args.action == "freeze":
        value = freeze(args.folder, args.authorization, args.authorization_sha256)
    else:
        value = act(
            args.folder,
            args.action,
            args.release_sha256,
            getattr(args, "terminal_sha256", None),
            getattr(args, "job_id", None),
        )
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()

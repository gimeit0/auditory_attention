"""Local GPU controller: explicit actions; pre-existing SSH master only.

No password collection/reconnection. submit additionally requires a new exact
resource confirmation and a reviewed, matching successful test-only receipt.
"""
import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[3]
sys.path.insert(0, str(HERE))
import remote_ops as ops  # noqa: E402

EVIDENCE = WORKSPACE / "docs/superpowers/evidence/gpu-control-20260914-v4"
SOCKET = WORKSPACE / ".hakusan-control/master.sock"


def package():
    raw = ops.read(HERE / "CONTROL_RELEASE.json")
    release = ops.validate_release(raw, ops.sha(raw))
    files, total = {}, 0
    for name, digest in release["files"].items():
        data = ops.read(WORKSPACE / ops.member(name))
        total += len(data)
        ops.require(total <= 16 * 1024**2 and ops.sha(data) == digest, "local source SHA/size differs: " + name)
        files[name] = data
    candidate = json.loads(files[ops.MANIFEST])
    ops.require(len(candidate["files"]) == 52 and all(release["files"].get(n) == s for n, s in candidate["files"].items()),
                "job candidate inventory differs")
    return raw, release, files


def ssh_command(socket_path):
    return ["/usr/bin/ssh", "-S", str(socket_path), "-o", "ControlMaster=no", "-o", "BatchMode=yes",
            "-o", "ProxyCommand=/usr/bin/false", "-o", "ConnectionAttempts=1", "-o", "ConnectTimeout=12",
            "-o", "StrictHostKeyChecking=yes", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2",
            "s2510040@hakusan1", "/home/s2510040/miniconda3/envs/attn/bin/python -I -B -"]


def master_check(socket_path):
    ops.directory(socket_path.parent)
    info = ops.path_check(socket_path).lstat()
    ops.require(stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid(), "owned authenticated SSH socket required")
    result = subprocess.run(["/usr/bin/ssh", "-S", str(socket_path), "-O", "check", "s2510040@hakusan1"],
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=15)
    ops.require(result.returncode == 0, "shared master unavailable; authenticate separately, no automatic reconnect")


def test_receipt(path, release_sha):
    value = json.loads(ops.read(path))
    ops.require(value.get("action") == "test-only" and value.get("returncode") == 0
                and value.get("release_sha256") == release_sha and value.get("remote", {}).get("ok") is True,
                "matching successful test-only receipt required")
    result = value["remote"]["result"]
    ops.require(result.get("status") == "SCHEDULER_TEST_ONLY_PASS", "not a successful scheduler test")
    return {"test_id": result["test_id"], "test_sha256": result["test_sha256"]}


def make_request(action, release_raw, files, *, confirmation=None, reviewed=None):
    spec = {"action": action, "request_id": uuid.uuid4().hex, "release_sha256": ops.sha(release_raw)}
    if action in ("preflight", "deploy", "status"):
        spec["release_base64"] = base64.b64encode(release_raw).decode("ascii")
    if action == "deploy":
        spec["files"] = {n: base64.b64encode(raw).decode("ascii") for n, raw in files.items()}
    if action == "submit":
        ops.require(confirmation == ops.CONFIRM and type(reviewed) is dict, "explicit new resource confirmation and test receipt required")
        spec.update(reviewed)
        spec["confirm"] = confirmation
        spec["authorization"] = {"approved": True, "package_sha256": ops.PACKAGE_SHA, "pair_nonce": uuid.uuid4().hex,
                                 "limits": dict(ops.LIMITS), "scope": ops.SCOPE}
    return spec


def payload(spec, source):
    # Decode only locally pinned source; remote SPEC fields are data, not code.
    header = "import base64, hashlib\nSPEC=" + repr(spec) + "\n"
    header += "_source=base64.b64decode(" + repr(base64.b64encode(source).decode("ascii")) + ",validate=True)\n"
    header += "SOURCE_SHA=hashlib.sha256(_source).hexdigest()\nexec(compile(_source,'<pinned-gpu-control>','exec'))\n"
    return header.encode("ascii")


def transport(command, payload_bytes, folder, *, timeout=180, log_cap=16 * 1024**2):
    # File-backed stdin avoids producer/SSH pipe deadlocks on the bounded upload.
    ops.write_new(folder / "request.py", payload_bytes)
    process, error = None, None
    started = time.monotonic()
    with (folder / "request.py").open("rb") as source, (folder / "output.log").open("xb") as log:
        try:
            process = subprocess.Popen(command, stdin=source, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True, close_fds=True)
            heartbeat = started
            while process.poll() is None:
                now = time.monotonic()
                if now - started >= timeout:
                    raise TimeoutError("control operation timeout; state may have changed, query without retry")
                if os.fstat(log.fileno()).st_size > log_cap:
                    raise RuntimeError("control log budget exceeded")
                if now - heartbeat >= 30:
                    print("CONTROL_WAIT_SECONDS=" + str(round(now - started)), flush=True)
                    heartbeat = now
                time.sleep(0.1)
            ops.require(os.fstat(log.fileno()).st_size <= log_cap, "control log budget exceeded")
        except BaseException as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            log.flush()
            os.fsync(log.fileno())
    return {"pid": process.pid if process else None,
            "returncode": process.returncode if process else None, "error": error,
            "elapsed_seconds": round(time.monotonic() - started, 3)}


def operate(spec, files, evidence=EVIDENCE, execute=None):
    ops.require(evidence.is_dir(), "local evidence directory required")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(tempfile.mkdtemp(prefix=spec["action"] + "-" + stamp + "-", dir=evidence))
    # Fixed local intent prevents a second SSH submit attempt even when the
    # remote reply was lost. Merely displaying confirmation text is not consent.
    if spec["action"] == "submit":
        ops.write_new(evidence / "LOCAL_SUBMIT_INTENT.json", ops.wire({
            "release_sha256": spec["release_sha256"], "authorization": spec["authorization"],
            "request_id": spec["request_id"], "test_id": spec["test_id"], "test_sha256": spec["test_sha256"],
            "automatic_retry": False}))
    request = payload(spec, files[ops.OPS])
    try:
        run = (execute or transport)(ssh_command(SOCKET), request, folder)
    except BaseException as exc:
        run = {"returncode": None, "error": {"type": type(exc).__name__, "message": str(exc)}}
    log_path = folder / "output.log"
    if not log_path.exists():
        ops.write_new(log_path, b"")
    log_size = log_path.stat().st_size
    if log_size <= 16 * 1024**2:
        raw = ops.read(log_path, limit=16 * 1024**2)
        log_record = {"size": len(raw), "sha256": ops.sha(raw), "complete": True}
    else:
        # Preserve the oversized original file; only display/hash a bounded
        # prefix. Never label this as a complete-log hash or a successful call.
        with log_path.open("rb") as stream:
            raw = stream.read(256 * 1024)
        log_record = {"size": log_size, "prefix_sha256": ops.sha(raw), "complete": False}
        run["error"] = {"type": "LogBudgetError", "message": "oversized original log retained"}
    remote, parse_error = None, None
    try:
        lines = [line[len("GPU_CONTROL="):] for line in raw.decode(errors="replace").splitlines() if line.startswith("GPU_CONTROL=")]
        ops.require(len(lines) == 1, "exactly one structured remote result required")
        remote = json.loads(lines[0])
        ops.require(all(remote.get(k) == spec[k] for k in ("request_id", "action", "release_sha256")), "remote response binding differs")
        ops.require(remote.get("ok") is True and run["returncode"] == 0 and run["error"] is None, "remote operation failed/uncertain")
    except BaseException as exc:
        parse_error = {"type": type(exc).__name__, "message": str(exc)}
    receipt = {"action": spec["action"], "request_id": spec["request_id"], "release_sha256": spec["release_sha256"],
               "package_sha256": ops.PACKAGE_SHA, "returncode": 0 if parse_error is None else 2,
               "transport": run, "parse_error": parse_error, "remote": remote,
               "output": log_record, "payload_sha256": ops.sha(request), "automatic_retry": False}
    ops.write_new(folder / "receipt.json", ops.wire(receipt))
    print("GPU_CONTROL_EVIDENCE=" + str(folder), flush=True)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return receipt


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("check-only", "preflight", "deploy", "test-only", "submit", "status"))
    p.add_argument("--confirm", choices=(ops.CONFIRM,))
    p.add_argument("--test-receipt", type=Path)
    args = p.parse_args()
    raw, release, files = package()
    if args.action == "check-only":
        print(json.dumps({"status": "LOCAL_GPU_CONTROL_PACKAGE_PASS", "files": len(files), "release_sha256": ops.sha(raw),
                          "job_package_sha256": ops.PACKAGE_SHA, "proposed_limits": ops.LIMITS,
                          "resources_authorized": False, "jobs_submitted": 0, "remote_executed": False}, sort_keys=True))
        return 0
    reviewed = None
    if args.action == "submit":
        ops.require(args.confirm == ops.CONFIRM and args.test_receipt is not None, "new explicit confirmation and reviewed test receipt required")
        reviewed = test_receipt(args.test_receipt.resolve(), ops.sha(raw))
    else:
        ops.require(args.confirm is None and args.test_receipt is None, "authorization arguments only valid for submit")
    spec = make_request(args.action, raw, files, confirmation=args.confirm, reviewed=reviewed)
    master_check(SOCKET)  # no intent or upload if authentication unavailable
    EVIDENCE.mkdir(mode=0o700, exist_ok=True)
    ops.directory(EVIDENCE)
    result = operate(spec, files)
    package()  # source postcheck, never an automatic repeat of the remote action
    return result["returncode"]


if __name__ == "__main__":
    raise SystemExit(main())

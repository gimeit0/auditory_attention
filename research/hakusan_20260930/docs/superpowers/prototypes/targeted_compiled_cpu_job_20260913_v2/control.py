"""Local controller: no passwords, no retry, at most one submission intent."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
EVIDENCE = ROOT / "docs/superpowers/evidence/compiled-cpu-job-20260913-v2"
OPS = "docs/superpowers/prototypes/targeted_compiled_cpu_job_20260913_v2/remote_ops.py"


def package():
    release_raw = (HERE / "RELEASE.json").read_bytes()
    release = json.loads(release_raw)
    files, total = {}, 0
    for name, digest in release["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("invalid package path")
        path = ROOT / relative
        if not stat.S_ISREG(path.lstat().st_mode):
            raise RuntimeError("source is not regular")
        raw = path.read_bytes()
        total += len(raw)
        if len(raw) > 2 * 1024**2 or total > 8 * 1024**2 or hashlib.sha256(raw).hexdigest() != digest:
            raise RuntimeError("source SHA/budget differs: " + name)
        files[name] = raw
    return release_raw, files


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check-only", "deploy", "test-only", "submit", "status", "fetch"))
    args = parser.parse_args()
    release_raw, files = package()
    release_sha = hashlib.sha256(release_raw).hexdigest()
    if args.action == "check-only":
        print(json.dumps({"status": "CPU_JOB_PACKAGE_PASS", "files": len(files), "release_sha256": release_sha}))
        return 0
    socket = ROOT / ".hakusan-control/master.sock"
    info = socket.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError("owned authenticated SSH socket required")
    EVIDENCE.mkdir(mode=0o700, exist_ok=True)
    if args.action == "submit":
        with (EVIDENCE / "LOCAL_SUBMIT_INTENT.json").open("x") as stream:
            json.dump({"release_sha256": release_sha, "action": "submit_once", "automatic_retry": False}, stream)
    spec = {"action": args.action, "release_sha256": release_sha}
    if args.action == "deploy":
        spec.update({"release_base64": base64.b64encode(release_raw).decode(),
                     "files": {n: base64.b64encode(raw).decode() for n, raw in files.items()}})
    payload = ("SPEC=" + repr(spec) + "\n").encode() + files[OPS]
    command = ["/usr/bin/ssh", "-S", str(socket), "-o", "ControlMaster=no", "-o", "BatchMode=yes",
               "-o", "ConnectTimeout=12", "-o", "ConnectionAttempts=1", "-o", "StrictHostKeyChecking=yes",
               "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2", "s2510040@hakusan1",
               "/home/s2510040/miniconda3/envs/attn/bin/python -I -B -"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(tempfile.mkdtemp(prefix=args.action + "-" + stamp + "-", dir=EVIDENCE))
    with (folder / "output.log").open("xb") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.communicate(input=payload, timeout=90)
            rc = process.returncode
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            rc = 124
    raw = (folder / "output.log").read_bytes()
    records = [json.loads(line.removeprefix("CPU_OPERATION=")) for line in raw.decode(errors="replace").splitlines()
               if line.startswith("CPU_OPERATION=")]
    result = records[0] if len(records) == 1 else None
    if rc == 0 and result is None:
        rc = 2
    if args.action == "fetch" and rc == 0:
        for name, record in result["files"].items():
            if Path(name).name != name:
                raise RuntimeError("unsafe fetched filename")
            data = base64.b64decode(record["base64"], validate=True)
            if len(data) != record["size"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise RuntimeError("fetched bytes differ")
            with (folder / name).open("xb") as stream:
                stream.write(data)
        shown = {"status": result["status"], "job_id": result["job_id"], "files": list(result["files"])}
    else:
        shown = result
    receipt = {"action": args.action, "returncode": rc, "release_sha256": release_sha,
               "output_sha256": hashlib.sha256(raw).hexdigest(), "output_size": len(raw),
               "payload_sha256": hashlib.sha256(payload).hexdigest(), "result": shown, "automatic_retry": False}
    with (folder / "receipt.json").open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print("CPU_OPERATION_EVIDENCE=" + str(folder), flush=True)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    if rc != 0:
        print(raw.decode(errors="replace")[-5000:], flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

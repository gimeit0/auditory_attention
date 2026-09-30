"""Bounded synthetic CPU cold pair; no authentication prompts or Slurm calls."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def package():
    records = json.loads((HERE / "SOURCE_MANIFEST.json").read_bytes())["files"]
    if not 15 <= len(records) <= 24:
        raise RuntimeError("source inventory count differs")
    sources, total = {}, 0
    for name, expected in records.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".py":
            raise RuntimeError("invalid package member")
        path = ROOT / relative
        if not stat.S_ISREG(path.lstat().st_mode):
            raise RuntimeError("package member not regular")
        raw = path.read_bytes()
        total += len(raw)
        if len(raw) > 2 * 1024**2 or total > 8 * 1024**2 or digest(raw) != expected:
            raise RuntimeError("source changed or exceeds budget: " + name)
        sources[name] = raw.decode()
    return records, sources


BOOTSTRAP = '''
import base64, hashlib, json, os, pathlib, pwd, signal, subprocess, sys, tempfile, time, zlib
os.umask(0o077)
if SPEC["remote"] and (sys.version.split()[0] != "3.11.5" or pwd.getpwuid(os.getuid()).pw_name != "s2510040"):
    raise RuntimeError("unexpected remote Python/account")
def expired(*_):
    raise TimeoutError("80-second total CPU bootstrap deadline")
signal.signal(signal.SIGALRM, expired)
signal.alarm(80)
started = time.monotonic()
sources = json.loads(zlib.decompress(base64.b64decode(SPEC["blob"])))
if set(sources) != set(SPEC["pins"]):
    raise RuntimeError("payload inventory differs")
children, rc = [], 0
with tempfile.TemporaryDirectory(prefix="audattn-compiled-pair-", dir="/tmp") as temporary:
    root = pathlib.Path(temporary)
    for name, digest in SPEC["pins"].items():
        path = pathlib.Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError("invalid package path")
        raw = sources[name].encode()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise RuntimeError("payload SHA differs")
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with target.open("xb") as stream:
            stream.write(raw)
    env = dict(os.environ)
    env.update({"CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0",
                "PYTHONNOUSERSITE": "1", "TMPDIR": str(root)})
    modes = ("reference", "observed") if SPEC["remote"] else ("local-tests",)
    for mode in modes:
        remaining = 75 - (time.monotonic() - started)
        if remaining <= 0:
            rc = 124
            break
        if SPEC["remote"]:
            command = [sys.executable, "-I", "-B", str(root / SPEC["entry"]), mode]
        else:
            command = [sys.executable, "-I", "-B", "-m", "unittest", "discover",
                       "-s", str((root / SPEC["entry"]).parent), "-p", "test_verify_pair.py", "-v"]
        child_start = time.monotonic()
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                       env=env, start_new_session=True)
            try:
                try:
                    rc = process.wait(timeout=min(60, remaining))
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    rc = 124
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            output.seek(0)
            raw = output.read(4 * 1024**2 + 1)
        if len(raw) > 4 * 1024**2:
            raise RuntimeError("worker output exceeds budget")
        print(raw.decode(errors="replace"), end="", flush=True)
        records = [json.loads(line[len("LIFETIME_CHILD="):]) for line in raw.decode(errors="replace").splitlines()
                   if line.startswith("LIFETIME_CHILD=")]
        if SPEC["remote"] and rc == 0 and (len(records) != 1 or records[0].get("pid") != process.pid
                                           or records[0].get("mode") != mode):
            rc = 2
        children.append({"pid": process.pid, "mode": mode, "returncode": rc,
                         "elapsed_seconds": round(time.monotonic() - child_start, 3),
                         "output_sha256": hashlib.sha256(raw).hexdigest(), "output_size": len(raw)})
        if rc != 0:
            break
    for name, expected in SPEC["pins"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError("source changed during execution")
removed = not root.exists()
signal.alarm(0)
print("LIFETIME_BOOTSTRAP=" + json.dumps({"returncode": rc, "children": children,
      "temporary_directory_removed": removed, "source_sha256": SPEC["pins"],
      "remote": SPEC["remote"], "jobs_submitted": 0}), flush=True)
raise SystemExit(rc if removed else 2)
'''


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    flags = parser.add_mutually_exclusive_group(required=True)
    for name in ("check-only", "local-tests", "remote-pair"):
        flags.add_argument("--" + name, action="store_true")
    args = parser.parse_args()
    records, sources = package()
    if args.check_only:
        print("COMPILED_LIFETIME_SOURCE_SHA=PASS; no connection or execution")
        return 0
    remote = args.remote_pair
    if remote:
        socket = ROOT / ".hakusan-control/master.sock"
        info = socket.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError("owned authenticated SSH socket required")
        command = ["/usr/bin/ssh", "-S", str(socket), "-o", "BatchMode=yes", "-o", "ControlMaster=no",
                   "-o", "ConnectTimeout=12", "-o", "ConnectionAttempts=1", "-o", "StrictHostKeyChecking=yes",
                   "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2", "s2510040@hakusan1",
                   "env CUDA_VISIBLE_DEVICES= /home/s2510040/miniconda3/envs/attn/bin/python -I -B -"]
    else:
        command = [sys.executable, "-I", "-B", "-"]
    spec = {"remote": remote, "pins": records, "entry": str((HERE / "worker.py").relative_to(ROOT)),
            "blob": base64.b64encode(zlib.compress(json.dumps(sources).encode())).decode()}
    payload = ("SPEC=" + repr(spec) + "\n" + BOOTSTRAP).encode()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(tempfile.mkdtemp(prefix="compiled-lifetime-" + ("remote-" if remote else "local-") + stamp + "-",
                                  dir=ROOT / "docs/superpowers/evidence"))
    print("COMPILED_LIFETIME_EVIDENCE=" + str(folder), flush=True)
    with (folder / "output.log").open("xb") as output:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            process.communicate(input=payload, timeout=90)
            rc = process.returncode
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            rc = 124
    raw = (folder / "output.log").read_bytes()
    text = raw.decode(errors="replace")
    summary, error = None, None
    try:
        boots = [json.loads(line.removeprefix("LIFETIME_BOOTSTRAP=")) for line in text.splitlines()
                 if line.startswith("LIFETIME_BOOTSTRAP=")]
        if rc != 0 or len(boots) != 1:
            raise RuntimeError("missing successful bootstrap; rc=" + str(rc))
        boot = boots[0]
        if (boot["returncode"] != 0 or boot["temporary_directory_removed"] is not True
                or boot["source_sha256"] != records or boot["remote"] is not remote
                or boot["jobs_submitted"] != 0 or package()[0] != records):
            raise RuntimeError("bootstrap source/cleanup/returncode mismatch")
        if remote:
            values = [json.loads(line.removeprefix("LIFETIME_CHILD=")) for line in text.splitlines()
                      if line.startswith("LIFETIME_CHILD=")]
            if len(values) != 2 or len(boot["children"]) != 2:
                raise RuntimeError("two complete cold children required")
            for value, child in zip(values, boot["children"]):
                if value["pid"] != child["pid"] or value["mode"] != child["mode"] or child["returncode"] != 0:
                    raise RuntimeError("child process binding differs")
            path = HERE / "verify_pair.py"
            module_spec = importlib.util.spec_from_file_location("compiled_pair_verifier", path)
            verifier = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(verifier)
            summary = verifier.verify_pair(*values)
        else:
            if "Ran 16 tests" not in text or "\nOK\n" not in text or len(boot["children"]) != 1:
                raise RuntimeError("16 zero-skip verifier tests required")
            summary = {"status": "OFFLINE_PAIR_VERIFIER_TESTS_PASS", "tests": 16,
                       "compiled_execution_validated": False}
    except (ValueError, KeyError, TypeError, RuntimeError) as exc:
        error = str(exc)
    receipt = {"status": "COMPILED_LIFETIME_VERIFIED" if summary else "COMPILED_LIFETIME_NOT_VERIFIED",
               "returncode": rc, "summary": summary, "error": error,
               "output_sha256": digest(raw), "output_size": len(raw), "payload_sha256": digest(payload),
               "source_sha256": records, "remote": remote, "jobs_submitted": 0,
               "ready_for_gpu": False, "automatic_retry": False, "total_local_deadline_seconds": 90,
               "total_remote_deadline_seconds": 80, "child_deadline_seconds": 60}
    with (folder / "receipt.json").open("x") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in receipt.items() if k != "source_sha256"}, sort_keys=True), flush=True)
    if not summary:
        print("\n".join(line[:500] for line in text.splitlines()[-16:]), flush=True)
    return 0 if summary else (rc or 2)


if __name__ == "__main__":
    raise SystemExit(main())

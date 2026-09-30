"""One authenticated, bounded synthetic CPU validation. No production deployment.

Copies pinned test sources to a private ephemeral /tmp directory, runs 62 CPU
tests with a 60-second child timeout, then cleans its temporary directory.
The four static local-path checks are deliberately not labelled remote tests.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


PINS = {
    "targeted_trace_20260911/trace_observer.py":
        "dcbe162257fc130450a2f2b4a2fd5680caded503d10c67b704c6a0331ec86328",
    "targeted_trace_20260911/test_trace_observer.py":
        "25c427438faedd30fde6770ff1f7f26598f809d6a949d3f6050200b0f0450b16",
    "targeted_stream_20260911/stream_capture.py":
        "e0a0282a80b4e68aa0c0d250a0d1383238bfc948b871b9ab05baa585d386c01e",
    "targeted_stream_20260911/stream_observer.py":
        "d939436a0cc84c84c9e56a9c927719df677008405d1545acd537bb8f9bc79474",
    "targeted_stream_20260911/test_stream_capture.py":
        "cc1aba2b60dc0d8da1f3b1b2805d4cdc68c460ac283a36f97f953a97a2bd8527",
    "targeted_stream_20260911/run_cpu_subset.py":
        "cbbfa62973a9a9923286fd3546d9f1619b207e03919656705defc7c323d9371e",
}


def bootstrap(sources, local):
    spec = {"sources": sources, "pins": PINS, "local": local,
            "python": sys.version.split()[0] if local else "3.11.5",
            "torch": "2.12.1" if local else "2.1.1+cu118"}
    return ("SPEC = " + repr(spec) + "\n" + '''
import hashlib, json, os, pathlib, pwd, signal, subprocess, sys, tempfile
os.umask(0o077)
if sys.version.split()[0] != SPEC["python"]:
    raise RuntimeError("probe Python differs")
if not SPEC["local"] and pwd.getpwuid(os.getuid()).pw_name != "s2510040":
    raise RuntimeError("unexpected remote account")
for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[key] = "1"
os.environ["CUDA_VISIBLE_DEVICES"] = ""
import torch
if torch.__version__ != SPEC["torch"] or torch.cuda.is_initialized():
    raise RuntimeError("probe torch/CPU scope differs")
def expired(*_):
    raise TimeoutError("80-second remote bootstrap deadline")
signal.signal(signal.SIGALRM, expired)
signal.alarm(80)
scope = "LOCAL_STREAM_BOOTSTRAP_SELF_TEST" if SPEC["local"] else "HAKUSAN_STREAM_CPU_PROBE"
print("PROBE_SCOPE=" + scope, flush=True)
code = 2
summary = None
with tempfile.TemporaryDirectory(prefix="audattn-stream-cpu-", dir="/tmp") as directory:
    root = pathlib.Path(directory)
    for relative, sha in SPEC["pins"].items():
        data = SPEC["sources"][relative].encode("utf-8")
        if hashlib.sha256(data).hexdigest() != sha:
            raise RuntimeError("payload source digest differs")
        path = root / relative
        path.parent.mkdir(mode=0o700, exist_ok=True)
        with path.open("xb") as output:
            output.write(data)
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise RuntimeError("temporary source digest differs")
    # All generated tensor test files also live under this bounded-lifetime root.
    environment = dict(os.environ)
    environment["TMPDIR"] = str(root)
    command = [sys.executable, "-I", "-B",
               str(root / "targeted_stream_20260911/run_cpu_subset.py")]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env=environment, timeout=60, check=False)
        raw, code = result.stdout, result.returncode
    except subprocess.TimeoutExpired as error:
        raw, code = error.stdout or b"", 124
    print(raw.decode("utf-8", errors="replace"), end="", flush=True)
    records = [json.loads(line) for line in raw.decode("utf-8", errors="replace").splitlines()
               if line.startswith('{"status":')]
    for relative, sha in SPEC["pins"].items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != sha:
            raise RuntimeError("source changed during tests")
    if code == 0:
        if not (len(records) == 1 and records[0]["status"] == "STREAM_PORTABLE_CPU_PASS"
                and records[0]["tests"] == 62 and records[0]["excluded_local_static_tests"] == 4
                and records[0]["torch"] == SPEC["torch"]
                and records[0]["cuda_initialized"] is False
                and records[0]["production_model_loaded"] is False):
            raise RuntimeError("successful child evidence missing or inconsistent")
        summary = records[0]
if root.exists():
    raise RuntimeError("temporary directory cleanup not confirmed")
signal.alarm(0)
print(json.dumps({"probe_kind": scope, "rc": code, "summary": summary,
                  "temporary_source_files_written": True,
                  "temporary_directory_removed": True,
                  "production_files_published": False,
                  "production_model_loaded": False, "jobs_submitted": 0,
                  "source_sha256": SPEC["pins"]}), flush=True)
raise SystemExit(code)
''').encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    workspace = here.parents[3]
    sources = {}
    for relative, sha in PINS.items():
        path = here.parent / relative
        if not stat.S_ISREG(path.lstat().st_mode):
            raise RuntimeError("not a regular source file")
        data = path.read_bytes()
        if len(data) > 128 * 1024 or hashlib.sha256(data).hexdigest() != sha:
            raise RuntimeError(f"source digest differs: {relative}")
        sources[relative] = data.decode("utf-8")
    payload = bootstrap(sources, args.self_test)
    if args.self_test:
        command = [sys.executable, "-I", "-B", "-"]
    else:
        socket = workspace / ".hakusan-control/master.sock"
        info = socket.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError("authenticated owned SSH socket required")
        remote = ("env CUDA_VISIBLE_DEVICES= OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 "
                  "OPENBLAS_NUM_THREADS=1 /home/s2510040/miniconda3/envs/attn/bin/python -I -B -")
        command = ["/usr/bin/ssh", "-S", str(socket), "-o", "BatchMode=yes",
                   "-o", "ConnectTimeout=12", "-o", "ConnectionAttempts=1",
                   "-o", "StrictHostKeyChecking=yes", "-o", "ServerAliveInterval=15",
                   "-o", "ServerAliveCountMax=2", "s2510040@hakusan1", remote]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    label = "stream-bootstrap-selftest-" if args.self_test else "stream-remote-cpu-"
    run = Path(tempfile.mkdtemp(prefix=label + stamp + "-",
                               dir=workspace / "docs/superpowers/evidence"))
    print(f"STREAM_PROBE_LOG_DIRECTORY={run}", flush=True)
    code, error = 2, None
    with (run / "output.log").open("xb") as output:
        try:
            result = subprocess.run(command, input=payload, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=90, check=False)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code, error = 124, "90-second local deadline; no automatic retry"
        except OSError as failure:
            error = str(failure)
    raw = (run / "output.log").read_bytes()
    records = [json.loads(line) for line in raw.decode("utf-8", errors="replace").splitlines()
               if line.startswith('{"probe_kind":')]
    verified = (code == 0 and len(records) == 1 and records[0]["rc"] == 0
                and records[0]["source_sha256"] == PINS
                and records[0]["temporary_directory_removed"] is True
                and records[0]["summary"]["tests"] == 62)
    receipt = {"status": "STREAM_CPU_PROBE_VERIFIED" if verified else "PROBE_NOT_VERIFIED",
               "returncode": code, "error": error, "remote_probe": not args.self_test,
               "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "source_sha256": PINS, "bootstrap_sha256": hashlib.sha256(payload).hexdigest(),
               "output_sha256": hashlib.sha256(raw).hexdigest(),
               "probe_record": records[0] if len(records) == 1 else None,
               "production_model_loaded": False, "jobs_submitted": 0, "ready_for_gpu": False}
    with (run / "receipt.json").open("x") as output:
        json.dump(receipt, output, indent=2)
        output.write("\n")
    print(raw.decode("utf-8", errors="replace"), end="", flush=True)
    print(f"STREAM_PROBE_VERIFIED={int(verified)}", flush=True)
    return 0 if verified else (code or 2)


if __name__ == "__main__":
    raise SystemExit(main())

"""One-shot in-memory synthetic CPU probe over an already authenticated SSH.

No checkpoint, audio, evaluator, remote source deployment, freeze or Slurm call.
Does not request/read/store a password. Records raw output under a fresh local
private evidence directory. --self-test exercises bootstrap locally, not HAKUSAN.
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
    "trace_observer": "dcbe162257fc130450a2f2b4a2fd5680caded503d10c67b704c6a0331ec86328",
    "test_trace_observer": "25c427438faedd30fde6770ff1f7f26598f809d6a949d3f6050200b0f0450b16",
    "run_checks": "c182ba44dd44032099da559c7035090135884f93a98889392c4701043dab92cd",
}


def bootstrap(sources, local):
    payload = {"sources": sources, "pins": PINS,
               "python": sys.version.split()[0] if local else "3.11.5",
               "torch": "2.12.1" if local else "2.1.1+cu118",
               "kind": "LOCAL_BOOTSTRAP_SELF_TEST" if local else "HAKUSAN_SYNTHETIC_CPU_PROBE"}
    return ("PAYLOAD = " + repr(payload) + "\n" + '''
import hashlib, json, linecache, os, sys, types
if sys.version.split()[0] != PAYLOAD["python"]:
    raise RuntimeError("Python version differs from this probe target")
if PAYLOAD["kind"] == "HAKUSAN_SYNTHETIC_CPU_PROBE":
    import pwd
    if pwd.getpwuid(os.getuid()).pw_name != "s2510040":
        raise RuntimeError("Unexpected remote account")
for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[key] = "1"
os.environ["CUDA_VISIBLE_DEVICES"] = ""
import torch
if torch.__version__ != PAYLOAD["torch"]:
    raise RuntimeError("Torch version differs from this probe target")
torch.set_num_threads(1)
print("PROBE_SCOPE=" + PAYLOAD["kind"], flush=True)
for name in ("trace_observer", "test_trace_observer", "run_checks"):
    source = PAYLOAD["sources"][name]
    if hashlib.sha256(source.encode("utf-8")).hexdigest() != PAYLOAD["pins"][name]:
        raise RuntimeError("In-memory source SHA differs")
    filename = "/__audattn_synthetic_source__/" + name + ".py"
    linecache.cache[filename] = (len(source), None, source.splitlines(True), filename)
    module = types.ModuleType(name)
    module.__file__ = filename
    sys.modules[name] = module
    exec(compile(source, filename, "exec"), module.__dict__)
rc = sys.modules["run_checks"].main()
if torch.cuda.is_initialized():
    raise RuntimeError("CPU-only scope violated")
print(json.dumps({"probe_kind": PAYLOAD["kind"], "rc": rc,
                  "remote_source_files_written": False, "jobs_submitted": 0,
                  "production_model_loaded": False, "source_sha256": PAYLOAD["pins"]}), flush=True)
raise SystemExit(rc)
''').encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    root = here.parents[3]
    sources = {}
    for name, expected in PINS.items():
        path = here / (name + ".py")
        if not stat.S_ISREG(path.lstat().st_mode):
            raise RuntimeError(f"Not a regular source file: {name}")
        data = path.read_bytes()
        if len(data) > 128 * 1024 or hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError(f"Local source differs: {name}")
        sources[name] = data.decode("utf-8")
    payload = bootstrap(sources, args.self_test)
    if args.self_test:
        command = [sys.executable, "-I", "-B", "-"]
    else:
        socket = root / ".hakusan-control" / "master.sock"
        if not socket.exists() or not stat.S_ISSOCK(socket.lstat().st_mode):
            raise RuntimeError("No authenticated SSH socket; run the connection helper in your terminal")
        if socket.lstat().st_uid != os.getuid():
            raise RuntimeError("SSH socket is not owned by this account")
        remote = ("env CUDA_VISIBLE_DEVICES= OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 "
                  "OPENBLAS_NUM_THREADS=1 /home/s2510040/miniconda3/envs/attn/bin/python -I -B -")
        command = ["/usr/bin/ssh", "-S", str(socket), "-o", "BatchMode=yes",
                   "-o", "ConnectTimeout=12", "-o", "ConnectionAttempts=1",
                   "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2",
                   "s2510040@hakusan1", remote]
    evidence = root / "docs" / "superpowers" / "evidence"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    label = "trace-local-bootstrap-" if args.self_test else "trace-remote-cpu-"
    run = Path(tempfile.mkdtemp(prefix=label + stamp + "-", dir=evidence))
    raw = run / "output.log"
    print(f"PROBE_LOG_DIRECTORY={run}", flush=True)
    code, error = 2, None
    with raw.open("xb") as stream:
        try:
            completed = subprocess.run(command, input=payload, stdout=stream,
                                       stderr=subprocess.STDOUT, timeout=90, check=False)
            code = completed.returncode
        except subprocess.TimeoutExpired:
            code, error = 124, "90-second probe timeout; no automatic retry"
        except OSError as failure:
            code, error = 2, str(failure)
    output = raw.read_bytes()
    print(output.decode("utf-8", errors="replace"), end="", flush=True)
    receipt = {"status": "PROBE_PROCESS_RETURNED", "returncode": code,
               "remote_probe": not args.self_test, "source_sha256": PINS,
               "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "bootstrap_sha256": hashlib.sha256(payload).hexdigest(),
               "output_sha256": hashlib.sha256(output).hexdigest(), "error": error,
               "jobs_submitted": 0, "production_model_loaded": False}
    with (run / "receipt.json").open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(f"PROBE_RC={code}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

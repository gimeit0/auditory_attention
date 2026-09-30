"""Bounded local tests / one authenticated HAKUSAN synthetic CPU probe.

--remote-probe creates a private temporary source tree, makes ONE original-
guarded synthetic compiled forward, then cleans the temporary tree. No checkpoint,
production tree, GPU, Slurm submission, credential storage or automatic retry.
"""
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
import sys
import tempfile
import time
import zlib

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[3]
MANIFEST = HERE / "SOURCE_MANIFEST.json"
TEST_COUNT = 16


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def package_sources():
    manifest = json.loads(MANIFEST.read_bytes())
    records = manifest["files"]
    if manifest["schema_version"] != 1 or not 10 <= len(records) <= 24:
        raise RuntimeError("package manifest shape differs")
    total, sources = 0, {}
    for relative, digest in records.items():
        p = Path(relative)
        if p.is_absolute() or ".." in p.parts or p.suffix != ".py":
            raise RuntimeError("invalid package member")
        path = WORKSPACE / relative
        if not stat.S_ISREG(path.lstat().st_mode):
            raise RuntimeError("package source is not regular")
        raw = path.read_bytes()
        total += len(raw)
        if len(raw) > 2 * 1024**2 or total > 8 * 1024**2 or sha(raw) != digest:
            raise RuntimeError("package source digest/budget differs: " + relative)
        sources[relative] = raw.decode("utf8")
    return records, sources


def child(remote):
    import unittest
    sys.path.insert(0, str(HERE))
    import test_compiled_registration as tests
    import torch
    torch.set_num_threads(1)
    if torch.cuda.is_initialized():
        raise RuntimeError("CUDA unexpectedly initialized")
    if remote:
        value = tests.cold_probe()
    else:
        if str(torch.__version__) != "2.12.1":
            raise RuntimeError("local tests expect actual torch 2.12.1")
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(tests.CompiledTests))
        passed = result.wasSuccessful() and result.testsRun == TEST_COUNT and not result.skipped
        value = {"status": "LOCAL_COMPILED_ADAPTER_TESTS_PASS" if passed else "LOCAL_COMPILED_ADAPTER_TESTS_FAILED",
                 "tests": result.testsRun, "skips": len(result.skipped),
                 "dispatch_records": tests.CompiledTests.dispatch_records,
                 "original_compiled_guard_validated": False}
        if not passed:
            print("CHILD_RECORD=" + json.dumps(value), flush=True)
            return 2
    value.update({"pid": os.getpid(), "python": sys.version.split()[0], "torch": torch.__version__,
                  "cuda_initialized": torch.cuda.is_initialized(), "production_model_loaded": False,
                  "ready_for_gpu": False, "jobs_submitted": 0})
    print("CHILD_RECORD=" + json.dumps(value, sort_keys=True), flush=True)
    return 0


def make_bootstrap(records, sources, remote):
    blob = base64.b64encode(zlib.compress(json.dumps(sources).encode())).decode()
    spec = {"blob": blob, "pins": records, "remote": remote,
            "entry": str(HERE.relative_to(WORKSPACE) / "probe_driver.py")}
    return ("SPEC=" + repr(spec) + "\n" + BOOTSTRAP).encode()


BOOTSTRAP = """
import base64, hashlib, json, os, pathlib, pwd, signal, subprocess, sys, tempfile, zlib
os.umask(0o077)
if SPEC["remote"] and (sys.version.split()[0] != "3.11.5" or pwd.getpwuid(os.getuid()).pw_name != "s2510040"):
    raise RuntimeError("unexpected remote account/Python")
def expire(*_):
    raise TimeoutError("80-second bootstrap deadline")
signal.signal(signal.SIGALRM, expire)
signal.alarm(80)
sources = json.loads(zlib.decompress(base64.b64decode(SPEC["blob"])))
if set(sources) != set(SPEC["pins"]):
    raise RuntimeError("source inventory differs")
rc, record = 2, None
with tempfile.TemporaryDirectory(prefix="audattn-compiled-cpu-", dir="/tmp") as temporary:
    root = pathlib.Path(temporary)
    for relative, digest in SPEC["pins"].items():
        path = pathlib.Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError("invalid temporary member")
        raw = sources[relative].encode()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise RuntimeError("payload SHA differs")
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with target.open("xb") as stream:
            stream.write(raw)
    env = dict(os.environ)
    env.update({"CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0", "PYTHONNOUSERSITE": "1", "TMPDIR": str(root)})
    mode = "--child-remote" if SPEC["remote"] else "--child-local"
    command = [sys.executable, "-I", "-B", str(root / SPEC["entry"]), mode]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               env=env, start_new_session=True)
    try:
        try:
            output, _ = process.communicate(timeout=60)
            rc = process.returncode
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate()
            rc = 124
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    print(output.decode(errors="replace"), end="", flush=True)
    lines = [json.loads(line[len("CHILD_RECORD="):]) for line in output.decode(errors="replace").splitlines()
             if line.startswith("CHILD_RECORD=")]
    record = lines[0] if len(lines) == 1 else None
    for relative, digest in SPEC["pins"].items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != digest:
            raise RuntimeError("source changed during probe")
    if rc == 0 and (record is None or record.get("pid") != process.pid):
        rc = 2
removed = not root.exists()
signal.alarm(0)
print("BOOTSTRAP_RECORD=" + json.dumps({"returncode": rc, "child": record,
      "temporary_directory_removed": removed, "source_sha256": SPEC["pins"],
      "remote_probe": SPEC["remote"], "jobs_submitted": 0}), flush=True)
raise SystemExit(rc if removed else 2)
"""


def accepted(record, remote):
    if not isinstance(record, dict) or record.get("returncode") != 0 or record.get("temporary_directory_removed") is not True:
        return False
    child = record.get("child", {})
    if not all(child.get(k) is False for k in ("cuda_initialized", "production_model_loaded", "ready_for_gpu")):
        return False
    if child.get("jobs_submitted") != 0 or record.get("remote_probe") is not remote:
        return False
    if remote:
        return (child.get("status") == "HERMETIC_COMPILED_FIRST_BATCH_PASS" and child.get("torch") == "2.1.1+cu118"
                and child.get("python") == "3.11.5" and child.get("batches") == child.get("load_calls") == child.get("forward_calls") == 1
                and child.get("stage_invocations") == child.get("capture_records") == 4
                and child.get("complete_passes") == 0 and child.get("backend") == "eager"
                and child.get("original_guards_enabled") is True and child.get("original_compiler_authority") is True
                and child.get("compiler_backend_entered") is True and child.get("hooks_removed") is True
                and child.get("cold_pair_interference_verified") is False)
    return (child.get("status") == "LOCAL_COMPILED_ADAPTER_TESTS_PASS" and child.get("tests") == TEST_COUNT
            and child.get("skips") == 0 and child.get("torch") == "2.12.1"
            and child.get("original_compiled_guard_validated") is False
            and child.get("dispatch_records") == [{"backend": "eager", "batches": 1, "stage_invocations": 4,
                                                  "capture_records": 4, "original_guards_validated": False}])


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    for flag in ("check-only", "self-test-package", "remote-probe", "child-local", "child-remote"):
        group.add_argument("--" + flag, action="store_true")
    args = parser.parse_args()
    if args.child_local or args.child_remote:
        return child(args.child_remote)
    records, sources = package_sources()
    if args.check_only:
        print("COMPILED_CPU_PACKAGE_SHA=PASS; no connection or execution")
        return 0
    payload = make_bootstrap(records, sources, args.remote_probe)
    if args.remote_probe:
        socket = WORKSPACE / ".hakusan-control/master.sock"
        info = socket.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError("authenticated owned SSH socket required")
        remote_command = "env CUDA_VISIBLE_DEVICES= /home/s2510040/miniconda3/envs/attn/bin/python -I -B -"
        command = ["/usr/bin/ssh", "-S", str(socket), "-o", "BatchMode=yes", "-o", "ControlMaster=no",
                   "-o", "ConnectTimeout=12", "-o", "ConnectionAttempts=1", "-o", "StrictHostKeyChecking=yes",
                   "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2", "s2510040@hakusan1", remote_command]
    else:
        command = [sys.executable, "-I", "-B", "-"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = "compiled-remote-cpu-" if args.remote_probe else "compiled-package-local-"
    folder = Path(tempfile.mkdtemp(prefix=prefix + stamp + "-", dir=WORKSPACE / "docs/superpowers/evidence"))
    print("COMPILED_CPU_EVIDENCE=" + str(folder), flush=True)
    started = time.monotonic()
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
    lines = [json.loads(line[len("BOOTSTRAP_RECORD="):]) for line in raw.decode(errors="replace").splitlines()
             if line.startswith("BOOTSTRAP_RECORD=")]
    result = lines[0] if len(lines) == 1 else None
    passed = (rc == 0 and accepted(result, args.remote_probe) and result["source_sha256"] == records
              and package_sources()[0] == records)
    receipt = {"status": ("REMOTE_COMPILED_FIRST_BATCH_VERIFIED" if args.remote_probe else "LOCAL_COMPILED_PACKAGE_VERIFIED")
               if passed else "COMPILED_CPU_NOT_VERIFIED", "returncode": rc, "bootstrap_record": result,
               "driver_sha256": sha(Path(__file__).read_bytes()), "manifest_sha256": sha(MANIFEST.read_bytes()),
               "output_sha256": sha(raw), "output_size": len(raw), "payload_sha256": sha(payload),
               "elapsed_seconds": round(time.monotonic() - started, 3), "local_deadline_seconds": 90,
               "remote_child_deadline_seconds": 60, "remote_bootstrap_deadline_seconds": 80,
               "automatic_retry": False, "production_model_loaded": False, "ready_for_gpu": False, "jobs_submitted": 0}
    write_json(folder / "receipt.json", receipt)
    print(raw.decode(errors="replace"), end="", flush=True)
    print("COMPILED_CPU_VERIFIED=" + str(int(passed)), flush=True)
    print("No production forward or GPU submission; return the output for review.", flush=True)
    return 0 if passed else (rc or 2)


if __name__ == "__main__":
    raise SystemExit(main())


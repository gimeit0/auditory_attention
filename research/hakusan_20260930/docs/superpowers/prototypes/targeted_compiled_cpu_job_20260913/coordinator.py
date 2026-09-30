"""One authorized 1-CPU/4-GiB/30-minute Slurm experiment, no GPU.

Copies hash-pinned source into node-local scratch; preserves full child outputs
on shared storage. No retry, production checkpoint, inference change, or HOME
override. Child stack dumps give progress without instrumenting original code.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

REMOTE_ROOT = Path("/home/s2510040/audattn_external_eval_diag/compiled_lifetime_cpu_2026-09-13_v1")
ENTRY = "docs/superpowers/prototypes/targeted_compiled_cpu_job_20260913/child_entry.py"
VERIFY = "docs/superpowers/prototypes/targeted_compiled_lifetime_20260913/verify_pair.py"
MAX_OUTPUT = 4 * 1024**2
LIMITS = {"jobs": 1, "cpus": 1, "memory_mib": 4096, "wall_seconds": 1800, "gpus": 0}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_record(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def checked_read(path, expected, limit=2 * 1024**2):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_size <= limit,
            "source is not owned regular/bounded: " + str(path))
    raw = path.read_bytes()
    require(sha(raw) == expected, "source SHA differs: " + str(path))
    return raw


def validate_environment(env):
    require(re.fullmatch(r"[1-9][0-9]*", env.get("SLURM_JOB_ID", "")), "Slurm job required")
    require(env.get("SLURM_CPUS_PER_TASK") == "1" and env.get("SLURM_NTASKS") == "1"
            and env.get("SLURM_NNODES") == "1", "allocation CPU/task/node differs")
    require(env.get("CUDA_VISIBLE_DEVICES") == "", "CUDA must be hidden")
    require(not env.get("SLURM_JOB_GPUS") and not env.get("SLURM_STEP_GPUS"), "GPU allocation not authorized")
    require(env.get("SLURM_JOB_PARTITION") == "TINY", "unexpected partition")
    require(env.get("SLURM_MEM_PER_NODE") == "4096", "memory allocation differs")


def kill_group(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def run(root, release_sha, nonce):
    validate_environment(os.environ)
    require(root == REMOTE_ROOT and sys.version.split()[0] == "3.11.5", "remote root/Python differs")
    require(root.is_dir() and not root.is_symlink() and root.stat().st_uid == os.getuid(), "unsafe run root")
    release = json.loads(checked_read(root / "RELEASE.json", release_sha))
    require(release["limits"] == LIMITS, "authorized limits differ")
    intent = json.loads((root / "SUBMIT_INTENT.json").read_bytes())
    require(intent["nonce"] == nonce and intent["release_sha256"] == release_sha
            and intent["limits"] == LIMITS, "submission intent differs")
    job = os.environ["SLURM_JOB_ID"]
    running = {"job_id": job, "pid": os.getpid(), "hostname": socket.gethostname(),
               "release_sha256": release_sha, "limits": LIMITS, "status": "RUNNING", "nonce": nonce}
    write_record(root / "RUNNING.json", running)
    print("CPU_JOB_STARTED=" + json.dumps(running, sort_keys=True), flush=True)
    started = time.monotonic()
    rc, error, children, summary = 2, None, [], None
    removed = False
    try:
        with tempfile.TemporaryDirectory(prefix="audattn-cpu-" + job + "-", dir="/tmp") as temporary:
            scratch = Path(temporary)
            package = scratch / "package"
            for name, digest in release["files"].items():
                relative = Path(name)
                require(not relative.is_absolute() and ".." not in relative.parts, "invalid source path")
                raw = checked_read(root / "package" / relative, digest)
                target = package / relative
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with target.open("xb") as stream:
                    stream.write(raw)
            env = dict(os.environ)
            env.update({"CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                        "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
                        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONHASHSEED": "0",
                        "TMPDIR": str(scratch), "TMP": str(scratch), "TEMP": str(scratch),
                        "TORCH_HOME": str(scratch / "torch"), "MPLCONFIGDIR": str(scratch / "mpl"),
                        "TORCHINDUCTOR_CACHE_DIR": str(scratch / "inductor"), "XDG_CACHE_HOME": str(scratch / "cache"),
                        "TRITON_CACHE_DIR": str(scratch / "triton"), "NUMBA_CACHE_DIR": str(scratch / "numba"),
                        "CUDA_CACHE_PATH": str(scratch / "cuda")})
            values = []
            for mode in ("reference", "observed"):
                remaining = 1710 - (time.monotonic() - started)
                require(remaining > 5, "total execution budget exhausted")
                output_path = root / (mode + ".log")
                child_start = time.monotonic()
                with output_path.open("xb") as output:
                    process = subprocess.Popen([sys.executable, "-I", "-B", str(package / ENTRY), mode],
                                               stdout=output, stderr=subprocess.STDOUT, env=env, start_new_session=True)
                    print("CPU_CHILD_LAUNCHED=" + json.dumps({"mode": mode, "pid": process.pid}), flush=True)
                    try:
                        deadline = child_start + min(900, remaining)
                        while True:
                            budget = deadline - time.monotonic()
                            if budget <= 0:
                                kill_group(process)
                                rc = 124
                                break
                            try:
                                rc = process.wait(timeout=min(30, budget))
                                break
                            except subprocess.TimeoutExpired:
                                require(output_path.stat().st_size <= MAX_OUTPUT, "child output exceeds budget")
                                print("CPU_HEARTBEAT=" + json.dumps({"mode": mode, "pid": process.pid,
                                      "elapsed_seconds": round(time.monotonic() - child_start, 1),
                                      "output_bytes": output_path.stat().st_size}), flush=True)
                    finally:
                        kill_group(process)
                raw = output_path.read_bytes()
                require(len(raw) <= MAX_OUTPUT, "child output budget exceeded")
                child = {"mode": mode, "pid": process.pid, "returncode": rc, "output": output_path.name,
                         "elapsed_seconds": round(time.monotonic() - child_start, 3),
                         "output_sha256": sha(raw), "output_size": len(raw)}
                children.append(child)
                print("CPU_CHILD_FINISHED=" + json.dumps(child), flush=True)
                require(rc == 0, "child failed or timed out: " + mode + "; rc=" + str(rc))
                parsed = [json.loads(line.removeprefix("LIFETIME_CHILD=")) for line in raw.decode().splitlines()
                          if line.startswith("LIFETIME_CHILD=")]
                require(len(parsed) == 1 and parsed[0]["pid"] == process.pid and parsed[0]["mode"] == mode,
                        "child result identity/count differs")
                values.append(parsed[0])
            spec = importlib.util.spec_from_file_location("cpu_pair_verifier", package / VERIFY)
            verifier = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(verifier)
            summary = verifier.verify_pair(*values)
            for name, digest in release["files"].items():
                checked_read(package / name, digest)
                checked_read(root / "package" / name, digest)
            rc = 0
        removed = not scratch.exists()
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        rc = rc if rc not in (0, None) else 2
        removed = "scratch" in locals() and not scratch.exists()
    terminal = {**running, "status": "CPU_PAIR_VERIFIED" if summary and removed and rc == 0 else "CPU_PAIR_NOT_VERIFIED",
                "returncode": rc, "error": error, "children": children, "summary": summary,
                "elapsed_seconds": round(time.monotonic() - started, 3), "temporary_directory_removed": removed,
                "production_model_loaded": False, "ready_for_gpu": False, "slurm_jobs_submitted_by_coordinator": 0}
    write_record(root / "TERMINAL.json", terminal)
    print("CPU_JOB_TERMINAL=" + json.dumps(terminal, sort_keys=True), flush=True)
    return 0 if terminal["status"] == "CPU_PAIR_VERIFIED" else (rc or 2)


if __name__ == "__main__":
    os.umask(0o077)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(RuntimeError("Slurm termination signal")))
    raise SystemExit(run(REMOTE_ROOT, sys.argv[1], sys.argv[2]))

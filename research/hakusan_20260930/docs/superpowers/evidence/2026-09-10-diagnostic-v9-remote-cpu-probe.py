"""Temporary same-version/formal40 seal probe; no deployment, forward or sbatch.

Run on the Mac using the user-authenticated shared SSH socket. Only the two
SHA-pinned candidate sources and private dependency caches are materialized in
a freshly allocated remote temporary directory. Original scientific inputs are
read-only. This is deliberately NOT production worker attestation or GPU PASS.
"""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import shlex
import subprocess


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v9"
MANIFEST = (
    ROOT
    / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v9-candidate-manifest.sha256"
)
MANIFEST_SHA = "a625c64179823d8e1b45b820d99ccf81f2fa463981cb4ed60e9cb65f49a446f7"
SOURCES = {
    "diagnose_batch_invariance.py": "da76e3f062a83685c41b6f1f60f905af248af880194f2d5884239e8b3643c9b2",
    "numeric_trace.py": "fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b",
}

REMOTE = r"""
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import traceback

EXPECTED = {
    "diagnose_batch_invariance.py": "da76e3f062a83685c41b6f1f60f905af248af880194f2d5884239e8b3643c9b2",
    "numeric_trace.py": "fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b",
}
V4 = Path("/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4")
LOCK_SHA = "63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710"

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def event(stage, **fields):
    print(json.dumps({"stage": stage, **fields}, sort_keys=True), flush=True)

def expired(signum, frame):
    raise TimeoutError("240-second CPU probe budget exhausted")

def main():
    stage = "preflight"
    lock = None
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(240)
    try:
        require(pwd.getpwuid(os.getuid()).pw_name == "s2510040", "wrong account")
        require(socket.gethostname().split(".")[0] == "hakusan1", "wrong host")
        require(sys.version_info[:2] == (3, 11), "wrong Python")
        require(sys.flags.isolated and sys.dont_write_bytecode, "isolation required")
        for name in ("audattn_samebank_v4", "audattn_v4_numdiag"):
            queue = subprocess.run(
                ["/usr/bin/squeue", "-h", "-u", "s2510040", "-n", name],
                check=True, capture_output=True, text=True,
            )
            require(not queue.stdout.strip(), "related job exists")
        for directory in (V4, V4 / "state"):
            require(directory.is_dir() and not directory.is_symlink(), "invalid v4 directory")
        lock = os.open(V4 / "state/evaluation.lock", os.O_RDONLY | os.O_NOFOLLOW)
        require(stat.S_ISREG(os.fstat(lock).st_mode), "invalid evaluation lock")
        require(os.fstat(lock).st_uid == os.getuid(), "evaluation lock owner differs")
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        require(hashlib.sha256(os.read(lock, 8192)).hexdigest() == LOCK_SHA, "evaluation lock differs")
        data = sys.stdin.buffer.read(2_000_001)
        require(len(data) <= 2_000_000, "source payload too large")
        package = json.loads(data)
        require(type(package) is dict and set(package) == set(EXPECTED), "source inventory differs")
        sources = {}
        for name, digest in EXPECTED.items():
            source = base64.b64decode(package[name], validate=True)
            require(hashlib.sha256(source).hexdigest() == digest, "candidate SHA differs")
            sources[name] = source
        event(stage, status="PASS", scope="FROZEN_FORMAL40_CPU_SEAL_NO_FORWARD_NO_DEPLOYMENT")
        with tempfile.TemporaryDirectory(prefix="audattn-v9-cpu-probe-", dir="/tmp") as temporary:
            scratch = Path(temporary)
            for name, source in sources.items():
                descriptor = os.open(scratch / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as output:
                    output.write(source)
            # Configure private caches before importing the candidate's environment seal.
            # HOME, original model settings, frozen files and state markers are untouched.
            for key in ("MPLCONFIGDIR", "XDG_CACHE_HOME", "TORCHINDUCTOR_CACHE_DIR", "TRITON_CACHE_DIR", "CUDA_CACHE_PATH"):
                cache = scratch / key.lower()
                cache.mkdir(mode=0o700)
                os.environ[key] = str(cache)
            import torch
            require(str(torch.__version__) == "2.1.1+cu118", "wrong torch version")
            require(not torch.cuda.is_available(), "CPU-only login-node probe required")
            torch.set_num_threads(1)
            event("runtime", torch=str(torch.__version__), cpu_threads=1, forward_executed=False)
            stage = "load_unmodified_v9_candidate"
            spec = importlib.util.spec_from_file_location("v9_cpu_seal_probe", scratch / "diagnose_batch_invariance.py")
            diag = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = diag
            spec.loader.exec_module(diag)
            stage = "read_verified_frozen_context"
            context = diag.read_frozen_context()
            capability = context["_frozen_context_capability"]
            records = {item["relative_path"]: item for item in capability.source_records}
            event(stage, status="PASS", pinned_files=len(capability.pinned_records), snapshot_files=len(records))
            with diag.frozen_scene_context(context["snapshot_files"], records):
                evaluator = context["evaluator"]
                device = evaluator._configure_runtime(True)
                require(device.type == "cpu", "CPU device required")
                diag._read_frozen_numeric_runtime(torch)
                stage = "strict_load_frozen_formal40"
                model, report = evaluator.strict_load_model(context["manifest"], "formal40", device=device)
                diag._require_load_report(report)
                inventory = diag._direct_model_module_inventory(model)
                require(not any(diag._direct_module_training_state(item[1]) for item in inventory), "non-eval module")
                diag._require_frozen_direct_parameters(inventory)
                event(stage, status="PASS", state_keys=len(model.state_dict()), loaded_trainable_numel_ratio=report["loaded_trainable_numel_ratio"], module_count=len(inventory))
                stage = "materialize_model_callable_graphs"
                values = diag._model_callable_values(model)
                graphs = diag._callable_graphs(values, materialize_module_attributes=True)
                event(stage, status="PASS", callable_count=len(values))
                stage = "model_execution_fingerprint"
                fingerprint = diag._model_execution_fingerprint(model)
                event(stage, status="PASS", module_records=len(fingerprint))
                stage = "repeat_seal"
                require(fingerprint == diag._model_execution_fingerprint(model), "unchanged model fingerprint differs")
                require(graphs == diag._callable_graphs(values, materialize_module_attributes=False), "unchanged callable graph differs")
                event(stage, status="PASS")
            stage = "post_source_check"
            after = diag.collect_snapshot_records(context["source_manifest"], (), snapshot_files=context["snapshot_files"])
            require([(r["relative_path"], r["size"], r["sha256"]) for r in after] == [(r["relative_path"], r["size"], r["sha256"]) for r in capability.source_records], "snapshot inputs changed")
            diag._verify_v4_pinned_records(diag._get_trace(), context["manifest"], context["contract"])
            event(stage, status="PASS")
        event("complete", status="FORMAL40_CPU_SEAL_PROBE_PASS", production_worker_verified=False, gpu_numerics_verified=False, job_submitted=False)
        return 0
    except Exception as error:
        event(stage, status="PROBE_FAILED", error_type=type(error).__name__, message=str(error)[:1600])
        traceback.print_exc(limit=8)
        return 2
    finally:
        signal.alarm(0)
        if lock is not None:
            os.close(lock)

raise SystemExit(main())
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", action="store_true", help="execute the temporary remote CPU probe"
    )
    args = parser.parse_args()
    payload = MANIFEST.read_bytes()
    if hashlib.sha256(payload).hexdigest() != MANIFEST_SHA:
        raise SystemExit("STOP: candidate manifest differs")
    for line in payload.decode().splitlines():
        digest, name = line.split(maxsplit=1)
        path = PACKAGE / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SystemExit("STOP: candidate file differs: " + name)
    compile(REMOTE, "remote_cpu_probe", "exec")
    print("LOCAL_PROBE_PREFLIGHT=PASS", flush=True)
    if not args.run:
        print("Validation only; pass --run for temporary remote CPU execution.")
        return 0
    package = {}
    for name, digest in SOURCES.items():
        source = (PACKAGE / name).read_bytes()
        if hashlib.sha256(source).hexdigest() != digest:
            raise SystemExit("STOP: source changed before transfer")
        package[name] = base64.b64encode(source).decode("ascii")
    control = ROOT / ".hakusan-control/master.sock"
    subprocess.run(
        ["/usr/bin/ssh", "-S", str(control), "-O", "check", "s2510040@hakusan1"],
        check=True,
    )
    remote = shlex.join(
        [
            "/home/s2510040/miniconda3/envs/attn/bin/python",
            "-u",
            "-I",
            "-B",
            "-c",
            REMOTE,
        ]
    )
    completed = subprocess.run(
        [
            "/usr/bin/ssh",
            "-S",
            str(control),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=12",
            "s2510040@hakusan1",
            remote,
        ],
        input=json.dumps(package).encode(),
    )
    print("REMOTE_CPU_PROBE_RC=" + str(completed.returncode), flush=True)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

"""Candidate allocation-only coordinator. No SSH, sbatch, retry or new freeze.

Durable outputs stay under the NEW approved remote root; node-local package
copies and caches are temporary. Original v18/inputs/evidence remain read-only.
"""
import contextlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import job_contract as contract  # noqa: E402
import process_runner as process  # noqa: E402

ENTRY = "docs/superpowers/prototypes/targeted_gpu_job_20260914_v3/gpu_child.py"
MANIFEST = "docs/superpowers/prototypes/targeted_gpu_job_20260914_v3/SOURCE_MANIFEST.json"
WRITE_PATHS = {"XDG_CACHE_HOME": "xdg", "TORCH_HOME": "torch-home", "TMPDIR": "tmp", "TMP": "tmp", "TEMP": "tmp",
               "MPLCONFIGDIR": "mpl", "NUMBA_CACHE_DIR": "numba", "TORCHINDUCTOR_CACHE_DIR": "torchinductor",
               "TRITON_CACHE_DIR": "triton", "CUDA_CACHE_PATH": "cuda"}


def child_environment(parent, scratch, role):
    contract.require(role in ("reference", "observed"), "invalid child role")
    keys = ("HOME", "PATH", "SLURM_JOB_ID", "SLURM_JOB_NODELIST", "SLURM_NNODES", "SLURM_NTASKS",
            "SLURM_CPUS_PER_TASK", "SLURM_MEM_PER_NODE", "SLURM_JOB_PARTITION", "SLURM_JOB_GPUS",
            "SLURM_STEP_GPUS", "CUDA_VISIBLE_DEVICES")
    env = {key: parent[key] for key in keys if key in parent}
    contract.require(env.get("HOME") == parent.get("HOME") and type(env.get("HOME")) is str, "preserved real HOME required")
    child = Path(scratch) / ("reference_cold" if role == "reference" else "B2")
    env.update({name: str(child / relative) for name, relative in WRITE_PATHS.items()})
    env.update(DIAG_SCRATCH_ROOT=str(scratch), PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0")
    return env


@contextlib.contextmanager
def verifier_environment(base):
    """Only cache variables change; never repurpose the real account HOME."""
    previous = {key: os.environ.get(key) for key in WRITE_PATHS}
    for relative in set(WRITE_PATHS.values()):
        (base / relative).mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        os.environ.update({key: str(base / relative) for key, relative in WRITE_PATHS.items()})
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run(package_sha, nonce, spool):
    contract.allocation(os.environ)
    contract.require(sys.version.split()[0] == "3.11.5" and Path(sys.executable).resolve() == contract.PYTHON.resolve()
                     and sys.flags.isolated and sys.dont_write_bytecode, "isolated production Python required")
    authorization = contract.check_authorization(contract.REMOTE, package_sha, nonce)
    package = contract.check_sources(package_sha)
    job = os.environ["SLURM_JOB_ID"]
    contract.require(spool == f"/var/spool/slurm/slurmd/job{job}/slurm_script", "fixed Slurm spool runner required")
    runner_name = "docs/superpowers/prototypes/targeted_gpu_job_20260914_v3/run_gpu.sbatch"
    contract.pinned_read(Path(spool), package["files"][runner_name])
    process.write_once(contract.REMOTE / "COORDINATOR_STARTED.json", {"job_id": job, "pid": os.getpid(), **authorization})
    terminal = {"status": "GPU_PAIR_NOT_VERIFIED", "job_id": job, "package_sha256": package_sha,
                "pair_nonce": nonce, "ready_for_gpu": False, "jobs_submitted": 0, "error": None}
    try:
        (contract.REMOTE / "artifacts").mkdir(mode=0o700, exist_ok=False)
        with tempfile.TemporaryDirectory(prefix="gpu-pair-" + job + "-", dir="/tmp") as temporary, \
                verifier_environment(Path(temporary) / "verifier"):
            base = Path(temporary)
            bundle = base / "package"
            for relative, digest in package["files"].items():
                raw = contract.pinned_read(contract.WORKSPACE / relative, digest)
                target = bundle / relative
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with target.open("xb") as output:
                    output.write(raw)
            with (bundle / MANIFEST).open("xb") as output:
                output.write(contract.pinned_read(HERE / "SOURCE_MANIFEST.json", package_sha))
            scratch = base / ("audattn_v4_numdiag_" + job)
            scratch.mkdir(mode=0o700)
            commands = {role: [sys.executable, "-I", "-B", str(bundle / ENTRY), role, package_sha, nonce]
                        for role in ("reference", "observed")}
            environments = {role: child_environment(os.environ, scratch, role) for role in commands}
            # Imports here are verifier-side only; no prepared model in parent.
            import verify_results
            sys.path.insert(0, str(HERE.parent / "targeted_worker_20260912"))
            import baseline_bridge as bridge
            diag = bridge.load_v18(contract.V18 / "tools/diagnose_batch_invariance.py")
            parent_raw = contract.pinned_read(contract.WORKSPACE / contract.PARENT, bridge.PARENT_SHA)
            parent = bridge.replay._decode_contract(parent_raw, bridge.PARENT_SHA)

            def verify_child(role, record):
                return verify_results.verify_child(contract.REMOTE / "artifacts" / role, record,
                    role=role, job=job, package_sha=package_sha, nonce=nonce, diag=diag, parent=parent)

            def verify_pair(reference, observed):
                summary = verify_results.archive.verify_pinned_parent_pair(reference["arrays"], observed["arrays"], parent_raw)
                for name in ("python", "torch", "cuda_runtime", "cudnn", "gpu_name", "hostname", "cuda_visible_devices", "slurm_job_id"):
                    contract.require(reference["software"][name] == observed["software"][name], "pair hardware/environment differs: " + name)
                contract.check_sources(package_sha)
                for relative, digest in package["files"].items():
                    contract.pinned_read(bundle / relative, digest)
                return {"verified": True, "scope": "B2_GPU_CANDIDATE_ENDPOINT_PAIR_NOT_FINAL_MODEL_COMPARISON",
                        "array_gate": summary, "original_pass_commitments_verified": True,
                        "captures": observed["capture"], "child_inventories": {
                            "reference": reference["inventory"], "observed": observed["inventory"]},
                        "intermediate_equivalence_to_uninstrumented_compilation_proven": False,
                        "production_preparation_validated": False, "ready_for_gpu": False}

            paired = process.run_pair(contract.REMOTE / "processes", commands, environments,
                                      child_seconds=contract.LIMITS["child_seconds"], total_seconds=contract.LIMITS["pair_seconds"],
                                      verify_child=verify_child, verify_pair=verify_pair)
            terminal["pair"] = paired
            if paired["status"] == "PAIR_VERIFIED":
                terminal["status"] = "GPU_PAIR_CANDIDATE_ARTIFACTS_VERIFIED_REMOTE"
        terminal["temporary_package_and_caches_removed"] = not base.exists()
    except BaseException as exc:
        terminal.update(status="GPU_PAIR_NOT_VERIFIED", error={"type": type(exc).__name__, "message": str(exc)})
    try:
        contract.check_sources(package_sha)
    except BaseException as exc:
        terminal.update(status="GPU_PAIR_NOT_VERIFIED", source_postcheck_error={"type": type(exc).__name__, "message": str(exc)})
    process.write_once(contract.REMOTE / "COORDINATOR_TERMINAL.json", terminal)
    print(json.dumps(terminal, sort_keys=True), flush=True)
    return 0 if terminal["status"] == "GPU_PAIR_CANDIDATE_ARTIFACTS_VERIFIED_REMOTE" else 2


if __name__ == "__main__":
    os.umask(0o077)
    contract.require(len(sys.argv) == 4, "expected package SHA, pair nonce and Slurm spool script")
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(RuntimeError("Slurm termination")))
    raise SystemExit(run(*sys.argv[1:]))

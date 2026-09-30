"""Compute-node entry only: real formal40 CPU registration, never inference.

No SSH or sbatch interface. Must be packaged and run by a separately authorized
bounded CPU Slurm runner; copying this command onto the login node is rejected.
"""
import json
import os
from pathlib import Path
import re
import socket
import sys
import tempfile


def check_allocation(env, account, hostname):
    if not (account == "s2510040" and hostname.split(".")[0] != "hakusan1"
            and re.fullmatch(r"[1-9][0-9]*", env.get("SLURM_JOB_ID", ""))
            and env.get("SLURM_CPUS_PER_TASK") == "1" and env.get("SLURM_NTASKS") == "1"
            and env.get("SLURM_NNODES") == "1" and env.get("SLURM_MEM_PER_NODE") == "4096"
            and env.get("SLURM_JOB_PARTITION") == "TINY"
            and env.get("CUDA_VISIBLE_DEVICES") == ""
            and not env.get("SLURM_JOB_GPUS") and not env.get("SLURM_STEP_GPUS")):
        raise RuntimeError("authorized 1-CPU/4-GiB/TINY compute allocation required; no GPU/login-node run")


def main():
    raise RuntimeError("v19 integration is local-only; new freeze and runner review required")
    import fcntl
    import hashlib
    import pwd
    import stat

    check_allocation(os.environ, pwd.getpwuid(os.getuid()).pw_name, socket.gethostname())
    if sys.version.split()[0] != "3.11.5" or not sys.flags.isolated or not sys.dont_write_bytecode:
        raise RuntimeError("reviewed isolated Python required")
    if len(sys.argv) != 1:
        raise RuntimeError("fixed B2 CPU registration; no additional arguments")
    temporary_parent = Path(os.environ["TMPDIR"])
    info = temporary_parent.lstat()
    if not (stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700
            and temporary_parent.resolve().is_relative_to(Path("/tmp").resolve())):
        raise RuntimeError("private node-local scratch required")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import admission
    import torch
    torch.set_num_threads(1)
    print("REAL_REGISTRATION_BEGIN=" + json.dumps({"job_id": os.environ["SLURM_JOB_ID"],
          "pid": os.getpid(), "cell": "B2", "scope": "CPU strict load and callback admission only"}), flush=True)
    lock_path = admission.prior.V4 / "state/evaluation.lock"
    lock = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        admission.require(hashlib.sha256(os.read(lock, 8192)).hexdigest() == admission.prior.LOCK_SHA,
                          "frozen lock differs")
        diag = admission.bridge.load_v19(admission.prior.V18 / "tools/diagnose_batch_invariance.py")
        context = diag.read_frozen_context()
        with tempfile.TemporaryDirectory(prefix="real-compiled-registration-", dir=temporary_parent) as scratch:
            summary = admission.run_real_cpu(diag, context, "B2", Path(scratch))
        admission.require(not Path(scratch).exists(), "private scratch cleanup failed")
        admission.prior.pinned(lock_path, admission.prior.LOCK_SHA)
        summary.update({"worker_pid": os.getpid(), "job_id": os.environ["SLURM_JOB_ID"],
                        "temporary_directory_removed": True, "python": sys.version.split()[0],
                        "torch": str(torch.__version__)})
        print("REAL_REGISTRATION_RESULT=" + json.dumps(summary, sort_keys=True), flush=True)
    finally:
        os.close(lock)


if __name__ == "__main__":
    main()

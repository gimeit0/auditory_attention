"""Proposed allocation and immutable package checks; no authorization granted."""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[3]
REMOTE = Path("/home/s2510040/audattn_external_eval_diag/gpu_pair_2026-09-15_v5")
V19 = Path("/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v19")
V4 = Path("/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4")
PYTHON = Path("/home/s2510040/miniconda3/envs/attn/bin/python")
PARENT_FREEZE_SHA = "bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178"
V19_SHA = "c1ba3af9da8fb2be6e197fddbee38a03c0ef3a8f67da75e7abc0b1a9f568b50d"
PROTOCOL = "formal40_batch_invariance_diag_20260903_v19"
LOCK_SHA = "63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710"
PARENT = "docs/superpowers/evidence/parent-replay-local-20260911T155226Z-rcw6ytm5/PARENT_REPLAY_CONTRACT.json"
PLAN = "docs/superpowers/prototypes/targeted_trace_20260911/FORMAL40_PLAN_CANDIDATE.json"
LIMITS = {"jobs": 1, "gpus": 1, "cpus": 8, "memory_mib": 65536, "wall_seconds": 7200,
          "child_seconds": 3000, "pair_seconds": 6600, "partition": "GPU-1A"}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def pinned_read(path, expected=None, limit=8 * 1024**2):
    path = Path(path)
    require(path.is_absolute() and ".." not in path.parts, "absolute source path required")
    for component in (*reversed(path.parents), path):
        require(not component.is_symlink(), "symlink source path")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_size <= limit,
                "owned bounded source required")
        parts, count = [], 0
        while True:
            part = os.read(fd, min(1024**2, limit + 1 - count))
            if not part:
                break
            parts.append(part)
            count += len(part)
            require(count <= limit, "source byte budget exceeded")
        raw = b"".join(parts)
        def fields(s):
            return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode)
        require(fields(before) == fields(os.fstat(fd)) == fields(path.lstat()), "source changed while reading")
        require(expected is None or hashlib.sha256(raw).hexdigest() == expected, "source SHA differs: " + str(path))
        return raw
    finally:
        os.close(fd)


def check_sources(expected_sha):
    value = json.loads(pinned_read(HERE / "SOURCE_MANIFEST.json", expected_sha))
    for relative, sha in value["files"].items():
        path = Path(relative)
        require(not path.is_absolute() and ".." not in path.parts, "invalid package relative path")
        pinned_read(WORKSPACE / path, sha)
    return value


def check_authorization(root, expected_sha, nonce, input_sha):
    require(root == REMOTE and re.fullmatch(r"[0-9a-f]{64}", expected_sha)
            and re.fullmatch(r"[0-9a-f]{32}", nonce), "fixed deployment/identity required")
    require(type(input_sha) is str and re.fullmatch(r"[0-9a-f]{64}", input_sha)
            and input_sha != PARENT_FREEZE_SHA, "new candidate freeze SHA required")
    value = json.loads(pinned_read(root / "AUTHORIZATION.json"))
    expected = {"approved": True, "package_sha256": expected_sha, "pair_nonce": nonce,
                "input_freeze_sha256": input_sha, "parent_freeze_sha256": PARENT_FREEZE_SHA,
                "diagnostic_sha256": V19_SHA, "diagnostic_protocol": PROTOCOL,
                "limits": LIMITS, "scope": "B2_formal40_v19_cold_reference_observed_pair"}
    require(json.dumps(value, sort_keys=True) == json.dumps(expected, sort_keys=True),
            "separate reviewed resource authorization missing/different")
    intent = json.loads(pinned_read(root / "SUBMIT_INTENT.json"))
    require(json.dumps(intent, sort_keys=True) == json.dumps(expected, sort_keys=True), "single-submission intent differs from authorization")
    return value


def allocation(env, *, host=None):
    require(re.fullmatch(r"[1-9][0-9]{0,19}", env.get("SLURM_JOB_ID", "")), "Slurm allocation required")
    require((host or socket.gethostname()).split(".")[0].startswith("spcc-a100g"), "reviewed A100 compute node required")
    expected = {"SLURM_CPUS_PER_TASK": "8", "SLURM_NTASKS": "1", "SLURM_NNODES": "1",
                "SLURM_MEM_PER_NODE": "65536", "SLURM_JOB_PARTITION": "GPU-1A"}
    require(all(env.get(k) == v for k, v in expected.items()), "allocation CPU/memory/partition differs")
    # These are GPU INDICES, not counts. The string "0" means GPU zero.
    require(re.fullmatch(r"[0-9]+", env.get("SLURM_JOB_GPUS", ""))
            and re.fullmatch(r"[0-9]+", env.get("CUDA_VISIBLE_DEVICES", "")), "exactly one visible allocated GPU index required")


def child_cold_gate(env):
    import runtime_environment
    runtime_environment.check(env)
    allocation(env)
    require(sys.version.split()[0] == "3.11.5" and sys.flags.isolated and sys.dont_write_bytecode
            and Path(sys.executable).resolve() == PYTHON.resolve(), "actual isolated production Python required")
    require(not any(n.partition(".")[0] in {"torch", "numpy", "pandas", "torchaudio"} for n in sys.modules),
            "new candidate child must precede all numeric imports")

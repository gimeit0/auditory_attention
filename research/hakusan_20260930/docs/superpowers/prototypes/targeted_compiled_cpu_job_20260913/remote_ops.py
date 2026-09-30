"""Single-root deployment/submission/read-only query operations, stdlib only."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid

ROOT = Path("/home/s2510040/audattn_external_eval_diag/compiled_lifetime_cpu_2026-09-13_v1")
RUNNER = "docs/superpowers/prototypes/targeted_compiled_cpu_job_20260913/run_cpu.sbatch"
LIMITS = {"jobs": 1, "cpus": 1, "memory_mib": 4096, "wall_seconds": 1800, "gpus": 0}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_new(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def save(name, value):
    write_new(ROOT / name, (json.dumps(value, sort_keys=True, indent=2) + "\n").encode())


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def regular(path, limit=8 * 1024**2):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_size <= limit,
            "file ownership/type/budget differs")
    return path.read_bytes()


def sources(release):
    require(release["limits"] == LIMITS and 20 <= len(release["files"]) <= 28, "release scope/count differs")
    total = 0
    for name, digest in release["files"].items():
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts, "invalid release path")
        raw = regular(ROOT / "package" / relative, 2 * 1024**2)
        total += len(raw)
        require(sha(raw) == digest and total <= 8 * 1024**2, "source SHA/budget differs")


def clean_queue():
    result = command(["squeue", "-h", "-u", "s2510040", "-n", "audattn_cmp_cpu", "-o", "%i|%T|%j"])
    require(result["returncode"] == 0 and not result["stdout"].strip(), "existing related job or queue query failed")


def submission_command(root, release_sha, nonce, dry_run=False):
    args = ["sbatch", "--parsable", "--export=NONE", "--comment=compiled-cpu-" + nonce]
    if dry_run:
        args.append("--test-only")
    return args + [str(root / "package" / RUNNER), release_sha, nonce]


def approved_job(text):
    fields = dict(re.findall(r"(?:^|\s)([A-Za-z/]+)=([^\s]+)", text))
    return (fields.get("Partition") == "TINY" and fields.get("NumCPUs") == "1"
            and fields.get("NumNodes") == "1" and fields.get("NumTasks") == "1"
            and fields.get("CPUs/Task") == "1" and fields.get("TimeLimit") == "00:30:00"
            and fields.get("MinMemoryNode") in ("4G", "4096M")
            and not any("gres/" in part for part in fields.get("ReqTRES", "").split(",")))


def main(spec):
    os.umask(0o077)
    require(os.getuid() == ROOT.parent.stat().st_uid and sys.version.split()[0] == "3.11.5",
            "unexpected remote account/Python")
    require(ROOT.parent.is_dir() and not ROOT.parent.is_symlink(), "unsafe base")
    action = spec["action"]
    if action == "deploy":
        require(not ROOT.exists() and not ROOT.is_symlink(), "CPU job root already exists; do not recreate")
        clean_queue()
        release_raw = base64.b64decode(spec["release_base64"], validate=True)
        require(sha(release_raw) == spec["release_sha256"], "release wire SHA differs")
        release = json.loads(release_raw)
        require(release["limits"] == LIMITS and set(spec["files"]) == set(release["files"]), "payload scope differs")
        # Verify every payload before creating anything remotely.
        decoded, total = {}, 0
        for name, digest in release["files"].items():
            p = Path(name)
            require(not p.is_absolute() and ".." not in p.parts and p.suffix in (".py", ".sbatch"), "unsafe member")
            raw = base64.b64decode(spec["files"][name], validate=True)
            total += len(raw)
            require(len(raw) <= 2 * 1024**2 and total <= 8 * 1024**2 and sha(raw) == digest, "payload source differs")
            decoded[name] = raw
        ROOT.mkdir(mode=0o700)
        for name, raw in decoded.items():
            target = ROOT / "package" / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            write_new(target, raw)
        write_new(ROOT / "RELEASE.json", release_raw)
        sources(release)
        return {"status": "CPU_PACKAGE_DEPLOYED", "release_sha256": sha(release_raw), "files": len(decoded), "jobs_submitted": 0}
    require(ROOT.is_dir() and not ROOT.is_symlink(), "CPU root missing/invalid")
    release_raw = regular(ROOT / "RELEASE.json")
    require(sha(release_raw) == spec["release_sha256"], "remote release differs")
    release = json.loads(release_raw)
    if action in ("test-only", "submit"):
        sources(release)
        require(not (ROOT / "SUBMIT_INTENT.json").exists(), "submission intent already exists; never resubmit")
        clean_queue()
        if action == "test-only":
            result = command(submission_command(ROOT, spec["release_sha256"], "0" * 32, True))
            save("TEST_ONLY.json", {**result, "release_sha256": spec["release_sha256"], "jobs_submitted": 0})
            require(result["returncode"] == 0, "scheduler test-only rejected: " + result["stderr"])
            return {"status": "SCHEDULER_TEST_ONLY_PASS", **result, "jobs_submitted": 0}
        test = json.loads(regular(ROOT / "TEST_ONLY.json"))
        require(test["returncode"] == 0 and test["release_sha256"] == spec["release_sha256"], "no matching scheduler preflight")
        nonce = uuid.uuid4().hex
        save("SUBMIT_INTENT.json", {"nonce": nonce, "release_sha256": spec["release_sha256"], "limits": LIMITS})
        # Exactly one sbatch invocation; failures remain recorded, never retried.
        result = command(submission_command(ROOT, spec["release_sha256"], nonce))
        save("SBATCH_RESPONSE.json", result)
        require(result["returncode"] == 0, "sbatch rejected; no automatic retry: " + result["stderr"])
        match = re.fullmatch(r"([1-9][0-9]*)(?:;[A-Za-z0-9_.-]+)?\n?", result["stdout"])
        require(match is not None, "ambiguous sbatch response; inspect journal, do not resubmit")
        job = match.group(1)
        receipt = {"status": "SUBMITTED", "job_id": job, "nonce": nonce,
                   "release_sha256": spec["release_sha256"], "limits": LIMITS, "jobs_submitted": 1}
        save("SUBMISSION_RECEIPT.json", receipt)
        live = command(["scontrol", "show", "job", "-o", job])
        save("SCHEDULER_ALLOCATION.json", live)
        if live["returncode"] == 0 and not approved_job(live["stdout"]):
            cancelled = command(["scancel", job])
            save("LIMIT_MISMATCH_CANCELLATION.json", cancelled)
            raise RuntimeError("scheduler request exceeds/differs from approved limits; cancellation requested for " + job)
        return {**receipt, "scheduler_allocation": live}
    receipt = json.loads(regular(ROOT / "SUBMISSION_RECEIPT.json")) if (ROOT / "SUBMISSION_RECEIPT.json").exists() else None
    if action == "status":
        result = {"status": "NO_RECEIPT" if receipt is None else "QUERY", "submission": receipt,
                  "intent_exists": (ROOT / "SUBMIT_INTENT.json").exists(), "jobs_submitted_by_query": 0}
        if receipt:
            job = receipt["job_id"]
            result["squeue"] = command(["squeue", "-h", "-j", job, "-o", "%i|%T|%M|%R"])
            result["sacct"] = command(["sacct", "-j", job, "-X", "-P", "--format=JobIDRaw,State,ExitCode,Elapsed,AllocCPUS,ReqMem,NodeList"])
            log = ROOT / ("slurm-" + job + ".log")
            if log.exists():
                result["log_tail"] = regular(log)[-6000:].decode(errors="replace")
        if (ROOT / "TERMINAL.json").exists():
            result["terminal"] = json.loads(regular(ROOT / "TERMINAL.json"))
        for mode in ("reference", "observed"):
            path = ROOT / (mode + ".log")
            if path.exists():
                raw = regular(path)
                result[mode + "_tail"] = "\n".join(line[:500] for line in raw.decode(errors="replace").splitlines()[-18:])
        return result
    require(action == "fetch", "unknown operation")
    require(receipt is not None, "no receipt to fetch")
    files = {}
    names = ["RELEASE.json", "TEST_ONLY.json", "SUBMIT_INTENT.json", "SBATCH_RESPONSE.json",
             "SUBMISSION_RECEIPT.json", "SCHEDULER_ALLOCATION.json", "RUNNING.json", "TERMINAL.json",
             "reference.log", "observed.log", "slurm-" + receipt["job_id"] + ".log"]
    for name in names:
        path = ROOT / name
        if path.exists():
            raw = regular(path)
            files[name] = {"sha256": sha(raw), "size": len(raw), "base64": base64.b64encode(raw).decode()}
    return {"status": "READ_ONLY_EVIDENCE", "job_id": receipt["job_id"], "files": files, "jobs_submitted": 0}


if __name__ == "__main__":
    print("CPU_OPERATION=" + json.dumps(main(SPEC), sort_keys=True), flush=True)  # noqa: F821

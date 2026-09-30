"""Fixed-root GPU deployment/control, stdlib only. No inference or auto retry."""
import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import subprocess
import sys
import time

REMOTE = Path("/home/s2510040/audattn_external_eval_diag/gpu_pair_2026-09-14_v4")
PREFIX = "docs/superpowers/prototypes/targeted_gpu_job_20260914_v4/"
OPS = "docs/superpowers/prototypes/targeted_gpu_control_20260914_v4/remote_ops.py"
MANIFEST = PREFIX + "SOURCE_MANIFEST.json"
RUNNER = PREFIX + "run_gpu.sbatch"
PACKAGE_SHA = "91b263ac3a22171e97314e6574a4422515b80a2b74f8e1e96e87b0fa6debb7e8"
LIMITS = {"jobs": 1, "gpus": 1, "cpus": 8, "memory_mib": 65536, "wall_seconds": 7200,
          "child_seconds": 3000, "pair_seconds": 6600, "partition": "GPU-1A"}
CONFIRM = "SUBMIT_ONE_B2_GPU_V4_A100_8CPU_64G_2H"
SCOPE = "B2_formal40_cold_reference_observed_pair"
PINNED = {
    "audattn_external_eval/same_bank_2026-08-29_v4/input_freeze.json": "1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5",
    "audattn_external_eval/same_bank_2026-08-29_v4/state/evaluation.lock": "63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710",
    "audattn_external_eval/same_bank_2026-08-29_v4/tools/locked_same_bank_eval.py": "31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4",
    "audattn_external_eval/same_bank_2026-08-29_v4/tools/run_locked_same_bank_eval.sbatch": "b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495",
    "audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v18/input_freeze.json": "bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178",
    "audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v18/tools/diagnose_batch_invariance.py": "7ba4d1f143fd1b957639588b209600377d745bf34e1207768cdd577e3f1d5a7b",
}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def path_check(path):
    path = Path(path)
    require(path.is_absolute() and ".." not in path.parts, "absolute canonical path required")
    for part in (*reversed(path.parents), path):
        require(not part.is_symlink(), "symlink path rejected")
    return path


def directory(path):
    info = path_check(path).lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700, "private directory required")


def read(path, limit=8 * 1024**2):
    path = path_check(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_size <= limit,
                "owned bounded regular file required")
        chunks, count = [], 0
        while True:
            raw = os.read(fd, min(1024**2, limit + 1 - count))
            if not raw:
                break
            count += len(raw)
            require(count <= limit, "read budget exceeded")
            chunks.append(raw)
        def identity(s):
            return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode)
        require(count == before.st_size and identity(before) == identity(os.fstat(fd)) == identity(path.lstat()),
                "file changed during read")
        return b"".join(chunks)
    finally:
        os.close(fd)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_new(path, raw):
    directory(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    sync_dir(path.parent)


def member(name):
    p = Path(name)
    require(type(name) is str and not p.is_absolute() and str(p) == name and ".." not in p.parts
            and len(p.parts) >= 2 and p.suffix in (".py", ".json", ".md", ".sbatch")
            and p.parts[0] in ("docs", "same_bank_eval_2026_09_03_v4_numeric_diag_v18"), "invalid package member")
    return p


def validate_release(raw, digest):
    require(sha(raw) == digest, "control release SHA differs")
    value = json.loads(raw)
    require(set(value) == {"schema_version", "root", "limits", "package_sha256", "files", "scope"}
            and value["schema_version"] == 1 and value["root"] == str(REMOTE) and value["limits"] == LIMITS
            and value["package_sha256"] == PACKAGE_SHA and value["scope"] == SCOPE
            and 48 <= len(value["files"]) <= 64, "release scope differs")
    for name, digest in value["files"].items():
        member(name)
        require(re.fullmatch(r"[0-9a-f]{64}", digest), "invalid source digest")
    require(value["files"].get(MANIFEST) == PACKAGE_SHA and OPS in value["files"], "job/control pins missing")
    return value


def command(args):
    # Prevent submit-option environment variables from overriding the script.
    env = {k: os.environ[k] for k in ("HOME", "PATH", "USER", "LOGNAME", "LANG") if k in os.environ}
    try:
        p = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, timeout=30, env=env)
        out, err = p.stdout, p.stderr
        return {"returncode": p.returncode, "stdout": out[:1024**2].decode(errors="replace"),
                "stderr": err[:1024**2].decode(errors="replace"),
                "truncated": len(out) > 1024**2 or len(err) > 1024**2, "timed_out": False}
    except subprocess.TimeoutExpired as exc:
        return {"returncode": None, "stdout": (exc.stdout or b"")[:1024**2].decode(errors="replace"),
                "stderr": (exc.stderr or b"")[:1024**2].decode(errors="replace"), "truncated": False, "timed_out": True}


def success(result):
    return result["returncode"] == 0 and not result.get("timed_out") and not result.get("truncated")


def submission_command(root, nonce, *, dry_run=False):
    args = ["/usr/bin/sbatch", "--parsable", "--export=NONE", "--comment=audattn-b2-" + nonce]
    args.append("--test-only" if dry_run else "--hold")
    return args + [str(root / "package" / RUNNER), PACKAGE_SHA, nonce]


def job_id(result):
    require(success(result), "scheduler rejected/timed out; do not retry")
    found = re.fullmatch(r"([1-9][0-9]*)(?:;[A-Za-z0-9_.-]+)?\n?", result["stdout"])
    require(found is not None, "ambiguous scheduler response; do not retry")
    return found.group(1)


def resource_fields(text):
    pairs = [part.split("=", 1) for part in text.split(",")]
    require(all(len(p) == 2 and all(p) for p in pairs), "malformed resource list")
    value = dict(pairs)
    require(len(value) == len(pairs), "duplicate resource keys")
    if value.get("mem") == "65536M":
        value["mem"] = "64G"
    return value


def held_request_matches(text, job, nonce, root):
    # A single-node --gres request must explicitly name A100 in ReqTRES and
    # TresPerNode. TresPerJob may be absent; if supplied, only the same typed
    # GPU is accepted. Aggregate gres/gpu=1 never substitutes for typed A100.
    # Empty NodeList is a real Slurm field, not a value to be skipped.
    pairs = re.findall(r"(?:^|\s)([A-Za-z0-9_/]+)=([^\s]*)", text)
    fields = dict(pairs)
    require(len(fields) == len(pairs), "duplicate scheduler fields")
    expected = {"JobId": job, "JobName": "audattn_b2_coldpair", "Partition": "GPU-1A", "JobState": "PENDING",
                "Reason": "JobHeldUser", "Priority": "0", "NumCPUs": "8", "NumTasks": "1", "CPUs/Task": "8",
                "TimeLimit": "02:00:00", "RunTime": "00:00:00", "Requeue": "0", "Restarts": "0",
                "AllocTRES": "(null)", "NodeList": "", "Comment": "audattn-b2-" + nonce,
                "WorkDir": str(root), "Command": str(root / "package" / RUNNER),
                "StdIn": "/dev/null", "StdOut": str(root / "logs" / ("coldpair_" + job + ".log")),
                "StdErr": str(root / "logs" / ("coldpair_" + job + ".log")),
                "TresPerTask": "cpu=8",
                "TresPerNode": "gres/gpu:nvidia_a100:1"}
    require(all(fields.get(k) == v for k, v in expected.items()), "held scheduler request differs")
    require(fields.get("TresPerJob") in (None, "gres/gpu:nvidia_a100:1"),
            "optional per-job GPU must be the same single typed A100")
    require(fields.get("NumNodes") in ("1", "1-1") and fields.get("MinMemoryNode") in ("64G", "65536M")
            and re.fullmatch(r"s2510040\([0-9]+\)", fields.get("UserId", "")), "held owner/node/memory differs")
    require(all(k not in fields for k in ("HetJobId", "ArrayJobId", "TresPerSocket", "MemPerTres", "CpusPerTres")),
            "unexpected additional job resource constraints")
    resource = resource_fields(fields.get("ReqTRES", ""))
    expected_tres = {"cpu": "8", "mem": "64G", "node": "1", "billing": "8", "gres/gpu:nvidia_a100": "1"}
    if "gres/gpu" in resource:
        expected_tres["gres/gpu"] = "1"
    require(resource == expected_tres, "requested resources must be exactly one typed A100, 8 CPU and 64 GiB")
    return resource


def held_accounting_matches(text, job, requested):
    lines = [line for line in text.splitlines() if line.strip()]
    require(len(lines) == 1, "one accounting job record required; keep held")
    fields = lines[0].split("|")
    require(len(fields) == 5 and fields[0] == job and fields[1] == "PENDING"
            and fields[3] == "" and fields[4] == "00:00:00", "accounting identity/state/allocation differs; keep held")
    require(resource_fields(fields[2]) == requested, "accounting request disagrees with scontrol; keep held")


class Operations:
    """Injectable root/commands are test seams; main always uses fixed literals."""
    def __init__(self, root=REMOTE, invoke=command, now=time.time):
        self.root, self.invoke, self.now = root, invoke, now

    def save(self, name, value):
        raw = wire(value)
        write_new(self.root / name, raw)
        return sha(raw)

    def clean_queue(self):
        result = self.invoke(["/usr/bin/squeue", "-h", "-u", "s2510040", "-n",
                              "audattn_b2_coldpair,audattn_reg_cpu,audattn_cmp_cpu,audattn_v4_numdiag,audattn_samebank_v4",
                              "-o", "%i|%T|%j"])
        require(success(result) and not result["stdout"].strip(), "related job exists or queue query failed")

    def protected_inputs(self):
        for relative, digest in PINNED.items():
            require(sha(read(Path("/home/s2510040") / relative)) == digest, "protected input changed: " + relative)

    def preflight(self):
        base = path_check(self.root.parent)
        require(base.is_dir() and base.stat().st_uid == os.getuid(), "owned diagnostic base required")
        self.protected_inputs()
        self.clean_queue()
        partition = self.invoke(["/usr/bin/scontrol", "show", "partition", "GPU-1A", "-o"])
        require(success(partition) and "PartitionName=GPU-1A" in partition["stdout"]
                and re.search(r"(?:^|\s)State=UP(?:\s|$)", partition["stdout"]), "GPU-1A unavailable")
        disk = os.statvfs(base)
        free = disk.f_bavail * disk.f_frsize
        require(free >= 8 * 1024**3, "diagnostic filesystem has less than 8 GiB available")
        return {"status": "REMOTE_PREFLIGHT_PASS", "protected_pins": len(PINNED), "partition": partition,
                "root_exists": self.root.exists() or self.root.is_symlink(), "filesystem_free_bytes": free,
                "account_quota_checked": False, "compute_scratch_checked": False, "jobs_submitted": 0}

    def sources(self, release):
        directory(self.root)
        directory(self.root / "package")
        total = 0
        for name, digest in release["files"].items():
            raw = read(self.root / "package" / member(name))
            total += len(raw)
            require(sha(raw) == digest and total <= 16 * 1024**2, "deployed source SHA/budget differs")
        job = json.loads(read(self.root / "package" / MANIFEST))
        require(len(job["files"]) == 52 and all(release["files"].get(n) == s for n, s in job["files"].items()),
                "pinned job package coverage differs")

    def deploy(self, spec):
        require(not self.root.exists() and not self.root.is_symlink(), "root already exists; inspect, never overwrite/retry")
        raw = base64.b64decode(spec["release_base64"], validate=True)
        release = validate_release(raw, spec["release_sha256"])
        require(set(spec["files"]) == set(release["files"]), "upload member set differs")
        decoded, total = {}, 0
        for name, digest in release["files"].items():
            data = base64.b64decode(spec["files"][name], validate=True)
            total += len(data)
            require(len(data) <= 8 * 1024**2 and total <= 16 * 1024**2 and sha(data) == digest, "upload bytes differ")
            decoded[name] = data
        self.preflight()  # all checks precede the first remote write
        self.root.mkdir(mode=0o700)
        sync_dir(self.root.parent)
        for name in ("logs", "test_only", ".upload-staging"):
            (self.root / name).mkdir(mode=0o700)
        stage = self.root / ".upload-staging/package"
        stage.mkdir(mode=0o700)
        for name, data in decoded.items():
            target = stage / member(name)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            write_new(target, data)
            require(sha(read(target)) == release["files"][name], "staging readback differs")
        for path, _, _ in os.walk(stage, topdown=False):
            sync_dir(Path(path))
        require(not (self.root / "package").exists(), "publication destination exists")
        os.rename(stage, self.root / "package")
        sync_dir(self.root)
        write_new(self.root / "CONTROL_RELEASE.json", raw)
        self.sources(release)
        result = {"status": "GPU_PACKAGE_DEPLOYED", "release_sha256": spec["release_sha256"],
                  "package_sha256": PACKAGE_SHA, "files": len(decoded), "bytes": total, "jobs_submitted": 0}
        self.save("DEPLOYMENT.json", result)
        return result

    def test_only(self, spec, release):
        self.sources(release)
        require(not (self.root / "AUTHORIZATION.json").exists() and not (self.root / "SUBMIT_INTENT.json").exists(),
                "already authorized/submission attempted; query only")
        self.preflight()
        result = self.invoke(submission_command(self.root, "0" * 32, dry_run=True))
        record = {"test_id": spec["request_id"], "created_at": self.now(), "release_sha256": spec["release_sha256"],
                  "package_sha256": PACKAGE_SHA, "runner_sha256": release["files"][RUNNER], "scheduler": result,
                  "jobs_submitted": 0}
        digest = self.save("test_only/" + spec["request_id"] + ".json", record)
        require(success(result), "scheduler test-only failed; no job submitted")
        return {"status": "SCHEDULER_TEST_ONLY_PASS", "test_id": spec["request_id"], "test_sha256": digest,
                "scheduler": result, "jobs_submitted": 0}

    def submit(self, spec, release):
        require(spec.get("confirm") == CONFIRM, "new explicit one-job resource authorization required")
        auth = spec.get("authorization")
        require(type(auth) is dict and re.fullmatch(r"[0-9a-f]{32}", auth.get("pair_nonce", "")), "authorization nonce missing")
        require(auth == {"approved": True, "package_sha256": PACKAGE_SHA, "pair_nonce": auth["pair_nonce"],
                         "limits": LIMITS, "scope": SCOPE}, "resource authorization differs")
        require(re.fullmatch(r"[0-9a-f]{32}", spec.get("test_id", ""))
                and re.fullmatch(r"[0-9a-f]{64}", spec.get("test_sha256", "")), "reviewed test-only receipt required")
        raw = read(self.root / "test_only" / (spec["test_id"] + ".json"))
        test = json.loads(raw)
        require(sha(raw) == spec["test_sha256"] and test["release_sha256"] == spec["release_sha256"]
                and test["package_sha256"] == PACKAGE_SHA and test["runner_sha256"] == release["files"][RUNNER]
                and test["test_id"] == spec["test_id"] and 0 <= self.now() - test["created_at"] <= 86400
                and success(test["scheduler"]), "test-only receipt stale/changed/rejected")
        require(not (self.root / "SUBMIT_INTENT.json").exists(), "submission attempted; never resubmit")
        self.sources(release)
        self.preflight()
        # Exclusive authorization + fsynced intent stop concurrent attempts.
        self.save("AUTHORIZATION.json", auth)
        self.save("SUBMIT_INTENT.json", auth)  # exact original candidate schema
        job = None
        try:
            response = self.invoke(submission_command(self.root, auth["pair_nonce"]))
            self.save("SBATCH_RESPONSE.json", response)
            job = job_id(response)
            self.save("SUBMISSION_RECEIPT.json", {"status": "SUBMITTED_HELD", "job_id": job,
                "release_sha256": spec["release_sha256"], "authorization": auth, "jobs_submitted": 1})
            live = self.invoke(["/usr/bin/scontrol", "show", "job", "-o", job])
            self.save("HELD_ALLOCATION.json", live)
            require(success(live), "held job query failed; do not release or resubmit")
            requested = held_request_matches(live["stdout"], job, auth["pair_nonce"], self.root)
            accounting = self.invoke(["/usr/bin/sacct", "-j", job, "-X", "-n", "-P",
                                      "--format=JobIDRaw,State,ReqTRES%256,AllocTRES%256,Elapsed"])
            self.save("HELD_ACCOUNTING.json", accounting)
            require(success(accounting), "held accounting query failed; do not release or resubmit")
            held_accounting_matches(accounting["stdout"], job, requested)
            self.sources(release)
            self.protected_inputs()
            self.save("RELEASE_INTENT.json", {"job_id": job, "authorization_sha256": sha(wire(auth)), "once": True})
            released = self.invoke(["/usr/bin/scontrol", "release", job])
            self.save("RELEASE_RESPONSE.json", released)
            require(success(released), "release response uncertain; inspect same job, never resubmit")
            result = {"status": "SUBMITTED_AND_RELEASED", "job_id": job, "authorization": auth,
                      "package_sha256": PACKAGE_SHA, "jobs_submitted": 1, "automatic_retry": False}
            self.save("RELEASED.json", result)
            return result
        except BaseException as exc:
            self.save("SUBMIT_ERROR.json", {"job_id": job, "type": type(exc).__name__, "message": str(exc),
                                            "retry_allowed": False, "note": "query journals; job may exist or be released"})
            raise

    def status(self):
        result = {"status": "READ_ONLY_QUERY", "jobs_submitted": 0, "journals": {}}
        if self.root.exists() or self.root.is_symlink():
            directory(self.root)
            names = sorted(p.name for p in self.root.iterdir())
            require(len(names) <= 64, "unexpected top-level inventory")
            result["top_level"] = names
        else:
            result["root_exists"] = False
        for name in ("DEPLOYMENT.json", "AUTHORIZATION.json", "SUBMIT_INTENT.json", "SBATCH_RESPONSE.json",
                     "SUBMISSION_RECEIPT.json", "HELD_ALLOCATION.json", "HELD_ACCOUNTING.json",
                     "RELEASE_INTENT.json", "RELEASE_RESPONSE.json", "RELEASED.json", "SUBMIT_ERROR.json"):
            path = self.root / name
            if path.exists() or path.is_symlink():
                result["journals"][name] = json.loads(read(path))
        receipt = result["journals"].get("SUBMISSION_RECEIPT.json")
        if receipt:
            job = receipt["job_id"]
            require(re.fullmatch(r"[1-9][0-9]*", job), "invalid saved job identity")
            result["squeue"] = self.invoke(["/usr/bin/squeue", "-h", "-j", job, "-o", "%i|%T|%M|%R"])
            result["sacct"] = self.invoke(["/usr/bin/sacct", "-j", job, "-X", "-P", "--format=JobIDRaw,State,ExitCode,Elapsed,NodeList"])
        elif "SUBMIT_INTENT.json" in result["journals"]:
            result["reconciliation_required"] = True
            result["squeue_by_name"] = self.invoke(["/usr/bin/squeue", "-h", "-u", "s2510040", "-n", "audattn_b2_coldpair",
                                                      "-o", "%i|%T|%j|%k"])
        terminal = self.root / "COORDINATOR_TERMINAL.json"
        if terminal.exists():
            value = json.loads(read(terminal))
            result["coordinator_summary"] = {k: value.get(k) for k in ("status", "job_id", "error", "package_sha256")}
            result["results_verified_locally"] = False
        return result


def main(spec, source_sha):
    os.umask(0o077)
    require(sys.platform == "linux" and sys.version.split()[0] == "3.11.5" and pwd.getpwuid(os.getuid()).pw_name == "s2510040"
            and socket.gethostname().split(".")[0] == "hakusan1", "fixed login account/Python required")
    require(re.fullmatch(r"[0-9a-f]{32}", spec["request_id"]) and re.fullmatch(r"[0-9a-f]{64}", spec["release_sha256"]),
            "invalid request identity")
    ops = Operations()
    action = spec["action"]
    require(action in ("preflight", "deploy", "test-only", "submit", "status"), "unsupported action")
    if action in ("preflight", "deploy", "status"):
        release_raw = base64.b64decode(spec["release_base64"], validate=True)
    else:
        release_raw = read(REMOTE / "CONTROL_RELEASE.json")
    release = validate_release(release_raw, spec["release_sha256"])
    require(release["files"][OPS] == source_sha, "remote controller source differs")
    if action == "status" and (REMOTE / "CONTROL_RELEASE.json").exists():
        require(sha(read(REMOTE / "CONTROL_RELEASE.json")) == spec["release_sha256"], "remote control release differs")
    if action == "preflight":
        return ops.preflight()
    if action == "deploy":
        return ops.deploy(spec)
    if action == "test-only":
        return ops.test_only(spec, release)
    if action == "submit":
        return ops.submit(spec, release)
    return ops.status()


if __name__ == "__main__":
    try:
        value = {"ok": True, "result": main(SPEC, SOURCE_SHA)}  # noqa: F821
    except BaseException as error:
        value = {"ok": False, "error": {"type": type(error).__name__, "message": str(error)}, "automatic_retry": False}
    print("GPU_CONTROL=" + json.dumps({"request_id": SPEC["request_id"], "action": SPEC["action"],  # noqa: F821
           "release_sha256": SPEC["release_sha256"], **value}, sort_keys=True), flush=True)  # noqa: F821
    raise SystemExit(0 if value["ok"] else 2)

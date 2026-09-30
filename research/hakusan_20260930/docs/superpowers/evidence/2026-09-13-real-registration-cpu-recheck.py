"""Offline read-only evidence recheck for the single authorized Job703751.

Arguments are the fetch and terminal-status directories. No torch/SSH/submission.
Failure evidence is verified as failure; it cannot yield registration PASS.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import stat

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs/superpowers/evidence/real-registration-cpu-job-20260913-v1"
TOOLS = "docs/superpowers/prototypes/targeted_real_registration_cpu_job_20260913/"
RELEASE_SHA = "38b9130fdbd5c135c179cd91edf2635876e0de8b33208692306a50a641bb0a17"
OUTPUT_PINS = {"fetch": "bdacb53d89e63161d3358c86534e3986335110a2a4c0d09ddc8a91e82cd7068c",
               "status": "2fff442fdae05df1db0204f9a650809052fe2823fe80c5a96bb927aa876dcad7"}
NONCE = "61b4cc32809f411ea095d4d7452f2e00"
JOB = "703751"
LIMITS = {"jobs": 1, "cpus": 1, "memory_mib": 4096, "wall_seconds": 1800, "gpus": 0}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= 8 * 1024**2,
            "nonregular or oversized evidence: " + str(path))
    return path.read_bytes()


def one(raw, prefix):
    records = [json.loads(s[len(prefix):]) for s in raw.decode().splitlines() if s.startswith(prefix)]
    require(len(records) == 1, "missing or duplicate " + prefix)
    return records[0]


def operation(folder, action):
    require(folder.resolve().parent == EVIDENCE.resolve() and folder.name.startswith(action + "-"),
            "unexpected evidence directory")
    receipt = json.loads(read(folder / "receipt.json"))
    raw = read(folder / "output.log")
    require(receipt["action"] == action and receipt["returncode"] == 0
            and receipt["automatic_retry"] is False and receipt["release_sha256"] == RELEASE_SHA,
            "operation receipt differs")
    require(sha(raw) == receipt["output_sha256"] == OUTPUT_PINS[action] and len(raw) == receipt["output_size"],
            "operation output differs")
    payload = ("SPEC=" + repr({"action": action, "release_sha256": RELEASE_SHA}) + "\n").encode()
    payload += read(ROOT / TOOLS / "remote_ops.py")
    require(sha(payload) == receipt["payload_sha256"], "operation payload differs")
    return one(raw, "CPU_OPERATION=")


def recheck(fetch, status_folder):
    release_raw = read(fetch / "RELEASE.json")
    require(sha(release_raw) == RELEASE_SHA and read(ROOT / TOOLS / "RELEASE.json") == release_raw,
            "release differs")
    release = json.loads(release_raw)
    require(release["limits"] == LIMITS and len(release["files"]) == 26
            and release["predecessor_job_id"] == "703415", "release scope differs")
    local_intent = json.loads(read(EVIDENCE / "LOCAL_SUBMIT_INTENT.json"))
    require(local_intent == {"release_sha256": RELEASE_SHA, "action": "submit_once", "automatic_retry": False},
            "local submission intent differs")
    for name, digest in release["files"].items():
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts, "unsafe source path")
        require(sha(read(ROOT / relative)) == digest, "source changed: " + name)
    wire = operation(fetch, "fetch")
    status = operation(status_folder, "status")
    require(wire["status"] == "READ_ONLY_EVIDENCE" and wire["job_id"] == JOB
            and wire["jobs_submitted"] == 0 and status["jobs_submitted_by_query"] == 0,
            "read-only evidence scope differs")
    files = wire["files"]
    expected = {"RELEASE.json", "TEST_ONLY.json", "SUBMIT_INTENT.json", "SBATCH_RESPONSE.json",
                "SUBMISSION_RECEIPT.json", "SCHEDULER_ALLOCATION.json", "RUNNING.json", "TERMINAL.json",
                "registration.log", "slurm-703751.log"}
    require(set(files) == expected, "artifact inventory differs")
    for name, item in files.items():
        raw = read(fetch / name)
        require(raw == base64.b64decode(item["base64"], validate=True)
                and sha(raw) == item["sha256"] and len(raw) == item["size"], "artifact differs: " + name)
    records = {n: json.loads(read(fetch / n)) for n in files if n.endswith(".json")}
    running, terminal = records["RUNNING.json"], records["TERMINAL.json"]
    submission = records["SUBMISSION_RECEIPT.json"]
    for item in (records["SUBMIT_INTENT.json"], submission, running, terminal):
        require(item["nonce"] == NONCE and item["limits"] == LIMITS
                and item["release_sha256"] == RELEASE_SHA, "authorization differs")
    for item in (submission, running, terminal):
        require(item["job_id"] == JOB, "job identity differs")
    require(records["SBATCH_RESPONSE.json"] == {"returncode": 0, "stderr": "", "stdout": JOB + "\n"}
            and submission["jobs_submitted"] == 1 and submission["status"] == "SUBMITTED",
            "submission response differs")
    allocation = records["SCHEDULER_ALLOCATION.json"]
    fields = dict(s.split("=", 1) for s in allocation["stdout"].split() if "=" in s)
    require(allocation["returncode"] == 0 and all(fields.get(k) == v for k, v in {
        "JobId": JOB, "Partition": "TINY", "NumCPUs": "1", "NumNodes": "1-1", "NumTasks": "1",
        "CPUs/Task": "1", "TimeLimit": "00:30:00", "MinMemoryNode": "4G",
        "ReqTRES": "cpu=1,mem=4G,node=1,billing=1", "Requeue": "0", "Restarts": "0",
        "Comment": "real-registration-cpu-" + NONCE}.items()), "resource request differs")
    test = records["TEST_ONLY.json"]
    require(test["returncode"] == 0 and test["jobs_submitted"] == 0
            and test["release_sha256"] == RELEASE_SHA, "test-only record differs")
    require(status["terminal"] == terminal and status["submission"] == submission,
            "query and fetched records disagree")
    accounting = status["sacct"]
    rows = [s.split("|") for s in accounting["stdout"].splitlines() if s.startswith(JOB + "|")]
    require(accounting["returncode"] == 0 and len(rows) == 1 and rows[0][4:6] == ["1", "4G"],
            "accounting resources differ")
    require(rows[0][1] not in ("PENDING", "RUNNING", "COMPLETING"), "not terminal")
    slurm = read(fetch / ("slurm-" + JOB + ".log"))
    require(one(slurm, "CPU_JOB_STARTED=") == running and one(slurm, "CPU_JOB_TERMINAL=") == terminal,
            "Slurm log records differ")
    require(len(terminal["children"]) == 1, "not exactly one worker")
    child = terminal["children"][0]
    require(child["mode"] == "registration" and child["output"] == "registration.log"
            and type(child["pid"]) is int and child["pid"] > 0, "child identity differs")
    raw = read(fetch / "registration.log")
    require(sha(raw) == child["output_sha256"] and len(raw) == child["output_size"], "child bytes differ")
    require(one(raw, "CPU_CHILD_START=")["pid"] == child["pid"], "child entry differs")
    require(terminal["ready_for_gpu"] is False and terminal["slurm_jobs_submitted_by_coordinator"] == 0,
            "coordinator exceeded scope")
    passed = terminal["status"] == "REAL_REGISTRATION_CPU_VERIFIED"
    summary = None
    if passed:
        require(rows[0][1:3] == ["COMPLETED", "0:0"] and child["returncode"] == 0
                and terminal["returncode"] == 0 and terminal["error"] is None
                and terminal["temporary_directory_removed"] is True,
                "successful completion/cleanup unproven")
        require(0 < child["elapsed_seconds"] <= 1710 and 0 < terminal["elapsed_seconds"] <= 1800,
                "execution budget exceeded")
        spec = importlib.util.spec_from_file_location("pinned_registration_verifier", ROOT / TOOLS / "verify_registration.py")
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        summary = verifier.verify_output(raw, JOB, child["pid"])
        require(summary == terminal["summary"], "independent result differs")
    else:
        require(terminal["status"] == "REAL_REGISTRATION_CPU_NOT_VERIFIED"
                and terminal["returncode"] != 0 and terminal["error"] is not None,
                "failure status ambiguous")
    return {"status": "REAL_REGISTRATION_EVIDENCE_RECHECK_PASS" if passed else "REAL_REGISTRATION_FAILURE_EVIDENCE_VERIFIED",
            "job_id": JOB, "registration_verified": passed, "source_files_verified": 26,
            "remote_artifacts_verified": len(files), "release_sha256": RELEASE_SHA,
            "terminal_sha256": sha(read(fetch / "TERMINAL.json")),
            "fetch_output_sha256": sha(read(fetch / "output.log")),
            "status_output_sha256": sha(read(status_folder / "output.log")),
            "worker_pid": child["pid"], "accounting": rows[0], "summary": summary,
            "error": terminal["error"], "ready_for_gpu": False, "jobs_submitted_by_recheck": 0,
            "scope": "real checkpoint CPU cold registration only; not inference or final model comparison"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fetch", type=Path)
    parser.add_argument("status", type=Path)
    args = parser.parse_args()
    print(json.dumps(recheck(args.fetch, args.status), sort_keys=True))

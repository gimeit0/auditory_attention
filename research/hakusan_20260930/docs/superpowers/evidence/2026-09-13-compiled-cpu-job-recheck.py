"""Offline, read-only recheck of Job703415; no torch imports or job submission."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import stat

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).parent / "compiled-cpu-job-20260913-v2"
FETCH = EVIDENCE / "fetch-20260913T050308Z-7r3gmq7x"
STATUS = EVIDENCE / "status-20260913T050241Z-iw5uq0t2"
RELEASE_SHA = "e4f73042e3a7ffbe9026acd9a0539db8695f118bfc48d424fcc2016b4c1c0ca5"
FETCH_SHA = "3398b87b03a732c71098fc9b09b795de84b9c3b5ed32b8498ebd03a36444f41d"
STATUS_SHA = "7689169abc321c987c6036714b289ef085f0a91dd976076a5274c40579b48b26"
TOOLS = "docs/superpowers/prototypes/targeted_compiled_cpu_job_20260913_v2/"
VERIFY = "docs/superpowers/prototypes/targeted_compiled_lifetime_20260913/verify_pair.py"
LIMITS = {"jobs": 1, "cpus": 1, "memory_mib": 4096, "wall_seconds": 1800, "gpus": 0}
NONCE = "a214e11a54234ebc95cc94a4c2780cb1"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= 8 * 1024**2,
            "not a bounded regular file: " + str(path))
    return path.read_bytes()


def unique_record(raw, prefix):
    rows = [json.loads(line[len(prefix):]) for line in raw.decode().splitlines()
            if line.startswith(prefix)]
    require(len(rows) == 1, "record missing or duplicate: " + prefix)
    return rows[0]


def operation(folder, action, expected_sha):
    raw = read(folder / "output.log")
    receipt = json.loads(read(folder / "receipt.json"))
    require(sha(raw) == expected_sha == receipt["output_sha256"]
            and len(raw) == receipt["output_size"], "operation bytes differ")
    require(receipt["action"] == action and receipt["returncode"] == 0
            and receipt["automatic_retry"] is False
            and receipt["release_sha256"] == RELEASE_SHA, "operation receipt differs")
    spec = {"action": action, "release_sha256": RELEASE_SHA}
    payload = ("SPEC=" + repr(spec) + "\n").encode() + read(ROOT / TOOLS / "remote_ops.py")
    require(sha(payload) == receipt["payload_sha256"], "read-only payload differs")
    return unique_record(raw, "CPU_OPERATION=")


def main():
    release_raw = read(FETCH / "RELEASE.json")
    require(sha(release_raw) == RELEASE_SHA, "frozen release differs")
    release = json.loads(release_raw)
    require(release["limits"] == LIMITS and release["predecessor_job_id"] == "703335"
            and len(release["files"]) == 25, "release scope differs")
    require(read(ROOT / TOOLS / "RELEASE.json") == release_raw, "local release differs")
    for name, digest in release["files"].items():
        path = Path(name)
        require(not path.is_absolute() and ".." not in path.parts, "unsafe source path")
        require(sha(read(ROOT / path)) == digest, "source changed: " + name)

    fetched = operation(FETCH, "fetch", FETCH_SHA)
    require(fetched["status"] == "READ_ONLY_EVIDENCE" and fetched["job_id"] == "703415",
            "fetch identity differs")
    files = fetched["files"]
    expected_names = {"RELEASE.json", "RUNNING.json", "SBATCH_RESPONSE.json",
                      "SCHEDULER_ALLOCATION.json", "SUBMISSION_RECEIPT.json", "SUBMIT_INTENT.json",
                      "TERMINAL.json", "TEST_ONLY.json", "observed.log", "reference.log", "slurm-703415.log"}
    require(set(files) == expected_names, "evidence coverage differs")
    for name, item in files.items():
        raw = read(FETCH / name)
        require(raw == base64.b64decode(item["base64"], validate=True)
                and sha(raw) == item["sha256"] and len(raw) == item["size"], "fetched artifact differs: " + name)
    records = {name: json.loads(read(FETCH / name)) for name in files if name.endswith(".json")}
    intent, submission = records["SUBMIT_INTENT.json"], records["SUBMISSION_RECEIPT.json"]
    running, terminal = records["RUNNING.json"], records["TERMINAL.json"]
    for item in (intent, submission, running, terminal):
        require(item["nonce"] == NONCE and item["release_sha256"] == RELEASE_SHA
                and item["limits"] == LIMITS, "authorization chain differs")
    for item in (submission, running, terminal):
        require(item["job_id"] == "703415", "job identity differs")
    require(records["SBATCH_RESPONSE.json"] == {"returncode": 0, "stderr": "", "stdout": "703415\n"}
            and submission["status"] == "SUBMITTED" and submission["jobs_submitted"] == 1,
            "submission response differs")
    allocation = records["SCHEDULER_ALLOCATION.json"]
    values = dict(field.split("=", 1) for field in allocation["stdout"].split() if "=" in field)
    require(allocation["returncode"] == 0 and all(values.get(k) == v for k, v in {
        "JobId": "703415", "Partition": "TINY", "NumCPUs": "1", "NumNodes": "1-1",
        "NumTasks": "1", "CPUs/Task": "1", "MinMemoryNode": "4G", "TimeLimit": "00:30:00",
        "ReqTRES": "cpu=1,mem=4G,node=1,billing=1", "Requeue": "0", "Restarts": "0",
        "Comment": "compiled-cpu-" + NONCE}.items()), "actual requested resources differ")
    status = operation(STATUS, "status", STATUS_SHA)
    require(status["terminal"] == terminal and status["submission"] == submission
            and status["jobs_submitted_by_query"] == 0, "status and fetched records differ")
    require(status["sacct"]["returncode"] == 0 and status["sacct"]["stdout"].splitlines() == [
        "JobIDRaw|State|ExitCode|Elapsed|AllocCPUS|ReqMem|NodeList",
        "703415|COMPLETED|0:0|00:02:52|1|4G|lcpcc-062"], "Slurm completion differs")
    require(terminal["status"] == "CPU_PAIR_VERIFIED" and terminal["returncode"] == 0
            and terminal["error"] is None and terminal["temporary_directory_removed"] is True
            and terminal["production_model_loaded"] is False and terminal["ready_for_gpu"] is False,
            "terminal gates differ")
    slurm = read(FETCH / "slurm-703415.log")
    require(unique_record(slurm, "CPU_JOB_STARTED=") == running
            and unique_record(slurm, "CPU_JOB_TERMINAL=") == terminal, "Slurm record binding differs")
    require([c["mode"] for c in terminal["children"]] == ["reference", "observed"], "child order differs")
    children = []
    for child, pid in zip(terminal["children"], (787357, 787426)):
        raw = read(FETCH / child["output"])
        require(child["returncode"] == 0 and child["pid"] == pid
                and 0 < child["elapsed_seconds"] <= 900 and sha(raw) == child["output_sha256"]
                and len(raw) == child["output_size"], "child execution/bytes differ")
        start = unique_record(raw, "CPU_CHILD_START=")
        value = unique_record(raw, "LIFETIME_CHILD=")
        require(start["pid"] == value["pid"] == pid and start["mode"] == value["mode"] == child["mode"],
                "child identity binding differs")
        children.append(value)
    spec = importlib.util.spec_from_file_location("pinned_pair_verifier", ROOT / VERIFY)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    summary = verifier.verify_pair(*children)
    require(summary == terminal["summary"], "independent verification differs from remote result")
    return {"status": "CPU_JOB_EVIDENCE_RECHECK_PASS", "job_id": "703415",
            "source_files_verified": 25, "remote_artifacts_verified": len(files),
            "release_sha256": RELEASE_SHA, "fetch_output_sha256": FETCH_SHA,
            "terminal_sha256": sha(read(FETCH / "TERMINAL.json")), "summary": summary,
            "jobs_submitted_by_recheck": 0, "ready_for_gpu": False,
            "scope": "synthetic CPU eager cold pair; not production, Inductor, A100 or final model comparison"}


if __name__ == "__main__":
    print(json.dumps(main(), sort_keys=True))

"""One existing held job only. No sbatch, cancellation, requeue or auto retry.

This recovery is deliberately outside the immutable CONTROL_RELEASE inventory.
Slurm 25.05.5 update_job.c supports both TresPerJob and TresPerNode.
Updating the typed request and releasing it are separate, journaled actions.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import types
import uuid

JOB = "713897"
NONCE = "899e59b8732346d782e54b091d6f05e6"
RELEASE_SHA = "355f29740dfdc159402c49a80b01e79acc1b69b9000e1361edf1e680d50aec52"
GPU = "gres/gpu:nvidia_a100:1"
UPDATE = ["/usr/bin/scontrol", "update", "JobId=" + JOB,
          "TresPerJob=" + GPU, "TresPerNode=" + GPU]
RELEASE = ["/usr/bin/scontrol", "release", JOB]
SCONTROL = ["/usr/bin/scontrol", "show", "job", "-o", JOB]
ACCOUNTING = ["/usr/bin/sacct", "-j", JOB, "-X", "-n", "-P",
              "--format=JobIDRaw,State,ReqTRES%256,AllocTRES%256,Elapsed"]


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fields(text):
    pairs = re.findall(r"(?:^|\s)([A-Za-z0-9_/]+)=([^\s]*)", text)
    result = dict(pairs)
    require(len(result) == len(pairs), "duplicate job fields")
    return result


def resources(text):
    pairs = [part.split("=", 1) for part in text.split(",")]
    require(all(len(p) == 2 for p in pairs), "malformed resource list")
    result = dict(pairs)
    require(len(result) == len(pairs), "duplicate resource keys")
    if result.get("mem") == "65536M":
        result["mem"] = "64G"
    return result


def validate_job(text, root, *, corrected):
    value = fields(text)
    expected = {"JobId": JOB, "JobName": "audattn_b2_coldpair",
                "Partition": "GPU-1A", "JobState": "PENDING", "Reason": "JobHeldUser",
                "Priority": "0", "NumCPUs": "8", "NumTasks": "1", "CPUs/Task": "8",
                "TimeLimit": "02:00:00", "RunTime": "00:00:00", "Requeue": "0", "Restarts": "0",
                "AllocTRES": "(null)", "NodeList": "", "Comment": "audattn-b2-" + NONCE,
                "Account": "student", "QOS": "normal", "WorkDir": str(root),
                "Command": str(root / "package/docs/superpowers/prototypes/targeted_gpu_job_20260914_v3/run_gpu.sbatch"),
                "StdIn": "/dev/null", "StdOut": str(root / "logs/coldpair_713897.log"),
                "StdErr": str(root / "logs/coldpair_713897.log"), "TresPerTask": "cpu=8",
                "TresPerNode": GPU if corrected else "gres/gpu:1"}
    if corrected:
        expected["TresPerJob"] = GPU
    else:
        require("TresPerJob" not in value, "unreviewed before-update TresPerJob")
    require(all(value.get(k) == v for k, v in expected.items()),
            "job identity, hold, resource or execution fields differ: " +
            ",".join(k for k, v in expected.items() if value.get(k) != v))
    require(value.get("NumNodes") in ("1", "1-1") and value.get("MinMemoryNode") in ("64G", "65536M")
            and re.fullmatch(r"s2510040\([0-9]+\)", value.get("UserId", "")), "owner/node/memory differs")
    require(all(k not in value for k in ("HetJobId", "ArrayJobId", "TresPerSocket", "MemPerTres", "CpusPerTres")),
            "unexpected additional job resource constraints")
    requested = resources(value.get("ReqTRES", ""))
    expected_tres = {"cpu": "8", "mem": "64G", "node": "1", "billing": "8",
                     "gres/gpu:nvidia_a100" if corrected else "gres/gpu:h100-20c": "1"}
    # Some versions include the aggregate alongside the typed GPU. Both must
    # be exactly one; a different model (including H100) is never an alias.
    if corrected and "gres/gpu" in requested:
        expected_tres["gres/gpu"] = "1"
    require(requested == expected_tres, "ReqTRES must match the exact reviewed GPU/CPU/memory request")
    return requested


def validate_accounting(text, requested):
    lines = [line for line in text.splitlines() if line.strip()]
    require(len(lines) == 1, "one accounting job record required")
    parts = lines[0].split("|")
    require(len(parts) == 5 and parts[0] == JOB and parts[1] == "PENDING"
            and not parts[3] and parts[4] == "00:00:00", "accounting identity/state/allocation differs")
    require(resources(parts[2]) == requested, "accounting GPU request disagrees; keep held")


def validate_nodes(text):
    lines = [line.split("|") for line in text.splitlines() if line.strip()]
    require(len(lines) == 10 and {p[0] for p in lines} == {"spcc-a100g%02d" % i for i in range(1, 11)},
            "GPU-1A node set differs")
    require(all(len(p) == 3 and p[1] == "gpu:nvidia_a100:2(S:0-1)" for p in lines), "GPU-1A model differs")


def snapshot(invoke):
    result = {"version": invoke(["/usr/bin/scontrol", "--version"]),
              "job": invoke(SCONTROL), "accounting": invoke(ACCOUNTING),
              "nodes": invoke(["/usr/bin/sinfo", "-p", "GPU-1A", "-N", "-h", "-o", "%N|%G|%t"]),
              "queue": invoke(["/usr/bin/squeue", "-h", "-u", "s2510040", "-n",
                    "audattn_b2_coldpair,audattn_reg_cpu,audattn_cmp_cpu,audattn_v4_numdiag,audattn_samebank_v4",
                    "-o", "%i|%T|%j"])}
    return result


def validate_snapshot(value, root, *, corrected):
    for name, result in value.items():
        require(result["returncode"] == 0 and not result.get("timed_out") and not result.get("truncated"),
                "read-only query failed: " + name)
    require(value["version"]["stdout"].strip() == "slurm 25.05.5", "reviewed Slurm version differs")
    require(value["queue"]["stdout"].strip() == JOB + "|PENDING|audattn_b2_coldpair", "related queue differs")
    validate_nodes(value["nodes"]["stdout"])
    requested = validate_job(value["job"]["stdout"], root, corrected=corrected)
    validate_accounting(value["accounting"]["stdout"], requested)


def checked_context(ops):
    raw = ops.read(ops.REMOTE / "CONTROL_RELEASE.json")
    release = ops.validate_release(raw, RELEASE_SHA)
    ops.Operations().sources(release)
    ops.Operations().protected_inputs()
    auth = {"approved": True, "package_sha256": ops.PACKAGE_SHA, "pair_nonce": NONCE,
            "limits": ops.LIMITS, "scope": ops.SCOPE}
    for name in ("AUTHORIZATION.json", "SUBMIT_INTENT.json"):
        require(json.loads(ops.read(ops.REMOTE / name)) == auth, "original authorization differs")
    receipt = json.loads(ops.read(ops.REMOTE / "SUBMISSION_RECEIPT.json"))
    require(receipt == {"authorization": auth, "job_id": JOB, "jobs_submitted": 1,
            "release_sha256": RELEASE_SHA, "status": "SUBMITTED_HELD"}, "original receipt differs")
    require(ops.job_id(json.loads(ops.read(ops.REMOTE / "SBATCH_RESPONSE.json"))) == JOB, "original sbatch response differs")
    return auth


def mutate(action, ops, spec):
    require(action in ("update", "release"), "unsupported mutation")
    auth = checked_context(ops)
    for name in ("RELEASE_INTENT.json", "RELEASE_RESPONSE.json", "RELEASED.json", "COORDINATOR_TERMINAL.json"):
        require(not (ops.REMOTE / name).exists() and not (ops.REMOTE / name).is_symlink(),
                "already released/attempted/terminal: inspect only")
    before = snapshot(ops.command)
    validate_snapshot(before, ops.REMOTE, corrected=(action == "release"))
    if action == "release":
        prior = json.loads(ops.read(ops.REMOTE / "GPU_TYPE_UPDATE_RESPONSE.json"))
        intent = json.loads(ops.read(ops.REMOTE / "GPU_TYPE_UPDATE_INTENT.json"))
        require(ops.success(prior) and intent["command"] == UPDATE and intent["job_id"] == JOB
                and intent["pair_nonce"] == NONCE, "successful same-job typed update required")
        require(intent["repair_source_sha256"] == spec["repair_source_sha256"], "update recovery source differs")
        verified = json.loads(ops.read(ops.REMOTE / "GPU_TYPE_UPDATED.json"))
        require(verified["status"] == "GPU_TYPE_CORRECTED_STILL_HELD"
                and verified["job_id"] == JOB and verified["jobs_submitted"] == 0, "verified update required")
        validate_snapshot(verified["after"], ops.REMOTE, corrected=True)
    record = {"job_id": JOB, "pair_nonce": NONCE, "request_id": spec["request_id"],
              "command": UPDATE if action == "update" else RELEASE, "before": before,
              "repair_source_sha256": spec["repair_source_sha256"], "authorization_sha256": ops.sha(ops.wire(auth)),
              "authorization_basis": "user-approved one A100 job; restore only the held job to that approved GPU type",
              "jobs_submitted": 0, "automatic_retry": False}
    prefix = "GPU_TYPE_UPDATE" if action == "update" else "RELEASE"
    ops.Operations().save(prefix + "_INTENT.json", record)  # exclusive + fsync BEFORE mutation
    response = ops.command(record["command"])
    ops.Operations().save(prefix + "_RESPONSE.json", response)
    after = snapshot(ops.command)  # always read after even if the RPC failed
    ops.Operations().save(prefix + "_READBACK.json", after)
    require(ops.success(response), "same-job command failed/uncertain; no automatic retry")
    if action == "update":
        validate_snapshot(after, ops.REMOTE, corrected=True)
    checked_context(ops)  # immutable inputs and code remain unchanged
    if action == "release":
        require(ops.success(after["job"]), "release succeeded but follow-up query failed")
        live = fields(after["job"]["stdout"])
        prior_fields = fields(before["job"]["stdout"])
        stable = ("JobId", "JobName", "UserId", "Comment", "Partition", "NumCPUs",
                  "CPUs/Task", "NumTasks", "TimeLimit", "Requeue", "Restarts", "Command",
                  "WorkDir", "StdIn", "StdOut", "StdErr", "TresPerJob", "TresPerNode", "TresPerTask")
        require(all(live.get(k) == prior_fields.get(k) for k in stable), "post-release resource/identity fields differ")
        require(resources(live.get("ReqTRES", "")) == resources(prior_fields["ReqTRES"]),
                "post-release requested resources differ")
        require(live.get("JobId") == JOB and live.get("Comment") == "audattn-b2-" + NONCE
                and live.get("Reason") not in ("JobHeldUser", "JobHeldAdmin")
                and live.get("Priority") not in (None, "0"), "release response successful but live hold not cleared")
    result = {"status": "GPU_TYPE_CORRECTED_STILL_HELD" if action == "update" else "SAME_JOB_RELEASED",
              "job_id": JOB, "jobs_submitted": 0, "after": after, "automatic_retry": False}
    ops.Operations().save("GPU_TYPE_UPDATED.json" if action == "update" else "RELEASED.json", result)
    return result


def remote_main(spec, ops):
    import pwd
    import socket
    os.umask(0o077)
    require(sys.platform == "linux" and sys.version.split()[0] == "3.11.5"
            and pwd.getpwuid(os.getuid()).pw_name == "s2510040"
            and socket.gethostname().split(".")[0] == "hakusan1", "fixed login environment required")
    if spec["action"] == "inspect":
        checked_context(ops)
        result = {"status": "READ_ONLY", "job_id": JOB, "snapshot": snapshot(ops.command), "journals": {}}
        for name in ("GPU_TYPE_UPDATE_INTENT.json", "GPU_TYPE_UPDATE_RESPONSE.json", "GPU_TYPE_UPDATED.json",
                     "RELEASE_INTENT.json", "RELEASE_RESPONSE.json", "RELEASED.json"):
            if (ops.REMOTE / name).exists():
                result["journals"][name] = json.loads(ops.read(ops.REMOTE / name))
        return result
    return mutate(spec["action"], ops, spec)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("inspect", "update", "release"))
    p.add_argument("--expected-source-sha256", required=True)
    args = p.parse_args()
    os.umask(0o077)
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    import control
    ops = control.ops
    raw, release, files = control.package()
    require(digest(raw) == RELEASE_SHA, "fixed original release required")
    source = ops.read(here / "repair_713897.py")
    require(digest(source) == args.expected_source_sha256, "reviewed recovery source SHA differs")
    control.master_check(control.SOCKET)
    spec = {"action": args.action, "request_id": uuid.uuid4().hex,
            "repair_source_sha256": digest(source), "release_sha256": RELEASE_SHA}
    if args.action != "inspect":
        ops.write_new(control.EVIDENCE / ("LOCAL_GPU713897_" + args.action.upper() + "_INTENT.json"), ops.wire(spec))
    code = "import base64,hashlib,json,types\nSPEC=" + repr(spec) + "\n"
    for label, content in (("OPS", files[ops.OPS]), ("REPAIR", source)):
        code += "raw=base64.b64decode(" + repr(base64.b64encode(content).decode()) + ",validate=True)\n"
        code += "assert hashlib.sha256(raw).hexdigest()==" + repr(digest(content)) + "\n"
        code += label + "=types.ModuleType(" + repr(label) + ")\nexec(compile(raw,'<fixed-recovery>','exec')," + label + ".__dict__)\n"
    code += "try:\n result={'ok':True,'result':REPAIR.remote_main(SPEC,OPS)}\n"
    code += "except BaseException as e:\n result={'ok':False,'error':{'type':type(e).__name__,'message':str(e)}}\n"
    code += "print('GPU_CONTROL='+json.dumps({**SPEC,**result}),flush=True)\nraise SystemExit(0 if result['ok'] else 2)\n"
    # Reuse the already pinned bounded transport and receipt writer, replacing
    # only the payload builder for this invocation. No submit entry is called.
    original = control.payload
    control.payload = lambda _spec, _source: code.encode("ascii")
    try:
        result = control.operate(spec, files)
    finally:
        control.payload = original
    control.package()
    require(digest(ops.read(here / "repair_713897.py")) == spec["repair_source_sha256"], "recovery source changed")
    return result["returncode"]


if __name__ == "__main__":
    raise SystemExit(main())

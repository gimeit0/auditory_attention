"""Bounded local bootstrap test or one remote CPU attempt via existing master."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent / "targeted_gpu_control_20260913"))
import control
import remote_ops as ops

MANIFEST = "docs/superpowers/prototypes/targeted_gpu_job_20260914/SOURCE_MANIFEST.json"
PACKAGE_SHA = "8ddf8cc8ece27a14c49336b60fd1a45ffa295f57fb45778a66c559514d6d04f5"


def package(local):
    control.package()  # old 51 files must remain unchanged
    raw = ops.read(ROOT / MANIFEST)
    ops.require(ops.sha(raw) == PACKAGE_SHA, "new GPU candidate manifest differs")
    names = json.loads(raw)["files"]
    ops.require(len(names) == 49, "candidate count differs")
    names[MANIFEST] = PACKAGE_SHA
    relative = str((HERE / "probe_child.py").relative_to(ROOT))
    names[relative] = ops.sha(ops.read(HERE / "probe_child.py"))
    sources = {}
    for name, digest in names.items():
        raw = ops.read(ROOT / ops.member(name))
        ops.require(ops.sha(raw) == digest, "pinned CPU source differs: " + name)
        sources[name] = {"base64": base64.b64encode(raw).decode("ascii"), "sha256": digest}
    return {"local_test": local, "package_sha256": PACKAGE_SHA, "files": sources}


def verify(remote, local):
    ops.require(remote["status"] == ("LOCAL_STARTUP_PAYLOAD_PASS" if local else "HAKUSAN_STARTUP_CPU_PASS")
                and remote["local_test"] is local and remote["sources_unchanged"]
                and remote["temporary_directory_removed"] and remote["package_sha256"] == PACKAGE_SHA
                and len(remote["cases"]) == 3 and remote["source_files"] == 51 and remote["error"] is None
                and remote["jobs_submitted"] == remote["forward_calls"] == 0
                and remote["production_model_loaded"] is False and remote["ready_for_gpu"] is False,
                "CPU result not complete")
    ops.require({c["case"] for c in remote["cases"]} == {"old-reference", "new-reference", "new-observed"}
                and len({c["process"]["pid"] for c in remote["cases"]}) == 3, "cold cases/PIDs differ")
    for case in remote["cases"]:
        p, r = case["process"], case["result"]
        data = base64.b64decode(case["log_base64"], validate=True)
        ops.require(p["error"] is None and p["returncode"] == 0 and r["pid"] == p["pid"]
                    and len(data) == p["log"]["size"] and ops.sha(data) == p["log"]["sha256"], "CPU log/result differs")
        ops.require(r["error"] is None and not r["cuda_initialized"] and not r["production_model_loaded"]
                    and r["forward_calls"] == r["jobs_submitted"] == 0 and r["home_preserved"]
                    and r["local_test"] is local and r["torch"] == ("2.12.1" if local else "2.1.1+cu118"), "CPU scope differs")
        ops.require(case["case"] == r["mode"] + "-" + r["role"] and r["package_sha256"] == PACKAGE_SHA
                    and r["status"] == ("LOCAL_STARTUP_IMPORT_PASS" if local else "HAKUSAN_STARTUP_IMPORT_PASS")
                    and r["python"] == (sys.version.split()[0] if local else "3.11.5")
                    and r["allocation_claimed"] is False and r["ready_for_gpu"] is False,
                    "child identity, package or scope label differs")
        if case["case"].startswith("new-"):
            ops.require(r["torch_absent_before_scratch"] and r["caches_initially_empty"]
                        and r["anchors_closed"] and r["original_loader_binding_checked"], "new startup failed")
            if not local:
                ops.require(r["mount"].get("filesystem") in ("tmpfs", "ext4", "xfs", "btrfs"), "native mount missing")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    before = package(args.self_test)
    source = ops.read(HERE / "probe_parent.py")
    payload = control.payload(before, source)
    folder = Path(tempfile.mkdtemp(prefix=("startup-probe-local-" if args.self_test else "startup-probe-remote-") +
                 datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-", dir=ROOT / "docs/superpowers/evidence"))
    print("EVIDENCE_DIRECTORY=" + str(folder), flush=True)
    process, remote, error = None, None, None
    try:
        if args.self_test:
            argv = [sys.executable, "-I", "-B", "-"]
        else:
            control.master_check(control.SOCKET)
            argv = control.ssh_command(control.SOCKET)
        process = control.transport(argv, payload, folder, timeout=115, log_cap=4 * 1024**2)
        log = ops.read(folder / "output.log")
        records = [json.loads(line) for line in log.decode().splitlines() if line.startswith('{"startup_cpu_result":')]
        ops.require(len(records) == 1, "one complete CPU result required")
        remote = records[0]["startup_cpu_result"]
        ops.require(process["returncode"] == 0 and process["error"] is None, "CPU transport failed")
        verify(remote, args.self_test)
        for case in remote["cases"]:
            ops.write_new(folder / (case["case"] + ".log"), base64.b64decode(case["log_base64"], validate=True))
            ops.write_new(folder / (case["case"] + ".json"), ops.wire(case["result"]))
        ops.require(before == package(args.self_test) and source == ops.read(HERE / "probe_parent.py"), "local source changed")
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    receipt = {"status": "STARTUP_CPU_PROBE_VERIFIED" if error is None else "STARTUP_CPU_PROBE_NOT_VERIFIED",
        "self_test": args.self_test, "process": process, "result": remote, "error": error,
        "package_sha256": PACKAGE_SHA, "parent_sha256": ops.sha(source), "payload_sha256": ops.sha(payload),
        "driver_sha256": ops.sha(ops.read(Path(__file__))), "source_sha256": {n:v["sha256"] for n,v in before["files"].items()},
        "artifacts": {p.name:{"size":p.stat().st_size,"sha256":ops.sha(ops.read(p))} for p in folder.iterdir() if p.is_file()},
        "automatic_retry": False, "jobs_submitted": 0, "ready_for_gpu": False}
    ops.write_new(folder / "receipt.json", ops.wire(receipt))
    print(json.dumps({"status": receipt["status"], "self_test": args.self_test, "error": error,
                      "jobs_submitted": 0, "ready_for_gpu": False}), flush=True)
    return 0 if error is None else 2


if __name__ == "__main__":
    raise SystemExit(main())

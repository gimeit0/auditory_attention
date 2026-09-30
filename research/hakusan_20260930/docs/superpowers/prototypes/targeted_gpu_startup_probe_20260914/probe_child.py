"""CPU import/scratch probe, NOT a GPU worker or model-preparation entry.

Synthetic job label exists only to exercise the unmodified directory factory;
no Slurm allocation is asserted or requested. Native mode keeps original Linux
mount verification; only explicit --local-test uses the labeled Mac test seam.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import traceback
import types

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
JOB = HERE.parent / "targeted_gpu_job_20260914"
sys.path.insert(0, str(JOB))
import job_contract as contract
import process_runner as process
import gpu_child
startup = gpu_child._startup


def numeric_imports():
    sys.path.insert(0, str(HERE.parent / "targeted_production_preparation_20260913"))
    sys.path.insert(0, str(HERE.parent / "targeted_gpu_pair_20260913"))
    import cuda_registration as cuda
    import archive_adapter
    from bounded_archive import archive
    return cuda


def main(args):
    startup.require(sys.flags.isolated and sys.dont_write_bytecode and os.environ.get("CUDA_VISIBLE_DEVICES") == "",
                    "isolated CPU-only probe required")
    startup.require(sys.version.split()[0] == (args.local_python if args.local_test else "3.11.5"), "Python differs")
    if not args.local_test:
        import pwd
        startup.require(sys.platform.startswith("linux") and pwd.getpwuid(os.getuid()).pw_name == "s2510040",
                        "HAKUSAN Linux account required")
    record = {"status": "STARTUP_CPU_PROBE_FAILED", "pid": os.getpid(), "mode": args.mode, "role": args.role,
              "package_sha256": args.package_sha,
              "local_test": args.local_test, "production_model_loaded": False, "forward_calls": 0,
              "jobs_submitted": 0, "allocation_claimed": False, "ready_for_gpu": False,
              "synthetic_directory_job_label": os.environ["SLURM_JOB_ID"], "python": sys.version.split()[0]}
    native_load = startup.checked_load
    if args.local_test:
        # A separate local path; never reassign HOME or overwrite real v18.
        contract.V18 = ROOT / "local_fixture_v18"
        def local_load(*values):
            diag = native_load(*values)
            diag._require_local_scratch_mount = lambda p: {"scope": "LOCAL_TEST_MOUNT_STUB"}
            return diag
        startup.checked_load = local_load
    events = []
    root = Path(os.environ["DIAG_SCRATCH_ROOT"])
    worker_role = "reference_cold" if args.role == "reference" else "B2"
    original_home = os.environ.get("HOME")
    def audit(event, values):
        if event != "os.mkdir" or len(events) >= 8:
            return
        path = os.fsdecode(values[0])
        if path != worker_role and not path.startswith(str(root / worker_role)):
            return
        events.append({"path": path.replace(str(root), "<scratch-parent>"),
            "callers": [{"file": "/".join(Path(f.filename).parts[-4:]), "line": f.lineno, "function": f.name}
                        for f in traceback.extract_stack(limit=8)[:-1]]})
    sys.addaudithook(audit)
    error = None
    try:
        contract.check_sources(args.package_sha)
        diag_path = contract.V18 / "tools/diagnose_batch_invariance.py"
        contract.pinned_read(diag_path, startup.V18_SHA)
        invocation = types.SimpleNamespace(job_id=os.environ["SLURM_JOB_ID"],
                                            expected_input_freeze_sha256=contract.FREEZE_SHA)
        if args.mode == "old":
            cuda = numeric_imports()
            diag = cuda.bridge.load_v18(diag_path)
            if args.local_test:
                diag._require_local_scratch_mount = lambda p: {"scope": "LOCAL_TEST_MOUNT_STUB"}
            _, scope, _ = startup.adapter.build(diag)
            record["role_exists_before_factory"] = (root / worker_role).exists()
            try:
                with scope(invocation, worker_role) as scratch:
                    record.update(collision_reproduced=False, mount=scratch.record["mount"])
            except FileExistsError as exc:
                record.update(collision_reproduced=True, filename=exc.filename)
        else:
            with startup.open_scratch(contract, args.role) as boot:
                record.update(torch_absent_before_scratch="torch" not in sys.modules,
                              caches_initially_empty=boot.scratch.record["caches_initially_empty"],
                              mount=boot.scratch.record["mount"])
                cuda = numeric_imports()
                diag = cuda.bridge.load_v18(diag_path)
                private, scope, _ = startup.bind_scope(boot, diag, cuda.bridge)
                with scope(invocation, worker_role) as scratch:
                    startup.require(type(scratch) is private and scratch.anchors is boot.scratch.anchors,
                                    "actual execution scratch type/anchors differ")
                    scratch.check()
                record["original_loader_binding_checked"] = True
            record["anchors_closed"] = all(not anchor.chain for anchor, *_ in boot.anchor_ids)
            startup.require(record["anchors_closed"] and record["torch_absent_before_scratch"]
                            and record["caches_initially_empty"], "scratch startup ordering/cleanup differs")
        record.update(torch=str(cuda.torch.__version__), cuda_initialized=cuda.torch.cuda.is_initialized(),
                      home_preserved=os.environ.get("HOME") == original_home)
        startup.require(record["torch"] == ("2.12.1" if args.local_test else "2.1.1+cu118")
                        and not record["cuda_initialized"] and record["home_preserved"], "version/CPU/HOME scope differs")
        if not args.local_test and args.mode == "new":
            startup.require(record["mount"].get("filesystem") in ("tmpfs", "ext4", "xfs", "btrfs"),
                            "native Linux mount was not validated")
        contract.check_sources(args.package_sha)
        contract.pinned_read(diag_path, startup.V18_SHA)
        record["status"] = "LOCAL_STARTUP_IMPORT_PASS" if args.local_test else "HAKUSAN_STARTUP_IMPORT_PASS"
    except BaseException as exc:
        traceback.print_exc()
        error = {"type": type(exc).__name__, "message": str(exc)}
    record.update(error=error, mkdir_events=events)
    process.write_once(args.output, record)
    print(json.dumps({k: v for k, v in record.items() if k != "mkdir_events"}, sort_keys=True), flush=True)
    return 0 if error is None else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("old", "new"))
    parser.add_argument("role", choices=("reference", "observed"))
    parser.add_argument("package_sha")
    parser.add_argument("output", type=Path)
    parser.add_argument("--local-test", action="store_true")
    parser.add_argument("--local-python", default="")
    raise SystemExit(main(parser.parse_args()))

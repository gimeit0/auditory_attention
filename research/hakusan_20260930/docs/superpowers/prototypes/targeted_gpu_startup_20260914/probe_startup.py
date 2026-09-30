"""Fresh LOCAL CPU import/real-mmap probe. Never production or GPU evidence.

Uses test_startup's explicitly labeled mount-decision stub on this Mac. All
other original scratch-factory checks run. No job, checkpoint, or network I/O.
The optional synthetic cache import proves the failure path even if this
local torch version doesn't create the role during its real import chain.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_startup as fixture
import startup


def numeric_imports():
    sys.path.insert(0, str(HERE.parent / "targeted_production_preparation_20260913"))
    sys.path.insert(0, str(HERE.parent / "targeted_gpu_pair_20260913"))
    import cuda_registration as cuda
    import archive_adapter
    from bounded_archive import archive
    return cuda, archive_adapter, archive


def mmap_lifetime(boot, args, archive_adapter, archive):
    sys.path.insert(0, str(HERE.parent / "targeted_worker_20260912"))
    import test_baseline_bridge as f
    from test_pair_archive import binding
    f.torch.set_num_threads(1)
    parent = f.expected_contract()
    wire = f.replay.canonical(parent)
    private, scope, _ = startup.bind_scope(boot, f.diag, f.bridge)
    with scope(args, boot.role) as scratch, f.worker("B2") as (context, trials, evaluator, scene):
        gate = f.bridge.BaselineBridge(f.diag, context, trials, wire, f.replay.sha(wire), "B2", hermetic_test=True)
        writer = archive.PassArchive(boot.scratch.root.parent / "synthetic-archive", binding())
        try:
            collector = archive_adapter.PassCollector(gate, scratch, writer, spill=False)
            collector.names = (f.replay.BOUNDARIES, f.replay.COARSE)
            tree, audit = startup.adapter.reference_loop(archive_adapter, private)
            namespace = {**vars(f.bridge), "_private_scratch_type": private}
            exec(compile(tree, "<scratch-first-synthetic-mmap>", "exec"), namespace)
            result = namespace["archived_reference"](gate, scratch=scratch, _archiver=collector)
            startup.require(result["status"] == "HERMETIC_V18_BASELINE_BRIDGE_PASS", "synthetic lifetime failed")
            startup.require(evaluator.calls.count("model") == 34 and len(evaluator.load_calls) == 1,
                            "synthetic lifetime schedule differs")
            startup.require(len(scratch.spills) == len(scratch._maps) == 4, "spill/mmap count differs")
            scratch.verify_spills()
            document = archive.verify_archive(writer.root, writer.finish(), writer.binding, parent)
            for part in document["passes"]:
                f.diag.decode_pass_evidence(part["original_pass_evidence"])
            return {"synthetic_lifetime_pass": True, "synthetic_forward_calls": 34,
                    "spill_files": 4, "mapped_files": 4, "archive_passes": len(document["passes"]),
                    "original_bridge_issuance_checked": True, "loop_audit": audit}
        finally:
            writer.close()
            f.diag._revoke_attestation(gate.attestation)


def run(mode, role, output):
    startup.require(os.environ.get("CUDA_VISIBLE_DEVICES") == "", "local CPU-only environment required")
    record = {"mode": mode, "role": role, "pid": os.getpid(), "python": sys.version.split()[0],
              "remote_executed": False, "production_model_loaded": False, "jobs_submitted": 0,
              "ready_for_gpu": False, "mount_validation": "LOCAL_TEST_MOUNT_STUB"}
    original_home = os.environ.get("HOME")
    events = []
    with fixture.local_scope_test_environment(role) as (_, parent, contract, args, loaded):
        worker_role = "reference_cold" if role == "reference" else "B2"
        root = parent / worker_role
        active = [True]

        def audit(event, values):
            if not active[0] or event != "os.mkdir" or len(events) >= 12:
                return
            path = os.fsdecode(values[0])
            # Relative original mkdir is included without exposing unrelated paths.
            if path != worker_role and not path.startswith(str(root)):
                return
            events.append({"path": path.replace(str(parent), "<scratch-parent>"),
                           "callers": [{"file": "/".join(Path(f.filename).parts[-4:]), "line": f.lineno, "function": f.name}
                                       for f in traceback.extract_stack(limit=9)[:-1]]})

        sys.addaudithook(audit)
        try:
            if mode in ("old-real", "old-synthetic"):
                if mode == "old-real":
                    cuda, _, _ = numeric_imports()
                    diag = cuda.bridge.load_v18(contract.V18 / "tools/diagnose_batch_invariance.py")
                    diag._require_local_scratch_mount = lambda p: {"scope": "LOCAL_TEST_MOUNT_STUB"}
                    record["torch"] = str(cuda.torch.__version__)
                else:
                    diag = startup.checked_load(contract.V18 / "tools/diagnose_batch_invariance.py",
                                                startup.V18_SHA, "synthetic_old_startup_v18")
                    # Explicit simulation of an import creating its cache parents.
                    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
                record["role_exists_before_factory"] = root.exists()
                _, scope, _ = startup.adapter.build(diag)
                try:
                    with scope(args, worker_role):
                        record["collision_reproduced"] = False
                except FileExistsError as exc:
                    record.update(collision_reproduced=True, error_type=type(exc).__name__,
                                  filename=exc.filename)
                if mode == "old-synthetic":
                    startup.require(record["collision_reproduced"], "old synthetic ordering did not fail")
            else:
                with startup.open_scratch(contract, role) as boot:
                    record["caches_initially_empty"] = boot.scratch.record["caches_initially_empty"]
                    record["torch_absent_when_scratch_opened"] = "torch" not in sys.modules
                    cuda, archive_adapter, archive = numeric_imports()
                    record["torch"] = str(cuda.torch.__version__)
                    # The same cache-side-effect that fails old ordering is safe
                    # after the original factory exclusively owns live anchors.
                    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
                    boot.check()
                    if role == "reference":
                        record["mmap"] = mmap_lifetime(boot, args, archive_adapter, archive)
                    else:
                        diag = cuda.bridge.load_v18(contract.V18 / "tools/diagnose_batch_invariance.py")
                        private, scope, _ = startup.bind_scope(boot, diag, cuda.bridge)
                        with scope(args, worker_role) as scratch:
                            startup.require(type(scratch) is private and scratch.root == root, "binding differs")
                            startup.require(scratch.anchors is boot.scratch.anchors, "anchors differ")
                            scratch.check()
                        record["original_bridge_issuance_checked"] = True
                    record["new_startup_pass"] = True
                record["anchors_closed"] = all(not a.chain for a, *_ in boot.anchor_ids)
                startup.require(record["anchors_closed"], "original factory left anchors open")
        finally:
            active[0] = False
        record["mkdir_events"] = events
        record["home_preserved"] = os.environ.get("HOME") == original_home
        torch = sys.modules.get("torch")
        record["cuda_initialized"] = bool(torch and torch.cuda.is_initialized())
        startup.require(record["home_preserved"] and not record["cuda_initialized"], "CPU/HOME scope differs")
    fixture.process_runner.write_once(output, {**record, "status": "LOCAL_STARTUP_PROBE_PASS"})
    print(json.dumps({k: v for k, v in record.items() if k != "mkdir_events"}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("old-real", "old-synthetic", "new"))
    parser.add_argument("role", choices=("reference", "observed"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.mode, args.role, args.output))

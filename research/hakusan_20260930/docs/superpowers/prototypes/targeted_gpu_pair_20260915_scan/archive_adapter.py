"""Unreleased pass-archive insertion; no allocation, preparation or job entry.

Derive the exact pinned reference/observed loops with artifact-only calls.
Removing these calls and the extra argument restores the source AST exactly.
The original modules/functions are never replaced. CUDA execution unvalidated.
"""
import ast
import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
SOURCE = {
    "reference": (HERE.parent / "targeted_worker_20260915_scan/baseline_bridge.py",
                  "808995cb5118e1f4a6fd27b778cf65b903c886d5e52faba023e7faa4748f15f5"),
    "observed": (HERE.parent / "targeted_production_preparation_20260915_scan/cuda_registration.py",
                 "124d13aeb1754f5847024dc186487719400555f332c566d6bdefbdad30410f11"),
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def derive(role):
    require(role in SOURCE, "unsupported archive role")
    path, pin = SOURCE[role]
    raw = path.read_bytes()
    require(not path.is_symlink() and hashlib.sha256(raw).hexdigest() == pin, "pinned loop source differs")
    tree = ast.parse(raw)
    if role == "reference":
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BaselineBridge")
        original = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "run")
    else:
        original = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_observed_candidate")
    function = copy.deepcopy(original)
    function.name = "archived_" + role
    function.args.kwonlyargs.append(ast.arg(arg="_archiver"))
    function.args.kw_defaults.append(None)
    loops = [n for n in ast.walk(function) if isinstance(n, ast.For)
             and isinstance(n.target, ast.Tuple) and ast.unparse(n.target) == "(pass_id, size)"]
    require(len(loops) == 1 and ast.literal_eval(loops[0].iter) == (("pass1", 16), ("pass2", 1)), "original pass schedule differs")
    loop = loops[0]
    positions = [i for i, n in enumerate(loop.body) if isinstance(n, ast.Expr)
                 and ast.unparse(n) == "passes.append(result)"]
    require(len(positions) == 1, "original pass retention differs")
    # Reference already spills before this point. Observed needs the exact
    # original spill operation to keep both large feature captures mmap-backed.
    loop.body.insert(positions[0], ast.parse("_archiver.capture(result)").body[0])
    loop.body.insert(0, ast.parse("_archiver.before()").body[0])
    returns = [n for n in ast.walk(function) if isinstance(n, ast.Return)]
    require(len(returns) == 1, "original return coverage differs")
    added = 0
    for node in ast.walk(function):
        for _, value in ast.iter_fields(node):
            if isinstance(value, list) and returns[0] in value:
                value.insert(value.index(returns[0]), ast.parse("_archiver.after()").body[0])
                added += 1
    require(added == 1, "archive postcheck insertion differs")
    restored = copy.deepcopy(function)
    removed = []
    for node in ast.walk(restored):
        for _, value in ast.iter_fields(node):
            if isinstance(value, list):
                for item in list(value):
                    if isinstance(item, ast.Expr) and isinstance(item.value, ast.Call):
                        name = ast.unparse(item.value.func)
                        if name.startswith("_archiver."):
                            removed.append(name)
                            value.remove(item)
    restored.name = original.name
    restored.args.kwonlyargs.pop()
    restored.args.kw_defaults.pop()
    require(sorted(removed) == ["_archiver.after", "_archiver.before", "_archiver.capture"]
            and ast.dump(restored) == ast.dump(original), "artifact insertion changed parent logic")
    return ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), {
        "parent_sha256": pin, "artifact_calls_inserted": 3,
        "original_ast_restored_exactly": True, "runtime_execution_tested": False,
    }


class PassCollector:
    def __init__(self, gate, scratch, writer, *, spill):
        self.gate, self.scratch, self.writer, self.spill = gate, scratch, writer, spill
        self.count = 0

    def before(self):
        self.scratch.check()

    def capture(self, result):
        diag = self.gate.diag
        original = diag.encode_pass_evidence(result)
        if self.spill:
            self.scratch.spill(result)
        boundaries = {}
        for name in self.names[0]:
            record = result.boundary_records[name] if name in self.names[1] else result.boundary_records["derived"][name]
            boundaries[name] = diag._cpu_artifact_array(record["tensor"])
        self.writer.capture_pass(result.pass_id, result.batch_size, list(result.trial_ids),
                                 boundaries, dict(result.outputs), original)
        require(diag.encode_pass_evidence(result) == original, "artifact capture altered pass evidence")
        self.count += 1
        self.scratch.check()

    def after(self):
        require(self.count == 2, "both complete passes required")
        self.scratch.verify_spills()


def run_archived(gate, scratch, writer, *, lease=None):
    """Coordinator-only in-process candidate; no model loading or resource grant.

Returns the completed endpoint archive receipt. The observation capture store,
ledger, state/RNG documents and original worker provenance still need the
supervisor's separate durable inventory and execution checks.
"""
    sys.path.insert(0, str(HERE))
    import pass_archive
    path, pin = SOURCE["observed"]
    require(hashlib.sha256(path.read_bytes()).hexdigest() == pin, "CUDA adapter differs")
    # Reuse an already imported exact candidate; do not create second callback
    # class identities or replace an existing module under its registry name.
    module = sys.modules.get("cuda_registration")
    if module is None:
        spec = importlib.util.spec_from_file_location("cuda_registration", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    require(Path(module.__file__).resolve() == path.resolve(), "unexpected CUDA candidate module")
    module.source_check()
    bridge = module.bridge
    require(type(gate) is bridge.BaselineBridge and not gate.hermetic_test and gate.cell == "B2"
            and gate.attestation.frozen_capability.trust_domain == "production"
            and gate.context["device"].type == "cuda", "original production B2 CUDA gate required")
    require(type(scratch) is gate.diag._WorkerScratch and scratch.anchors
            and str(scratch.root) == gate.context["scratch_root"], "original coordinator scratch required")
    role = "reference" if lease is None else "observed"
    require(type(writer) is pass_archive.PassArchive and writer.binding["role"] == role
            and writer.binding["pid"] == os.getpid() and writer.binding["input_sha256"] == bridge.replay.FREEZE_SHA,
            "archive process/input binding differs")
    require(lease is None or type(lease) is module.CudaCompiledLease, "exact CUDA lease required")
    authority = gate.diag._ISSUED_COMPILER_LIFECYCLES.get(id(gate.model))
    require(type(authority) is gate.diag._CompilerLifecycle and not authority.entered, "cold original compiler required")
    authority.verify()
    if lease is None:
        require(all(not m._forward_hooks and not m._forward_pre_hooks for m in gate.model.modules()), "reference must have no observer hooks")
    # Collector stores names separately: never add attributes to the issued gate
    # or modify its original function/module dictionary.
    collector = PassCollector(gate, scratch, writer, spill=lease is not None)
    collector.names = (bridge.replay.BOUNDARIES, bridge.replay.COARSE)
    tree, audit = derive(role)
    namespace = dict(vars(bridge if lease is None else module))
    exec(compile(tree, str(HERE / ("<archived-" + role + ">")), "exec"), namespace)
    try:
        if lease is None:
            result = namespace["archived_reference"](gate, scratch=scratch, _archiver=collector)
        else:
            result = namespace["archived_observed"](gate, lease, _archiver=collector)
        if lease is None:
            authority.verify()
        else:
            require(lease.closed and authority is lease.compiler and authority.revoked,
                    "observed candidate did not close its original compiler")
        require(bool(authority.entered), "compiler never entered")
        receipt = writer.finish()
        return {"archive": receipt, "loop": audit, "parent_gate_result": result,
                "execution_authority_verified": False, "ready_for_gpu": False}
    finally:
        if lease is not None:
            lease.close()
        gate.diag._revoke_attestation(gate.attestation)
        authority.revoked = True

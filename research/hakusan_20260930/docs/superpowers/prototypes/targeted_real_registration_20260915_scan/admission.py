"""Real-checkpoint CPU registration candidate, NO forward or worker issuance.

The production CUDA preparation function is neither invoked nor modified.
This closes the gap between the former empty StreamObserver binding probe and
the actual CompiledLease callbacks verified in synthetic Job703415. It does not
open a production/GPU inference path or accept a caller-supplied loaded model.
"""
import hashlib
import json
from pathlib import Path
import sys

import torch

HERE = Path(__file__).resolve().parent
COMPILED = HERE.parent / "targeted_compiled_20260915_scan/compiled_registration.py"
COMPILED_SHA = "0910fa29d204566130bf906784a09e999e4419fe7d69dfa63d2c35ef903b3e7f"
if hashlib.sha256(COMPILED.read_bytes()).hexdigest() != COMPILED_SHA:
    raise RuntimeError("compiled observer source differs")
sys.path.insert(0, str(COMPILED.parent))
import compiled_registration as compiled  # noqa: E402

if Path(compiled.__file__).resolve() != COMPILED.resolve():
    raise RuntimeError("unexpected compiled adapter import")
bridge, life, stream = compiled.bridge, compiled.life, compiled.stream
BINDING_PATH = HERE.parent / "targeted_binding_20260911/probe_cpu.py"
BINDING_SHA = "1e7e0e0a2668eda482026ea3002c9c249ffc8cc0f84bdb23940b800ce00e5d6f"
prior = bridge._load(BINDING_PATH, BINDING_SHA, "real_registration_prior_binding")
PLAN_PATH = HERE.parent / "targeted_trace_20260911/FORMAL40_PLAN_CANDIDATE.json"
FORMAL_SHA = "2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff"


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def source_check():
    compiled.source_check()
    require(hashlib.sha256(BINDING_PATH.read_bytes()).hexdigest() == BINDING_SHA,
            "prior binding source changed")


def plan_documents(plan_raw, freeze_raw, cell):
    """Bind the exact existing 32 trials and 42 positions, not a new selection."""
    require(cell in ("A2", "B2"), "unknown diagnostic cell")
    require(hashlib.sha256(plan_raw).hexdigest() == prior.PLAN_SHA, "plan bytes changed")
    require(hashlib.sha256(freeze_raw).hexdigest() == prior.FREEZE_SHA, "freeze bytes changed")
    plan, freeze = json.loads(plan_raw), json.loads(freeze_raw)
    ids = prior.validate_plan(plan, freeze)
    return stream.base.Plan(ids, tuple(t["trial"]["trial_id"] for t in plan["targets"][cell]),
                            tuple(stream.base.Stage(s["module"], s["branch"])
                                  for s in plan["post_hook_stages"]))


def require_real_context(diag, context):
    """Original loader-issued identities are required; no hermetic opt-in."""
    bridge._require_module(diag)
    require(type(context) is dict, "native frozen context required")
    cap = context.get("_frozen_context_capability")
    require(type(cap) is diag._FrozenContextCapability
            and cap.trust_domain == "production"
            and diag._ISSUED_FROZEN_CONTEXT_CAPABILITIES.get(id(cap)) is cap,
            "original production frozen capability required")
    require(cap.evaluator is context.get("evaluator") and cap.manifest is context.get("manifest"),
            "frozen loader objects differ")
    diag._validate_frozen_capability_contents(cap)
    require(len(cap.pinned_records) == 24 and cap.source_records
            and cap.evaluator_record["sha256"] == diag.V4_EVALUATOR_SHA256
            and cap.manifest_record["sha256"] == diag.V4_MANIFEST_SHA256
            and context["manifest"]["models"]["formal40"]["sha256"] == FORMAL_SHA,
            "frozen source/checkpoint contract differs")
    require(not diag._ISSUED_FORMAL40_ATTESTATIONS and not diag._ISSUED_COMPILER_LIFECYCLES
            and life._ACTIVE.get() is None, "fresh unissued registration process required")
    return cap


def expected_stage_types(cnn_module, custom_module):
    result = {"model_dict.norm_coch_rep": torch.nn.LayerNorm,
              "model_dict.attnfc": cnn_module.SimpleAttentionalGain,
              "fullyconnected": torch.nn.Linear, "relufc": torch.nn.ReLU,
              "dropout": torch.nn.Dropout, "classification": torch.nn.Linear}
    for index in range(7):
        result.update({f"model_dict.attn{index}": cnn_module.SimpleAttentionalGain,
                       f"model_dict.conv_block_{index}": torch.nn.Sequential,
                       f"model_dict.hann_pool_{index}": custom_module.HannPooling2d})
    return result


def install_empty(diag, model, plan, store, *, outer_type, cnn_type, stage_types):
    """Low-level registration only, NOT provenance or permission to infer.

Portable tests call this on synthetic topology. The real entry below owns its
strict load and derives every type from the original verified snapshot loader.
The unchanged lease rejects any invocation without its original worker scope.
"""
    source_check()
    require(type(plan) is stream.base.Plan and len(plan.stages) == 42
            and len(plan.schedule()) == 34, "42-position/34-batch plan required")
    binding = stream.bind_compiled_outer(model, plan, expected_outer_type=outer_type,
                                         expected_cnn_type=cnn_type)
    require(len(binding.modules) == 27 and set(stage_types) == {s.module for s in plan.stages},
            "exact 27-module type inventory required")
    for path, module in binding.modules:
        require(type(module) is stage_types[path.removeprefix("model._orig_mod.")],
                "stage class differs: " + path)
    lease = compiled.CompiledLease(diag, binding, store)
    try:
        lease.install_before_issuance()
        require(len(lease.handles) == 29 and not lease.records and not store.refs
                and store.used_bytes == 0, "empty 27-stage plus outer pre/post registration required")
        return lease
    except BaseException:
        lease.close()
        raise


def snapshot(diag, model):
    return compiled.prep.wire({"state": diag._snapshot_model_entries(model),
                               "rng": diag._get_trace().snapshot_rng_state(),
                               "runtime": diag._read_frozen_numeric_runtime(torch)})


def verified_classes(diag, context, records):
    authority = diag._ACTIVE_SNAPSHOT_AUTHORITY.get()
    require(authority is not None, "original snapshot loader scope required")
    modules = []
    for name in ("src.spatial_attn_lightning", "src.spatial_attn_architecture", "src.custom_modules"):
        module = sys.modules[name]
        path = Path(module.__file__)
        relative = path.relative_to(context["snapshot_files"]).as_posix()
        prior.pinned(path, records[relative]["sha256"])
        require(any(item[0] is module for item in authority.issued_modules[name]),
                "model class module was not issued by frozen loader")
        modules.append(module)
    authority.verify_runtime_bindings()
    return modules


def run_real_cpu(diag, context, cell, scratch):
    """Load formal40 ONCE, install the actual callbacks, seal cold, remove.

Returns only data. No prepared model or executable capability leaves this
function. No original prepare_formal40_worker/forward/trace_predict_batch call.
Requires a separate, bounded remote CPU execution to be considered validated.
"""
    source_check()
    cap = require_real_context(diag, context)
    require(str(torch.__version__) == "2.1.1+cu118" and sys.version.split()[0] == "3.11.5",
            "actual reviewed Python/torch required")
    require(not torch.cuda.is_initialized() and not torch.cuda.is_available(), "CPU-only process required")
    plan = plan_documents(prior.pinned(PLAN_PATH, prior.PLAN_SHA),
                          prior.pinned(prior.V18 / "input_freeze.json", prior.FREEZE_SHA), cell)
    archived = json.loads(prior.pinned(prior.V18 / "attempts/slurm-685198/cells/A2/STATE_BEFORE.jsonl",
                                       prior.STATE_SHA))
    require(archived["observation"] == "pass1_before", "parent state phase differs")
    records = {r["relative_path"]: r for r in cap.source_records}
    with diag.frozen_scene_context(context["snapshot_files"], records):
        device = context["evaluator"]._configure_runtime(True)
        require(device.type == "cpu", "CPU configuration required")
        model, report = context["evaluator"].strict_load_model(context["manifest"], "formal40", device=device)
        diag._require_load_report(report)
        restored = diag._restore_missing_snapshot_modules_before_seal(diag._ACTIVE_SNAPSHOT_AUTHORITY.get())
        diag._validate_frozen_capability_contents(cap)
        outer, cnn, custom = verified_classes(diag, context, records)
        inventory = diag._direct_model_module_inventory(model)
        diag._require_registered_modules_eval(model)
        diag._require_frozen_direct_parameters(inventory)
        before_state = diag._snapshot_model_entries(model)
        require(len(before_state) == 60
                and prior.comparable_state(before_state) == prior.comparable_state(archived["value"]),
                "strict loaded state differs from parent A2 pre-forward evidence")
        before = snapshot(diag, model)
        lease = None
        with life.capture.CaptureStore(Path(scratch) / "real-registration-empty", total_bytes=1) as store:
            try:
                lease = install_empty(diag, model, plan, store, outer_type=outer.BinauralAttentionModule,
                                      cnn_type=cnn.BinauralAuditoryAttentionCNN,
                                      stage_types=expected_stage_types(cnn, custom))
                lease.seal_compiler()
                authority = diag._ACTIVE_SNAPSHOT_AUTHORITY.get()
                authority.seal_runtime_bindings()
                lease.check()
                require(snapshot(diag, model) == before and not lease.compiler.entered,
                        "registration changed state/RNG/runtime or entered compiler")
                require(not diag._ISSUED_FORMAL40_ATTESTATIONS and not lease.records and store.used_bytes == 0,
                        "CPU registration must not issue a worker, forward, or capture")
                authority.verify_runtime_bindings()
            finally:
                if lease is not None:
                    lease.close()
            require(not any(m._forward_hooks or m._forward_pre_hooks for m in model.modules()),
                    "registration hooks remain")
            require(lease.compiler.revoked and snapshot(diag, model) == before,
                    "cold compiler not revoked or cleanup changed state")
            require(not store.refs and store.used_bytes == 0 and not list(store.root.iterdir()),
                    "registration unexpectedly wrote tensor files")
        diag._validate_model_module_inventory(model, inventory)
        diag._ACTIVE_SNAPSHOT_AUTHORITY.get().verify_runtime_bindings()
        diag._validate_frozen_capability_contents(cap)
        require(not torch.cuda.is_initialized(), "CUDA initialized")
        summary = {"status": "REAL_COMPILED_CALLBACK_REGISTRATION_CPU_PASS", "cell": cell,
                   "parent_job_id": "685198", "strict_load_calls": 1, "strict_load_report": report,
                   "checkpoint_sha256": FORMAL_SHA, "plan_sha256": prior.PLAN_SHA,
                   "freeze_sha256": prior.FREEZE_SHA, "stages": 42, "unique_stage_modules": 27,
                   "installed_hooks": 29, "callbacks": "unchanged_CompiledLease",
                   "compiled_adapter_sha256": COMPILED_SHA, "registered_state_entries": 60,
                   "parent_state_bytes_equal": True, "state_rng_runtime_unchanged": True,
                   "compiler_authority_issued": True, "compiler_backend_entered": False,
                   "compiler_authority_revoked": True, "hooks_removed": True,
                   "source_objects_restored": list(restored), "source_reexecuted_for_restoration": False,
                   "production_model_loaded": True, "production_worker_issued": False,
                   "production_preparation_validated": False, "forward_calls": 0, "captures": 0,
                   "cuda_initialized": False, "ready_for_gpu": False, "jobs_submitted_by_probe": 0}
    after_sources = diag.collect_snapshot_records(context["source_manifest"], (),
                                                  snapshot_files=context["snapshot_files"])
    require([(r["relative_path"], r["size"], r["sha256"]) for r in after_sources]
            == [(r["relative_path"], r["size"], r["sha256"]) for r in cap.source_records], "snapshot changed")
    diag._verify_v4_pinned_records(diag._get_trace(), context["manifest"], context["contract"])
    source_check()
    bridge._require_module(diag)
    return summary

"""Compiled-wrapper registration candidate: hermetic CPU probe ONLY.

Uses the unchanged v18 compiler authority, not a replacement for it. A separate
lease admits exactly one OptimizedModule. No production/CUDA worker is enabled.
The previous eager-only prototypes and all their rejection paths are unchanged.
"""
import ast
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import sys
import types

import torch

HERE = Path(__file__).resolve().parent
PREP_SHA = "70ed9822b37b524bd19e2d8d316d8b53cdfb735168e0f2163723ea17de735382"
PREP_PATH = HERE.parent / "targeted_preparation_20260912/prepare_registration.py"
if hashlib.sha256(PREP_PATH.read_bytes()).hexdigest() != PREP_SHA:
    raise RuntimeError("pinned preparation candidate differs")
sys.path.insert(0, str(PREP_PATH.parent))
import prepare_registration as prep  # noqa: E402
if Path(prep.__file__).resolve() != PREP_PATH.resolve():
    raise RuntimeError("unexpected preparation module")
life, bridge = prep.life, prep.bridge
STREAM_PATH = HERE.parent / "targeted_stream_20260911/stream_observer.py"
STREAM_SHA = "d939436a0cc84c84c9e56a9c927719df677008405d1545acd537bb8f9bc79474"
stream = bridge._load(STREAM_PATH, STREAM_SHA, "compiled_registration_binding")
SELF_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
POLICY = "COMPILED_REGISTRATION_CPU_CANDIDATE_20260912"


def require(ok, message):
    if not ok:
        raise prep.PreparationError(message)


def source_check():
    prep.source_check()
    require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == SELF_SHA,
            "compiled adapter source changed")
    require(hashlib.sha256(STREAM_PATH.read_bytes()).hexdigest() == STREAM_SHA,
            "compiled binding source changed")
    for owner, name, function, code, wrapped, wrapped_code in CODE:
        require(vars(owner).get(name) is function and function.__code__ is code,
                "compiled adapter callable changed: " + name)
        require(getattr(function, "__wrapped__", None) is wrapped,
                "compiled adapter wrapped callable changed: " + name)
        if wrapped is not None:
            require(wrapped.__code__ is wrapped_code, "compiled observer body changed")


class CompiledLease(life.ObservationLease):
    """Explicit extension; inherited accounting/state/RNG/runtime gates retained."""
    def __init__(self, diag, binding, store):
        source_check()
        bridge._require_module(diag)
        require(type(binding) is stream.WrapperBinding, "exact wrapper binding required")
        binding.check()
        model, plan = binding.outer, binding.plan
        require(type(plan) is life.base.Plan and len(plan.trials) == 32
                and plan.batch_sizes == (16, 1), "exact 32-trial 16-to-1 plan required")
        require(type(store) is life.capture.CaptureStore and not store.refs, "fresh capture store required")
        require(sum(type(m) is torch._dynamo.eval_frame.OptimizedModule for m in model.modules()) == 1,
                "exactly one compiled wrapper required")
        require(all(t.device.type == "cpu" for t in model.state_dict().values()), "CPU probe only")
        # Same recorder initialization/configuration tuple as the pinned base,
        # with compiled binding/lifecycle added and independently checked.
        self.diag, self.model, self.plan, self.store = diag, model, plan, store
        self.schedule = plan.schedule()
        self.modules = tuple(model.named_modules())
        self.handles, self.records = [], []
        self.hooks = None
        self.record_seal = life._wire(self.records)
        self.current = self.context = self.pass_id = None
        self.failed = self.used = self.closed = False
        self.pid = os.getpid()
        self.config = (id(diag), id(model), life._wire(asdict(plan)), id(store), store.root, store.fd,
                       store.store_id, store.chunk_bytes, store.total_bytes, store.tensor_bytes,
                       store.max_records, self.modules, self.schedule)
        self.binding = binding
        self.binding_receipt = (binding, binding.outer, binding.wrapper, binding.cnn, binding.plan, binding.modules)
        self.compiler = None
        self.compiler_receipt = None

    def check(self):
        source_check()
        require(type(self) is CompiledLease, "exact compiled lease required")
        require(not any(n in vars(self) for n, v in vars(CompiledLease).items()
                        if type(v) is types.FunctionType), "compiled lease instance method replaced")
        super().check()
        live = (self.binding, self.binding.outer, self.binding.wrapper, self.binding.cnn,
                self.binding.plan, self.binding.modules)
        require(all(a is b for a, b in zip(live, self.binding_receipt)),
                "compiled binding receipt changed")
        self.binding.check()
        if self.compiler is not None:
            require(self.compiler is self.compiler_receipt, "compiler authority replaced")
            self.compiler.verify()

    def seal_compiler(self):
        self.check()
        require(self.compiler is None, "compiler issuance is single use")
        inventory = self.diag._direct_model_module_inventory(self.model)
        previous = self.diag._ISSUED_COMPILER_LIFECYCLES.get(id(self.model))
        try:
            self.compiler = self.diag._issue_compiler_lifecycle(self.model, inventory)
        except BaseException:
            issued = self.diag._ISSUED_COMPILER_LIFECYCLES.get(id(self.model))
            if issued is not None and issued is not previous:
                issued.revoked = True
            raise
        self.compiler_receipt = self.compiler
        require(self.compiler is not None and not self.compiler.entered, "cold compiler authority required")
        self.check()

    @torch._dynamo.disable
    def stage(self, path, module, output):
        # The mutable recorder is explicitly eager. This may split compiled
        # graphs: later endpoint/cold-pair validation remains mandatory.
        return super().stage(path, module, output)

    def close(self):
        if self.compiler is not None:
            self.compiler.revoked = True
        super().close()


class CompiledRequest(prep.RegistrationRequest):
    """Only exact hermetic CPU requests; type arguments confer no provenance."""
    def __init__(self, diag, context, relative_plan, store, outer_type, cnn_type):
        super().__init__(diag, context, relative_plan, store, hermetic_test=True)
        self.outer_type, self.cnn_type = outer_type, cnn_type
        self.type_receipt = (outer_type, cnn_type)

    def check(self):
        super().check()
        source_check()
        require(type(self) is CompiledRequest and self.outer_type is self.type_receipt[0]
                and self.cnn_type is self.type_receipt[1], "compiled request type binding changed")
        require(not any(n in vars(self) for n, v in vars(CompiledRequest).items()
                        if type(v) is types.FunctionType), "compiled request instance method replaced")

    def install(self, model, report, device):
        self.check()
        capability = self.context.get("_frozen_context_capability")
        require(self.used and self.install_count == 0 and self.lease is None, "registration already installed")
        require(self.hermetic_test and capability.trust_domain == "hermetic-test"
                and device.type == "cpu", "only hermetic CPU compiled registration is admitted")
        require(type(report) is dict, "native strict-load report required")
        self.model = model
        self.before = self.snapshot()
        binding = stream.bind_compiled_outer(model, self.plan, expected_outer_type=self.outer_type,
                                             expected_cnn_type=self.cnn_type)
        self.lease = CompiledLease(self.diag, binding, self.store)
        self.lease.install_before_issuance()
        self.lease.seal_compiler()
        self.install_count += 1
        require(self.snapshot() == self.before, "registration changed state/RNG/runtime")

    def before_issue(self, model):
        super().before_issue(model)
        require(not self.lease.compiler.entered, "compiled forward occurred before issuance")

    def finish(self, prepared, audit):
        value = super().finish(prepared, audit)
        value.update({"candidate": POLICY, "compiled_wrapper_bound": True,
                      "original_compiler_authority_issued": True, "compiler_backend_entered": False,
                      "observed_plan_sha256": hashlib.sha256(prep.wire(asdict(self.lease.plan))).hexdigest(),
                      "source_sha256": {**value["source_sha256"], "compiled_adapter": SELF_SHA,
                                        "wrapper_binding": STREAM_SHA},
                      "compiled_guard_probe_completed": False})
        self.receipt = prep.wire(value)
        return value


def prepare_compiled(request):
    """Reuse the audited two-call AST insertion; never replace original helpers."""
    require(type(request) is CompiledRequest, "exact compiled request required")
    try:
        request.check()
        require(not request.used, "compiled preparation is single use")
        capability = request.context.get("_frozen_context_capability")
        require(capability is not None and capability.trust_domain == "hermetic-test",
                "production compiled preparation is not released")
        require(str(torch.__version__) == "2.1.1+cu118",
                "unchanged original compiler authority requires torch 2.1.1+cu118")
        require(not torch.cuda.is_initialized(), "CPU probe cannot reuse CUDA process")
        request.used = True
        diag = request.diag
        request.issued_before = frozenset(diag._ISSUED_FORMAL40_ATTESTATIONS)
        raw = Path(diag.__file__).read_bytes()
        tree = prep.build_candidate(raw)
        audit = prep.verify_delta(raw, tree.body[0])
        namespace = dict(vars(diag))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
                 and isinstance(n.ctx, ast.Load) and n.id in vars(diag)}
        bindings = {name: namespace[name] for name in names}
        exec(compile(tree, str(HERE / "<compiled-preparation>"), "exec"), namespace)
        require(prep.CANDIDATE_NAME not in vars(diag), "original namespace changed")
        prepared = namespace[prep.CANDIDATE_NAME](request.context, allow_cpu=True, _registration=request)
        require(all(vars(diag)[n] is v for n, v in bindings.items()), "original helper binding changed")
        bridge._require_module(diag)
        receipt = request.finish(prepared, audit)
        return prepared, request.lease, receipt
    except BaseException:
        request.failed = True
        request.close()
        raise


def first_batch_probe(request, prepared, raw_scene, raw_cue, labels, probes):
    """ONE cold compiled forward through original prediction guards, not a pass.

    Synthetic input only. Successful output does NOT validate the 34-batch
    lifetime, parent replay, interference, A100, Inductor, or scientific scores.
    """
    lease, diag = request.lease, request.diag
    require(type(request) is CompiledRequest and type(lease) is CompiledLease,
            "exact compiled registration required")
    try:
        request.check()
        require(prepared is request.prepared and not lease.used and life._ACTIVE.get() is None,
                "probe preparation differs, reused, or nested")
        lease.used, lease.pass_id = True, "pass1"
        attestation = prepared["_formal40_worker_attestation"]
        token = life._ACTIVE.set(lease)
        try:
            with diag._prediction_evaluator_context(prepared["evaluator"], model=prepared["model"],
                                                    attestation=attestation):
                diag._validate_issued_model_state(attestation)
                result = diag.trace_predict_batch(prepared["model"], raw_scene, raw_cue, labels, probes,
                                                  prepared["device"], autocast_enabled=False,
                                                  trial_ids=lease.plan.trials[:16])
                lease.check()
                require(len(lease.records) == 1 and lease.current is None, "one completed batch required")
                require(bool(lease.compiler.entered), "compiler backend never entered")
                diag._validate_issued_model_state(attestation)
                diag._live_inference_attestation(prepared["model"], "compiled_probe_complete")
                for ref in lease.store.refs:
                    require(lease.store.compare(ref, ref), "captured bytes reread differs")
                expected = life.descriptor(result.native_logits)
                require(lease.records[0]["logits"] == expected, "original/observer logits differ")
                return {"status": "HERMETIC_COMPILED_FIRST_BATCH_PASS", "batches": 1,
                        "stage_invocations": len(lease.plan.stages), "capture_records": len(lease.store.refs),
                        "original_guards_enabled": True, "original_compiler_authority": True,
                        "compiler_backend_entered": True, "production_model_loaded": False,
                        "complete_passes": 0, "cold_pair_interference_verified": False,
                        "ready_for_gpu": False, "jobs_submitted": 0}
        finally:
            life._ACTIVE.reset(token)
    except BaseException:
        request.failed = lease.failed = True
        raise
    finally:
        request.close()


CODE = tuple((owner, name, value, value.__code__, getattr(value, "__wrapped__", None),
              getattr(getattr(value, "__wrapped__", None), "__code__", None))
             for owner in (sys.modules[__name__], CompiledLease, CompiledRequest, stream, stream.WrapperBinding)
             for name, value in vars(owner).items() if type(value) is types.FunctionType)

"""Unreleased CUDA preparation adapter; no runner, submission or result claim.

Old v18 and CPU adapters are byte-identical. The original production function
is derived only by its reviewed two-call insertion. It retains the CUDA gate
and issues its compiler authority exactly once; this adapter adopts that
existing authority just before worker issuance. No inference runs on prepare.
Actual CUDA/Inductor preparation and cold-pair interference remain unvalidated.
"""
import ast
import copy
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import sys
import types

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
ADMISSION_PATH = HERE.parent / "targeted_real_registration_20260915_scan/admission.py"
ADMISSION_SHA = "20484839cab04c2eea0b84d1d2a246e11cf4e982c571a00285fdaef5d2ff0757"
if hashlib.sha256(ADMISSION_PATH.read_bytes()).hexdigest() != ADMISSION_SHA:
    raise RuntimeError("reviewed real registration source differs")
sys.path.insert(0, str(ADMISSION_PATH.parent))
import admission  # noqa: E402

if Path(admission.__file__).resolve() != ADMISSION_PATH.resolve():
    raise RuntimeError("unexpected admission module")
compiled = admission.compiled
prep, life, stream, bridge = compiled.prep, compiled.life, compiled.stream, compiled.bridge
SELF_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
MAX_ENDPOINT = 128 * 1024**2
CHUNK = 1024**2


def require(ok, message):
    if not ok:
        raise prep.PreparationError(message)


def source_check():
    admission.source_check()
    require(hashlib.sha256(ADMISSION_PATH.read_bytes()).hexdigest() == ADMISSION_SHA
            and hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == SELF_SHA,
            "production candidate source changed")
    for owner, name, function, code, wrapped, wrapped_code in CODE:
        require(vars(owner).get(name) is function and function.__code__ is code
                and getattr(function, "__wrapped__", None) is wrapped,
                "production candidate callable changed: " + name)
        if wrapped is not None:
            require(wrapped.__code__ is wrapped_code, "wrapped callback changed")
    for name in ("pre", "post"):
        namespace = getattr(CudaCompiledLease, name).__globals__
        require(namespace.get("endpoint_descriptor") is endpoint_descriptor
                and all(namespace.get(n) is vars(life)[n] for n in ("require", "_wire", "torch")),
                "endpoint adapter global changed")


def endpoint_descriptor(tensor):
    """Same C-order endpoint digest, using bounded existing transfer chunks.

CPU support is for portable encoding tests, not permission for a CPU worker.
No rescaling, dtype cast, tolerance, RNG reset or compiler configuration change.
"""
    source_check()
    require(type(tensor) is torch.Tensor and tensor.layout == torch.strided
            and tensor.dtype in (torch.float16, torch.float32, torch.float64),
            "unsupported native endpoint")
    size = tensor.numel() * tensor.element_size()
    require(0 < size <= MAX_ENDPOINT, "endpoint byte budget exceeded")
    digest, written = hashlib.sha256(), 0
    chunks = iter(life.capture.tensor_chunks(tensor, CHUNK))
    while True:
        payload = next(chunks, None)
        if payload is None:
            break
        digest.update(payload)
        written += len(payload)
        del payload
    require(written == size, "endpoint byte count differs")
    dtype = {torch.float16: "float16", torch.float32: "float32", torch.float64: "float64"}[tensor.dtype]
    return {"dtype": np.dtype(dtype).str, "shape": list(tensor.shape),
            "nbytes": size, "sha256": digest.hexdigest()}


def endpoint_method(name):
    """Only replace descriptor lookup in exact pinned pre/post method ASTs."""
    require(name in ("pre", "post"), "unsupported endpoint method")
    raw = prep.LIFE_PATH.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == prep.LIFE_SHA, "endpoint parent differs")
    cls = next(n for n in ast.parse(raw).body if isinstance(n, ast.ClassDef) and n.name == "ObservationLease")
    original = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    changed = copy.deepcopy(original)
    count = 0
    for node in ast.walk(changed):
        if isinstance(node, ast.Name) and node.id == "descriptor":
            node.id = "endpoint_descriptor"
            count += 1
    require(count == (2 if name == "pre" else 3), "endpoint insertion count differs")
    restored = copy.deepcopy(changed)
    for node in ast.walk(restored):
        if isinstance(node, ast.Name) and node.id == "endpoint_descriptor":
            node.id = "descriptor"
    require(ast.dump(restored) == ast.dump(original), "endpoint parent logic changed")
    namespace = dict(vars(life))
    namespace["endpoint_descriptor"] = endpoint_descriptor
    exec(compile(ast.fix_missing_locations(ast.Module(body=[changed], type_ignores=[])),
                 str(HERE / "<cuda-endpoint-adapter>"), "exec"), namespace)
    return namespace[name]


class CudaCompiledLease(life.ObservationLease):
    """Separate CUDA-only candidate; pinned CPU CompiledLease is not relaxed."""
    def __init__(self, diag, binding, store):
        source_check()
        bridge._require_module(diag)
        require(type(binding) is stream.WrapperBinding, "exact wrapper binding required")
        binding.check()
        model, plan = binding.outer, binding.plan
        require(type(plan) is life.base.Plan and len(plan.trials) == 32
                and plan.batch_sizes == (16, 1) and len(plan.stages) == 42
                and len(binding.modules) == 27, "exact real 42-position plan required")
        require(type(store) is life.capture.CaptureStore and not store.refs, "fresh capture store required")
        require(sum(type(m) is torch._dynamo.eval_frame.OptimizedModule for m in model.modules()) == 1,
                "exactly one compiled wrapper required")
        states = tuple(model.state_dict().values())
        require(states and all(t.device.type == "cuda" for t in states)
                and len({t.device for t in states}) == 1, "single CUDA device model required")
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
        self.compiler = self.compiler_receipt = None

    def check(self):
        source_check()
        require(type(self) is CudaCompiledLease, "exact CUDA lease required")
        require(not any(n in vars(self) for n, v in vars(CudaCompiledLease).items()
                        if type(v) is types.FunctionType), "CUDA lease instance method replaced")
        super().check()
        now = (self.binding, self.binding.outer, self.binding.wrapper, self.binding.cnn,
               self.binding.plan, self.binding.modules)
        require(all(a is b for a, b in zip(now, self.binding_receipt)), "CUDA wrapper binding changed")
        self.binding.check()
        if self.compiler is not None:
            require(self.compiler is self.compiler_receipt, "original compiler replaced")
            self.compiler.verify()

    def adopt_original_compiler(self):
        self.check()
        require(self.compiler is None, "compiler adoption is single use")
        authority = self.diag._ISSUED_COMPILER_LIFECYCLES.get(id(self.model))
        require(type(authority) is self.diag._CompilerLifecycle and authority.model is self.model,
                "original preparation did not issue compiler authority")
        authority.verify()
        require(not authority.entered, "compiler entered before preparation finished")
        self.compiler = self.compiler_receipt = authority
        self.check()

    pre = endpoint_method("pre")
    post = endpoint_method("post")

    @torch._dynamo.disable
    def stage(self, path, module, output):
        # CaptureStore already transfers CUDA tensors in bounded CPU chunks.
        return super().stage(path, module, output)

    def close(self):
        if self.compiler is not None:
            self.compiler.revoked = True
        super().close()


class ProductionRequest(prep.RegistrationRequest):
    """No model/type injection or hermetic switch in this public candidate."""
    def __init__(self, diag, context, store, cell, plan_raw, freeze_raw):
        source_check()
        admission.require_real_context(diag, context)
        plan = admission.plan_documents(plan_raw, freeze_raw, cell)
        require(context.get("cell_id") == cell, "context cell differs")
        super().__init__(diag, context, plan, store, hermetic_test=False)
        self.cell = cell
        self.compilers_before = None
        self.production_config = (cell, hashlib.sha256(plan_raw).hexdigest(), hashlib.sha256(freeze_raw).hexdigest())

    def check(self):
        super().check()
        source_check()
        require(type(self) is ProductionRequest and not self.hermetic_test
                and self.cell == self.production_config[0] == self.context.get("cell_id"),
                "production registration policy changed")
        require(not any(n in vars(self) for n, v in vars(ProductionRequest).items()
                        if type(v) is types.FunctionType), "production instance method replaced")
        cap = self.context.get("_frozen_context_capability")
        require(type(cap) is self.diag._FrozenContextCapability and cap.trust_domain == "production"
                and self.diag._ISSUED_FROZEN_CONTEXT_CAPABILITIES.get(id(cap)) is cap
                and cap.evaluator is self.context.get("evaluator") and cap.manifest is self.context.get("manifest"),
                "original production context changed")
        self.diag._validate_frozen_capability_contents(cap)

    def install(self, model, report, device):
        self.check()
        require(self.used and self.install_count == 0 and self.lease is None
                and device.type == "cuda", "production install order/device differs")
        self.model = model
        self.diag._require_load_report(report)
        cap = self.context["_frozen_context_capability"]
        records = {r["relative_path"]: r for r in cap.source_records}
        outer, cnn, custom = admission.verified_classes(self.diag, self.context, records)
        binding = stream.bind_compiled_outer(model, self.plan, expected_outer_type=outer.BinauralAttentionModule,
                                             expected_cnn_type=cnn.BinauralAuditoryAttentionCNN)
        expected = admission.expected_stage_types(cnn, custom)
        require(len(binding.modules) == 27 and all(type(m) is expected[p.removeprefix("model._orig_mod.")]
                for p, m in binding.modules), "real module types differ")
        require(id(model) not in self.diag._ISSUED_COMPILER_LIFECYCLES, "compiler already issued before install")
        self.before = self.snapshot()
        self.lease = CudaCompiledLease(self.diag, binding, self.store)
        self.lease.install_before_issuance()
        require(len(self.lease.handles) == 29, "29 exact callbacks required")
        self.install_count += 1
        require(self.snapshot() == self.before, "registration changed state/RNG/runtime")

    def before_issue(self, model):
        # Parent function has now issued the compiler, but not the worker.
        super().before_issue(model)
        self.lease.adopt_original_compiler()

    def finish(self, prepared, audit):
        value = super().finish(prepared, audit)
        value.update({"candidate": "PRODUCTION_PREPARATION_CUDA_CANDIDATE_20260913",
                      "compiler_issued_by_original_preparation": True, "compiler_reissued_by_adapter": False,
                      "compiler_backend_entered": False, "registration_only": True,
                      "stages": 42, "unique_stage_modules": 27, "installed_hooks": 29,
                      "cuda_cold_pair_validated": False,
                      "source_sha256": {**value["source_sha256"], "production_adapter": SELF_SHA,
                                        "real_registration": ADMISSION_SHA}})
        require(self.lease.compiler is not None and not self.lease.compiler.entered, "cold preparation required")
        self.receipt = prep.wire(value)
        return value

    def close(self):
        # A failure can happen AFTER original compiler issuance but BEFORE
        # before_issue/adoption. Revoke only this newly loaded model's identity.
        if self.model is not None and self.compilers_before is not None:
            authority = self.diag._ISSUED_COMPILER_LIFECYCLES.get(id(self.model))
            if authority is not None and authority.model is self.model and id(authority) not in self.compilers_before:
                authority.revoked = True
        super().close()


def prepare_production(request):
    """Candidate preparation only, with original allow_cpu=False unconditionally.

Returns prepared model/lease to a future controlled runner. No forward, Slurm,
automatic submission, tolerance adjustment or production success marker.
"""
    require(type(request) is ProductionRequest, "exact production request required")
    try:
        request.check()
        require(not request.used, "production preparation is single use")
        require(str(torch.__version__) == "2.1.1+cu118", "actual reviewed torch 2.1.1+cu118 required")
        require(torch.cuda.is_available(), "actual CUDA runtime required")
        request.used = True
        diag = request.diag
        request.issued_before = frozenset(diag._ISSUED_FORMAL40_ATTESTATIONS)
        request.compilers_before = frozenset(id(a) for a in diag._ISSUED_COMPILER_LIFECYCLES.values())
        raw = Path(diag.__file__).read_bytes()
        tree = prep.build_candidate(raw)
        audit = prep.verify_delta(raw, tree.body[0])
        namespace = dict(vars(diag))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
                 and isinstance(n.ctx, ast.Load) and n.id in vars(diag)}
        bindings = {n: namespace[n] for n in names}
        exec(compile(tree, str(HERE / "<production-preparation>"), "exec"), namespace)
        require(prep.CANDIDATE_NAME not in vars(diag), "original namespace changed")
        prepared = namespace[prep.CANDIDATE_NAME](request.context, allow_cpu=False, _registration=request)
        require(all(vars(diag)[n] is value for n, value in bindings.items()), "original helper binding changed")
        bridge._require_module(diag)
        receipt = request.finish(prepared, audit)
        return prepared, request.lease, receipt
    except BaseException:
        request.failed = True
        request.close()
        raise


def run_observed_candidate(gate, lease):
    """Two unchanged v18 passes with original guards and parent-result replay.

In-process candidate, NOT a Slurm/GPU launcher or a cold-reference verifier.
Never marks scientific completion. Requires coordinator-owned real context,
scratch and fresh processes, and a separately verified unobserved reference.
"""
    require(type(lease) is CudaCompiledLease, "exact CUDA observation lease required")
    try:
        source_check()
        require(type(gate) is bridge.BaselineBridge and gate.hermetic_test is False
                and gate.attestation.frozen_capability.trust_domain == "production"
                and gate.context["device"].type == "cuda", "original production CUDA worker required")
        require(lease.model is gate.model and lease.diag is gate.diag,
                "observer and original worker differ")
        require(not lease.used and not gate._finished and life._ACTIVE.get() is None,
                "observer run is single use and non-nested")
        require(tuple(t.trial_id for t in gate.trials) == lease.plan.trials, "observer trial order differs")
        lease.check()
        require(lease.compiler is not None and not lease.compiler.entered, "fresh cold compiler required")
        lease.context = gate.context
        lease.used = gate._finished = True
        token = life._ACTIVE.set(lease)
        passes, summaries = [], []
        try:
            with gate._scope():
                for pass_id, size in (("pass1", 16), ("pass2", 1)):
                    lease.check()
                    lease.pass_id = pass_id
                    gate._live("cuda_observer_pre_" + pass_id)
                    result = gate.diag.run_trace_pass(gate.context, gate.trials, pass_id, size,
                                                     gate.cell == "A2", Path(gate.context["scratch_root"]))
                    passes.append(result)
                    summaries.append(gate._consume(result, pass_id, size))
                    lease.verify_pass(result)
                    gate._live("cuda_observer_post_" + pass_id)
                gate.gate.finish()
                lease.check()
                require(lease.current is None and len(lease.records) == 34 and len(passes) == 2,
                        "incomplete CUDA observation lifetime")
                require(len(lease.store.refs) == 2 * len(lease.plan.targets) * len(lease.plan.stages),
                        "incomplete target capture coverage")
                for ref in lease.store.refs:
                    require(lease.store.compare(ref, ref), "capture bytes changed")
                require(bool(lease.compiler.entered), "compiler backend not entered")
                gate._live("cuda_observer_final")
                source_check()
            return {"status": "CUDA_OBSERVED_PARENT_REPLAY_CANDIDATE_PASS", "cell": gate.cell,
                    "worker_pid": os.getpid(), "batches": 34, "passes": 2,
                    "stage_invocations": 34 * len(lease.plan.stages), "capture_records": len(lease.store.refs),
                    "capture_bytes": lease.store.used_bytes,
                    "observer_ledger_sha256": hashlib.sha256(lease.record_seal).hexdigest(),
                    "original_passes": summaries, "original_guard_domain": "production",
                    "mutable_observer_state_covered_by_original_v18_seal": False,
                    "separate_observer_lifecycle_checked": True,
                    "real_parent_replay_completed": True, "production_model_loaded": True,
                    "cold_reference_pair_verified": False,
                    "intermediate_equivalence_to_uninstrumented_compilation_proven": False,
                    "ready_for_gpu": False, "jobs_submitted": 0}
        finally:
            life._ACTIVE.reset(token)
    except BaseException:
        lease.failed = True
        raise
    finally:
        lease.close()


CODE = tuple((owner, name, value, value.__code__, getattr(value, "__wrapped__", None),
              getattr(getattr(value, "__wrapped__", None), "__code__", None))
             for owner in (sys.modules[__name__], CudaCompiledLease, ProductionRequest)
             for name, value in vars(owner).items() if type(value) is types.FunctionType)

"""Explicit pre-seal registration candidate; old v18 is never edited.

Derive only its preparation function in memory: add a private request argument,
one install call after strict load validation, and one check before issuance.
Every original AST statement remains. This is a new candidate, not original
v18 execution provenance. Production registration is forward-disabled pending
the separately reviewed compiled observer integration.
"""

import ast
import copy
from dataclasses import asdict
import hashlib
from pathlib import Path
import sys
import types

import torch

HERE = Path(__file__).resolve().parent
LIFE_SHA = "5b0baced33ff0fa09f51f189f942436354de706737dda1d73a605eac37b16f9f"
LIFE_PATH = HERE.parent / "targeted_lifecycle_20260912/observer_lifecycle.py"
if hashlib.sha256(LIFE_PATH.read_bytes()).hexdigest() != LIFE_SHA:
    raise RuntimeError("reviewed observer lifecycle source differs")
sys.path.insert(0, str(LIFE_PATH.parent))
import observer_lifecycle as life  # noqa: E402

if Path(life.__file__).resolve() != LIFE_PATH.resolve():
    raise RuntimeError("unexpected lifecycle module")
bridge = life.bridge
SELF_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
CANDIDATE_NAME = "prepare_with_registered_observer"
INSTALL = "_registration.install(model, report, device)"
BEFORE_ISSUE = "_registration.before_issue(model)"
POLICY = "PRESEAL_REGISTRATION_CANDIDATE_20260912"


class PreparationError(RuntimeError):
    pass


def require(ok, message):
    if not ok:
        raise PreparationError(message)


def wire(value):
    return bridge.replay.canonical(value)


def original_node(raw):
    require(hashlib.sha256(raw).hexdigest() == bridge.V18_SHA, "v18 preparation source SHA differs")
    tree = ast.parse(raw)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "prepare_formal40_worker"]
    require(len(nodes) == 1 and not nodes[0].decorator_list, "original preparation definition differs")
    return nodes[0]


def build_candidate(raw):
    original = original_node(raw)
    candidate = copy.deepcopy(original)
    candidate.name = CANDIDATE_NAME
    candidate.args.kwonlyargs.append(ast.arg(arg="_registration"))
    candidate.args.kw_defaults.append(None)
    load = [i for i, n in enumerate(candidate.body) if ast.dump(n) == ast.dump(ast.parse("_require_load_report(report)").body[0])]
    require(len(load) == 1, "unique post-load insertion point required")
    candidate.body.insert(load[0] + 1, ast.parse(INSTALL).body[0])
    issue = [i for i, n in enumerate(candidate.body) if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == "attestation" for t in n.targets)]
    require(len(issue) == 1, "unique pre-issuance insertion point required")
    candidate.body.insert(issue[0], ast.parse(BEFORE_ISSUE).body[0])
    verify_delta(raw, candidate)
    return ast.fix_missing_locations(ast.Module(body=[candidate], type_ignores=[]))


def verify_delta(raw, candidate):
    """Not a textual similarity check: restore exact original syntax tree."""
    original = original_node(raw)
    require(candidate.name == CANDIDATE_NAME, "candidate function name differs")
    restored = copy.deepcopy(candidate)
    require(restored.args.kwonlyargs[-1].arg == "_registration"
            and restored.args.kw_defaults[-1] is None, "registration argument differs")
    restored.args.kwonlyargs.pop()
    restored.args.kw_defaults.pop()
    restored.name = original.name
    for statement, predecessor in ((INSTALL, "_require_load_report(report)"), (BEFORE_ISSUE, None)):
        target = ast.dump(ast.parse(statement).body[0])
        positions = [i for i, n in enumerate(restored.body) if ast.dump(n) == target]
        require(len(positions) == 1, "registration call count differs")
        index = positions[0]
        if predecessor:
            require(index > 0 and ast.dump(restored.body[index - 1]) == ast.dump(ast.parse(predecessor).body[0]),
                    "install is not immediately after strict report validation")
        else:
            next_node = restored.body[index + 1]
            require(isinstance(next_node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "attestation" for t in next_node.targets),
                    "check is not immediately before original issuance")
        restored.body.pop(index)
    require(ast.dump(restored) == ast.dump(original), "original preparation logic was changed")
    return {"original_ast_restored_exactly": True, "added_calls": [INSTALL, BEFORE_ISSUE],
            "old_function_replaced": False, "old_source_sha256": bridge.V18_SHA,
            "parent_prepare_ast_sha256": hashlib.sha256(ast.dump(original).encode()).hexdigest(),
            "candidate_prepare_ast_sha256": hashlib.sha256(ast.dump(candidate).encode()).hexdigest()}


def source_check():
    require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == SELF_SHA,
            "preparation adapter source changed")
    require(hashlib.sha256(LIFE_PATH.read_bytes()).hexdigest() == LIFE_SHA,
            "observer lifecycle source changed")
    life._source_check()
    for owner, name, function, code in CODE:
        require(vars(owner).get(name) is function and function.__code__ is code,
                "preparation callable changed: " + name)


class RegistrationRequest:
    """Fixed installer, NOT a caller-supplied arbitrary callback.

    Hermetic path admits the already-tested recorder. Production registration
    is deliberately unavailable until its compiled lifecycle can be admitted;
    retain this explicit rejection rather than bypassing CPU/compile guards.
    """
    def __init__(self, diag, context, plan, store, *, hermetic_test=False):
        bridge._require_module(diag)
        require(type(hermetic_test) is bool and type(plan) is life.base.Plan,
                "invalid registration policy/plan")
        require(type(store) is life.capture.CaptureStore and not store.refs, "fresh capture store required")
        self.diag, self.context, self.plan, self.store = diag, context, plan, store
        self.hermetic_test = hermetic_test
        self.used = self.failed = False
        self.model = self.lease = self.prepared = None
        self.before = None
        self.install_count = self.before_issue_count = 0
        self.receipt = None
        self.issued_before = None
        self.config = (id(diag), id(context), wire(asdict(plan)), id(store), hermetic_test)

    def check(self):
        source_check()
        bridge._require_module(self.diag)
        require(not self.failed and self.config == (id(self.diag), id(self.context),
                wire(asdict(self.plan)), id(self.store), self.hermetic_test), "registration changed or failed")
        require(not any(n in vars(self) for n, v in vars(RegistrationRequest).items()
                        if type(v) is types.FunctionType), "registration instance method replaced")

    def install(self, model, report, device):
        self.check()
        require(self.used and self.install_count == 0 and self.lease is None, "registration already installed")
        capability = self.context.get("_frozen_context_capability")
        # Do not issue a production worker with a recorder that currently only
        # supports CPU/eager. The original production CUDA gate remains intact.
        require(self.hermetic_test and capability.trust_domain == "hermetic-test"
                and device.type == "cpu", "compiled production registration is not released")
        require(type(report) is dict, "strict report must be native data")
        self.model = model
        self.before = self.snapshot()
        self.lease = life.ObservationLease(self.diag, model, self.plan, self.store)
        self.lease.install_before_issuance()
        self.install_count += 1
        require(self.snapshot() == self.before, "observer installation changed state/RNG/runtime")

    def snapshot(self):
        return wire({"state": self.diag._snapshot_model_entries(self.model),
                     "rng": self.diag._get_trace().snapshot_rng_state(),
                     "runtime": self.diag._read_frozen_numeric_runtime(torch)})

    def before_issue(self, model):
        self.check()
        require(self.install_count == 1 and self.before_issue_count == 0 and model is self.model,
                "pre-issuance registration order/model differs")
        require(not any(a.model is model for a in self.diag._ISSUED_FORMAL40_ATTESTATIONS.values()),
                "model was already issued")
        self.lease.check()
        require(self.snapshot() == self.before, "pre-issuance state/RNG/runtime changed")
        self.before_issue_count += 1

    def finish(self, prepared, audit):
        self.check()
        require(self.install_count == self.before_issue_count == 1 and prepared["model"] is self.model,
                "registration did not bracket original issuance")
        attestation = prepared["_formal40_worker_attestation"]
        require(self.diag._ISSUED_FORMAL40_ATTESTATIONS.get(id(attestation)) is attestation,
                "original worker was not issued")
        self.prepared = prepared
        self.lease.context = prepared
        self.lease.check()
        require(self.snapshot() == self.before, "preparation changed registered state/RNG/runtime")
        with self.diag._prediction_evaluator_context(prepared["evaluator"], model=self.model,
                                                    attestation=attestation):
            require(self.diag._require_active_inference_attestation(self.model, "prepared_registration") == attestation.public_record(),
                    "new prepared worker is not live")
        value = {"candidate": POLICY, "original_attestation": attestation.public_record(),
                 "plan_sha256": hashlib.sha256(wire(asdict(self.plan))).hexdigest(),
                 "source_sha256": {"preparation_adapter": SELF_SHA, "observer_lifecycle": LIFE_SHA,
                                   "v18_parent": bridge.V18_SHA}, "ast_audit": audit,
                 "install_count": self.install_count, "pre_issue_check_count": self.before_issue_count,
                 "registered_module_paths": list(dict.fromkeys(s.module for s in self.plan.stages)),
                 "preparation_state_rng_runtime_unchanged": True, "model_received_from_strict_load": True,
                 "test_model_preinjection_used": False, "production_preparation_validated": False,
                 "ready_for_gpu": False, "jobs_submitted": 0}
        self.receipt = wire(value)
        return value

    def close(self):
        if self.model is not None and self.issued_before is not None:
            for attestation in self.diag._ISSUED_FORMAL40_ATTESTATIONS.values():
                if attestation.model is self.model and id(attestation) not in self.issued_before:
                    self.diag._revoke_attestation(attestation)
        if self.lease is not None:
            self.lease.close()


def prepare_registered(request, *, allow_cpu):
    """No patch to diag globals or old functions. Only this new entry adapts."""
    require(type(request) is RegistrationRequest, "exact reviewed registration request required")
    try:
        request.check()
        require(not request.used, "preparation request is single use")
        require(request.hermetic_test, "production registration is not released; no runtime/load attempted")
        request.used = True
        diag = request.diag
        request.issued_before = frozenset(diag._ISSUED_FORMAL40_ATTESTATIONS)
        raw = Path(diag.__file__).read_bytes()
        tree = build_candidate(raw)
        audit = verify_delta(raw, tree.body[0])
        # The copied namespace shares the original registries/ContextVars and
        # exact helper functions. Original module dictionary stays untouched.
        namespace = dict(vars(diag))
        globals_used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
                        and isinstance(n.ctx, ast.Load) and n.id in vars(diag)}
        bindings = {name: namespace[name] for name in globals_used}
        exec(compile(tree, str(HERE / "<derived-preparation>"), "exec"), namespace)
        function = namespace[CANDIDATE_NAME]
        require(CANDIDATE_NAME not in vars(diag), "old v18 namespace unexpectedly changed")
        prepared = function(request.context, allow_cpu=allow_cpu, _registration=request)
        require(all(vars(diag)[name] is value for name, value in bindings.items()),
                "original preparation global binding changed")
        bridge._require_module(diag)
        value = request.finish(prepared, audit)
        return prepared, request.lease, value
    except BaseException:
        request.failed = True
        request.close()
        raise


CODE = tuple((owner, name, value, value.__code__)
             for owner in (sys.modules[__name__], RegistrationRequest)
             for name, value in vars(owner).items() if type(value) is types.FunctionType)

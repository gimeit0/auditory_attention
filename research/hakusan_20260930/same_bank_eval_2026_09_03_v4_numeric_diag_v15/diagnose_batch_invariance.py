"""SHA-bound bootstrap and immutable input freeze for the v4 diagnostic."""

from __future__ import annotations

import argparse
import base64
import contextlib
import csv
import dataclasses
import dis
import fcntl
import hashlib
import importlib
import importlib.abc
import importlib.util
import io
import json
import math
import mmap
import os
import pathlib
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types
import uuid
import warnings
from collections import OrderedDict, deque
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextvars import ContextVar
from typing import Any, Literal


DIAGNOSTIC_PROTOCOL = "formal40_batch_invariance_diag_20260903_v15"
V4_PROTOCOL = "fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1"
EVALUATION_ROLE = "REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST"
V4_ROOT = pathlib.Path("/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4")
DIAGNOSTIC_ROOT = pathlib.Path(
    "/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v15"
)
PRODUCTION_PYTHON = pathlib.Path("/home/s2510040/miniconda3/envs/attn/bin/python")
SBATCH_PATH = pathlib.Path("/usr/bin/sbatch")
V4_EVALUATOR_SHA256 = "31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4"
V4_RUNNER_SHA256 = "b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495"
V4_MANIFEST_SHA256 = "1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5"
V4_LOCK_SHA256 = "63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710"
FORMAL40_SHA256 = "2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff"
FORMAL40_BASENAME = "formal-final.ckpt"
FORMAL40_EPOCH = 40
FORMAL40_GLOBAL_STEP = 69440
PACKAGE_SCHEMA_VERSION = 1
PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent
NUMERIC_TRACE_SIZE = 36321
NUMERIC_TRACE_SHA256 = (
    "fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b"
)
PRODUCTION_FILES = (
    "diagnose_batch_invariance.py",
    "numeric_trace.py",
    "submit_numeric_diag.py",
    "run_numeric_diag.sbatch",
)
DIAGNOSTIC_LAYOUT = ("tools", "logs", "state", "attempts", "submitted_runners")
ROLE_NAMES = (
    "target",
    "correct_cue",
    "distractor_1",
    "distractor_2",
    "distractor_3",
    "distractor_4",
    "probe_distractor_cue",
    "shuffled_cue",
)
TRIAL_IDENTITY_COLUMNS = (
    "control_subset",
    "distractor_count",
    "probe_distractor_label",
    "scene_kind",
    "snr_bin",
    "target_gender",
    "target_label",
    "target_speaker",
    "snr_db",
    "trial_id",
)
V4_EVALUATOR_WHITELIST = (
    "_frozen_import_context",
    "strict_load_model",
    "singleton_native_preprocess",
    "predict_batch",
    "_select_smoke_bank",
    "_configure_runtime",
    "_tensor_hashes",
)


class DiagnosticError(RuntimeError):
    """A frozen diagnostic boundary could not be proven."""


@dataclasses.dataclass(frozen=True)
class FrozenContract:
    v4_root: pathlib.Path
    v4_protocol: str
    evaluation_role: str
    evaluator_sha256: str
    runner_sha256: str
    manifest_sha256: str
    lock_sha256: str
    formal40_sha256: str


@dataclasses.dataclass(frozen=True)
class TrialSpec:
    ordinal: int
    trial_id: int
    bank_row_index: int
    identity: Mapping[str, Any]


@dataclasses.dataclass(frozen=True)
class FrozenSceneAPI:
    waveform_cache_class: type
    raw_scene_batch: Callable[..., Any]
    correct_cue_batch: Callable[..., Any]
    imported_source_records: tuple[Mapping[str, Any], ...]


@dataclasses.dataclass(frozen=True)
class CellSpec:
    cell_id: Literal["A1", "A2", "B1", "B2"]
    autocast_enabled: bool
    pass_batch_sizes: tuple[int, int]


CELL_SPECS = types.MappingProxyType(
    {
        "A1": CellSpec("A1", True, (16, 16)),
        "A2": CellSpec("A2", True, (16, 1)),
        "B1": CellSpec("B1", False, (16, 16)),
        "B2": CellSpec("B2", False, (16, 1)),
    }
)
EXECUTION_ORDER = ("REFERENCE_COLD", "A2", "EQUIVALENCE", "A1", "B1", "B2")


@dataclasses.dataclass
class TraceBatch:
    trial_ids: tuple[int, ...]
    raw_scene: Any
    raw_cue: Any
    normalized_scene: Any
    normalized_cue: Any
    scene_features: Any
    cue_features: Any
    native_logits: Any
    log_probabilities: Any
    outputs: Mapping[str, Any]


@dataclasses.dataclass
class PassResult:
    pass_id: Literal["pass1", "pass2"]
    batch_size: int
    trial_ids: tuple[int, ...]
    outputs: Mapping[str, Any]
    boundary_records: Mapping[str, Any]
    model_snapshots: Mapping[str, Sequence[Mapping[str, Any]]]
    rng_snapshots: Mapping[str, Mapping[str, Any]]


@dataclasses.dataclass(frozen=True)
class _Formal40WorkerAttestation:
    evaluator: Any
    model: Any
    load_report: Any
    diagnostic_protocol: str
    v4_protocol: str
    evaluator_sha256: str
    manifest_sha256: str
    load_report_sha256: str
    worker_pid: int
    worker_nonce: str
    model_nonce: str
    input_context_sha256: str
    imported_source_records: tuple[Any, ...]
    frozen_capability: _FrozenContextCapability
    scene_api: Any
    scene_scope_nonce: str
    evaluator_authority_callables: Mapping[str, Any]
    scene_callables: Mapping[str, Any]
    model_callables: Mapping[str, Any]
    scene_callable_graphs: Mapping[str, Any]
    model_callable_graphs: Mapping[str, Any]
    operator_authorities: Mapping[str, Any]
    model_module_inventory: tuple[Any, ...]
    model_execution_fingerprint: tuple[Any, ...]
    imported_source_snapshot: bytes

    def public_record(self) -> dict[str, Any]:
        return {
            "basis": "static_formal40_worker_attestation",
            "limitation": "inference-disabled versions are not dynamic mutation detection",
            "diagnostic_protocol": self.diagnostic_protocol,
            "v4_protocol": self.v4_protocol,
            "evaluator_sha256": self.evaluator_sha256,
            "manifest_sha256": self.manifest_sha256,
            "model_id": "formal40",
            "worker_pid": self.worker_pid,
            "worker_nonce": self.worker_nonce,
            "model_nonce": self.model_nonce,
            "load_report_sha256": self.load_report_sha256,
            "input_context_sha256": self.input_context_sha256,
            "trust_domain": self.frozen_capability.trust_domain,
            "scene_scope_nonce": self.scene_scope_nonce,
        }


_ISSUED_FORMAL40_ATTESTATIONS: dict[int, _Formal40WorkerAttestation] = {}
_REVOKED_FORMAL40_ATTESTATIONS: set[int] = set()


@dataclasses.dataclass(frozen=True)
class _FrozenContextCapability:
    evaluator: Any
    manifest: Any
    evaluator_record: Mapping[str, Any]
    manifest_record: Mapping[str, Any]
    pinned_records: tuple[Mapping[str, Any], ...]
    source_records: tuple[Mapping[str, Any], ...]
    root: pathlib.Path
    source_root: pathlib.Path
    trust_domain: Literal["production", "hermetic-test"]
    nonce: str
    evaluator_callables: Mapping[str, Any]
    evaluator_callable_graphs: Mapping[str, Any]
    manifest_snapshot: bytes
    pinned_records_snapshot: bytes
    source_records_snapshot: bytes
    manifest_sha256: str
    pinned_records_sha256: str
    source_records_sha256: str


_ISSUED_FROZEN_CONTEXT_CAPABILITIES: dict[int, _FrozenContextCapability] = {}
_FROZEN_CONTEXT_CAPABILITY_RECEIPTS: dict[int, tuple[Any, ...]] = {}
_REVOKED_FROZEN_CONTEXT_CAPABILITIES: set[int] = set()
_FORMAL40_ATTESTATION_RECEIPTS: dict[int, tuple[Any, ...]] = {}
_FORMAL40_ISSUED_MODEL_STATE: dict[int, bytes] = {}
_VERIFIED_PRODUCTION_EVALUATORS: dict[
    int, tuple[Any, Mapping[str, Any], Mapping[str, Sequence[Any]], Mapping[str, Any]]
] = {}
_VERIFIED_PRODUCTION_MANIFESTS: dict[int, tuple[Any, Mapping[str, Any]]] = {}
_VERIFIED_PRODUCTION_INVENTORIES: dict[
    int,
    tuple[
        Any, tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...], pathlib.Path
    ],
] = {}


@dataclasses.dataclass(frozen=True)
class _AuthenticatedPassEvidence:
    result: PassResult
    binding_sha256: str
    artifact_record: Mapping[str, Any]
    frozen_capability: _FrozenContextCapability
    scene_scope_nonce: str
    imported_source_snapshot: bytes
    nonce: str


_AUTHENTICATED_PASS_RESULTS: dict[int, _AuthenticatedPassEvidence] = {}
_AUTHENTICATED_PASS_RECEIPTS: dict[int, tuple[Any, ...]] = {}
_REVOKED_AUTHENTICATED_PASS_RESULTS: set[int] = set()
_ACTIVE_CALLABLE_GRAPH_IDS: ContextVar[frozenset[int]] = ContextVar(
    "active_callable_graph_ids", default=frozenset()
)
_MATERIALIZE_CALLABLE_MODULE_ATTRIBUTES: ContextVar[bool] = ContextVar(
    "materialize_callable_module_attributes", default=False
)
_ACTIVE_FROZEN_SCENE_API: ContextVar[FrozenSceneAPI | None] = ContextVar(
    "active_frozen_scene_api", default=None
)
_ACTIVE_WORKER_SCENE_SCOPE: ContextVar[Mapping[str, Any] | None] = ContextVar(
    "active_worker_scene_scope", default=None
)
_PROCESS_MODULE_REGISTRY = sys.modules
_VERIFIED_RUNTIME_READERS: dict[int, Any] = {}
_VERIFIED_SNAPSHOT_IMPORTERS: dict[int, Any] = {}
_ALLOW_REGISTRY_RUNTIME_IDENTITY: ContextVar[bool] = ContextVar(
    "allow_registry_runtime_identity", default=False
)
_ACTIVE_SNAPSHOT_AUTHORITY: ContextVar[Any] = ContextVar(
    "active_snapshot_authority", default=None
)


def _verify_active_import_authority() -> None:
    if sys.modules is not _PROCESS_MODULE_REGISTRY:
        raise DiagnosticError("process module registry object was replaced")
    authority = _ACTIVE_SNAPSHOT_AUTHORITY.get()
    if authority is not None:
        authority.verify_runtime_bindings()


def _is_verified_snapshot_import(function: Any, module_name: str) -> bool:
    """One SHA-bound edge has a scoped source identity, not a process binding.

    The frozen strict loader imports this module inside its nested context,
    which removes/restores modules on exit. Do not eagerly import it from the
    process path while issuing a graph. Its executing source is checked by the
    active snapshot finder and the instantiated model has its own live seal.
    Arbitrary functions, other src imports and process dependencies do not get
    this exception; graph checks never rebaseline their bindings.
    """
    if (
        module_name != "src.spatial_attn_lightning"
        or _VERIFIED_SNAPSHOT_IMPORTERS.get(id(function)) is not function
    ):
        return False
    authority = _ACTIVE_SNAPSHOT_AUTHORITY.get()
    if authority is not None:
        authority.verify_runtime_bindings()
        if module_name not in authority.modules:
            raise DiagnosticError(
                "verified model import absent from snapshot authority"
            )
    return True


def _graph_container_identity(function: Any, value: Any, *args, **kwargs):
    # Only the exact SHA-verified v4 import-context function is permitted to
    # inspect a mutable process registry without sealing its complete contents.
    # All other functions retain the original recursive container seal.
    allowed = _VERIFIED_RUNTIME_READERS.get(id(function)) is function
    token = _ALLOW_REGISTRY_RUNTIME_IDENTITY.set(allowed)
    try:
        return _container_execution_identity(value, *args, **kwargs)
    finally:
        _ALLOW_REGISTRY_RUNTIME_IDENTITY.reset(token)


def _register_frozen_context_capability(
    *,
    evaluator: Any,
    manifest: Any,
    evaluator_record: Mapping[str, Any],
    manifest_record: Mapping[str, Any],
    pinned_records: Sequence[Mapping[str, Any]],
    source_records: Sequence[Mapping[str, Any]],
    root: pathlib.Path,
    source_root: pathlib.Path | None = None,
    trust_domain: Literal["production", "hermetic-test"],
) -> _FrozenContextCapability:
    if (
        not isinstance(evaluator_record, Mapping)
        or not isinstance(manifest_record, Mapping)
        or not pinned_records
        or not source_records
    ):
        raise DiagnosticError("frozen provenance records are incomplete")
    if trust_domain == "production":
        evaluator_entry = _VERIFIED_PRODUCTION_EVALUATORS.get(id(evaluator))
        manifest_entry = _VERIFIED_PRODUCTION_MANIFESTS.get(id(manifest))
        if (
            evaluator_entry is None
            or len(evaluator_entry) != 4
            or evaluator_entry[0] is not evaluator
            or dict(evaluator_entry[1]) != dict(evaluator_record)
            or manifest_entry is None
            or manifest_entry[0] is not manifest
            or dict(manifest_entry[1]) != dict(manifest_record)
        ):
            raise DiagnosticError(
                "production capability requires exact verified loader objects"
            )
    trace = _get_trace()
    root = _real_directory_root(root, "frozen capability root")
    source_root = _real_directory_root(
        source_root if source_root is not None else root,
        "frozen capability source root",
    )
    if trust_domain == "production":
        authority = _VERIFIED_PRODUCTION_INVENTORIES.get(id(manifest))
        if (
            authority is None
            or authority[0] is not manifest
            or tuple(dict(item) for item in authority[1])
            != tuple(dict(item) for item in pinned_records)
            or tuple(dict(item) for item in authority[2])
            != tuple(dict(item) for item in source_records)
            or authority[3] != source_root
        ):
            raise DiagnosticError(
                "production capability inventories differ from verified manifest"
            )

    def verify_record(record: Mapping[str, Any], allowed_root: pathlib.Path) -> None:
        try:
            raw_path = record.get("path")
            if isinstance(raw_path, str) and pathlib.Path(raw_path).is_absolute():
                _, current = trace.read_stable_bytes(
                    pathlib.Path(raw_path), allowed_root=pathlib.Path(raw_path).parent
                )
                if current.get("size") != record.get("size") or current.get(
                    "sha256"
                ) != record.get("sha256"):
                    raise DiagnosticError("frozen provenance record changed")
            else:
                allowed_extras = {"type", "observed_import"}
                identity_keys = {
                    "relative_path",
                    "mode",
                    "size",
                    "st_mtime_ns",
                    "st_dev",
                    "st_ino",
                    "sha256",
                }
                if (
                    set(record) - identity_keys - allowed_extras
                    or set(record) & identity_keys != identity_keys
                    or ("type" in record and record["type"] != "file")
                    or (
                        "observed_import" in record
                        and not isinstance(record["observed_import"], bool)
                    )
                ):
                    raise DiagnosticError("frozen provenance record extras are invalid")
                trace.verify_file_record(
                    {key: record[key] for key in identity_keys},
                    allowed_root=allowed_root,
                )
        except Exception as error:
            if isinstance(error, DiagnosticError):
                raise
            raise DiagnosticError(
                "frozen provenance record verification failed"
            ) from error

    verify_record(evaluator_record, root)
    verify_record(manifest_record, root)
    for record in pinned_records:
        verify_record(record, root)
    for record in source_records:
        verify_record(record, source_root)
    callable_records = {
        name: _callable_anchor(getattr(evaluator, name))
        for name in V4_EVALUATOR_WHITELIST
        if callable(_static_attribute(evaluator, name))
    }
    if not callable_records:
        raise DiagnosticError("frozen evaluator callable inventory is empty")
    callable_graphs = _callable_graphs(
        {name: getattr(evaluator, name) for name in callable_records},
        materialize_module_attributes=True,
    )
    if trust_domain == "production":
        authority_callables = evaluator_entry[2]
        authority_graphs = evaluator_entry[3]
        if (
            set(callable_records) != set(V4_EVALUATOR_WHITELIST)
            or set(authority_callables) != set(V4_EVALUATOR_WHITELIST)
            or any(
                not _callable_anchor_equal(
                    callable_records[name], authority_callables[name]
                )
                for name in V4_EVALUATOR_WHITELIST
            )
            or dict(callable_graphs) != dict(authority_graphs)
        ):
            raise DiagnosticError("production evaluator differs from verified loader")
    manifest_sha = hashlib.sha256(trace.canonical_json_bytes(manifest)).hexdigest()
    pinned_sha = hashlib.sha256(
        trace.canonical_json_bytes(tuple(dict(item) for item in pinned_records))
    ).hexdigest()
    source_sha = hashlib.sha256(
        trace.canonical_json_bytes(tuple(dict(item) for item in source_records))
    ).hexdigest()
    capability = _FrozenContextCapability(
        evaluator=evaluator,
        manifest=manifest,
        evaluator_record=types.MappingProxyType(dict(evaluator_record)),
        manifest_record=types.MappingProxyType(dict(manifest_record)),
        pinned_records=tuple(
            types.MappingProxyType(dict(item)) for item in pinned_records
        ),
        source_records=tuple(
            types.MappingProxyType(dict(item)) for item in source_records
        ),
        root=root,
        source_root=source_root,
        trust_domain=trust_domain,
        nonce=uuid.uuid4().hex,
        evaluator_callables=types.MappingProxyType(callable_records),
        evaluator_callable_graphs=callable_graphs,
        manifest_snapshot=trace.canonical_json_bytes(manifest),
        pinned_records_snapshot=trace.canonical_json_bytes(
            tuple(dict(item) for item in pinned_records)
        ),
        source_records_snapshot=trace.canonical_json_bytes(
            tuple(dict(item) for item in source_records)
        ),
        manifest_sha256=manifest_sha,
        pinned_records_sha256=pinned_sha,
        source_records_sha256=source_sha,
    )
    _ISSUED_FROZEN_CONTEXT_CAPABILITIES[id(capability)] = capability
    _FROZEN_CONTEXT_CAPABILITY_RECEIPTS[id(capability)] = (
        _frozen_capability_issuance_receipt(capability)
    )
    return capability


def _issue_hermetic_frozen_capability(
    *,
    evaluator: Any,
    manifest: Any,
    root: pathlib.Path,
    evaluator_record: Mapping[str, Any],
    manifest_record: Mapping[str, Any],
    pinned_records: Sequence[Mapping[str, Any]],
    source_records: Sequence[Mapping[str, Any]],
) -> _FrozenContextCapability:
    """Private test seam backed by real, descriptor-verified temporary bytes."""
    trace = _get_trace()
    root = _real_directory_root(root, "hermetic provenance root")
    records = (evaluator_record, manifest_record, *pinned_records, *source_records)
    if not pinned_records or not source_records:
        raise DiagnosticError("hermetic provenance inventories are empty")
    verified = []
    for record in records:
        if not isinstance(record, Mapping):
            raise DiagnosticError("hermetic provenance record is malformed")
        try:
            verified.append(trace.verify_file_record(record, allowed_root=root))
        except Exception as error:
            raise DiagnosticError(
                "hermetic provenance record verification failed"
            ) from error
    return _register_frozen_context_capability(
        evaluator=evaluator,
        manifest=manifest,
        evaluator_record=verified[0],
        manifest_record=verified[1],
        pinned_records=verified[2 : 2 + len(pinned_records)],
        source_records=verified[2 + len(pinned_records) :],
        root=root,
        source_root=root,
        trust_domain="hermetic-test",
    )


@contextlib.contextmanager
def _hermetic_frozen_scene_scope(
    capability: _FrozenContextCapability,
    scene_api: Any,
    imported_source_records: Sequence[Mapping[str, Any]],
) -> Iterator[None]:
    """Private scoped source/import capability for hermetic worker tests."""
    if (
        _ISSUED_FROZEN_CONTEXT_CAPABILITIES.get(id(capability)) is not capability
        or capability.trust_domain != "hermetic-test"
        or not imported_source_records
    ):
        raise DiagnosticError("hermetic frozen scene scope is invalid")
    allowed = {
        (item.get("relative_path"), item.get("sha256"))
        for item in capability.source_records
    }
    records = tuple(imported_source_records)
    if any(
        (item.get("relative_path"), item.get("sha256")) not in allowed
        for item in records
    ):
        raise DiagnosticError("hermetic frozen scene source is unverified")
    scope = types.MappingProxyType(
        {
            "scene_api": scene_api,
            "imported_source_records": records,
            "nonce": uuid.uuid4().hex,
        }
    )
    token = _ACTIVE_WORKER_SCENE_SCOPE.set(scope)
    try:
        yield
    finally:
        _ACTIVE_WORKER_SCENE_SCOPE.reset(token)


def _callable_function(value: Any) -> Any:
    return value.__func__ if type(value) is types.MethodType else value


def _callable_metadata(value: Any, name: str, default: Any = None) -> Any:
    if type(value) in (
        types.FunctionType,
        types.MethodType,
        types.BuiltinFunctionType,
        types.BuiltinMethodType,
    ):
        return getattr(value, name, default)
    namespace = _safe_instance_dict(value)
    return namespace.get(name, default) if namespace is not None else default


def _static_attribute(value: Any, name: str, default: Any = None) -> Any:
    """Resolve dictionaries/MRO without invoking user attribute protocols."""
    namespace = _safe_instance_dict(value)
    if namespace is not None and name in namespace:
        return namespace[name]
    if namespace is not None:
        # nn.Module resolves registered state/children through __getattr__.
        # Reproduce that lookup directly, without calling a replacement hook.
        for registry_name in ("_parameters", "_buffers", "_modules"):
            if registry_name not in namespace:
                continue
            for key, member in _native_registry_items(namespace[registry_name]):
                if key == name:
                    return member
    cls = value if isinstance(value, type) else type(value)
    for owner in type.__getattribute__(cls, "__mro__"):
        namespace = type.__getattribute__(owner, "__dict__")
        if name not in namespace:
            continue
        member = namespace[name]
        if type(member) is staticmethod:
            return member.__func__
        if type(member) is classmethod:
            return types.MethodType(member.__func__, cls)
        if type(member) is types.FunctionType and not isinstance(value, type):
            return types.MethodType(member, value)
        return member
    return default


def _callable_anchor(value: Any) -> tuple[Any, ...]:
    function = _callable_function(value)
    bound_self = _callable_metadata(value, "__self__")
    code = _callable_metadata(function, "__code__")
    defaults = _callable_metadata(function, "__defaults__")
    keyword_defaults = _callable_metadata(function, "__kwdefaults__")
    budget = _ACTIVE_SEAL_BUDGET.get()
    eligible = (
        budget is not None
        and type(function) is types.FunctionType
        and keyword_defaults is None
    )
    key = (id(function), id(bound_self))
    if eligible:
        cached = budget.callable_anchors.get(key)
        if (
            cached is not None
            and cached[0] is function
            and cached[1] is bound_self
            and cached[2] is code
            and cached[3] is defaults
        ):
            # Read every live binding above, including absence of kwdefaults.
            # Only a previously proved immutable record is reused; executable
            # globals, closures, hooks and model state are checked elsewhere.
            return cached[4]
    record = (
        bound_self,
        function,
        code,
        _default_anchor_identity(defaults),
        _default_anchor_identity(keyword_defaults),
    )
    if eligible and (
        defaults is None or id(defaults) in budget.literal_defaults
    ):
        # Strong references prevent identity reuse. Never store anchors for a
        # mutable default (including a nested container or an empty kwdict).
        budget.callable_anchors[key] = (function, bound_self, code, defaults, record)
    return record


def _callable_anchor_equal(left: Sequence[Any], right: Sequence[Any]) -> bool:
    return (
        len(left) == 5
        and len(right) == 5
        and left[0] is right[0]
        and left[1] is right[1]
        and left[2] is right[2]
        and left[3] == right[3]
        and left[4] == right[4]
    )


def _callable_anchor_matches(value: Any, anchor: Sequence[Any]) -> bool:
    if not callable(value) or len(anchor) != 5:
        return False
    return _callable_anchor_equal(_callable_anchor(value), anchor)


_EXECUTION_OBSERVATION_ATTRIBUTES = frozenset(
    {
        "calls",
        "call_count",
        "load_calls",
        "predict_calls",
        "preprocess_count",
        "raw_calls",
        "cue_calls",
    }
)
_MODULE_HOOK_NAMES = (
    "_forward_pre_hooks",
    "_forward_hooks",
    "_backward_pre_hooks",
    "_backward_hooks",
    "_state_dict_hooks",
    "_load_state_dict_pre_hooks",
    "_load_state_dict_post_hooks",
)
_MODULE_HOOK_FLAG_NAMES = (
    "_forward_hooks_with_kwargs",
    "_forward_hooks_always_called",
    "_forward_pre_hooks_with_kwargs",
    "_is_full_backward_hook",
)


def _is_execution_observation_name(value: Any) -> bool:
    return type(value) is str and value in _EXECUTION_OBSERVATION_ATTRIBUTES


def _safe_instance_dict(value: Any) -> dict[str, Any] | None:
    """Read a Python instance namespace without dispatching a user property."""
    if type(value) is types.ModuleType:
        namespace = types.ModuleType.__getattribute__(value, "__dict__")
        if any(type(key) is not str for key in dict.keys(namespace)):
            raise DiagnosticError("execution namespace has a non-string key")
        return namespace
    for owner in type.__getattribute__(type(value), "__mro__"):
        descriptor = type.__getattribute__(owner, "__dict__").get("__dict__")
        if type(descriptor) in (types.GetSetDescriptorType, types.MemberDescriptorType):
            try:
                namespace = descriptor.__get__(value, type(value))
            except (AttributeError, TypeError):
                continue
            if type(namespace) is dict:
                if any(type(key) is not str for key in dict.keys(namespace)):
                    raise DiagnosticError("execution namespace has a non-string key")
                return namespace
    return None


class _SealBudget:
    """One bounded work allowance shared by nested executable/configuration seals."""

    def __init__(self):
        self.nodes = set()
        self.work = 0
        self.depth = 0
        # Per-check immutable analysis only. Strong code references prevent id
        # reuse; no globals/closures/bound objects or live seals here.
        self.instructions = {}
        self.literal_defaults = {}
        self.callable_anchors = {}

    def visit(
        self, value: Any = None, *, executable: bool = False, cost: int = 1
    ) -> None:
        self.work += cost
        if self.work > 600_000:
            raise DiagnosticError("execution seal work budget exceeded")
        if executable:
            self.nodes.add(id(_callable_function(value)))
            if len(self.nodes) > 10_000:
                raise DiagnosticError("callable execution graph exceeds node limit")


_ACTIVE_SEAL_BUDGET = ContextVar("active_seal_budget", default=None)


def _bounded_seal(function):
    def bounded(*args, **kwargs):
        budget = _ACTIVE_SEAL_BUDGET.get()
        token = None
        if budget is None:
            budget = _SealBudget()
            token = _ACTIVE_SEAL_BUDGET.set(budget)
        budget.depth += 1
        try:
            budget.visit()
            if budget.depth > 96:
                raise DiagnosticError("execution seal exceeds depth limit")
            return function(*args, **kwargs)
        finally:
            budget.depth -= 1
            if token is not None:
                _ACTIVE_SEAL_BUDGET.reset(token)

    return bounded


def _seal_visit(value: Any = None, *, executable: bool = False, cost: int = 1) -> None:
    budget = _ACTIVE_SEAL_BUDGET.get()
    if budget is not None:
        budget.visit(value, executable=executable, cost=cost)


def _has_only_immutable_default_literals(value: Any, depth: int = 0) -> bool:
    if depth > 12:
        return False
    if value is None or type(value) in (bool, int, float, str, bytes):
        return True
    if type(value) is not tuple:
        return False
    _seal_visit(cost=tuple.__len__(value))
    return all(
        _has_only_immutable_default_literals(item, depth + 1)
        for item in tuple.__iter__(value)
    )


def _default_anchor_identity(value: Any) -> Any:
    """Reuse only exact immutable default literals, never a live binding."""
    if value is None:
        return ("scalar", id(type(None)), "None")
    budget = _ACTIVE_SEAL_BUDGET.get()
    if budget is None or type(value) is not tuple:
        return _container_execution_identity(value)
    _seal_visit()
    cached = budget.literal_defaults.get(id(value))
    if cached is not None:
        if cached[0] is not value:
            raise DiagnosticError("execution defaults cache identity changed")
        return cached[1]
    literal = _has_only_immutable_default_literals(value)
    record = _container_execution_identity(value)
    if literal:
        # Strong reference prevents id reuse; tuple contents cannot change.
        budget.literal_defaults[id(value)] = (value, record)
    return record


@_bounded_seal
def _seal_instructions(code: Any) -> tuple[Any, ...]:
    """Decode exact immutable code once within the current bounded check."""
    if code is None:
        return ()
    if type(code) is not types.CodeType:
        raise DiagnosticError("execution bytecode has an unsupported type")
    budget = _ACTIVE_SEAL_BUDGET.get()
    cached = budget.instructions.get(id(code))
    if cached is not None:
        if cached[0] is not code:
            raise DiagnosticError("execution bytecode cache identity changed")
        return cached[1]
    _seal_visit(cost=max(1, len(code.co_code) // 2))
    instructions = tuple(dis.get_instructions(code))
    budget.instructions[id(code)] = (code, instructions)
    return instructions


def _namespace_items(namespace):
    _seal_visit(cost=dict.__len__(namespace))
    items = tuple(dict.items(namespace))
    if any(type(name) is not str for name, _ in items):
        raise DiagnosticError("execution namespace has a non-string key")
    return sorted(items)


@_bounded_seal
def _native_registry_items(registry: Any) -> tuple[Any, ...]:
    """Read exact Torch registry storage in native order, without overrides."""
    if type(registry) is dict:
        length = dict.__len__(registry)
        items = dict.items
    elif type(registry) is OrderedDict:
        length = OrderedDict.__len__(registry)
        items = OrderedDict.items
    else:
        raise DiagnosticError("model registry requires exact dict or OrderedDict")
    _seal_visit(cost=length)
    # OrderedDict.items re-hashes keys while walking its linked order. Inspect
    # the underlying dict first so malformed keys cannot execute __hash__.
    if any(type(key) is not str for key in dict.keys(registry)):
        raise DiagnosticError("model registry has a non-string key")
    try:
        records = tuple(items(registry))
    except RuntimeError as error:
        raise DiagnosticError("model registry changed during seal") from error
    if len(records) != length:
        raise DiagnosticError("model registry changed during seal")
    if any(type(key) is not str for key, _ in records):
        raise DiagnosticError("model registry has a non-string key")
    return records


@_bounded_seal
def _require_native_ordered_key(key: Any, path: str) -> None:
    """Only native immutable key trees can safely be re-hashed by OrderedDict."""
    if key is None or type(key) in (bool, int, float, str, bytes):
        return
    if type(key) in (tuple, frozenset):
        for child in key:
            _require_native_ordered_key(child, path)
        return
    raise _unsupported_execution_container("mapping key", type(key), path)


@_bounded_seal
def _native_ordered_execution_items(value: Any, path: str) -> tuple[Any, ...]:
    if type(value) is not OrderedDict:
        raise _unsupported_execution_container("mapping", type(value), path)
    length = dict.__len__(value)
    _seal_visit(cost=length)
    for key in dict.keys(value):
        _require_native_ordered_key(key, path)
    try:
        records = tuple(OrderedDict.items(value))
    except RuntimeError as error:
        raise DiagnosticError(
            "execution ordered mapping changed during seal"
        ) from error
    if len(records) != length:
        raise DiagnosticError("execution ordered mapping changed during seal")
    return records


def _model_callable_values(model: Any) -> dict[str, Any]:
    coch = _static_attribute(_static_attribute(model, "coch_gram"), "full_rep")
    return {
        "forward": _static_attribute(model, "forward"),
        "model_call": _static_attribute(model, "__call__"),
        "model_type_call": _static_attribute(type(model), "__call__"),
        "model_call_impl": _static_attribute(model, "_call_impl"),
        "model_wrapped_call_impl": _static_attribute(model, "_wrapped_call_impl"),
        "named_modules": _static_attribute(model, "named_modules"),
        "audio_transforms": _static_attribute(model, "audio_transforms"),
        "coch_full_rep": coch,
        "coch_type_call": _static_attribute(type(coch), "__call__"),
    }


def _environment_binding_identity(value: Any) -> tuple[Any, ...]:
    """Metadata only: never invoke environment methods, codecs or descriptors."""
    if type(value) is types.FunctionType:
        cells = []
        for cell in value.__closure__ or ():
            try:
                content_id = id(cell.cell_contents)
            except ValueError:
                content_id = None
            cells.append((id(cell), content_id))
        return (
            id(value),
            id(value.__code__),
            id(value.__defaults__),
            id(value.__kwdefaults__),
            tuple(cells),
        )
    return (id(value), id(type(value)))


def _environment_structure(value: Any) -> tuple[Any, ...]:
    namespace = object.__getattribute__(value, "__dict__")
    if (
        type(namespace) is not dict
        or len(namespace) != 5
        or set(namespace)
        != {
            "_data",
            "encodekey",
            "decodekey",
            "encodevalue",
            "decodevalue",
        }
    ):
        raise DiagnosticError("process environment namespace differs")
    classes = []
    mro = type.__getattribute__(type(value), "__mro__")
    if len(mro) > 8:
        raise DiagnosticError("process environment type exceeds structural budget")
    for cls in mro:
        members = type.__getattribute__(cls, "__dict__")
        if len(members) > 128:
            raise DiagnosticError("process environment type exceeds structural budget")
        classes.append(
            (
                id(cls),
                tuple(
                    (name, _environment_binding_identity(member))
                    for name, member in members.items()
                ),
            )
        )
    return (
        id(namespace),
        tuple((k, _environment_binding_identity(v)) for k, v in dict.items(namespace)),
        tuple(classes),
    )


# Capture bindings at trusted interpreter/module bootstrap, not at first seal.
# Only the original POSIX text environ is supported; aliases must refer to it.
_PROCESS_ENVIRON = os.environ
_PROCESS_ENVIRON_TYPE = type(_PROCESS_ENVIRON)
_PROCESS_ENVIRON_DATA = object.__getattribute__(_PROCESS_ENVIRON, "__dict__")["_data"]
_PROCESS_ENVIRON_STRUCTURE = _environment_structure(_PROCESS_ENVIRON)
_ENVIRONMENT_HASH_FACTORY = hashlib.blake2b
_ENVIRONMENT_HASH_KEY = os.urandom(32)
_ENVIRONMENT_MAX_ITEMS = 4096
_ENVIRONMENT_MAX_BYTES = 4 * 1024 * 1024


def _environment_execution_identity(value: Any) -> tuple[Any, ...]:
    """Private keyed content seal; no plaintext, callbacks or OS environment writes.

    This is a same-process seal of Python's environment mapping, not a claim
    about native putenv calls that bypass that mapping, nor a cross-process hash.
    """
    if (
        value is not _PROCESS_ENVIRON
        or type(value) is not _PROCESS_ENVIRON_TYPE
        or vars(os).get("environ") is not _PROCESS_ENVIRON
        or vars(os).get("_Environ") is not _PROCESS_ENVIRON_TYPE
    ):
        raise DiagnosticError("process environment object/type binding differs")
    if _environment_structure(value) != _PROCESS_ENVIRON_STRUCTURE:
        raise DiagnosticError("process environment method/codec binding differs")
    data = object.__getattribute__(value, "__dict__").get("_data")
    if data is not _PROCESS_ENVIRON_DATA or type(data) is not dict:
        raise DiagnosticError("process environment backing data differs")
    length = dict.__len__(data)
    if length > _ENVIRONMENT_MAX_ITEMS:
        raise DiagnosticError("process environment exceeds item budget")
    _seal_visit(cost=max(1, 2 * length))
    # Exact dict.copy does not dispatch a user iterator or _Environ codec.
    snapshot = dict.copy(data)
    if len(snapshot) != length:
        raise DiagnosticError("process environment changed while sealing")
    byte_count = 0
    for key, item in dict.items(snapshot):
        if type(key) is not bytes or type(item) is not bytes:
            raise DiagnosticError("process environment requires exact POSIX bytes")
        byte_count += len(key) + len(item)
        if byte_count > _ENVIRONMENT_MAX_BYTES:
            raise DiagnosticError("process environment exceeds byte budget")
    digest = _ENVIRONMENT_HASH_FACTORY(key=_ENVIRONMENT_HASH_KEY, digest_size=32)
    digest.update(b"audattn-process-environment-v1\x00")
    for key in sorted(snapshot):
        item = snapshot[key]
        digest.update(len(key).to_bytes(8, "big"))
        digest.update(key)
        digest.update(len(item).to_bytes(8, "big"))
        digest.update(item)
    # Recheck exact bytes without invoking overridden mapping methods.
    if (
        _environment_structure(value) != _PROCESS_ENVIRON_STRUCTURE
        or vars(os).get("environ") is not value
        or dict.copy(data) != snapshot
    ):
        raise DiagnosticError("process environment changed while sealing")
    return (
        "process-environment",
        id(value),
        id(type(value)),
        id(data),
        length,
        digest.hexdigest(),
    )


def _unsupported_execution_container(kind: str, value_type: type, path: str):
    """Report static type/path without calling repr or a custom metaclass getter."""
    # Invoke type's own descriptors directly, bypassing metaclass properties as
    # well as an overridden __getattribute__.
    module = type.__dict__["__module__"].__get__(value_type)
    name = type.__dict__["__qualname__"].__get__(value_type)
    module = module[:256] if type(module) is str else "<unknown-module>"
    name = name[:256] if type(name) is str else "<unknown-type>"
    return DiagnosticError(
        f"unsupported execution {kind} type: path={path[:1024]}; type={module}.{name}"
    )


def _torch_version_execution_identity(value: Any, version_type: type) -> Any:
    """Seal the exact dependency string without its comparison/repr overrides."""
    if type(value) is not version_type or type.__getattribute__(
        version_type, "__mro__"
    ) != (version_type, str, object):
        raise DiagnosticError("torch version type differs")
    if str.__len__(value) > 256:
        raise DiagnosticError("torch version exceeds character budget")
    namespace = _safe_instance_dict(value)
    if namespace is not None and (type(namespace) is not dict or namespace):
        raise DiagnosticError("torch version instance attributes are unsupported")
    members = type.__getattribute__(version_type, "__dict__")
    if len(members) > 128:
        raise DiagnosticError("torch version type exceeds structural budget")
    _seal_visit(cost=max(1, len(members)))
    bindings = tuple(
        (name, _environment_binding_identity(member))
        for name, member in members.items()
    )
    return ("torch-version", id(value), id(version_type), str.__str__(value), bindings)


@_bounded_seal
def _container_execution_identity(
    value: Any,
    depth: int = 0,
    *,
    _seen: set[int] | None = None,
    _callables: list[tuple[str, Any]] | None = None,
    _path: str = "value",
    _expand_module: bool = False,
) -> Any:
    """Bounded, data-free identity/configuration seal for executable values.

    Tensor payloads are deliberately opaque: this routine never copies, hashes,
    converts, or synchronizes a tensor.  Mutable ordinary containers are sealed
    recursively, and callable children are returned to the caller for graph
    sealing rather than invoked.
    """
    if value is _PROCESS_MODULE_REGISTRY and _ALLOW_REGISTRY_RUNTIME_IDENTITY.get():
        _verify_active_import_authority()
        return ("verified-import-runtime-registry", id(value), id(type(value)))
    if _seen is None:
        _seen = set()
    if depth > 12:
        raise DiagnosticError("execution configuration exceeds depth limit")
    value_type = type(value)
    type_record = id(value_type)
    # Run before generic callable/mapping dispatch, including hostile subclasses
    # and a dict installed as os.environ. Never expand environment plaintext.
    if (
        value is _PROCESS_ENVIRON
        or issubclass(value_type, _PROCESS_ENVIRON_TYPE)
        or value is vars(os).get("environ")
    ):
        return _environment_execution_identity(value)
    version_module = _PROCESS_MODULE_REGISTRY.get("torch.torch_version")
    version_type = (
        vars(version_module).get("TorchVersion")
        if type(version_module) is types.ModuleType
        else None
    )
    if type(version_type) is type and issubclass(value_type, version_type):
        return _torch_version_execution_identity(value, version_type)
    # Exact stdlib deque is supported below; subclasses must never route through
    # overridden iteration, properties, or the generic callable branch.
    if value_type is not deque and issubclass(value_type, deque):
        raise _unsupported_execution_container("collection", value_type, _path)
    if value_type is not OrderedDict and issubclass(value_type, OrderedDict):
        raise _unsupported_execution_container("mapping", value_type, _path)
    if value is None or value_type in (bool, int, float, str, bytes):
        return ("scalar", type_record, repr(value))
    if isinstance(value, types.ModuleType):
        return ("module", id(value))
    if callable(value):
        function = _callable_function(value)
        if _callables is not None:
            _callables.append((_path, value))
        return (
            "callable",
            id(function),
            id(_callable_metadata(value, "__self__")),
            id(function),
            id(_callable_metadata(function, "__code__")),
            type_record,
        )
    object_id = id(value)
    if object_id in _seen:
        return ("cycle", object_id, type_record)
    _seen.add(object_id)
    # Torch/numpy values are execution data or registered state.  Their exact
    # object identity is sealed here; registered parameters/buffers additionally
    # carry version counters in the module fingerprint below.
    import torch
    import numpy as np

    if value_type in (torch.Tensor, torch.nn.Parameter, np.ndarray):
        return ("opaque-array", object_id, type_record)
    if isinstance(value, Mapping):
        if value_type is OrderedDict:
            source_items = _native_ordered_execution_items(value, _path)
        elif isinstance(value, dict):
            source_items = dict.items(value)
        elif type(value) is type(types.MappingProxyType({})):
            source_items = value.items()
        else:
            raise _unsupported_execution_container("mapping", value_type, _path)
        items = []
        for index, (key, item) in enumerate(source_items):
            if _is_execution_observation_name(key):
                continue
            key_record = _container_execution_identity(
                key,
                depth + 1,
                _seen=_seen,
                _callables=_callables,
                _path=f"{_path}.key[{index}]",
                _expand_module=_expand_module,
            )
            item_record = _container_execution_identity(
                item,
                depth + 1,
                _seen=_seen,
                _callables=_callables,
                _path=f"{_path}[{index}]",
                _expand_module=_expand_module,
            )
            items.append((key_record, item_record))
        return ("mapping", object_id, type_record, tuple(items))
    if value_type is deque:
        length = deque.__len__(value)
        _seal_visit(cost=length)
        maximum = deque.maxlen.__get__(value, deque)
        try:
            children = tuple(
                _container_execution_identity(
                    item,
                    depth + 1,
                    _seen=_seen,
                    _callables=_callables,
                    _path=f"{_path}[{index}]",
                    _expand_module=_expand_module,
                )
                for index, item in enumerate(deque.__iter__(value))
            )
        except DiagnosticError:
            # Nested type/budget failures must keep their original path/cause.
            raise
        except RuntimeError as error:
            raise DiagnosticError(
                f"execution deque changed during seal: path={_path[:1024]}"
            ) from error
        if deque.__len__(value) != length:
            raise DiagnosticError(
                f"execution deque changed during seal: path={_path[:1024]}"
            )
        return ("deque", object_id, type_record, maximum, children)
    if value_type is torch.Size:
        _seal_visit(cost=tuple.__len__(value))
        dimensions = tuple(tuple.__iter__(value))
        if any(type(item) is not int for item in dimensions):
            raise _unsupported_execution_container("shape dimension", value_type, _path)
        return ("torch-size", object_id, type_record, dimensions)
    if value_type in (tuple, list):
        return (
            "sequence",
            object_id,
            type_record,
            tuple(
                _container_execution_identity(
                    item,
                    depth + 1,
                    _seen=_seen,
                    _callables=_callables,
                    _path=f"{_path}[{index}]",
                    _expand_module=_expand_module,
                )
                for index, item in enumerate(value)
            ),
        )
    if value_type in (set, frozenset):
        children = [
            _container_execution_identity(
                item,
                depth + 1,
                _seen=_seen,
                _callables=_callables,
                _path=f"{_path}.set",
                _expand_module=_expand_module,
            )
            for item in value
        ]
        return ("set", object_id, type_record, tuple(sorted(children, key=repr)))
    if isinstance(value, Collection):
        raise _unsupported_execution_container("collection", value_type, _path)
    namespace = _safe_instance_dict(value)
    is_module = isinstance(namespace, dict) and isinstance(
        namespace.get("_modules"), dict
    )
    if is_module:
        return ("module-reference", object_id, type_record)
    if namespace is not None and _expand_module:
        attributes = []
        for name, item in _namespace_items(namespace):
            if _is_execution_observation_name(name):
                continue
            attributes.append(
                (
                    name,
                    _container_execution_identity(
                        item,
                        depth + 1,
                        _seen=_seen,
                        _callables=_callables,
                        _path=f"{_path}.{name}",
                        _expand_module=False,
                    ),
                )
            )
        return ("object", object_id, type_record, tuple(attributes))
    return (
        "object-reference" if namespace is not None else "opaque",
        object_id,
        type_record,
    )


@_bounded_seal
def _instance_execution_configuration(
    value: Any,
    *,
    path: str,
) -> tuple[Any, ...] | None:
    namespace = _safe_instance_dict(value)
    if namespace is None:
        return None
    callables: list[tuple[str, Any]] = []
    attributes = tuple(
        (
            name,
            _container_execution_identity(
                item, _callables=callables, _path=f"{path}.{name}"
            ),
        )
        for name, item in _namespace_items(namespace)
        if not _is_execution_observation_name(name)
    )
    return (
        id(value),
        id(type(value)),
        attributes,
        tuple(
            (child_path, _callable_graph_fingerprint(child))
            for child_path, child in callables
        ),
    )


@_bounded_seal
def _execution_configuration_fingerprint(
    value: Any,
    *,
    path: str = "value",
    expand_module: bool = False,
) -> tuple[Any, ...]:
    callable_children: list[tuple[str, Any]] = []
    identity = _container_execution_identity(
        value,
        _callables=callable_children,
        _path=path,
        _expand_module=expand_module,
    )
    graphs = tuple(
        (child_path, _callable_graph_fingerprint(child))
        for child_path, child in callable_children
    )
    return (identity, graphs)


@_bounded_seal
def _callable_graph_fingerprint(value: Any) -> tuple[Any, ...]:
    _verify_active_import_authority()
    function = _callable_function(value)
    active = _ACTIVE_CALLABLE_GRAPH_IDS.get()
    if id(function) in active:
        return (("recursive-root", id(function), id(type(function))),)
    token = _ACTIVE_CALLABLE_GRAPH_IDS.set(active | {id(function)})
    try:
        return _callable_graph_fingerprint_impl(value)
    finally:
        _ACTIVE_CALLABLE_GRAPH_IDS.reset(token)


def _callable_requires_transitive_seal(
    value: Any,
    parent_namespace: Mapping[str, Any] | None = None,
    _seen: set[int] | None = None,
) -> bool:
    """Keep Python project/helper graphs deep and dependency APIs opaque.

    Exact callable/code identity is always recorded.  Python source loaded from
    the reviewed project (or synthetic ``<string>`` test helpers) is traversed;
    stdlib/site-package implementations underneath the interpreter prefix are
    treated as sealed dependency entry points.  This prevents a reachable
    ``torch`` or ``pathlib`` API from recursively inventorying mutable process
    caches that are not part of the reviewed execution configuration.
    """
    pending = [(value, 0)]
    seen = set() if _seen is None else _seen
    runtime_prefix = os.path.normpath(sys.base_prefix)
    while pending:
        current, depth = pending.pop()
        _seal_visit()
        if depth > 96 or len(seen) > 10_000:
            raise DiagnosticError("callable classification exceeds depth or node limit")
        function = _callable_function(current)
        if id(function) in seen:
            continue
        seen.add(id(function))
        code = _callable_metadata(function, "__code__")
        if type(code) is not types.CodeType:
            continue
        filename = code.co_filename
        if filename == "<string>" or (
            not filename.startswith("<")
            and not os.path.normpath(filename).startswith(runtime_prefix + os.sep)
            and os.path.normpath(filename) != runtime_prefix
        ):
            return True
        wrapped = _callable_metadata(function, "__wrapped__")
        if callable(wrapped):
            pending.append((wrapped, depth + 1))
        for cell in _callable_metadata(function, "__closure__", ()) or ():
            try:
                child = cell.cell_contents
            except ValueError:
                continue
            if callable(child):
                pending.append((child, depth + 1))
    return False


def _materialize_callable_direct_imports(value: Any) -> None:
    """Resolve explicit import edges during trusted graph issuance."""
    function = _callable_function(value)
    code = _callable_metadata(function, "__code__", None)
    if code is None:
        return
    current_import = None
    for instruction in _seal_instructions(code):
        if instruction.opname == "IMPORT_NAME":
            current_import = str(instruction.argval)
            if _is_verified_snapshot_import(function, current_import):
                continue
            if current_import and current_import not in sys.modules:
                try:
                    importlib.import_module(current_import)
                except ModuleNotFoundError:
                    pass
        elif instruction.opname == "IMPORT_FROM" and current_import:
            if _is_verified_snapshot_import(function, current_import):
                continue
            imported_name = str(instruction.argval)
            parent = sys.modules.get(current_import)
            parent_namespace = (
                vars(parent) if isinstance(parent, types.ModuleType) else None
            )
            if (
                not isinstance(parent_namespace, dict)
                or imported_name not in parent_namespace
            ):
                try:
                    importlib.import_module(f"{current_import}.{imported_name}")
                except ModuleNotFoundError:
                    pass


def _referenced_attribute_values(function: Any, bound_self: Any):
    """Track static global/closure/default/local aliases without executing code.

    Unknown computed values terminate a chain. Known roots are recorded on every
    load, so attribute rebinding cannot hide behind a local alias or class MRO.
    """
    code = _callable_metadata(function, "__code__")
    if type(code) is not types.CodeType:
        return
    namespace = _callable_metadata(function, "__globals__", {})
    locals_ = {}
    defaults = _callable_metadata(function, "__defaults__", ()) or ()
    for name, item in zip(
        code.co_varnames[code.co_argcount - len(defaults) : code.co_argcount], defaults
    ):
        locals_[name] = item
    kwdefaults = _callable_metadata(function, "__kwdefaults__", {}) or {}
    if type(kwdefaults) is dict:
        locals_.update(kwdefaults)
    if bound_self is not None and code.co_argcount:
        locals_[code.co_varnames[0]] = bound_self
    for name, cell in zip(
        code.co_freevars, _callable_metadata(function, "__closure__", ()) or ()
    ):
        try:
            locals_[name] = cell.cell_contents
        except ValueError:
            pass
    unknown = object()
    target = unknown
    target_path = ""
    for instruction in _seal_instructions(code):
        _seal_visit()
        op, name = instruction.opname, instruction.argval
        if op in {"LOAD_GLOBAL", "LOAD_NAME"}:
            target = namespace.get(name, unknown)
            target_path = name
        elif op == "IMPORT_NAME":
            target = (
                unknown
                if _is_verified_snapshot_import(function, str(name))
                else sys.modules.get(str(name), unknown)
            )
            target_path = f"import[{name}]"
        elif op in {"LOAD_FAST", "LOAD_DEREF"}:
            target = locals_.get(name, unknown)
            target_path = name
        elif op in {"STORE_FAST", "STORE_DEREF"}:
            locals_[name] = target
            target = unknown
        elif op in {"LOAD_ATTR", "LOAD_METHOD"} and target is not unknown:
            if _is_execution_observation_name(name):
                target = unknown
                continue
            parent = target
            if (
                isinstance(parent, types.ModuleType)
                and name not in vars(parent)
                and _MATERIALIZE_CALLABLE_MODULE_ATTRIBUTES.get()
            ):
                try:
                    getattr(parent, name)
                except AttributeError:
                    pass
                except Exception as error:
                    raise DiagnosticError(
                        "imported module attribute materialization failed"
                    ) from error
            target = _static_attribute(parent, name, unknown)
            target_path = f"{target_path}.{name}"
            yield (
                target_path,
                id(parent),
                target is unknown,
                None if target is unknown else target,
            )
        elif op not in {"CACHE", "EXTENDED_ARG", "RESUME", "NOP", "PUSH_NULL"}:
            target = unknown


def _callable_graph_fingerprint_impl(value: Any) -> tuple[Any, ...]:
    """Identity-only seal of a callable and its reachable executable graph."""
    pending = [("root", value, 0)]
    queued = {id(_callable_function(value))}
    _seal_visit(value, executable=callable(value))
    seen: set[int] = set()
    records: list[Any] = []

    def queue(path: str, child: Any, *, transitive: bool = True) -> None:
        if not callable(child):
            return
        _seal_visit(child, executable=True)
        child_function = _callable_function(child)
        child_id = id(child_function)
        if not transitive:
            records.append(
                (
                    path,
                    "opaque-callable",
                    id(child_function),
                    id(_callable_metadata(child, "__self__", None)),
                    child_id,
                    id(_callable_metadata(child_function, "__code__", None)),
                    _graph_container_identity(
                        function, _callable_metadata(child_function, "__defaults__")
                    ),
                    _graph_container_identity(
                        function, _callable_metadata(child_function, "__kwdefaults__")
                    ),
                )
            )
            return
        if child_id in queued or child_id in seen:
            records.append((path, "edge", child_id))
            return
        queued.add(child_id)
        if current_depth >= 96:
            raise DiagnosticError("callable execution graph exceeds depth limit")
        pending.append((path, child, current_depth + 1))

    while pending:
        if len(records) > 10000:
            raise DiagnosticError("callable execution graph exceeds node limit")
        path, current, current_depth = pending.pop()
        original_value = current
        function = _callable_function(current)
        queued.discard(id(function))
        if not callable(function):
            records.append((path, "value", id(current), id(type(current))))
            continue
        if id(function) in seen:
            records.append((path, "seen", id(function)))
            continue
        # Mark before child discovery: builtin wrapper descriptors can point
        # back to their own type.__call__ surface.
        seen.add(id(function))
        if isinstance(function, type):
            # A class object executes its constructor surface, not every method
            # in its namespace.  Following all methods made an unrelated
            # ``pathlib.Path.expanduser -> os.environ`` branch part of the seal
            # and rejected valid reviewed callables.  Resolve __new__/__init__
            # plus only class helpers reachable from their bytecode.
            class_pending = ["__new__", "__init__"]
            class_seen: set[str] = set()
            while class_pending:
                member_name = class_pending.pop()
                if member_name in class_seen:
                    continue
                class_seen.add(member_name)
                member = None
                raw_member = None
                for candidate in type.__getattribute__(function, "__mro__"):
                    candidate_namespace = type.__getattribute__(candidate, "__dict__")
                    if member_name in candidate_namespace:
                        raw_member = candidate_namespace[member_name]
                        member = (
                            raw_member.__func__
                            if isinstance(raw_member, (staticmethod, classmethod))
                            else raw_member
                        )
                        break
                if not callable(member):
                    continue
                queue(
                    f"{path}.class[{member_name}]",
                    member,
                    transitive=_callable_requires_transitive_seal(member),
                )
                member_function = _callable_function(member)
                member_code = _callable_metadata(member_function, "__code__", None)
                if member_code is None:
                    continue
                for member_instruction in _seal_instructions(member_code):
                    if member_instruction.opname not in {"LOAD_ATTR", "LOAD_METHOD"}:
                        continue
                    reachable_name = str(member_instruction.argval)
                    if reachable_name in class_seen:
                        continue
                    if any(
                        reachable_name in type.__getattribute__(candidate, "__dict__")
                        and callable(_static_attribute(candidate, reachable_name))
                        for candidate in type.__getattribute__(function, "__mro__")
                    ):
                        class_pending.append(reachable_name)
            queue(
                f"{path}.type.__call__", _static_attribute(type(function), "__call__")
            )
        elif _callable_metadata(function, "__code__", None) is None:
            queue(f"{path}.type.__call__", _static_attribute(function, "__call__"))
        code = _callable_metadata(function, "__code__", None)
        defaults_records = []
        for defaults_name in ("__defaults__", "__kwdefaults__"):
            default_children = []
            defaults_records.append(
                _graph_container_identity(
                    function,
                    _callable_metadata(function, defaults_name),
                    _callables=default_children,
                    _path=f"{path}.{defaults_name}",
                )
            )
            for child_path, child in default_children:
                queue(
                    child_path,
                    child,
                    transitive=_callable_requires_transitive_seal(child),
                )
        closure_records = []
        for index, cell in enumerate(
            _callable_metadata(function, "__closure__", ()) or ()
        ):
            try:
                content = cell.cell_contents
            except ValueError:
                content = None
            children: list[tuple[str, Any]] = []
            identity = _graph_container_identity(
                function, content, _callables=children, _path=f"{path}.closure[{index}]"
            )
            closure_records.append((index, id(cell), identity))
            for child_path, child in children:
                queue(
                    child_path,
                    child,
                    transitive=_callable_requires_transitive_seal(
                        child, _callable_metadata(function, "__globals__", None)
                    ),
                )
        instructions = _seal_instructions(code)
        if _MATERIALIZE_CALLABLE_MODULE_ATTRIBUTES.get():
            # IMPORT_FROM may initialize a reviewed dependency's lazy callable
            # wrappers.  Perform that exact import transition before recording
            # any identities, while no capability has yet been issued.  A live
            # validation pass never imports or resolves a missing attribute.
            _materialize_callable_direct_imports(function)
            # An opaque dependency entry point may itself perform an
            # IMPORT_FROM transition which replaces other public wrappers.
            # Materialize every exact bytecode-referenced module attribute
            # before recording *any* sibling identity, while issuance is still
            # trusted.  No dependency callable is executed.
            namespace_for_materialization = _callable_metadata(
                function, "__globals__", None
            )
            for materialize_index, materialize_instruction in enumerate(instructions):
                if materialize_instruction.opname not in {"LOAD_GLOBAL", "LOAD_NAME"}:
                    continue
                materialize_name = str(materialize_instruction.argval)
                if (
                    not isinstance(namespace_for_materialization, dict)
                    or materialize_name not in namespace_for_materialization
                ):
                    continue
                materialize_target = namespace_for_materialization[materialize_name]
                if not isinstance(materialize_target, types.ModuleType):
                    if callable(materialize_target):
                        _materialize_callable_direct_imports(materialize_target)
                    continue
                for materialize_child in instructions[materialize_index + 1 :]:
                    if materialize_child.opname not in {"LOAD_ATTR", "LOAD_METHOD"}:
                        break
                    materialize_attribute = str(materialize_child.argval)
                    materialize_namespace = (
                        vars(materialize_target)
                        if isinstance(materialize_target, types.ModuleType)
                        else _safe_instance_dict(materialize_target)
                    )
                    if (
                        isinstance(materialize_target, types.ModuleType)
                        and isinstance(materialize_namespace, dict)
                        and materialize_attribute not in materialize_namespace
                    ):
                        try:
                            getattr(materialize_target, materialize_attribute)
                        except AttributeError:
                            break
                        except Exception as error:
                            raise DiagnosticError(
                                "callable module attribute materialization failed"
                            ) from error
                        materialize_namespace = vars(materialize_target)
                    if (
                        not isinstance(materialize_namespace, dict)
                        or materialize_attribute not in materialize_namespace
                    ):
                        break
                    materialize_target = materialize_namespace[materialize_attribute]
                    if callable(materialize_target):
                        _materialize_callable_direct_imports(materialize_target)
        global_names = sorted(
            {
                str(instruction.argval)
                for instruction in instructions
                if instruction.opname in {"LOAD_GLOBAL", "LOAD_NAME"}
            }
        )
        global_records = []
        namespace = _callable_metadata(function, "__globals__", None)
        for name in global_names:
            if not isinstance(namespace, dict) or name not in namespace:
                continue
            target = namespace[name]
            children = []
            identity = _graph_container_identity(
                function, target, _callables=children, _path=f"{path}.global[{name}]"
            )
            global_records.append((name, identity))
            for child_path, child in children:
                queue(
                    child_path,
                    child,
                    transitive=_callable_requires_transitive_seal(child, namespace),
                )
        # Seal only module/object attributes that this bytecode actually reads.
        # Expanding an entire module namespace is both unnecessary and unsafe;
        # following the concrete LOAD_* -> LOAD_ATTR/LOAD_METHOD chain catches
        # monkey-patching without invoking a module-level ``__getattr__``.
        closure_values = []
        for cell in _callable_metadata(function, "__closure__", ()) or ():
            try:
                closure_values.append(cell.cell_contents)
            except ValueError:
                closure_values.append(None)
        closure_by_name = dict(
            zip(
                getattr(code, "co_freevars", ()) if code is not None else (),
                closure_values,
            )
        )
        attribute_records = []
        for attribute_path, parent_id, missing, target in _referenced_attribute_values(
            function, _callable_metadata(current, "__self__")
        ):
            children = []
            identity = _graph_container_identity(
                function,
                target,
                _callables=children,
                _path=f"{path}.resolved[{attribute_path}]",
            )
            attribute_records.append(
                ("resolved", attribute_path, parent_id, missing, identity)
            )
            for child_path, child in children:
                queue(
                    child_path,
                    child,
                    transitive=_callable_requires_transitive_seal(child, namespace),
                )
        for index, instruction in enumerate(instructions):
            if instruction.opname in {"LOAD_GLOBAL", "LOAD_NAME"}:
                base_name = str(instruction.argval)
                if not isinstance(namespace, dict) or base_name not in namespace:
                    continue
                target = namespace[base_name]
            elif instruction.opname == "LOAD_DEREF":
                base_name = str(instruction.argval)
                if base_name not in closure_by_name:
                    continue
                target = closure_by_name[base_name]
            else:
                continue
            if not isinstance(target, types.ModuleType):
                continue
            attribute_path = base_name
            for child_instruction in instructions[index + 1 :]:
                if child_instruction.opname not in {"LOAD_ATTR", "LOAD_METHOD"}:
                    break
                attribute_name = str(child_instruction.argval)
                target_namespace = (
                    vars(target)
                    if isinstance(target, types.ModuleType)
                    else _safe_instance_dict(target)
                )
                if (
                    isinstance(target, types.ModuleType)
                    and isinstance(target_namespace, dict)
                    and attribute_name not in target_namespace
                    and _MATERIALIZE_CALLABLE_MODULE_ATTRIBUTES.get()
                ):
                    # Some reviewed dependencies expose bytecode-referenced
                    # submodules lazily (for example ``numpy.random``).  Resolve
                    # that exact attribute chain only while issuing the trusted
                    # graph.  Liveness checks never call module ``__getattr__``;
                    # they compare the already-materialized object identity.
                    try:
                        getattr(target, attribute_name)
                    except AttributeError:
                        pass
                    except Exception as error:
                        raise DiagnosticError(
                            "callable module attribute materialization failed"
                        ) from error
                    target_namespace = vars(target)
                if (
                    not isinstance(target_namespace, dict)
                    or attribute_name not in target_namespace
                ):
                    attribute_records.append(
                        (
                            instruction.opname,
                            base_name,
                            f"{attribute_path}.{attribute_name}",
                            "unavailable",
                            id(target),
                            id(type(target)),
                        )
                    )
                    break
                target = target_namespace[attribute_name]
                attribute_path = f"{attribute_path}.{attribute_name}"
                children = []
                identity = _graph_container_identity(
                    function,
                    target,
                    _callables=children,
                    _path=f"{path}.attribute[{attribute_path}]",
                )
                attribute_records.append(
                    (
                        instruction.opname,
                        base_name,
                        attribute_path,
                        identity,
                    )
                )
                for child_path, child in children:
                    queue(
                        child_path,
                        child,
                        transitive=_callable_requires_transitive_seal(child, namespace),
                    )
        queue(f"{path}.__wrapped__", _callable_metadata(function, "__wrapped__", None))
        import_records = []
        current_module = None
        for instruction in instructions:
            if instruction.opname == "IMPORT_NAME":
                current_module = str(instruction.argval)
                if _is_verified_snapshot_import(function, current_module):
                    import_records.append(
                        (current_module, "sha-verified-snapshot-import")
                    )
                    continue
                imported_module = sys.modules.get(current_module)
                import_records.append(
                    (current_module, "module-binding", id(imported_module))
                )
            elif instruction.opname == "IMPORT_FROM" and current_module:
                if _is_verified_snapshot_import(function, current_module):
                    import_records.append(
                        (current_module, str(instruction.argval), "snapshot-export")
                    )
                    continue
                module = sys.modules.get(current_module)
                module_namespace = (
                    vars(module) if isinstance(module, types.ModuleType) else None
                )
                imported = (
                    module_namespace.get(str(instruction.argval))
                    if isinstance(module_namespace, dict)
                    else None
                )
                children = []
                identity = _graph_container_identity(
                    function,
                    imported,
                    _callables=children,
                    _path=f"{path}.import[{current_module}.{instruction.argval}]",
                )
                import_records.append(
                    (current_module, str(instruction.argval), id(module), identity)
                )
                for child_path, child in children:
                    queue(
                        child_path,
                        child,
                        transitive=_callable_requires_transitive_seal(child),
                    )
        bound_self = _callable_metadata(current, "__self__", None)
        self_record = None
        if bound_self is not None and not isinstance(bound_self, type):
            if code is None:
                # Native extension method state can be enormous and mutable as
                # ordinary runtime state (for example NumPy's RandomState).
                # Its exact bound-object/callable identity is the executable
                # seal; Python callable objects remain recursively configured.
                self_record = (
                    "opaque-native-bound-self",
                    id(bound_self),
                    id(type(bound_self)),
                )
            else:
                bound_namespace = _safe_instance_dict(bound_self)
                if bound_namespace is not None and not isinstance(
                    bound_namespace.get("_modules"), dict
                ):
                    self_record = _instance_execution_configuration(
                        bound_self, path=f"{path}.__self__"
                    )
                else:
                    self_record = (
                        "module-reference",
                        id(bound_self),
                        id(type(bound_self)),
                    )
        object_record = None
        if code is None and not isinstance(original_value, type):
            namespace_record = _safe_instance_dict(original_value)
            if namespace_record is not None:
                if isinstance(namespace_record.get("_modules"), dict):
                    object_record = (
                        "module-reference",
                        id(original_value),
                        id(type(original_value)),
                    )
                else:
                    object_record = _instance_execution_configuration(
                        original_value, path=f"{path}.__callable__"
                    )
        records.append(
            (
                path,
                id(current) if code is None else 0,
                id(bound_self),
                id(function),
                id(code),
                *defaults_records,
                tuple(closure_records),
                tuple(global_records),
                tuple(attribute_records),
                tuple(import_records),
                id(original_value) if isinstance(original_value, type) else 0,
                self_record,
                object_record,
            )
        )
    return tuple(sorted(records, key=lambda item: item[0]))


@_bounded_seal
def _callable_graphs(
    values: Mapping[str, Any],
    *,
    materialize_module_attributes: bool = False,
) -> Mapping[str, Any]:
    token = None
    if materialize_module_attributes:
        token = _MATERIALIZE_CALLABLE_MODULE_ATTRIBUTES.set(True)
    try:
        return types.MappingProxyType(
            {name: _callable_graph_fingerprint(value) for name, value in values.items()}
        )
    finally:
        if token is not None:
            _MATERIALIZE_CALLABLE_MODULE_ATTRIBUTES.reset(token)


def _materialized_model_execution_fingerprint(
    model: Any,
    module_inventory: Sequence[Any],
) -> tuple[Any, ...]:
    """Issue a model seal after resolving only its reachable lazy imports."""
    token = _MATERIALIZE_CALLABLE_MODULE_ATTRIBUTES.set(True)
    try:
        return _model_execution_fingerprint(model, module_inventory)
    finally:
        _MATERIALIZE_CALLABLE_MODULE_ATTRIBUTES.reset(token)


@_bounded_seal
def _class_reachable_callable_fingerprint(
    value: Any,
    entry_names: Sequence[str],
) -> tuple[Any, ...]:
    """Seal class/MRO callables reachable from the actual dispatch entries.

    Resolution reads class dictionaries directly, so a hostile descriptor is
    never executed by the liveness check.  Only method names referenced by the
    selected bytecode are followed; broad framework class scans are avoided.
    """
    value_type = type(value)
    mro = tuple(type.__getattribute__(value_type, "__mro__"))
    pending = list(reversed(tuple(dict.fromkeys(str(name) for name in entry_names))))
    queued = set(pending)
    seen: set[str] = set()
    records = []

    def resolve(name: str) -> tuple[Any, Any, Any] | None:
        for owner in mro:
            namespace = type.__getattribute__(owner, "__dict__")
            if name not in namespace:
                continue
            raw = namespace[name]
            member = (
                raw.__func__ if isinstance(raw, (staticmethod, classmethod)) else raw
            )
            return owner, raw, member
        return None

    while pending:
        _seal_visit()
        name = pending.pop()
        queued.discard(name)
        if name in seen:
            continue
        seen.add(name)
        resolved = resolve(name)
        if resolved is None:
            records.append((name, "unavailable"))
            continue
        owner, raw, member = resolved
        if not callable(member):
            records.append(
                (
                    name,
                    "noncallable",
                    id(owner),
                    id(raw),
                    id(type(raw)),
                )
            )
            continue
        graph = _callable_graph_fingerprint(member)
        records.append((name, id(owner), id(raw), id(member), graph))
        function = _callable_function(member)
        code = _callable_metadata(function, "__code__", None)
        if code is None:
            continue
        for instruction in _seal_instructions(code):
            if instruction.opname not in {"LOAD_ATTR", "LOAD_METHOD"}:
                continue
            child_name = str(instruction.argval)
            child = resolve(child_name)
            if (
                child is not None
                and callable(child[2])
                and child_name not in seen
                and child_name not in queued
            ):
                queued.add(child_name)
                pending.append(child_name)
    return (
        tuple(id(owner) for owner in mro),
        tuple(sorted(records, key=lambda item: item[0])),
    )


def _deep_frozen_records(
    records: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    return tuple(_deep_immutable(record) for record in records)


def _deep_immutable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return types.MappingProxyType(
            {key: _deep_immutable(item) for key, item in value.items()}
        )
    if isinstance(value, (tuple, list)):
        return tuple(_deep_immutable(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_deep_immutable(item) for item in value)
    return value


def _deep_plain_record(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _deep_plain_record(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_deep_plain_record(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_deep_plain_record(item) for item in value), key=repr)
    return value


def _frozen_capability_issuance_receipt(
    capability: _FrozenContextCapability,
) -> tuple[Any, ...]:
    """Independent immutable anchors for a mutable-runtime capability."""
    return (
        capability,
        capability.evaluator,
        capability.manifest,
        capability.evaluator_record,
        capability.manifest_record,
        capability.pinned_records,
        capability.source_records,
        capability.root,
        capability.source_root,
        capability.trust_domain,
        capability.nonce,
        capability.evaluator_callables,
        capability.evaluator_callable_graphs,
        capability.manifest_snapshot,
        capability.pinned_records_snapshot,
        capability.source_records_snapshot,
        capability.manifest_sha256,
        capability.pinned_records_sha256,
        capability.source_records_sha256,
    )


def _frozen_capability_receipt_matches(
    capability: _FrozenContextCapability,
    receipt: Any,
) -> bool:
    if not isinstance(receipt, tuple) or len(receipt) != 19:
        return False
    return (
        receipt[0] is capability
        and capability.evaluator is receipt[1]
        and capability.manifest is receipt[2]
        and capability.evaluator_record is receipt[3]
        and capability.manifest_record is receipt[4]
        and capability.pinned_records is receipt[5]
        and capability.source_records is receipt[6]
        and capability.root is receipt[7]
        and capability.source_root is receipt[8]
        and capability.trust_domain is receipt[9]
        and capability.nonce is receipt[10]
        and capability.evaluator_callables is receipt[11]
        and capability.evaluator_callable_graphs is receipt[12]
        and capability.manifest_snapshot is receipt[13]
        and capability.pinned_records_snapshot is receipt[14]
        and capability.source_records_snapshot is receipt[15]
        and capability.manifest_sha256 is receipt[16]
        and capability.pinned_records_sha256 is receipt[17]
        and capability.source_records_sha256 is receipt[18]
    )


def _model_inventory_identity_snapshot(
    inventory: Sequence[Any],
) -> tuple[Any, ...]:
    return tuple(
        (
            name,
            id(module),
            id(children),
            tuple((child_name, id(child)) for child_name, child in edges),
        )
        for name, module, children, edges in inventory
    )


def _formal40_attestation_issuance_receipt(
    attestation: _Formal40WorkerAttestation,
) -> tuple[Any, ...]:
    return (
        attestation,
        attestation.evaluator,
        attestation.model,
        attestation.load_report,
        _get_trace().canonical_json_bytes(attestation.load_report),
        attestation.frozen_capability,
        attestation.scene_api,
        (
            attestation.diagnostic_protocol,
            attestation.v4_protocol,
            attestation.evaluator_sha256,
            attestation.manifest_sha256,
            attestation.load_report_sha256,
            attestation.worker_pid,
            attestation.worker_nonce,
            attestation.model_nonce,
            attestation.input_context_sha256,
            attestation.scene_scope_nonce,
        ),
        attestation.imported_source_records,
        attestation.evaluator_authority_callables,
        attestation.scene_callables,
        attestation.model_callables,
        attestation.scene_callable_graphs,
        attestation.model_callable_graphs,
        attestation.operator_authorities,
        attestation.model_module_inventory,
        _model_inventory_identity_snapshot(attestation.model_module_inventory),
        attestation.model_execution_fingerprint,
        attestation.imported_source_snapshot,
    )


def _formal40_attestation_receipt_matches(
    attestation: _Formal40WorkerAttestation,
    receipt: Any,
) -> bool:
    if not isinstance(receipt, tuple) or len(receipt) != 19:
        return False
    scalars = (
        attestation.diagnostic_protocol,
        attestation.v4_protocol,
        attestation.evaluator_sha256,
        attestation.manifest_sha256,
        attestation.load_report_sha256,
        attestation.worker_pid,
        attestation.worker_nonce,
        attestation.model_nonce,
        attestation.input_context_sha256,
        attestation.scene_scope_nonce,
    )
    return (
        receipt[0] is attestation
        and attestation.evaluator is receipt[1]
        and attestation.model is receipt[2]
        and attestation.load_report is receipt[3]
        and _get_trace().canonical_json_bytes(attestation.load_report) == receipt[4]
        and attestation.frozen_capability is receipt[5]
        and attestation.scene_api is receipt[6]
        and all(live is issued for live, issued in zip(scalars, receipt[7]))
        and attestation.imported_source_records is receipt[8]
        and attestation.evaluator_authority_callables is receipt[9]
        and attestation.scene_callables is receipt[10]
        and attestation.model_callables is receipt[11]
        and attestation.scene_callable_graphs is receipt[12]
        and attestation.model_callable_graphs is receipt[13]
        and attestation.operator_authorities is receipt[14]
        and attestation.model_module_inventory is receipt[15]
        and _model_inventory_identity_snapshot(attestation.model_module_inventory)
        == receipt[16]
        and attestation.model_execution_fingerprint is receipt[17]
        and attestation.imported_source_snapshot is receipt[18]
    )


@_bounded_seal
def _direct_model_module_inventory(model: Any) -> tuple[Any, ...]:
    """Discover module edges without calling mutable ``named_modules`` code."""
    pending = [("", model)]
    expanded: set[int] = set()
    inventory = []
    while pending:
        _seal_visit()
        name, module = pending.pop()
        namespace = _safe_instance_dict(module)
        children = namespace.get("_modules") if namespace is not None else None
        edges = _native_registry_items(children)
        # AudioCompose keeps transforms in an ordinary list, outside _modules.
        # Include those modules in the same state/dispatch inventory.
        containers = [("transforms", namespace.get("transforms"))]
        audio = namespace.get("audio_transforms")
        audio_namespace = _safe_instance_dict(audio)
        if audio_namespace is not None:
            containers.append(
                ("audio_transforms.transforms", audio_namespace.get("transforms"))
            )
        extra = []
        for prefix, sequence in containers:
            if sequence is None:
                continue
            if type(sequence) not in (tuple, list):
                raise DiagnosticError("audio transform container is not ordered")
            for index, child in enumerate(sequence):
                _seal_visit()
                child_namespace = _safe_instance_dict(child)
                if child_namespace is not None and "_modules" in child_namespace:
                    _native_registry_items(child_namespace["_modules"])
                    extra.append((f"{prefix}[{index}]", child))
        edges += tuple(extra)
        inventory.append((name, module, children, edges))
        if id(module) in expanded:
            continue
        expanded.add(id(module))
        for child_name, child in reversed(edges):
            if child is not None:
                path = f"{name}.{child_name}" if name else child_name
                pending.append((path, child))
    return tuple(inventory)


def _validate_model_module_inventory(
    model: Any,
    frozen: Sequence[Any],
) -> None:
    current = _direct_model_module_inventory(model)
    if len(current) != len(frozen):
        raise DiagnosticError("model module inventory changed")
    for live, sealed in zip(current, frozen):
        live_name, live_module, live_children, live_edges = live
        sealed_name, sealed_module, sealed_children, sealed_edges = sealed
        if (
            live_name != sealed_name
            or live_module is not sealed_module
            or live_children is not sealed_children
            or len(live_edges) != len(sealed_edges)
            or any(
                left_name != right_name or left_child is not right_child
                for (left_name, left_child), (right_name, right_child) in zip(
                    live_edges, sealed_edges
                )
            )
        ):
            raise DiagnosticError("model module inventory changed")


@_bounded_seal
def _registered_state_fingerprint(module: Any, name: str) -> tuple[Any, ...]:
    namespace = _safe_instance_dict(module)
    value = namespace.get(name) if namespace is not None else None
    records = []
    for key, tensor in _native_registry_items(value):
        _seal_visit()
        if type(key) is not str:
            raise DiagnosticError("model state registry has a non-string key")
        version: Any = None
        if tensor is not None:
            _require_plain_state_tensor(tensor)
            try:
                version = int(tensor._version)
            except (AttributeError, RuntimeError):
                version = "unavailable"
        records.append(
            (
                key,
                id(tensor),
                id(type(tensor)),
                version,
                tensor.requires_grad if tensor is not None else False,
                _state_tensor_layout(tensor) if tensor is not None else None,
            )
        )
    return (id(value), tuple(records))


def _direct_module_training_state(module: Any) -> bool:
    namespace = _safe_instance_dict(module)
    value = namespace.get("training") if namespace is not None else None
    if not isinstance(value, bool):
        raise DiagnosticError("model module training state is unavailable")
    return value


@_bounded_seal
def _require_registered_modules_eval(model: Any) -> None:
    """Check the native eval recursion scope without changing any modes.

    AudioCompose's list-held transforms are execution dependencies, not native
    registered children. Their original modes remain sealed by the complete
    execution inventory/fingerprint; they are not forced into a different mode.
    """
    pending = [model]
    visited: set[int] = set()
    while pending:
        _seal_visit()
        module = pending.pop()
        if id(module) in visited:
            continue
        visited.add(id(module))
        if _direct_module_training_state(module):
            raise DiagnosticError("strict-loaded formal40 module is not in eval mode")
        namespace = _safe_instance_dict(module)
        children = namespace.get("_modules") if namespace is not None else None
        for _, child in _native_registry_items(children):
            if child is not None:
                pending.append(child)


def _require_frozen_direct_parameters(module_inventory: Sequence[Any]) -> None:
    """Reject trainable state without calling replaceable discovery methods."""
    for _, module, _, _ in module_inventory:
        namespace = _safe_instance_dict(module)
        parameters = namespace.get("_parameters") if namespace is not None else None
        for name, parameter in _native_registry_items(parameters):
            if type(name) is not str:
                raise DiagnosticError(
                    "strict-loaded formal40 parameter registry is invalid"
                )
            if parameter is None:
                continue
            _require_plain_state_tensor(parameter)
            requires_grad = getattr(parameter, "requires_grad", None)
            if not isinstance(requires_grad, bool):
                raise DiagnosticError(
                    "strict-loaded formal40 parameter registry is invalid"
                )
            if requires_grad:
                raise DiagnosticError("strict-loaded formal40 has trainable parameters")


def _module_config_fingerprint(module: Any) -> tuple[Any, ...]:
    namespace = _safe_instance_dict(module)
    if namespace is None:
        raise DiagnosticError("model module configuration is unavailable")
    excluded = {
        "_parameters",
        "_buffers",
        "_modules",
        "training",
        *_MODULE_HOOK_NAMES,
        *_MODULE_HOOK_FLAG_NAMES,
        *_EXECUTION_OBSERVATION_ATTRIBUTES,
    }
    return tuple(
        (
            name,
            _execution_configuration_fingerprint(
                value, path=f"module.{name}", expand_module=True
            ),
        )
        for name, value in _namespace_items(namespace)
        if name not in excluded and not _is_execution_observation_name(name)
    )


@_bounded_seal
def _audio_transform_fingerprint(audio: Any) -> tuple[Any, ...]:
    transforms = _static_attribute(audio, "transforms")
    children = []
    if transforms is not None:
        if type(transforms) not in (tuple, list):
            raise DiagnosticError("audio transform container is not ordered")
        for index, child in enumerate(transforms):
            namespace = _safe_instance_dict(child)
            child_config = None
            child_training = None
            if namespace is not None:
                child_training = namespace.get("training")
                if child_training is not None and not isinstance(child_training, bool):
                    raise DiagnosticError("audio child training state is invalid")
                child_config = tuple(
                    (
                        name,
                        _execution_configuration_fingerprint(
                            item, path=f"audio[{index}].{name}", expand_module=True
                        ),
                    )
                    for name, item in _namespace_items(namespace)
                    if name
                    not in {
                        "_parameters",
                        "_buffers",
                        "_modules",
                        "training",
                        *_MODULE_HOOK_NAMES,
                        *_MODULE_HOOK_FLAG_NAMES,
                        *_EXECUTION_OBSERVATION_ATTRIBUTES,
                    }
                    and not _is_execution_observation_name(name)
                )
            children.append(
                (
                    index,
                    id(child),
                    id(type(child)),
                    _callable_graph_fingerprint(child),
                    _callable_graph_fingerprint(_static_attribute(child, "forward"))
                    if callable(_static_attribute(child, "forward"))
                    else None,
                    child_training,
                    _class_reachable_callable_fingerprint(
                        child,
                        ("__call__", "_wrapped_call_impl", "_call_impl", "forward"),
                    ),
                    child_config,
                )
            )
    return (
        id(audio),
        id(type(audio)),
        _callable_graph_fingerprint(audio),
        _class_reachable_callable_fingerprint(
            audio, ("__call__", "_wrapped_call_impl", "_call_impl", "forward")
        ),
        id(transforms),
        tuple(children),
    )


@_bounded_seal
def _model_execution_fingerprint(
    model: Any,
    module_inventory: Sequence[Any] | None = None,
) -> tuple[Any, ...]:
    modules = (
        tuple(module_inventory)
        if module_inventory is not None
        else _direct_model_module_inventory(model)
    )
    if module_inventory is not None:
        _validate_model_module_inventory(model, modules)
    records = []
    for name, module, children, edges in modules:
        hooks = []
        namespace = _safe_instance_dict(module)
        if namespace is None:
            raise DiagnosticError("model module configuration is unavailable")
        for hook_name in _MODULE_HOOK_NAMES:
            value = namespace.get(hook_name)
            if not isinstance(value, Mapping):
                raise DiagnosticError(f"model hook registry unavailable: {hook_name}")
            hooks.append(
                (
                    hook_name,
                    _execution_configuration_fingerprint(
                        value, path=f"{name}.{hook_name}"
                    ),
                )
            )
        hook_flags = tuple(
            (
                flag_name,
                _execution_configuration_fingerprint(
                    namespace.get(flag_name), path=f"{name}.{flag_name}"
                ),
            )
            for flag_name in _MODULE_HOOK_FLAG_NAMES
        )
        dispatch = tuple(
            (dispatch_name, _callable_graph_fingerprint(dispatch_value))
            for dispatch_name, dispatch_value in (
                ("forward", _static_attribute(module, "forward")),
                ("resolved_call", _static_attribute(module, "__call__")),
                ("resolved_call_impl", _static_attribute(module, "_call_impl")),
                (
                    "resolved_wrapped_call_impl",
                    _static_attribute(module, "_wrapped_call_impl"),
                ),
                ("type_call", _static_attribute(type(module), "__call__")),
                ("type_call_impl", _static_attribute(type(module), "_call_impl")),
                (
                    "type_wrapped_call_impl",
                    _static_attribute(type(module), "_wrapped_call_impl"),
                ),
            )
            if callable(dispatch_value)
        )
        records.append(
            (
                name,
                id(module),
                id(type(module)),
                id(children),
                tuple((child_name, id(child)) for child_name, child in edges),
                _direct_module_training_state(module),
                dispatch,
                tuple(hooks),
                hook_flags,
                _registered_state_fingerprint(module, "_parameters"),
                _registered_state_fingerprint(module, "_buffers"),
                _class_reachable_callable_fingerprint(
                    module,
                    (
                        "__call__",
                        "_wrapped_call_impl",
                        "_call_impl",
                        "forward",
                        "__getattribute__",
                        "__getattr__",
                    ),
                ),
                _module_config_fingerprint(module),
            )
        )
    audio = _static_attribute(model, "audio_transforms")
    records.append(("__audio_transforms__", _audio_transform_fingerprint(audio)))
    return tuple(records)


def _revoke_capability(capability: _FrozenContextCapability) -> None:
    _REVOKED_FROZEN_CONTEXT_CAPABILITIES.add(id(capability))


def _revoke_attestation(attestation: _Formal40WorkerAttestation) -> None:
    _REVOKED_FORMAL40_ATTESTATIONS.add(id(attestation))
    receipt = _FORMAL40_ATTESTATION_RECEIPTS.get(id(attestation))
    issued_capability = (
        receipt[5]
        if isinstance(receipt, tuple)
        and len(receipt) == 19
        and isinstance(receipt[5], _FrozenContextCapability)
        else None
    )
    if issued_capability is not None:
        _revoke_capability(issued_capability)
    try:
        live_capability = attestation.frozen_capability
    except (AttributeError, TypeError):
        live_capability = None
    if (
        isinstance(live_capability, _FrozenContextCapability)
        and live_capability is not issued_capability
    ):
        _revoke_capability(live_capability)


@_bounded_seal
def _validate_frozen_capability_contents(
    capability: _FrozenContextCapability,
) -> None:
    """Fail closed if any mutable object/record changed after capability issue."""
    try:
        trace = _get_trace()
        receipt = _FROZEN_CONTEXT_CAPABILITY_RECEIPTS.get(id(capability))
        invalid = (
            not isinstance(capability, _FrozenContextCapability)
            or id(capability) in _REVOKED_FROZEN_CONTEXT_CAPABILITIES
            or _ISSUED_FROZEN_CONTEXT_CAPABILITIES.get(id(capability)) is not capability
            or not _frozen_capability_receipt_matches(capability, receipt)
            or any(
                not _callable_anchor_matches(
                    _static_attribute(capability.evaluator, name), callable_value
                )
                for name, callable_value in capability.evaluator_callables.items()
            )
            or any(
                _callable_graph_fingerprint(
                    _static_attribute(capability.evaluator, name)
                )
                != graph
                for name, graph in capability.evaluator_callable_graphs.items()
            )
            or trace.canonical_json_bytes(capability.manifest)
            != capability.manifest_snapshot
            or trace.canonical_json_bytes(
                tuple(dict(item) for item in capability.pinned_records)
            )
            != capability.pinned_records_snapshot
            or trace.canonical_json_bytes(
                tuple(dict(item) for item in capability.source_records)
            )
            != capability.source_records_snapshot
        )
        if invalid:
            raise DiagnosticError("frozen capability contents changed")
    except BaseException as error:
        if isinstance(capability, _FrozenContextCapability):
            _revoke_capability(capability)
        if isinstance(error, DiagnosticError):
            raise
        if isinstance(error, Exception):
            raise DiagnosticError("frozen capability validation failed") from error
        raise


def _validate_frozen_capability_liveness(
    capability: _FrozenContextCapability,
) -> None:
    """Identity/content comparison only; performs no digest or tensor work."""
    _validate_frozen_capability_contents(capability)


def production_contract() -> FrozenContract:
    return FrozenContract(
        V4_ROOT,
        V4_PROTOCOL,
        EVALUATION_ROLE,
        V4_EVALUATOR_SHA256,
        V4_RUNNER_SHA256,
        V4_MANIFEST_SHA256,
        V4_LOCK_SHA256,
        FORMAL40_SHA256,
    )


def _contract_json(contract: FrozenContract) -> dict[str, Any]:
    value = dataclasses.asdict(contract)
    value["v4_root"] = str(contract.v4_root)
    return value


def _canonical_contained(
    path: pathlib.Path, allowed_root: pathlib.Path
) -> tuple[pathlib.Path, pathlib.Path]:
    try:
        root = pathlib.Path(allowed_root).resolve(strict=True)
        if not stat.S_ISDIR(os.lstat(root).st_mode):
            raise DiagnosticError("allowed root is not a real directory")
        candidate = pathlib.Path(path)
        if not candidate.is_absolute():
            candidate = pathlib.Path.cwd() / candidate
        canonical = candidate.parent.resolve(strict=True) / candidate.name
        canonical.relative_to(root)
    except (OSError, ValueError) as error:
        raise DiagnosticError(
            "source path escapes or has an unavailable allowed root"
        ) from error
    return canonical, root


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_mode,
        left.st_nlink,
        left.st_size,
        left.st_mtime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_mode,
        right.st_nlink,
        right.st_size,
        right.st_mtime_ns,
    )


def _same_directory_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(left.st_mode)
        and stat.S_ISDIR(right.st_mode)
        and (left.st_dev, left.st_ino, left.st_mode)
        == (right.st_dev, right.st_ino, right.st_mode)
    )


def _read_stable_source_bytes(
    path: pathlib.Path, *, allowed_root: pathlib.Path
) -> tuple[bytes, dict[str, object]]:
    """Stdlib-only trust bootstrap; never consults numeric_trace or bytecode."""
    canonical, root = _canonical_contained(path, allowed_root)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if not isinstance(nofollow, int) or nofollow == 0:
        raise DiagnosticError("O_NOFOLLOW is unavailable")
    try:
        named_before = os.lstat(canonical)
        if not stat.S_ISREG(named_before.st_mode) or named_before.st_nlink != 1:
            raise DiagnosticError("source must be an ordinary single-link file")
        descriptor = os.open(canonical, os.O_RDONLY | nofollow)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or not _same_identity(named_before, opened)
            ):
                raise DiagnosticError("source changed before descriptor open")
            chunks = []
            while True:
                chunk = os.read(descriptor, 1 << 20)
                if not chunk:
                    break
                chunks.append(chunk)
            after_read = os.fstat(descriptor)
            if not _same_identity(opened, after_read):
                raise DiagnosticError("source changed during descriptor read")
        finally:
            os.close(descriptor)
        named_after = os.lstat(canonical)
        if not _same_identity(after_read, named_after):
            raise DiagnosticError("source pathname changed after descriptor read")
    except DiagnosticError:
        raise
    except OSError as error:
        raise DiagnosticError(f"cannot read stable source: {canonical}") from error
    payload = b"".join(chunks)
    return payload, {
        "path": str(canonical),
        "relative_path": canonical.relative_to(root).as_posix(),
        "type": "file",
        "mode": stat.S_IMODE(after_read.st_mode),
        "size": len(payload),
        "st_mtime_ns": after_read.st_mtime_ns,
        "st_dev": after_read.st_dev,
        "st_ino": after_read.st_ino,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def load_verified_source_module(
    path: pathlib.Path, *, expected_size: int, expected_sha256: str, module_name: str
) -> types.ModuleType:
    source, record = _read_stable_source_bytes(
        path, allowed_root=pathlib.Path(path).parent
    )
    if record["size"] != expected_size or record["sha256"] != expected_sha256:
        raise DiagnosticError(f"verified source identity mismatch: {path}")
    if module_name in sys.modules:
        raise DiagnosticError(f"module name already loaded: {module_name}")
    module = types.ModuleType(module_name)
    module.__file__ = str(record["path"])
    module.__package__ = module_name.rpartition(".")[0]
    module.__loader__ = None
    module.__spec__ = importlib.util.spec_from_loader(
        module_name, loader=None, origin=module.__file__
    )
    sys.modules[module_name] = module
    try:
        exec(
            compile(source, module.__file__, "exec", dont_inherit=True, optimize=0),
            module.__dict__,
        )
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


_TRACE: types.ModuleType | None = None


def _get_trace() -> types.ModuleType:
    global _TRACE
    if _TRACE is None:
        _TRACE = load_verified_source_module(
            PACKAGE_ROOT / "numeric_trace.py",
            expected_size=NUMERIC_TRACE_SIZE,
            expected_sha256=NUMERIC_TRACE_SHA256,
            module_name="_numeric_trace_verified",
        )
    return _TRACE


def load_verified_v4_evaluator(
    trace: types.ModuleType,
    path: pathlib.Path,
    expected_size: int,
    expected_sha256: str,
    *,
    allowed_root: pathlib.Path | None = None,
) -> types.SimpleNamespace:
    try:
        payload, record = trace.read_stable_bytes(
            path,
            allowed_root=(
                pathlib.Path(path).parent if allowed_root is None else allowed_root
            ),
        )
    except Exception as error:
        raise DiagnosticError("v4 evaluator stable read failed") from error
    if record["size"] != expected_size or record["sha256"] != expected_sha256:
        raise DiagnosticError("v4 evaluator identity mismatch")
    name = f"_verified_v4_evaluator_{uuid.uuid4().hex}"
    module = types.ModuleType(name)
    module.__file__ = str(pathlib.Path(path).resolve())
    module.__package__ = ""
    module.__spec__ = importlib.util.spec_from_loader(
        name, loader=None, origin=module.__file__
    )
    sys.modules[name] = module
    try:
        with (
            contextlib.redirect_stdout(sys.stderr),
            warnings.catch_warnings(record=False),
        ):
            warnings.simplefilter("always")
            exec(
                compile(
                    payload, module.__file__, "exec", dont_inherit=True, optimize=0
                ),
                module.__dict__,
            )
        missing = [
            name
            for name in V4_EVALUATOR_WHITELIST
            if not callable(module.__dict__.get(name))
        ]
        if missing:
            raise DiagnosticError(f"v4 evaluator lacks reviewed functions: {missing}")
        if record["sha256"] == V4_EVALUATOR_SHA256:
            # Dynamo installs its manual_seed wrapper on first import in some
            # torch versions. Finish that dependency initialization BEFORE
            # issuing the immutable callable graph, never rebaseline afterward.
            importlib.import_module("torch._dynamo")
            reader = module.__dict__["_frozen_import_context"].__wrapped__
            _VERIFIED_RUNTIME_READERS[id(reader)] = reader
            strict_loader = module.__dict__["strict_load_model"]
            _VERIFIED_SNAPSHOT_IMPORTERS[id(strict_loader)] = strict_loader
        facade = types.SimpleNamespace(
            **{name: module.__dict__[name] for name in V4_EVALUATOR_WHITELIST}
        )
        verified_values = {
            entry: getattr(facade, entry) for entry in V4_EVALUATOR_WHITELIST
        }
        _VERIFIED_PRODUCTION_EVALUATORS[id(facade)] = (
            facade,
            types.MappingProxyType(dict(record)),
            types.MappingProxyType(
                {
                    entry: _callable_anchor(verified_values[entry])
                    for entry in V4_EVALUATOR_WHITELIST
                }
            ),
            _callable_graphs(verified_values, materialize_module_attributes=True),
        )
        return facade
    finally:
        sys.modules.pop(name, None)


def _manifest_entry_relative(entry: Mapping[str, Any], snapshot: pathlib.Path) -> str:
    raw = entry.get("relative_path", entry.get("path"))
    if not isinstance(raw, str) or not raw:
        raise DiagnosticError("snapshot record has no path")
    path = pathlib.Path(raw)
    if path.is_absolute():
        try:
            return path.relative_to(snapshot).as_posix()
        except ValueError as error:
            raise DiagnosticError("snapshot source escapes frozen root") from error
    pure = pathlib.PurePosixPath(raw)
    if ".." in pure.parts or pure.is_absolute():
        raise DiagnosticError("snapshot source path escapes frozen root")
    return pure.as_posix()


def _snapshot_defined_callables(module: types.ModuleType) -> dict[str, Any]:
    namespace = vars(module)
    result = {}
    for name, value in tuple(namespace.items()):
        if isinstance(value, types.FunctionType) and value.__globals__ is namespace:
            result[name] = value
        elif isinstance(value, type) and value.__module__ == module.__name__:
            result[name] = value
            for member_name, member in tuple(vars(value).items()):
                if isinstance(member, (staticmethod, classmethod)):
                    member = member.__func__
                if isinstance(member, types.FunctionType):
                    result[f"{name}.{member_name}"] = member
                elif isinstance(member, property):
                    for role in ("fget", "fset", "fdel"):
                        function = getattr(member, role)
                        if function is not None:
                            result[f"{name}.{member_name}.{role}"] = function
    return result


def _frozen_module_binding_error(before, after):
    """Keep the rejection unchanged; attach bounded, non-content diagnostics."""
    error = DiagnosticError("sealed frozen module bindings changed")
    try:
        added = set(after) - set(before)
        removed = set(before) - set(after)
        replaced = {
            name for name in set(before) & set(after) if before[name] is not after[name]
        }
        error._binding_delta = tuple(
            (
                kind,
                len(names),
                tuple(sorted(name for name in names if type(name) is str)[:3]),
            )
            for kind, names in (
                ("added", added),
                ("removed", removed),
                ("replaced", replaced),
            )
        )
    except Exception:
        # Supplemental metadata must never replace the established rejection.
        pass
    return error


class _SnapshotLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(
        self,
        root: pathlib.Path,
        records: Mapping[str, Mapping[str, Any]],
        trace: types.ModuleType,
    ):
        self.root, self.records, self.trace = root, records, trace
        self.modules: dict[str, tuple[str, bool]] = {}
        self.imported: dict[str, dict[str, Any]] = {}
        self.api: FrozenSceneAPI | None = None
        self.issued_modules: dict[str, list[tuple[Any, ...]]] = {}
        self.required_modules: set[str] = set()
        self.sealed_bindings: dict[str, Any] | None = None
        self.invalid = False
        for relative in records:
            if not relative.endswith(".py"):
                continue
            pure = pathlib.PurePosixPath(relative)
            is_package = pure.name == "__init__.py"
            parts = pure.parts[:-1] if is_package else (*pure.parts[:-1], pure.stem)
            if parts:
                module_name = ".".join(parts)
                self.modules[module_name] = (relative, is_package)
                for end in range(1, len(parts)):
                    self.modules.setdefault(".".join(parts[:end]), ("", True))
        self.protected_tops = {name.partition(".")[0] for name in self.modules}

    def find_spec(self, fullname: str, path: Any = None, target: Any = None):
        if fullname in self.modules:
            relative, is_package = self.modules[fullname]
            return importlib.util.spec_from_loader(
                fullname,
                self,
                origin=(str(self.root / relative) if relative else "frozen-namespace"),
                is_package=is_package,
            )
        if fullname.partition(".")[0] in self.protected_tops:
            raise ImportError(f"frozen module absent from source manifest: {fullname}")
        return None

    def create_module(self, spec: Any):
        return None

    def exec_module(self, module: types.ModuleType) -> None:
        relative, is_package = self.modules[module.__name__]
        if not relative:
            module.__path__ = []
            self._bind_module(module)
            return
        expected = self.records[relative]
        payload, actual = self.trace.read_stable_bytes(
            self.root / relative, allowed_root=self.root
        )
        if (
            int(expected.get("size", -1)) != actual["size"]
            or expected.get("sha256") != actual["sha256"]
        ):
            raise ImportError(f"frozen source identity mismatch: {relative}")
        module.__file__ = str(self.root / relative)
        if is_package:
            module.__path__ = [str((self.root / relative).parent)]
        exec(
            compile(payload, module.__file__, "exec", dont_inherit=True, optimize=0),
            module.__dict__,
        )
        self.imported[relative] = {**actual, "relative_path": relative, "type": "file"}
        self._bind_module(module)
        if self.api is not None:
            object.__setattr__(
                self.api,
                "imported_source_records",
                tuple(self.imported[key] for key in sorted(self.imported)),
            )

    def _bind_module(self, module: types.ModuleType) -> None:
        callables = _snapshot_defined_callables(module)
        anchors = {name: _callable_anchor(value) for name, value in callables.items()}
        imports = {
            name: value
            for name, value in vars(module).items()
            if isinstance(value, types.ModuleType)
        }
        record = (
            module,
            module.__spec__,
            getattr(module, "__file__", None),
            callables,
            anchors,
            imports,
            (
                module.__spec__.name,
                module.__spec__.origin,
                module.__spec__.loader,
                tuple(getattr(module, "__path__", ())),
            ),
        )
        self.issued_modules.setdefault(module.__name__, []).append(record)

    def verify_runtime_bindings(self) -> None:
        if self.invalid:
            raise DiagnosticError("frozen import authority was revoked")
        try:
            if self not in sys.meta_path:
                raise DiagnosticError("frozen import finder was removed")
            bindings = {
                name: module
                for name, module in tuple(sys.modules.items())
                if name.partition(".")[0] in self.protected_tops
            }
            if self.sealed_bindings is not None and (
                set(bindings) != set(self.sealed_bindings)
                or any(
                    bindings[name] is not module
                    for name, module in self.sealed_bindings.items()
                )
            ):
                raise _frozen_module_binding_error(self.sealed_bindings, bindings)
            for name, module in tuple(sys.modules.items()):
                if name.partition(".")[0] not in self.protected_tops:
                    continue
                issued = next(
                    (
                        item
                        for item in self.issued_modules.get(name, ())
                        if item[0] is module
                    ),
                    None,
                )
                if issued is None:
                    raise DiagnosticError("unissued protected module binding")
                if (
                    module.__loader__ is not self
                    or module.__spec__ is not issued[1]
                    or getattr(module, "__file__", None) != issued[2]
                    or (
                        module.__spec__.name,
                        module.__spec__.origin,
                        module.__spec__.loader,
                        tuple(getattr(module, "__path__", ())),
                    )
                    != issued[6]
                ):
                    raise DiagnosticError("frozen module origin changed")
                current = _snapshot_defined_callables(module)
                if set(current) != set(issued[3]) or any(
                    current[key] is not issued[3][key]
                    or not _callable_anchor_equal(
                        _callable_anchor(current[key]), issued[4][key]
                    )
                    for key in current
                ):
                    raise DiagnosticError("frozen module callable changed")
                if any(
                    vars(module).get(key) is not value
                    for key, value in issued[5].items()
                ):
                    raise DiagnosticError("frozen module imported dependency changed")
            # A loaded module may be temporarily replaced by another module
            # issued by this same finder (v4's nested import context), never by
            # an arbitrary object or by removal outside that controlled call.
            if any(name not in sys.modules for name in self.required_modules):
                raise DiagnosticError("issued frozen module was removed")
            self.required_modules.update(
                name
                for name in sys.modules
                if name.partition(".")[0] in self.protected_tops
            )
        except Exception:
            self.invalid = True
            raise

    def seal_runtime_bindings(self) -> None:
        self.verify_runtime_bindings()
        if self.sealed_bindings is not None:
            raise DiagnosticError("frozen module bindings already sealed")
        self.sealed_bindings = {
            name: module
            for name, module in sys.modules.items()
            if name.partition(".")[0] in self.protected_tops
        }


def _restore_missing_snapshot_modules_before_seal(authority):
    """Rebind unique issued objects removed by v4's nested import context.

    Never import/re-execute source or overwrite current bindings. This step must
    precede model graph/state issuance; sealed or ambiguous ownership fails shut.
    The unchanged live-binding validator checks every restored object's anchors.
    """
    if type(authority) is not _SnapshotLoader:
        raise DiagnosticError("snapshot restoration requires exact import authority")
    restored = {}
    try:
        if authority is not _ACTIVE_SNAPSHOT_AUTHORITY.get():
            raise DiagnosticError("snapshot restoration authority is not active")
        if authority.sealed_bindings is not None:
            raise DiagnosticError("snapshot restoration is allowed only before seal")
        _verify_active_import_authority()
        pending = {}
        for name, issued in authority.issued_modules.items():
            if name in sys.modules:
                continue
            if name not in authority.modules or len(issued) != 1:
                raise DiagnosticError("ambiguous missing snapshot module ownership")
            module = issued[0][0]
            if type(module) is not types.ModuleType or module.__name__ != name:
                raise DiagnosticError("missing snapshot module identity differs")
            pending[name] = module
        for name in sorted(pending):
            if name in sys.modules:
                raise DiagnosticError("snapshot binding changed during restoration")
            sys.modules[name] = pending[name]
            restored[name] = pending[name]
        _verify_active_import_authority()
        for name, module in restored.items():
            parent, separator, child = name.rpartition(".")
            if separator and (
                type(sys.modules.get(parent)) is not types.ModuleType
                or vars(sys.modules[parent]).get(child) is not module
            ):
                raise DiagnosticError("restored snapshot parent binding differs")
        return tuple(sorted(restored))
    except Exception:
        # Only undo this function's insertions; never rewrite existing bindings.
        for name, module in restored.items():
            if sys.modules.get(name) is module:
                sys.modules.pop(name)
        authority.invalid = True
        raise


@contextlib.contextmanager
def frozen_scene_context(
    snapshot_files: pathlib.Path, source_records: Mapping[str, Mapping[str, Any]]
) -> Iterator[FrozenSceneAPI]:
    trace = _get_trace()
    root = _real_directory_root(snapshot_files, "snapshot import root")
    normalized = {
        _manifest_entry_relative(record, root): record
        for record in source_records.values()
    }
    finder = _SnapshotLoader(root, normalized, trace)
    protected = {
        name: module
        for name, module in sys.modules.items()
        if name.partition(".")[0] in finder.protected_tops
    }
    for name in protected:
        sys.modules.pop(name, None)
    original_dont_write, original_prefix = sys.dont_write_bytecode, sys.pycache_prefix
    scratch = tempfile.TemporaryDirectory(prefix="frozen-pycache-")
    sys.dont_write_bytecode = True
    sys.pycache_prefix = scratch.name
    sys.meta_path.insert(0, finder)
    try:
        with (
            contextlib.redirect_stdout(sys.stderr),
            warnings.catch_warnings(record=False),
        ):
            warnings.simplefilter("always")
            from selftrain.data.diotic_attention import WaveformCache
            from selftrain.scripts.eval_full_pilot import (
                _correct_cue_batch,
                _raw_scene_batch,
            )
        active = [True]

        def guarded(callable_value):
            def call(*args, **kwargs):
                if not active[0]:
                    raise DiagnosticError("frozen scene API used after context exit")
                return callable_value(*args, **kwargs)

            call.__module__ = callable_value.__module__
            return call

        class GuardedWaveformCacheMeta(type):
            def __call__(cls, *args, **kwargs):
                if not active[0]:
                    raise DiagnosticError("frozen scene API used after context exit")
                return WaveformCache(*args, **kwargs)

        GuardedWaveformCache = GuardedWaveformCacheMeta("WaveformCache", (), {})
        api = FrozenSceneAPI(
            GuardedWaveformCache,
            guarded(_raw_scene_batch),
            guarded(_correct_cue_batch),
            tuple(finder.imported[key] for key in sorted(finder.imported)),
        )
        finder.api = api
        authority_token = _ACTIVE_SNAPSHOT_AUTHORITY.set(finder)
        token = _ACTIVE_FROZEN_SCENE_API.set(api)
        scope_token = _ACTIVE_WORKER_SCENE_SCOPE.set(
            types.MappingProxyType(
                {
                    "scene_api": api,
                    "imported_source_records": tuple(api.imported_source_records),
                    "nonce": uuid.uuid4().hex,
                }
            )
        )
        try:
            yield api
        finally:
            _ACTIVE_WORKER_SCENE_SCOPE.reset(scope_token)
            _ACTIVE_FROZEN_SCENE_API.reset(token)
            _ACTIVE_SNAPSHOT_AUTHORITY.reset(authority_token)
    finally:
        if "active" in locals():
            active[0] = False
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)
        for name in list(sys.modules):
            if name.partition(".")[0] in finder.protected_tops:
                sys.modules.pop(name, None)
        sys.modules.update(protected)
        sys.dont_write_bytecode, sys.pycache_prefix = (
            original_dont_write,
            original_prefix,
        )
        scratch.cleanup()


def _json_value(value: Any) -> Any:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def select_trials(
    evaluator: types.ModuleType, bank: Any, *, count: int = 32
) -> tuple[TrialSpec, ...]:
    required_bank_columns = (
        set(TRIAL_IDENTITY_COLUMNS) - {"probe_distractor_label"}
    ) | {"distractor_1_label"}
    missing = sorted(required_bank_columns.difference(bank.columns))
    if missing:
        raise DiagnosticError(f"bank lacks trial identity columns: {missing}")
    ids = [int(value) for value in bank["trial_id"]]
    if len(ids) != len(set(ids)):
        raise DiagnosticError("bank has duplicate trial identities")
    row_by_trial = {int(row.trial_id): index for index, row in bank.iterrows()}
    selected = evaluator._select_smoke_bank(bank, count)
    selected_ids = [int(value) for value in selected["trial_id"]]
    if len(selected) != count or len(selected_ids) != len(set(selected_ids)):
        raise DiagnosticError("frozen selector returned ambiguous trial identities")
    specs = []
    for ordinal, (_, row) in enumerate(selected.iterrows()):
        trial_id = int(row["trial_id"])
        if trial_id not in row_by_trial:
            raise DiagnosticError("selected trial is absent from original bank")
        identity = {}
        for column in TRIAL_IDENTITY_COLUMNS:
            if column == "probe_distractor_label":
                value = (
                    int(row["distractor_1_label"])
                    if str(row["scene_kind"]) == "mixed"
                    else 0
                )
            else:
                value = row[column]
            identity[column] = _json_value(value)
        specs.append(
            TrialSpec(ordinal, trial_id, int(row_by_trial[trial_id]), identity)
        )
    return tuple(specs)


def collect_clip_records(bank: Any, *, clips_dir: pathlib.Path) -> list[dict[str, Any]]:
    trace = _get_trace()
    root = pathlib.Path(clips_dir).resolve(strict=True)
    ids = [int(value) for value in bank["trial_id"]]
    if len(ids) != len(set(ids)):
        raise DiagnosticError("selected bank has duplicate trial identity rows")
    usages: dict[str, list[dict[str, Any]]] = {}
    for _, row in bank.iterrows():
        for role in ROLE_NAMES:
            index_key, path_key = f"{role}_index", f"{role}_path"
            if index_key not in bank.columns or path_key not in bank.columns:
                raise DiagnosticError(f"bank lacks clip binding columns for {role}")
            if int(row[index_key]) < 0:
                continue
            raw = str(row[path_key])
            pure = pathlib.PurePosixPath(raw)
            if not raw or pure.is_absolute() or ".." in pure.parts:
                raise DiagnosticError("clip path escapes canonical clips root")
            usages.setdefault(pure.as_posix(), []).append(
                {"trial_id": int(row["trial_id"]), "role": role}
            )
    records = []
    for relative in sorted(usages):
        try:
            record = trace.stable_file_record(root / relative, allowed_root=root)
        except Exception as error:
            raise DiagnosticError(
                f"clip is missing, aliased, or unstable: {relative}"
            ) from error
        records.append({**record, "type": "file", "uses": usages[relative]})
    return records


def _source_entries(source_manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if source_manifest.get("schema_version") != 2:
        raise DiagnosticError("source manifest schema must be 2")
    entries = []
    seen: dict[str, tuple[int, str]] = {}
    for key in ("semantic_files", "provenance_files"):
        value = source_manifest.get(key)
        if not isinstance(value, list):
            raise DiagnosticError(f"source manifest lacks {key}")
        if any(not isinstance(item, Mapping) for item in value):
            raise DiagnosticError("source manifest contains a non-record")
        canonical = []
        for item in value:
            path, size, digest = item.get("path"), item.get("size"), item.get("sha256")
            if (
                not isinstance(path, str)
                or not path
                or pathlib.PurePosixPath(path).is_absolute()
                or ".." in pathlib.PurePosixPath(path).parts
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size < 0
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise DiagnosticError("source manifest record boundary is invalid")
            identity = (size, digest)
            if path in seen and seen[path] != identity:
                raise DiagnosticError("conflicting duplicate source manifest record")
            seen[path] = identity
            canonical.append({"path": path, "sha256": digest, "size": size})
        combined_key = key.replace("_files", "_combined_sha256")
        if combined_key in source_manifest:
            payload = "".join(
                f"{item['sha256']}  {item['path']}\n" for item in canonical
            ).encode("utf-8")
            if hashlib.sha256(payload).hexdigest() != source_manifest[combined_key]:
                raise DiagnosticError(f"source manifest {combined_key} mismatch")
        entries.extend(value)
    return entries


def collect_snapshot_records(
    source_manifest: Mapping[str, Any],
    used_paths: Collection[pathlib.Path],
    *,
    snapshot_files: pathlib.Path | None = None,
) -> list[dict[str, Any]]:
    trace = _get_trace()
    entries = _source_entries(source_manifest)
    if snapshot_files is None:
        roots = {
            pathlib.Path(str(entry.get("path", ""))).parent
            for entry in entries
            if pathlib.Path(str(entry.get("path", ""))).is_absolute()
        }
        if len(roots) != 1:
            raise DiagnosticError("snapshot root must be explicit")
        snapshot_files = roots.pop()
    root = _real_directory_root(snapshot_files, "snapshot inventory root")
    expected: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        relative = _manifest_entry_relative(entry, root)
        if relative in expected:
            prior = expected[relative]
            if prior.get("size") != entry.get("size") or prior.get(
                "sha256"
            ) != entry.get("sha256"):
                raise DiagnosticError("conflicting duplicate snapshot source record")
            continue
        expected[relative] = entry
    used = set()
    for path in used_paths:
        try:
            used.add(
                pathlib.Path(path).resolve(strict=False).relative_to(root).as_posix()
            )
        except ValueError as error:
            raise DiagnosticError("used snapshot source escapes frozen root") from error
    if not used.issubset(expected):
        raise DiagnosticError("used snapshot source is absent from manifest")
    records = []
    for relative in sorted(expected):
        entry = expected[relative]
        try:
            actual = trace.stable_file_record(root / relative, allowed_root=root)
        except Exception as error:
            raise DiagnosticError(
                f"snapshot source is unavailable: {relative}"
            ) from error
        if (
            entry.get("type", "file") not in {"file", "regular"}
            or int(entry.get("size", -1)) != actual["size"]
            or entry.get("sha256") != actual["sha256"]
        ):
            raise DiagnosticError(f"snapshot source record mismatch: {relative}")
        records.append(
            {
                **actual,
                "relative_path": relative,
                "type": "file",
                "observed_import": relative in used,
            }
        )
    return records


def _collect_pinned_records(value: Any) -> list[Mapping[str, Any]]:
    """Match frozen v4 verify_frozen_manifest's five-group, mapping-only walk."""
    found = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            if {"path", "size", "sha256"}.issubset(item):
                found.append(item)
            else:
                for child in item.values():
                    visit(child)

    if not isinstance(value, Mapping):
        raise DiagnosticError("v4 manifest must be a mapping")
    for name in (
        "inputs",
        "historical_evidence",
        "completion",
        "models",
        "checkpoint_selection",
    ):
        group = value.get(name)
        if not isinstance(group, Mapping):
            raise DiagnosticError(f"v4 manifest has no mapping group: {name}")
        visit(group)
    return found


def validate_v4_manifest(
    manifest: Mapping[str, Any], source_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    if (
        manifest.get("schema_version") != 1
        or manifest.get("protocol_id") != V4_PROTOCOL
        or manifest.get("evaluation_role") != EVALUATION_ROLE
    ):
        raise DiagnosticError("v4 manifest protocol/role boundary mismatch")
    pinned = _collect_pinned_records(manifest)
    if len(pinned) != 24:
        raise DiagnosticError("v4 manifest must bind exactly 24 pinned files")
    seen: dict[str, tuple[int, str]] = {}
    for record in pinned:
        path, size, digest = (
            record.get("path"),
            record.get("size"),
            record.get("sha256"),
        )
        if (
            not isinstance(path, str)
            or not path
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise DiagnosticError("v4 pinned record schema is invalid")
        identity = (size, digest)
        if path in seen and seen[path] != identity:
            raise DiagnosticError("conflicting duplicate v4 pinned record")
        seen[path] = identity
    _source_entries(source_manifest)
    formal = manifest.get("models", {}).get("formal40", {})
    if (
        formal.get("basename", pathlib.Path(str(formal.get("path", ""))).name)
        != FORMAL40_BASENAME
        or formal.get("epoch") != FORMAL40_EPOCH
        or formal.get("global_step") != FORMAL40_GLOBAL_STEP
        or formal.get("sha256") != FORMAL40_SHA256
    ):
        raise DiagnosticError("formal40 checkpoint boundary mismatch")
    return {
        "status": "V4_MANIFEST_PASS",
        "pinned_file_count": 24,
        "source_manifest_schema": 2,
        "formal40_sha256": FORMAL40_SHA256,
    }


def _verify_v4_layout_lock(trace, manifest, contract):
    layout = manifest.get("layout")
    lock = layout.get("evaluation_lock") if isinstance(layout, Mapping) else None
    path = contract.v4_root / "state/evaluation.lock"
    if (
        not isinstance(lock, Mapping)
        or lock.get("path") != str(path)
        or lock.get("sha256") != contract.lock_sha256
        or type(lock.get("size")) is not int
        or lock["size"] < 0
    ):
        raise DiagnosticError("v4 layout evaluation lock identity is invalid")
    _, actual = trace.read_stable_bytes(path, allowed_root=contract.v4_root)
    if actual["sha256"] != contract.lock_sha256 or actual["size"] != lock["size"]:
        raise DiagnosticError("v4 layout evaluation lock file changed")
    return dict(
        path=str(path), type="file", size=actual["size"], sha256=actual["sha256"]
    )


def _verify_v4_pinned_records(
    trace: types.ModuleType, manifest: Mapping[str, Any], contract: FrozenContract
) -> list[dict[str, Any]]:
    records = _collect_pinned_records(manifest)
    if len(records) != 24:
        raise DiagnosticError("v4 manifest must bind exactly 24 pinned files")
    verified = []
    by_path = {}
    for role_ordinal, frozen in enumerate(records):
        path = pathlib.Path(str(frozen.get("path", "")))
        if not path.is_absolute() or str(path) != str(pathlib.Path(str(path))):
            raise DiagnosticError("v4 pinned path is not canonical absolute")
        try:
            _, actual = trace.read_stable_bytes(path, allowed_root=path.parent)
        except Exception as error:
            raise DiagnosticError(f"v4 pinned file is unavailable: {path}") from error
        if (
            int(frozen.get("size", -1)) != actual["size"]
            or frozen.get("sha256") != actual["sha256"]
        ):
            raise DiagnosticError(f"v4 pinned file identity changed: {path}")
        if str(path) in by_path and (
            by_path[str(path)].get("size"),
            by_path[str(path)].get("sha256"),
        ) != (frozen.get("size"), frozen.get("sha256")):
            raise DiagnosticError("conflicting duplicate v4 pinned record")
        by_path[str(path)] = frozen
        verified.append(
            {
                "role_ordinal": role_ordinal,
                "path": str(path),
                "type": "file",
                "size": actual["size"],
                "sha256": actual["sha256"],
            }
        )
    fixed = {
        str(
            contract.v4_root / "tools/locked_same_bank_eval.py"
        ): contract.evaluator_sha256,
        str(
            contract.v4_root / "tools/run_locked_same_bank_eval.sbatch"
        ): contract.runner_sha256,
    }
    for path, digest in fixed.items():
        if path not in by_path or by_path[path].get("sha256") != digest:
            raise DiagnosticError(f"v4 fixed identity absent from pinned set: {path}")
    _verify_v4_layout_lock(trace, manifest, contract)
    return verified


def _historical_scene_binding(manifest: Mapping[str, Any]) -> dict[str, Any]:
    binding = manifest.get("audits", {}).get("job584990_scene_binding")
    if (
        not isinstance(binding, Mapping)
        or binding.get("trials") != 10000
        or binding.get("scene_hashes") != 10000
        or binding.get("identity_columns") != list(TRIAL_IDENTITY_COLUMNS)
        or not isinstance(binding.get("scene_hash_vector_sha256"), str)
        or len(binding["scene_hash_vector_sha256"]) != 64
    ):
        raise DiagnosticError(
            "Job584990 historical scene binding is absent or malformed"
        )
    return dict(binding)


def _real_directory_root(path: pathlib.Path, label: str) -> pathlib.Path:
    named_path = pathlib.Path(path)
    try:
        named = os.lstat(named_path)
        if stat.S_ISLNK(named.st_mode) or not stat.S_ISDIR(named.st_mode):
            raise DiagnosticError(f"{label} must be a real directory")
        resolved = named_path.resolve(strict=True)
        opened = os.stat(resolved)
        if (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino):
            raise DiagnosticError(f"{label} identity changed during resolution")
        return resolved
    except DiagnosticError:
        raise
    except OSError as error:
        raise DiagnosticError(f"{label} is unavailable") from error


def _read_canonical_json(
    trace: types.ModuleType,
    path: pathlib.Path,
    root: pathlib.Path,
    expected_sha: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, record = trace.read_stable_bytes(path, allowed_root=root)
    if expected_sha is not None and record["sha256"] != expected_sha:
        raise DiagnosticError(f"JSON identity mismatch: {path}")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DiagnosticError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise DiagnosticError("frozen JSON must be an object")
    return value, record


def read_frozen_context(*, contract: FrozenContract | None = None) -> dict[str, Any]:
    contract = contract or production_contract()
    trace = _get_trace()
    root_named = pathlib.Path(contract.v4_root)
    root_lstat = os.lstat(root_named)
    if stat.S_ISLNK(root_lstat.st_mode) or not stat.S_ISDIR(root_lstat.st_mode):
        raise DiagnosticError("v4 root must be a real directory")
    root = root_named.resolve(strict=True)
    manifest, manifest_record = _read_canonical_json(
        trace, root / "input_freeze.json", root, contract.manifest_sha256
    )
    _VERIFIED_PRODUCTION_MANIFESTS[id(manifest)] = (
        manifest,
        types.MappingProxyType(dict(manifest_record)),
    )
    roots = manifest.get("roots")
    if not isinstance(roots, Mapping):
        raise DiagnosticError("v4 manifest roots are missing")
    snapshot = pathlib.Path(str(roots.get("snapshot_files", "")))
    source_manifest_path = next(
        (
            pathlib.Path(str(record["path"]))
            for record in _collect_pinned_records(manifest)
            if pathlib.Path(str(record["path"])).name == "manifest.json"
        ),
        None,
    )
    if source_manifest_path is None:
        raise DiagnosticError("v4 source manifest record is missing")
    source_manifest, _ = _read_canonical_json(
        trace, source_manifest_path, pathlib.Path(str(roots.get("run_root")))
    )
    validation = validate_v4_manifest(manifest, source_manifest)
    validation["verified_pinned_files"] = _verify_v4_pinned_records(
        trace, manifest, contract
    )
    evaluator_path = root / "tools/locked_same_bank_eval.py"
    payload, evaluator_record = trace.read_stable_bytes(
        evaluator_path, allowed_root=root
    )
    evaluator = load_verified_v4_evaluator(
        trace,
        evaluator_path,
        len(payload),
        contract.evaluator_sha256,
        allowed_root=root,
    )
    try:
        import pandas as pd

        bank_record = manifest["inputs"]["bank"]
        bank_payload, bank_actual = trace.read_stable_bytes(
            pathlib.Path(bank_record["path"]),
            allowed_root=pathlib.Path(bank_record["path"]).parent,
        )
        if (
            bank_actual["size"] != bank_record["size"]
            or bank_actual["sha256"] != bank_record["sha256"]
        ):
            raise DiagnosticError("frozen bank identity changed")
        bank = pd.read_csv(
            io.BytesIO(bank_payload),
            sep="\t",
            dtype={f"{role}_speaker": str for role in ROLE_NAMES},
        )
    except Exception as error:
        raise DiagnosticError("cannot load frozen bank") from error
    verified_sources = collect_snapshot_records(
        source_manifest, (), snapshot_files=snapshot
    )
    _VERIFIED_PRODUCTION_INVENTORIES[id(manifest)] = (
        manifest,
        tuple(
            types.MappingProxyType(dict(item))
            for item in validation["verified_pinned_files"]
        ),
        tuple(types.MappingProxyType(dict(item)) for item in verified_sources),
        snapshot.resolve(strict=True),
    )
    capability = _register_frozen_context_capability(
        evaluator=evaluator,
        manifest=manifest,
        evaluator_record=evaluator_record,
        manifest_record=manifest_record,
        pinned_records=validation["verified_pinned_files"],
        source_records=verified_sources,
        root=root,
        source_root=snapshot,
        trust_domain="production",
    )
    return {
        "contract": contract,
        "manifest": manifest,
        "manifest_record": manifest_record,
        "validation": validation,
        "roots": dict(roots),
        "source_manifest": source_manifest,
        "snapshot_files": snapshot,
        "evaluator": evaluator,
        "evaluator_record": evaluator_record,
        "bank": bank,
        "historical_scene_binding": _historical_scene_binding(manifest),
        "_frozen_context_capability": capability,
    }


def _validate_layout(root: pathlib.Path, *, require_freeze: bool) -> dict[str, Any]:
    try:
        named_root = pathlib.Path(root)
        root_stat = os.lstat(named_root)
        if stat.S_ISLNK(root_stat.st_mode):
            raise DiagnosticError("diagnostic root may not be a symlink")
        root = named_root.resolve(strict=True)
    except OSError as error:
        raise DiagnosticError("diagnostic root is unavailable") from error
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or stat.S_IMODE(root_stat.st_mode) != 0o700
        or root_stat.st_uid != os.getuid()
    ):
        raise DiagnosticError("diagnostic root ownership/type/mode mismatch")
    allowed = set(DIAGNOSTIC_LAYOUT) | (
        {"input_freeze.json"} if require_freeze else set()
    )
    actual = {entry.name for entry in os.scandir(root)}
    if actual != allowed:
        raise DiagnosticError(
            "diagnostic root layout has missing or unexpected entries"
        )
    for name in DIAGNOSTIC_LAYOUT:
        observed = os.lstat(root / name)
        if (
            not stat.S_ISDIR(observed.st_mode)
            or stat.S_ISLNK(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != 0o700
            or observed.st_uid != os.getuid()
        ):
            raise DiagnosticError(f"diagnostic directory boundary mismatch: {name}")
    return {"root": str(root), "directories": list(DIAGNOSTIC_LAYOUT)}


def atomic_create_bytes(path: pathlib.Path, payload: bytes) -> None:
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    path = pathlib.Path(path)
    parent = path.parent.resolve(strict=True)
    named_parent = os.lstat(path.parent)
    if (
        not stat.S_ISDIR(named_parent.st_mode)
        or stat.S_ISLNK(named_parent.st_mode)
        or os.path.lexists(path)
    ):
        raise FileExistsError(f"refusing existing target: {path}")
    name = f".{path.name}.{uuid.uuid4().hex}.partial"
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if not isinstance(nofollow, int) or nofollow == 0:
        raise DiagnosticError("O_NOFOLLOW is unavailable")
    directory_fd = os.open(
        parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    )
    descriptor = None
    try:
        opened_parent = os.fstat(directory_fd)
        if not _same_directory_identity(named_parent, opened_parent):
            raise DiagnosticError("evidence parent changed while opening")
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=directory_fd,
        )
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise DiagnosticError("short evidence write")
                view = view[written:]
            os.fsync(descriptor)
            os.link(
                name,
                path.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        finally:
            os.close(descriptor)
            descriptor = None
            os.unlink(name, dir_fd=directory_fd)
        os.fsync(directory_fd)
        if not _same_directory_identity(opened_parent, os.lstat(path.parent)):
            raise DiagnosticError(
                "evidence parent namespace changed during publication"
            )
        final_named = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        final_fd = os.open(path.name, os.O_RDONLY | nofollow, dir_fd=directory_fd)
        try:
            final_opened = os.fstat(final_fd)
            chunks = []
            while True:
                chunk = os.read(final_fd, 1 << 20)
                if not chunk:
                    break
                chunks.append(chunk)
            final_after_read = os.fstat(final_fd)
            final_after_path = os.stat(
                path.name, dir_fd=directory_fd, follow_symlinks=False
            )
            if (
                not stat.S_ISREG(final_opened.st_mode)
                or final_opened.st_nlink != 1
                or stat.S_IMODE(final_opened.st_mode) != 0o600
                or not _same_identity(final_named, final_opened)
                or not _same_identity(final_opened, final_after_read)
                or not _same_identity(final_after_read, final_after_path)
                or b"".join(chunks) != payload
            ):
                raise DiagnosticError("published evidence final identity mismatch")
        finally:
            os.close(final_fd)
    finally:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        os.close(directory_fd)


def atomic_create_json(path: pathlib.Path, value: Any) -> None:
    atomic_create_bytes(path, _get_trace().canonical_json_bytes(value))


@contextlib.contextmanager
def shared_v4_lock(path: pathlib.Path) -> Iterator[Any]:
    path = pathlib.Path(path)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if not isinstance(nofollow, int) or nofollow == 0:
        raise DiagnosticError("O_NOFOLLOW is unavailable")
    try:
        named = os.lstat(path)
        descriptor = os.open(path, os.O_RDONLY | nofollow)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not _same_identity(named, opened):
            raise DiagnosticError("v4 lock identity mismatch")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DiagnosticError("v4 evaluation lock is held exclusively") from error
        yield descriptor
        if not _same_identity(opened, os.lstat(path)):
            raise DiagnosticError("v4 lock pathname changed while held")
    except DiagnosticError:
        raise
    except OSError as error:
        raise DiagnosticError("cannot acquire v4 shared lock") from error
    finally:
        if "descriptor" in locals():
            with contextlib.suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def audit_inputs(
    *,
    contract: FrozenContract | None = None,
    context: Mapping[str, Any] | None = None,
    diagnostic_root: pathlib.Path = DIAGNOSTIC_ROOT,
) -> dict[str, Any]:
    contract = contract or production_contract()
    context = dict(context or read_frozen_context(contract=contract))
    trials = select_trials(context["evaluator"], context["bank"], count=32)
    by_id = context["bank"].set_index("trial_id", drop=False)
    selected = by_id.loc[[trial.trial_id for trial in trials]].reset_index(drop=True)
    clips = collect_clip_records(
        selected, clips_dir=pathlib.Path(context["roots"]["clips_dir"])
    )
    snapshots = collect_snapshot_records(
        context["source_manifest"],
        (),
        snapshot_files=pathlib.Path(context["roots"]["snapshot_files"]),
    )
    tools_root = pathlib.Path(diagnostic_root) / "tools"
    trace = _get_trace()
    production = [
        trace.stable_file_record(tools_root / name, allowed_root=tools_root)
        for name in PRODUCTION_FILES
    ]
    frozen_roots = {
        "v4_root": str(contract.v4_root),
        "diagnostic_root": str(pathlib.Path(diagnostic_root)),
        "clips_dir": str(context["roots"]["clips_dir"]),
        "snapshot_files": str(context["roots"]["snapshot_files"]),
    }
    return {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "status": "AUDIT_PASS",
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "v4_contract": _contract_json(contract),
        "roots": frozen_roots,
        "v4": context["validation"],
        "trials": [dataclasses.asdict(item) for item in trials],
        "clips": clips,
        "snapshot_files": snapshots,
        "production_files": production,
    }


def _validate_freeze_value(
    value: Mapping[str, Any],
    contract: FrozenContract,
    *,
    status: str,
    diagnostic_root: pathlib.Path,
) -> None:
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version") != PACKAGE_SCHEMA_VERSION
        or value.get("status") != status
        or value.get("diagnostic_protocol") != DIAGNOSTIC_PROTOCOL
        or value.get("v4_contract") != _contract_json(contract)
    ):
        raise DiagnosticError("freeze protocol/contract schema is invalid")
    roots = value.get("roots")
    if (
        not isinstance(roots, Mapping)
        or set(roots) != {"v4_root", "diagnostic_root", "clips_dir", "snapshot_files"}
        or roots.get("v4_root") != str(contract.v4_root)
        or roots.get("diagnostic_root") != str(pathlib.Path(diagnostic_root))
        or any(
            not isinstance(roots.get(key), str)
            or not pathlib.Path(roots[key]).is_absolute()
            for key in ("v4_root", "diagnostic_root", "clips_dir", "snapshot_files")
        )
    ):
        raise DiagnosticError("freeze roots are incomplete or invalid")
    trials = value.get("trials")
    if not isinstance(trials, list) or len(trials) != 32:
        raise DiagnosticError("freeze must contain 32 trials")
    trial_ids = []
    for ordinal, trial in enumerate(trials):
        if (
            not isinstance(trial, Mapping)
            or set(trial) != {"ordinal", "trial_id", "bank_row_index", "identity"}
            or trial.get("ordinal") != ordinal
            or not isinstance(trial.get("trial_id"), int)
            or isinstance(trial.get("trial_id"), bool)
            or not isinstance(trial.get("bank_row_index"), int)
            or not isinstance(trial.get("identity"), Mapping)
            or set(trial["identity"]) != set(TRIAL_IDENTITY_COLUMNS)
            or trial["identity"].get("trial_id") != trial["trial_id"]
        ):
            raise DiagnosticError("freeze trial identity schema is invalid")
        trial_ids.append(trial["trial_id"])
    if len(set(trial_ids)) != 32:
        raise DiagnosticError("freeze trial IDs are not unique")

    def validate_inventory(name: str, *, uses: bool) -> None:
        records = value.get(name)
        if not isinstance(records, list) or not records:
            raise DiagnosticError(f"freeze {name} inventory is empty")
        paths = set()
        for record in records:
            required = {
                "relative_path",
                "mode",
                "size",
                "st_mtime_ns",
                "st_dev",
                "st_ino",
                "sha256",
                "type",
            }
            if (
                not isinstance(record, Mapping)
                or not required.issubset(record)
                or record.get("type") != "file"
                or record["relative_path"] in paths
            ):
                raise DiagnosticError(f"freeze {name} record is invalid")
            if not uses and not isinstance(record.get("observed_import"), bool):
                raise DiagnosticError("freeze snapshot import marker is invalid")
            paths.add(record["relative_path"])
            if uses and (
                not isinstance(record.get("uses"), list)
                or not record["uses"]
                or any(
                    not isinstance(use, Mapping)
                    or use.get("trial_id") not in trial_ids
                    or use.get("role") not in ROLE_NAMES
                    for use in record["uses"]
                )
            ):
                raise DiagnosticError("freeze clip uses are incomplete")

    validate_inventory("clips", uses=True)
    validate_inventory("snapshot_files", uses=False)
    production = value.get("production_files")
    if (
        not isinstance(production, list)
        or len(production) != 4
        or {
            record.get("relative_path")
            for record in production
            if isinstance(record, Mapping)
        }
        != set(PRODUCTION_FILES)
        or any(
            not {
                "relative_path",
                "mode",
                "size",
                "st_mtime_ns",
                "st_dev",
                "st_ino",
                "sha256",
            }.issubset(record)
            for record in production
            if isinstance(record, Mapping)
        )
    ):
        raise DiagnosticError("freeze production inventory is invalid")
    v4 = value.get("v4")
    role_records = v4.get("verified_pinned_files") if isinstance(v4, Mapping) else None
    if (
        not isinstance(role_records, list)
        or len(role_records) != 24
        or v4.get("pinned_file_count") != 24
    ):
        raise DiagnosticError("freeze v4 role records are incomplete")
    seen: dict[str, tuple[Any, Any]] = {}
    for ordinal, record in enumerate(role_records):
        if (
            not isinstance(record, Mapping)
            or record.get("role_ordinal") != ordinal
            or record.get("type") != "file"
            or not isinstance(record.get("path"), str)
            or not isinstance(record.get("size"), int)
            or not isinstance(record.get("sha256"), str)
        ):
            raise DiagnosticError("freeze v4 role record is invalid")
        identity = (record["size"], record["sha256"])
        if record["path"] in seen and seen[record["path"]] != identity:
            raise DiagnosticError("freeze v4 duplicate path identities conflict")
        seen[record["path"]] = identity


_ACTIVE_PREDICTION_CONTEXT: ContextVar[Mapping[str, Any] | None] = ContextVar(
    "active_prediction_context", default=None
)
_OFFICIAL_OUTPUT_KEYS = (
    "pred_label",
    "nll",
    "p_target",
    "p_probe_distractor",
)
_TRACE_BOUNDARIES = (
    "raw_scene",
    "raw_cue",
    "normalized_scene",
    "normalized_cue",
    "scene_features",
    "cue_features",
    "native_logits",
    "log_probabilities",
)


class _TraceOutputMap(dict[str, Any]):
    """Exact frozen outputs plus private, in-memory post-output trace evidence."""

    def __init__(
        self,
        outputs: Mapping[str, Any],
        *,
        evidence: Mapping[str, Any],
        derived: Mapping[str, Any],
        official_outputs_complete: bool,
    ) -> None:
        if official_outputs_complete is not True:
            raise DiagnosticError("trace capture preceded complete official outputs")
        super().__init__(outputs)
        self.evidence = evidence
        self.derived = derived
        self.official_outputs_complete = True


@contextlib.contextmanager
def _prediction_evaluator_context(
    evaluator: Any,
    *,
    model: Any = None,
    attestation: _Formal40WorkerAttestation | None = None,
) -> Iterator[None]:
    token = _ACTIVE_PREDICTION_CONTEXT.set(
        {
            "evaluator": evaluator,
            "model": model,
            "attestation": attestation,
        }
    )
    try:
        yield
    finally:
        _ACTIVE_PREDICTION_CONTEXT.reset(token)


@_bounded_seal
def _live_inference_attestation(
    model: Any, boundary: str
) -> _Formal40WorkerAttestation:
    active = _ACTIVE_PREDICTION_CONTEXT.get()
    scene_scope = _ACTIVE_WORKER_SCENE_SCOPE.get()
    attestation = active.get("attestation") if isinstance(active, Mapping) else None
    try:
        if not isinstance(attestation, _Formal40WorkerAttestation):
            raise DiagnosticError(
                f"{boundary} scene/model callable guard lacks exact formal40 attestation"
            )
        receipt = _FORMAL40_ATTESTATION_RECEIPTS.get(id(attestation))
        invalid = (
            id(attestation) in _REVOKED_FORMAL40_ATTESTATIONS
            or _ISSUED_FORMAL40_ATTESTATIONS.get(id(attestation)) is not attestation
            or not _formal40_attestation_receipt_matches(attestation, receipt)
            or _ISSUED_FROZEN_CONTEXT_CAPABILITIES.get(
                id(attestation.frozen_capability)
            )
            is not attestation.frozen_capability
            or active.get("evaluator") is not attestation.evaluator
            or active.get("model") is not model
            or attestation.model is not model
            or not isinstance(scene_scope, Mapping)
            or scene_scope.get("scene_api") is not attestation.scene_api
            or scene_scope.get("nonce") != attestation.scene_scope_nonce
            or tuple(getattr(attestation.scene_api, "imported_source_records", ()))
            != attestation.imported_source_records
            or os.getpid() != attestation.worker_pid
            or attestation.diagnostic_protocol != DIAGNOSTIC_PROTOCOL
            or attestation.v4_protocol != V4_PROTOCOL
            or attestation.evaluator_sha256 != V4_EVALUATOR_SHA256
            or attestation.manifest_sha256 != V4_MANIFEST_SHA256
            or not attestation.worker_nonce
            or not attestation.model_nonce
        )
        if invalid:
            raise DiagnosticError(
                f"{boundary} scene/model callable guard lacks exact formal40 attestation"
            )
        _validate_model_module_inventory(model, attestation.model_module_inventory)
        scene_values = {
            name: _static_attribute(attestation.scene_api, name)
            for name in attestation.scene_callable_graphs
        }
        model_values = _model_callable_values(model)
        if (
            any(
                _callable_graph_fingerprint(scene_values[name]) != graph
                for name, graph in attestation.scene_callable_graphs.items()
            )
            or any(
                _callable_graph_fingerprint(model_values[name]) != graph
                for name, graph in attestation.model_callable_graphs.items()
            )
            or _model_execution_fingerprint(model, attestation.model_module_inventory)
            != attestation.model_execution_fingerprint
            or _get_trace().canonical_json_bytes(
                tuple(dict(item) for item in attestation.imported_source_records)
            )
            != attestation.imported_source_snapshot
        ):
            raise DiagnosticError(
                f"{boundary} scene/model callable guard lacks exact formal40 attestation"
            )
        _validate_frozen_capability_liveness(attestation.frozen_capability)
    except BaseException as error:
        if isinstance(attestation, _Formal40WorkerAttestation):
            _revoke_attestation(attestation)
        if isinstance(error, DiagnosticError):
            raise
        if isinstance(error, Exception):
            raise DiagnosticError(
                f"{boundary} formal40 attestation validation failed"
            ) from error
        raise
    return attestation


def _invoke_attested_operator(
    model: Any,
    boundary: str,
    operator: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Lease one exact operator between data-free pre/post liveness checks."""
    attestation = _live_inference_attestation(model, f"pre_{boundary}")
    expected = attestation.operator_authorities.get(boundary)
    if not callable(operator) or expected is None or operator is not expected:
        _revoke_attestation(attestation)
        raise DiagnosticError(f"{boundary} operator is not the sealed authority")
    try:
        result = operator(*args, **kwargs)
    except BaseException as operator_error:
        try:
            _live_inference_attestation(model, f"post_{boundary}_exception")
        except DiagnosticError as seal_error:
            raise seal_error from operator_error
        _revoke_attestation(attestation)
        raise
    _live_inference_attestation(model, f"post_{boundary}")
    return result


def _require_active_inference_attestation(model: Any, boundary: str) -> dict[str, Any]:
    attestation = _live_inference_attestation(model, boundary)
    try:
        current_report_sha = hashlib.sha256(
            _get_trace().canonical_json_bytes(attestation.load_report)
        ).hexdigest()
        if current_report_sha != attestation.load_report_sha256:
            raise DiagnosticError(
                f"{boundary} formal40 attestation load report changed"
            )
        current_context_sha = hashlib.sha256(
            _get_trace().canonical_json_bytes(
                {
                    "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
                    "v4_protocol": V4_PROTOCOL,
                    "evaluator_sha256": V4_EVALUATOR_SHA256,
                    "manifest_sha256": V4_MANIFEST_SHA256,
                    "load_report_sha256": current_report_sha,
                    "imported_source_records": tuple(
                        dict(item) for item in attestation.imported_source_records
                    ),
                }
            )
        ).hexdigest()
        if current_context_sha != attestation.input_context_sha256:
            raise DiagnosticError(
                f"{boundary} formal40 attestation input context changed"
            )
        return attestation.public_record()
    except BaseException as error:
        _revoke_attestation(attestation)
        if isinstance(error, DiagnosticError):
            raise
        if isinstance(error, Exception):
            raise DiagnosticError(
                f"{boundary} formal40 attestation validation failed"
            ) from error
        raise


def _require_torch_tensor(value: Any, boundary: str) -> Any:
    try:
        import torch
    except ImportError as error:
        raise DiagnosticError("Torch is required for prediction tracing") from error
    if not isinstance(value, torch.Tensor):
        raise DiagnosticError(f"{boundary} is not a Torch tensor")
    return value


def _tensor_guard(value: Any, boundary: str, *, model: Any = None) -> dict[str, Any]:
    import torch

    tensor = _require_torch_tensor(value, boundary)
    try:
        version: int | None = int(tensor._version)
        tracking = "enabled"
    except RuntimeError as error:
        if not torch.is_inference(tensor):
            raise DiagnosticError(
                f"{boundary} version counter is unavailable"
            ) from error
        attestation = _require_active_inference_attestation(model, boundary)
        version = None
        tracking = "inference-disabled"
    result = {
        "object_id": id(tensor),
        "version": version,
        "version_tracking": tracking,
        "shape": [int(size) for size in tensor.shape],
        "dtype": str(tensor.dtype),
        "device": str(tensor.device),
    }
    if tracking == "inference-disabled":
        result["static_attestation"] = attestation
    return result


def _finish_tensor_guard(
    value: Any, boundary: str, before: Mapping[str, Any], *, model: Any = None
) -> dict[str, Any]:
    after = _tensor_guard(value, boundary, model=model)
    stable_keys = (
        "object_id",
        "version",
        "version_tracking",
        "shape",
        "dtype",
        "device",
        "static_attestation",
    )
    if any(before.get(key) != after.get(key) for key in stable_keys):
        raise DiagnosticError(f"{boundary} mutation guard changed")
    return {"before": dict(before), "after": after}


def _validate_trial_ids(trial_ids: Sequence[int], expected: int) -> tuple[int, ...]:
    if isinstance(trial_ids, (str, bytes)):
        raise DiagnosticError("trial IDs must be an integer sequence")
    values = tuple(trial_ids)
    if (
        len(values) != expected
        or any(
            not isinstance(value, int) or isinstance(value, bool) for value in values
        )
        or len(set(values)) != len(values)
    ):
        raise DiagnosticError("trial IDs are not unique aligned integers")
    return values


def _validate_label_tensor(value: Any, *, batch_size: int, name: str) -> Any:
    import torch

    tensor = _require_torch_tensor(value, name)
    if (
        tensor.ndim != 1
        or int(tensor.shape[0]) != batch_size
        or tensor.dtype != torch.long
    ):
        raise DiagnosticError(f"{name} must be a Torch int64 vector of length batch")
    if batch_size and (bool((tensor < 0).any()) or bool((tensor >= 800).any())):
        raise DiagnosticError(f"{name} contains an out-of-range class")
    return tensor


def _feature_tensor(value: Any, *, batch_size: int, boundary: str) -> Any:
    if not isinstance(value, (tuple, list)) or not value:
        raise DiagnosticError(f"{boundary} full_rep result must be a tuple/list")
    tensor = _require_torch_tensor(value[0], boundary)
    if tensor.ndim == 0 or int(tensor.shape[0]) != batch_size:
        raise DiagnosticError(f"{boundary} has no declared batch axis 0")
    return tensor


def _capture_tensor(value: Any) -> Any:
    """Copy a boundary only after all official batch outputs already exist."""
    return value.detach().cpu().clone()


def _trace_boundary_record(
    value: Any,
    *,
    boundary: str,
    trial_ids: tuple[int, ...],
    guard: Mapping[str, Any],
    model: Any,
) -> dict[str, Any]:
    trace = _get_trace()
    capture = _capture_tensor(value)
    aggregate = trace.tensor_record(capture, boundary=boundary)
    finished_guard = _finish_tensor_guard(value, boundary, guard, model=model)
    finished_guard["post_content"] = aggregate
    return {
        # Task 5 consumes this typed in-memory payload without rerunning inference.
        "tensor": capture,
        "aggregate": aggregate,
        "per_trial": trace.per_trial_tensor_records(
            capture, trial_ids=trial_ids, boundary=boundary, batch_axis=0
        ),
        "guard": finished_guard,
    }


def _validate_official_outputs(outputs: Any, *, batch_size: int) -> dict[str, Any]:
    import numpy as np

    if not isinstance(outputs, Mapping) or set(outputs) != set(_OFFICIAL_OUTPUT_KEYS):
        raise DiagnosticError("frozen prediction output schema is invalid")
    result: dict[str, Any] = {}
    for key in _OFFICIAL_OUTPUT_KEYS:
        value = outputs[key]
        if (
            not isinstance(value, np.ndarray)
            or value.ndim != 1
            or len(value) != batch_size
        ):
            raise DiagnosticError(
                f"frozen prediction output {key} is not a CPU NumPy vector"
            )
        if key == "pred_label":
            if not np.issubdtype(value.dtype, np.integer):
                raise DiagnosticError("pred_label is not an integer array")
            if batch_size and bool(((value < 0) | (value >= 800)).any()):
                raise DiagnosticError("pred_label contains an out-of-range class")
        elif not np.issubdtype(value.dtype, np.floating):
            raise DiagnosticError(f"{key} is not a floating array")
        elif not bool(np.isfinite(value).all()):
            raise DiagnosticError(f"{key} contains non-finite values")
        result[key] = value.copy()
    return result


def _require_finite_trace_values(
    boundaries: Mapping[str, Any], derived: Mapping[str, Any]
) -> None:
    """Validate every floating trace value after official outputs are complete."""
    import torch

    for group_name, records in (("boundary", boundaries), ("derived", derived)):
        if not isinstance(records, Mapping):
            raise DiagnosticError(f"{group_name} finite evidence is invalid")
        for name, value in records.items():
            tensor = _require_torch_tensor(value, name)
            if (tensor.is_floating_point() or tensor.is_complex()) and not bool(
                torch.isfinite(tensor).all()
            ):
                raise DiagnosticError(f"non-finite {group_name} value: {name}")


def trace_predict_batch(
    model: Any,
    raw_scene: Any,
    raw_cue: Any,
    labels: Any,
    probes: Any,
    device: Any,
    *,
    autocast_enabled: bool,
    trial_ids: Sequence[int],
) -> TraceBatch:
    """Reproduce frozen v4 prediction while deferring all copies/digests."""
    import torch

    active = _ACTIVE_PREDICTION_CONTEXT.get()
    evaluator = active.get("evaluator") if isinstance(active, Mapping) else None
    if evaluator is None:
        raise DiagnosticError("trace prediction requires a verified evaluator context")
    # Identity-only liveness check: no tensor capture, digest, copy, or dispatch.
    authority = _live_inference_attestation(model, "prediction")
    scene = _require_torch_tensor(raw_scene, "raw_scene")
    cue = _require_torch_tensor(raw_cue, "raw_cue")
    if scene.ndim == 0 or cue.ndim == 0 or tuple(scene.shape) != tuple(cue.shape):
        raise DiagnosticError("raw scene/cue tensors are not batch-aligned")
    batch_size = int(scene.shape[0])
    ids = _validate_trial_ids(trial_ids, batch_size)
    labels = _validate_label_tensor(labels, batch_size=batch_size, name="labels")
    probes = _validate_label_tensor(probes, batch_size=batch_size, name="probes")
    guards: dict[str, Mapping[str, Any]] = {
        "raw_scene": _tensor_guard(scene, "raw_scene"),
        "raw_cue": _tensor_guard(cue, "raw_cue"),
    }

    normalized_scene = _require_torch_tensor(
        _invoke_attested_operator(
            model,
            "scene_preprocess",
            authority.evaluator_authority_callables["singleton_native_preprocess"],
            model,
            scene,
        ),
        "normalized_scene",
    )
    normalized_cue = _require_torch_tensor(
        _invoke_attested_operator(
            model,
            "cue_preprocess",
            authority.evaluator_authority_callables["singleton_native_preprocess"],
            model,
            cue,
        ),
        "normalized_cue",
    )
    if tuple(normalized_scene.shape) != tuple(scene.shape) or tuple(
        normalized_cue.shape
    ) != tuple(cue.shape):
        raise DiagnosticError("native preprocessing changed the frozen batch shape")
    labels_device = labels.to(device, non_blocking=True)
    probes_device = probes.to(device, non_blocking=True)
    with torch.inference_mode():
        with torch.autocast(
            device_type=device.type,
            dtype=torch.float16 if device.type == "cuda" else torch.bfloat16,
            enabled=autocast_enabled and device.type == "cuda",
        ):
            normalized_scene = normalized_scene.to(device, non_blocking=True)
            guards["normalized_scene"] = _tensor_guard(
                normalized_scene, "normalized_scene", model=model
            )
            scene_result = _invoke_attested_operator(
                model,
                "scene_cochleagram",
                authority.model_callables["coch_full_rep"],
                normalized_scene,
                None,
            )
            scene_features = _feature_tensor(
                scene_result, batch_size=batch_size, boundary="scene_features"
            )
            guards["scene_features"] = _tensor_guard(
                scene_features, "scene_features", model=model
            )
            normalized_cue = normalized_cue.to(device, non_blocking=True)
            guards["normalized_cue"] = _tensor_guard(
                normalized_cue, "normalized_cue", model=model
            )
            cue_result = _invoke_attested_operator(
                model,
                "cue_cochleagram",
                authority.model_callables["coch_full_rep"],
                normalized_cue,
                None,
            )
            cue_features = _feature_tensor(
                cue_result, batch_size=batch_size, boundary="cue_features"
            )
            guards["cue_features"] = _tensor_guard(
                cue_features, "cue_features", model=model
            )
            logits = _require_torch_tensor(
                _invoke_attested_operator(
                    model,
                    "model",
                    authority.model_callables["model_call"],
                    cue_features,
                    scene_features,
                    None,
                ),
                "native_logits",
            )
            if tuple(logits.shape) != (batch_size, 800):
                raise DiagnosticError(
                    f"model output is not [batch, 800]: shape={tuple(logits.shape)}"
                )
            guards["native_logits"] = _tensor_guard(
                logits, "native_logits", model=model
            )
            log_probabilities = logits.float().log_softmax(dim=-1)
            guards["log_probabilities"] = _tensor_guard(
                log_probabilities, "log_probabilities", model=model
            )
            probabilities = log_probabilities.exp()
            predicted = probabilities.argmax(dim=-1)
            nll = -log_probabilities.gather(1, labels_device[:, None]).squeeze(1)
            p_target = probabilities.gather(1, labels_device[:, None]).squeeze(1)
            p_probe = probabilities.gather(1, probes_device[:, None]).squeeze(1)
            target_logit = logits.float().gather(1, labels_device[:, None]).squeeze(1)
            logsumexp = logits.float().logsumexp(dim=-1)
            target_log_probability = log_probabilities.gather(
                1, labels_device[:, None]
            ).squeeze(1)

    outputs = _validate_official_outputs(
        {
            "pred_label": predicted.cpu().numpy(),
            "nll": nll.cpu().numpy(),
            "p_target": p_target.cpu().numpy(),
            "p_probe_distractor": p_probe.cpu().numpy(),
        },
        batch_size=batch_size,
    )
    tensors = {
        "raw_scene": scene,
        "raw_cue": cue,
        "normalized_scene": normalized_scene,
        "normalized_cue": normalized_cue,
        "scene_features": scene_features,
        "cue_features": cue_features,
        "native_logits": logits,
        "log_probabilities": log_probabilities,
    }
    derived_tensors = {
        "target_logit": target_logit,
        "logsumexp": logsumexp,
        "target_log_probability": target_log_probability,
        "nll": nll,
        "p_target": p_target,
        "p_probe_distractor": p_probe,
    }
    _require_finite_trace_values(tensors, derived_tensors)
    evidence = {
        name: _trace_boundary_record(
            tensors[name],
            boundary=name,
            trial_ids=ids,
            guard=guards[name],
            model=model,
        )
        for name in _TRACE_BOUNDARIES
    }
    correct = predicted.eq(labels_device)
    derived = {
        "target_logit": _capture_tensor(target_logit),
        "logsumexp": _capture_tensor(logsumexp),
        "target_log_probability": _capture_tensor(target_log_probability),
        "nll": _capture_tensor(nll),
        "p_target": _capture_tensor(p_target),
        "p_probe_distractor": _capture_tensor(p_probe),
        "pred_label": _capture_tensor(predicted),
        "correct": _capture_tensor(correct),
    }
    output_map = _TraceOutputMap(
        outputs,
        evidence=evidence,
        derived=derived,
        official_outputs_complete=True,
    )
    return TraceBatch(
        trial_ids=ids,
        raw_scene=evidence["raw_scene"]["tensor"],
        raw_cue=evidence["raw_cue"]["tensor"],
        normalized_scene=evidence["normalized_scene"]["tensor"],
        normalized_cue=evidence["normalized_cue"]["tensor"],
        scene_features=evidence["scene_features"]["tensor"],
        cue_features=evidence["cue_features"]["tensor"],
        native_logits=evidence["native_logits"]["tensor"],
        log_probabilities=evidence["log_probabilities"]["tensor"],
        outputs=output_map,
    )


def _build_raw_batch(
    scene_api: FrozenSceneAPI,
    frame: Any,
    *,
    clips_dir: pathlib.Path,
    historical_scene_hashes: Mapping[int, str],
    cache: Any,
    snr_errors: list[float],
    authority_callables: Mapping[str, Any] | None = None,
    authority_validator: Callable[[str], Any] | None = None,
    authority_invoker: Callable[..., Any] | None = None,
) -> tuple[Any, Any]:
    raw_scene_batch = (
        authority_callables["raw_scene_batch"]
        if authority_callables is not None
        else scene_api.raw_scene_batch
    )
    correct_cue_batch = (
        authority_callables["correct_cue_batch"]
        if authority_callables is not None
        else scene_api.correct_cue_batch
    )
    if authority_invoker is not None:
        raw_scene_value = authority_invoker(
            "raw_scene_batch",
            raw_scene_batch,
            frame,
            cache,
            pathlib.Path(clips_dir),
            snr_errors=snr_errors,
        )
    else:
        if authority_validator is not None:
            authority_validator("pre_raw_scene_batch")
        raw_scene_value = raw_scene_batch(
            frame, cache, pathlib.Path(clips_dir), snr_errors=snr_errors
        )
        if authority_validator is not None:
            authority_validator("post_raw_scene_batch")
    raw_scene = _require_torch_tensor(raw_scene_value, "raw_scene")
    if authority_invoker is not None:
        raw_cue_value = authority_invoker(
            "correct_cue_batch",
            correct_cue_batch,
            frame,
            cache,
            pathlib.Path(clips_dir),
        )
    else:
        raw_cue_value = correct_cue_batch(frame, cache, pathlib.Path(clips_dir))
        if authority_validator is not None:
            authority_validator("post_correct_cue_batch")
    raw_cue = _require_torch_tensor(raw_cue_value, "raw_cue")
    if raw_scene.ndim == 0 or tuple(raw_scene.shape) != tuple(raw_cue.shape):
        raise DiagnosticError("frozen raw scene/cue shapes differ")
    try:
        trial_ids = _validate_trial_ids(
            tuple(int(value) for value in frame["trial_id"]), int(raw_scene.shape[0])
        )
    except (KeyError, TypeError, ValueError) as error:
        raise DiagnosticError("raw frame lacks valid trial identity") from error
    trace = _get_trace()
    actual = [
        hashlib.sha256(trace.canonical_tensor_bytes(raw_scene[index])).hexdigest()
        for index in range(len(trial_ids))
    ]
    try:
        expected = [historical_scene_hashes[trial_id] for trial_id in trial_ids]
    except KeyError as error:
        raise DiagnosticError("historical scene hash is missing") from error
    if actual != expected:
        bad = [
            trial_id
            for trial_id, left, right in zip(trial_ids, actual, expected)
            if left != right
        ]
        raise DiagnosticError(f"historical scene hash mismatch: trials={bad[:10]}")
    return raw_scene, raw_cue


def build_raw_batch(
    scene_api: FrozenSceneAPI,
    frame: Any,
    *,
    clips_dir: pathlib.Path,
    historical_scene_hashes: Mapping[int, str],
    cache: Any,
) -> tuple[Any, Any]:
    return _build_raw_batch(
        scene_api,
        frame,
        clips_dir=clips_dir,
        historical_scene_hashes=historical_scene_hashes,
        cache=cache,
        snr_errors=[],
    )


def _pass_frame(context: Mapping[str, Any], trials: Sequence[TrialSpec]) -> Any:
    bank = context.get("bank")
    if bank is None or not hasattr(bank, "loc"):
        raise DiagnosticError("pass context has no frozen bank")
    trial_values = tuple(trials)
    if (
        not trial_values
        or any(not isinstance(trial, TrialSpec) for trial in trial_values)
        or len({trial.trial_id for trial in trial_values}) != len(trial_values)
    ):
        raise DiagnosticError("prediction pass has invalid trial specs")
    try:
        frame = bank.loc[[trial.bank_row_index for trial in trial_values]]
        observed = tuple(int(value) for value in frame["trial_id"])
    except (KeyError, TypeError, ValueError) as error:
        raise DiagnosticError("trial specs cannot select the frozen bank") from error
    if observed != tuple(trial.trial_id for trial in trial_values):
        raise DiagnosticError("trial specs do not match frozen bank rows")
    return frame


def _labels_and_probes(frame: Any) -> tuple[Any, Any]:
    import numpy as np
    import torch

    try:
        labels = torch.as_tensor(
            frame["target_label"].to_numpy(dtype=np.int64, copy=True), dtype=torch.long
        )
        probes = torch.as_tensor(
            np.where(
                frame["scene_kind"].astype(str).to_numpy() == "mixed",
                frame["distractor_1_label"].to_numpy(dtype=np.int64, copy=True),
                0,
            ),
            dtype=torch.long,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise DiagnosticError("frozen bank has invalid label fields") from error
    return labels, probes


def _snapshot_model_entries(model: Any) -> list[Mapping[str, Any]]:
    """Read exact registries; never dispatch replaceable named_* iterators."""
    try:
        entries = []
        seen = set()
        for module_name, module, _, _ in _direct_model_module_inventory(model):
            namespace = _safe_instance_dict(module)
            for kind, registry_name in (
                ("parameter", "_parameters"),
                ("buffer", "_buffers"),
            ):
                registry = namespace.get(registry_name)
                for name, value in _native_registry_items(registry):
                    if type(name) is not str:
                        raise DiagnosticError(
                            "model state registry has a non-string key"
                        )
                    if value is None or (kind, id(value)) in seen:
                        continue
                    _require_plain_state_tensor(value)
                    seen.add((kind, id(value)))
                    full_name = f"{module_name}.{name}" if module_name else name
                    # The byte helper expects a non-scalar view. Preserve the
                    # original scalar shape in the state schema below.
                    digest_value = value.reshape(1) if value.ndim == 0 else value
                    record = _get_trace().tensor_record(
                        digest_value, boundary=f"model_{kind}:{full_name}"
                    )
                    version = int(value._version)
                    entries.append(
                        {
                            "kind": kind,
                            "name": full_name,
                            "identity": id(value),
                            "object_id": id(value),
                            "_version": version,
                            "version": version,
                            **{
                                key: record[key]
                                for key in ("shape", "dtype", "device", "sha256")
                            },
                            "shape": list(value.shape),
                        }
                    )
        entries.sort(key=lambda entry: (entry["kind"], entry["name"]))
    except Exception as error:
        raise DiagnosticError("model state snapshot failed") from error
    return entries


def _require_plain_state_tensor(value: Any) -> None:
    import torch

    if type(value) not in (torch.Tensor, torch.nn.Parameter):
        raise DiagnosticError("model state requires a plain Tensor or Parameter")


def _state_tensor_layout(value: Any) -> tuple[Any, ...]:
    """Host metadata only; no tensor copy, digest, or CUDA synchronization."""
    _require_plain_state_tensor(value)
    return (
        tuple(value.shape),
        str(value.dtype),
        str(value.device),
        tuple(value.stride()),
        value.storage_offset(),
        value.untyped_storage().data_ptr(),
    )


def _validate_issued_model_state(attestation: _Formal40WorkerAttestation) -> None:
    """Pass-boundary content check, deliberately outside every operator lease."""
    try:
        expected = _FORMAL40_ISSUED_MODEL_STATE.get(id(attestation))
        current = _get_trace().canonical_json_bytes(
            _snapshot_model_entries(attestation.model)
        )
        if expected is None or current != expected:
            raise DiagnosticError("model state changed since strict-load issuance")
    except BaseException:
        _revoke_attestation(attestation)
        raise


def _boundary_from_batches(
    name: str,
    payloads: Sequence[Any],
    trial_ids: tuple[int, ...],
    guards: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    import torch

    if not payloads:
        raise DiagnosticError(f"no payloads captured for {name}")
    value = torch.cat(tuple(payloads), dim=0)
    trace = _get_trace()
    # numeric_trace deliberately hashes logical tensor bytes.  Retain a
    # singleton value axis for scalar-per-trial vectors so each slice remains
    # a valid tensor view under all supported Torch versions.
    per_trial_value = value[:, None] if value.ndim == 1 else value
    return {
        "tensor": value,
        "aggregate": trace.tensor_record(value, boundary=name),
        "per_trial": trace.per_trial_tensor_records(
            per_trial_value, trial_ids=trial_ids, boundary=name, batch_axis=0
        ),
        "guards": tuple(guards),
    }


def _finish_pass(
    *,
    pass_id: str,
    batch_size: int,
    trial_ids: tuple[int, ...],
    output_chunks: Mapping[str, Sequence[Any]],
    boundary_chunks: Mapping[str, Sequence[Any]],
    guard_chunks: Mapping[str, Sequence[Mapping[str, Any]]],
    derived_chunks: Mapping[str, Sequence[Any]],
    state_before: list[Mapping[str, Any]],
    state_after: list[Mapping[str, Any]],
    rng_before: Mapping[str, Any],
    rng_after: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> PassResult:
    import numpy as np

    if pass_id not in {"pass1", "pass2"}:
        raise DiagnosticError("pass ID must be pass1 or pass2")
    outputs = _validate_official_outputs(
        {
            key: np.concatenate(tuple(output_chunks[key]), axis=0)
            for key in _OFFICIAL_OUTPUT_KEYS
        },
        batch_size=len(trial_ids),
    )
    boundaries = {
        name: _boundary_from_batches(
            name, boundary_chunks[name], trial_ids, guard_chunks.get(name, ())
        )
        for name in boundary_chunks
    }
    boundaries["derived"] = {
        name: _boundary_from_batches(name, chunks, trial_ids, ())
        for name, chunks in derived_chunks.items()
    }
    boundaries["metadata"] = dict(metadata)
    return PassResult(
        pass_id=pass_id,
        batch_size=batch_size,
        trial_ids=trial_ids,
        outputs=outputs,
        boundary_records=boundaries,
        model_snapshots={"before": state_before, "after": state_after},
        rng_snapshots={"before": rng_before, "after": rng_after},
    )


def _pass_context_value(context: Mapping[str, Any], name: str) -> Any:
    if name not in context:
        raise DiagnosticError(f"prediction pass context lacks {name}")
    return context[name]


def _pass_metadata(
    context: Mapping[str, Any],
    scene_api: Any,
    frame: Any,
    snr_errors: Sequence[float],
    **values: Any,
) -> dict[str, Any]:
    attestation = context.get("_formal40_worker_attestation")
    public_attestation = (
        attestation.public_record()
        if isinstance(attestation, _Formal40WorkerAttestation)
        else None
    )
    metadata = {
        "bank_row_indices": [int(index) for index in frame.index],
        "trial_bank_rows": [
            {"trial_id": int(trial_id), "bank_row_index": int(index)}
            for index, trial_id in zip(frame.index, frame["trial_id"])
        ],
        "load_report": context.get("load_report"),
        "load_report_sha256": context.get("load_report_sha256"),
        "runtime": context.get("runtime"),
        "imported_source_records": tuple(
            getattr(scene_api, "imported_source_records", ())
        ),
        "cache_max_items": 512,
        "snr_errors": list(snr_errors),
        "worker_pid": context.get("worker_pid"),
        "worker_nonce": context.get("worker_nonce"),
        "model_nonce": context.get("model_nonce"),
        "cache_roots": context.get("cache_roots"),
        "attestation": public_attestation,
    }
    metadata.update(values)
    if "worker_environment" in context:
        metadata["worker_environment"] = context["worker_environment"]
    return metadata


def run_reference_pass(
    context: Mapping[str, Any],
    trials: Sequence[TrialSpec],
    pass_id: Literal["pass1", "pass2"],
    batch_size: int,
) -> PassResult:
    import torch

    if (
        not isinstance(batch_size, int)
        or isinstance(batch_size, bool)
        or batch_size <= 0
    ):
        raise DiagnosticError("batch size must be a positive integer")
    evaluator = _pass_context_value(context, "evaluator")
    model = _pass_context_value(context, "model")
    scene_api = _pass_context_value(context, "scene_api")
    device = _pass_context_value(context, "device")
    frame = _pass_frame(context, trials)
    ids = tuple(int(value) for value in frame["trial_id"])
    attestation = context.get("_formal40_worker_attestation")
    initial_scope = (
        _prediction_evaluator_context(evaluator, model=model, attestation=attestation)
        if attestation is not None
        else contextlib.nullcontext()
    )
    try:
        with initial_scope:
            if attestation is not None:
                _live_inference_attestation(model, "pre_reference_cache")
                _validate_issued_model_state(attestation)
            cache_factory = (
                attestation.scene_callables["waveform_cache_class"]
                if attestation is not None
                else scene_api.waveform_cache_class
            )
            cache = (
                _invoke_attested_operator(
                    model, "reference_cache", cache_factory, max_items=512
                )
                if attestation is not None
                else cache_factory(max_items=512)
            )
    except DiagnosticError:
        raise
    except Exception as error:
        raise DiagnosticError("frozen waveform cache construction failed") from error
    snr_errors: list[float] = []
    output_chunks = {key: [] for key in _OFFICIAL_OUTPUT_KEYS}
    boundary_chunks: dict[str, list[Any]] = {"raw_scene": [], "raw_cue": []}
    guard_chunks: dict[str, list[Mapping[str, Any]]] = {
        "raw_scene": [],
        "raw_cue": [],
    }
    derived_chunks: dict[str, list[Any]] = {"correct": []}
    state_before = _snapshot_model_entries(model)
    rng_before = _get_trace().snapshot_rng_state()
    for start in range(0, len(frame), batch_size):
        batch_frame = frame.iloc[start : start + batch_size]
        batch_ids = tuple(int(value) for value in batch_frame["trial_id"])
        attestation = context.get("_formal40_worker_attestation")
        prediction_scope = (
            _prediction_evaluator_context(
                evaluator, model=model, attestation=attestation
            )
            if attestation is not None
            else contextlib.nullcontext()
        )
        with prediction_scope:
            if attestation is not None:
                _live_inference_attestation(model, "pre_reference_raw_batch")
            raw_scene, raw_cue = _build_raw_batch(
                scene_api,
                batch_frame,
                clips_dir=pathlib.Path(_pass_context_value(context, "clips_dir")),
                historical_scene_hashes=_pass_context_value(
                    context, "historical_scene_hashes"
                ),
                cache=cache,
                snr_errors=snr_errors,
                authority_callables=(
                    attestation.scene_callables if attestation is not None else None
                ),
                authority_validator=(
                    (lambda boundary: _live_inference_attestation(model, boundary))
                    if attestation is not None
                    else None
                ),
                authority_invoker=(
                    (
                        lambda boundary,
                        operator,
                        *args,
                        **kwargs: _invoke_attested_operator(
                            model, boundary, operator, *args, **kwargs
                        )
                    )
                    if attestation is not None
                    else None
                ),
            )
            raw_guards = {
                "raw_scene": _tensor_guard(raw_scene, "raw_scene"),
                "raw_cue": _tensor_guard(raw_cue, "raw_cue"),
            }
            if attestation is not None:
                _live_inference_attestation(model, "post_reference_raw_batch")
                _live_inference_attestation(model, "pre_reference_predict")
            labels, probes = _labels_and_probes(batch_frame)
            try:
                predictor = (
                    attestation.evaluator_authority_callables["predict_batch"]
                    if attestation is not None
                    else evaluator.predict_batch
                )
                values = (
                    _invoke_attested_operator(
                        model,
                        "reference_predict",
                        predictor,
                        model,
                        raw_scene,
                        raw_cue,
                        labels,
                        probes,
                        device,
                    )
                    if attestation is not None
                    else predictor(model, raw_scene, raw_cue, labels, probes, device)
                )
            except Exception as error:
                raise DiagnosticError("frozen reference prediction failed") from error
        outputs = _validate_official_outputs(values, batch_size=len(batch_ids))
        for key in _OFFICIAL_OUTPUT_KEYS:
            output_chunks[key].append(outputs[key])
        for name, value in (("raw_scene", raw_scene), ("raw_cue", raw_cue)):
            capture = _capture_tensor(value)
            guard = _finish_tensor_guard(value, name, raw_guards[name])
            guard["post_content"] = _get_trace().tensor_record(capture, boundary=name)
            guard_chunks[name].append(guard)
            boundary_chunks[name].append(capture)
        derived_chunks["correct"].append(
            torch.as_tensor(outputs["pred_label"] == labels.numpy())
        )
    state_after = _snapshot_model_entries(model)
    rng_after = _get_trace().snapshot_rng_state()
    result = _finish_pass(
        pass_id=pass_id,
        batch_size=batch_size,
        trial_ids=ids,
        output_chunks=output_chunks,
        boundary_chunks=boundary_chunks,
        guard_chunks=guard_chunks,
        derived_chunks=derived_chunks,
        state_before=state_before,
        state_after=state_after,
        rng_before=rng_before,
        rng_after=rng_after,
        metadata=_pass_metadata(
            context,
            scene_api,
            frame,
            snr_errors,
            role="REFERENCE_COLD",
            path="frozen_predict_batch",
            autocast_enabled=None,
            scratch_root=str(context.get("scratch_root", "")),
            cache_nonce=uuid.uuid4().hex,
        ),
    )
    _bind_pass_commitment(result)
    return result


def run_trace_pass(
    context: Mapping[str, Any],
    trials: Sequence[TrialSpec],
    pass_id: Literal["pass1", "pass2"],
    batch_size: int,
    autocast_enabled: bool,
    scratch_root: pathlib.Path,
) -> PassResult:
    if (
        not isinstance(batch_size, int)
        or isinstance(batch_size, bool)
        or batch_size <= 0
        or not isinstance(autocast_enabled, bool)
    ):
        raise DiagnosticError("trace pass settings are invalid")
    evaluator = _pass_context_value(context, "evaluator")
    model = _pass_context_value(context, "model")
    scene_api = _pass_context_value(context, "scene_api")
    device = _pass_context_value(context, "device")
    frame = _pass_frame(context, trials)
    ids = tuple(int(value) for value in frame["trial_id"])
    attestation = context.get("_formal40_worker_attestation")
    initial_scope = (
        _prediction_evaluator_context(evaluator, model=model, attestation=attestation)
        if attestation is not None
        else contextlib.nullcontext()
    )
    try:
        with initial_scope:
            if attestation is not None:
                _live_inference_attestation(model, "pre_trace_cache")
                _validate_issued_model_state(attestation)
            cache_factory = (
                attestation.scene_callables["waveform_cache_class"]
                if attestation is not None
                else scene_api.waveform_cache_class
            )
            cache = (
                _invoke_attested_operator(
                    model, "trace_cache", cache_factory, max_items=512
                )
                if attestation is not None
                else cache_factory(max_items=512)
            )
    except DiagnosticError:
        raise
    except Exception as error:
        raise DiagnosticError("frozen waveform cache construction failed") from error
    snr_errors: list[float] = []
    output_chunks = {key: [] for key in _OFFICIAL_OUTPUT_KEYS}
    boundary_chunks: dict[str, list[Any]] = {name: [] for name in _TRACE_BOUNDARIES}
    guard_chunks: dict[str, list[Mapping[str, Any]]] = {
        name: [] for name in _TRACE_BOUNDARIES
    }
    derived_chunks: dict[str, list[Any]] = {
        "target_logit": [],
        "logsumexp": [],
        "target_log_probability": [],
        "nll": [],
        "p_target": [],
        "p_probe_distractor": [],
        "pred_label": [],
        "correct": [],
    }
    state_before = _snapshot_model_entries(model)
    rng_before = _get_trace().snapshot_rng_state()
    for start in range(0, len(frame), batch_size):
        batch_frame = frame.iloc[start : start + batch_size]
        batch_ids = tuple(int(value) for value in batch_frame["trial_id"])
        with _prediction_evaluator_context(
            evaluator,
            model=model,
            attestation=attestation,
        ):
            if attestation is not None:
                _live_inference_attestation(model, "pre_trace_raw_batch")
            raw_scene, raw_cue = _build_raw_batch(
                scene_api,
                batch_frame,
                clips_dir=pathlib.Path(_pass_context_value(context, "clips_dir")),
                historical_scene_hashes=_pass_context_value(
                    context, "historical_scene_hashes"
                ),
                cache=cache,
                snr_errors=snr_errors,
                authority_callables=(
                    attestation.scene_callables if attestation is not None else None
                ),
                authority_validator=(
                    (lambda boundary: _live_inference_attestation(model, boundary))
                    if attestation is not None
                    else None
                ),
                authority_invoker=(
                    (
                        lambda boundary,
                        operator,
                        *args,
                        **kwargs: _invoke_attested_operator(
                            model, boundary, operator, *args, **kwargs
                        )
                    )
                    if attestation is not None
                    else None
                ),
            )
            if attestation is not None:
                _live_inference_attestation(model, "post_trace_raw_batch")
        labels, probes = _labels_and_probes(batch_frame)
        with _prediction_evaluator_context(
            evaluator,
            model=model,
            attestation=attestation,
        ):
            traced = trace_predict_batch(
                model,
                raw_scene,
                raw_cue,
                labels,
                probes,
                device,
                autocast_enabled=autocast_enabled,
                trial_ids=batch_ids,
            )
        if not isinstance(traced.outputs, _TraceOutputMap):
            raise DiagnosticError("trace output lost its private evidence channel")
        for key in _OFFICIAL_OUTPUT_KEYS:
            output_chunks[key].append(traced.outputs[key])
        for name in _TRACE_BOUNDARIES:
            record = traced.outputs.evidence[name]
            boundary_chunks[name].append(record["tensor"])
            guard_chunks[name].append(record["guard"])
        for name in derived_chunks:
            derived_chunks[name].append(traced.outputs.derived[name])
    state_after = _snapshot_model_entries(model)
    rng_after = _get_trace().snapshot_rng_state()
    result = _finish_pass(
        pass_id=pass_id,
        batch_size=batch_size,
        trial_ids=ids,
        output_chunks=output_chunks,
        boundary_chunks=boundary_chunks,
        guard_chunks=guard_chunks,
        derived_chunks=derived_chunks,
        state_before=state_before,
        state_after=state_after,
        rng_before=rng_before,
        rng_after=rng_after,
        metadata=_pass_metadata(
            context,
            scene_api,
            frame,
            snr_errors,
            role=context.get("cell_id", "A2"),
            path="traced",
            autocast_enabled=autocast_enabled,
            scratch_root=str(pathlib.Path(scratch_root)),
            cache_nonce=uuid.uuid4().hex,
        ),
    )
    _bind_pass_commitment(result)
    return result


def _require_load_report(report: Any) -> None:
    required = {
        "key_count",
        "missing_keys",
        "unexpected_keys",
        "shape_mismatches",
        "dtype_mismatches",
        "prefix_rule",
        "loaded_trainable_numel",
        "trainable_numel",
        "loaded_trainable_numel_ratio",
        "native_preprocessing",
        "model_module",
    }
    if not isinstance(report, Mapping) or not required.issubset(report):
        raise DiagnosticError("strict load report is incomplete")
    if (
        not isinstance(report["key_count"], int)
        or isinstance(report["key_count"], bool)
        or report["key_count"] <= 0
        or not isinstance(report["prefix_rule"], str)
        or not report["prefix_rule"]
        or not isinstance(report["loaded_trainable_numel"], int)
        or isinstance(report["loaded_trainable_numel"], bool)
        or report["loaded_trainable_numel"] <= 0
        or not isinstance(report["trainable_numel"], int)
        or isinstance(report["trainable_numel"], bool)
        or report["trainable_numel"] <= 0
        or report["native_preprocessing"] != "selftrain_singleton_per_example_leveling"
        or not isinstance(report["model_module"], Mapping)
        or not isinstance(report["model_module"].get("path"), str)
        or not report["model_module"]["path"]
        or report["missing_keys"] != []
        or report["unexpected_keys"] != []
        or report["shape_mismatches"] != {}
        or report["dtype_mismatches"] != {}
        or report["loaded_trainable_numel_ratio"] != 1.0
        or report["loaded_trainable_numel"] != report["trainable_numel"]
    ):
        raise DiagnosticError("strict load report does not prove exact state loading")


# The SHA-bound v4 configurator requests medium, then sets allow_tf32=True.
# PyTorch 2.1.1's setAllowTF32CuBLAS assigns HIGH. HAKUSAN's 2.1.1+cu118
# readback confirms this final state. Do not reorder or reapply its setters.
_FROZEN_NUMERIC_RUNTIME = types.MappingProxyType(
    {
        "deterministic_algorithms": True,
        "cudnn_deterministic": True,
        "cudnn_benchmark": False,
        "float32_matmul_precision": "high",
        "cuda_matmul_allow_tf32": True,
        "cudnn_allow_tf32": True,
    }
)


def _require_frozen_numeric_runtime(runtime, label, *, torch_version=None):
    """One exact typed contract for live and durable evidence; never repair it."""
    expected = _FROZEN_NUMERIC_RUNTIME
    if (
        isinstance(runtime, Mapping)
        and set(runtime) == set(expected)
        and all(
            type(runtime[k]) is type(v) and runtime[k] == v for k, v in expected.items()
        )
    ):
        return
    details = {
        "actual": dict(runtime) if isinstance(runtime, Mapping) else runtime,
        "expected": dict(expected),
    }
    if torch_version is not None:
        details["torch_version"] = str(torch_version)
    raise DiagnosticError(
        label + ": " + json.dumps(details, sort_keys=True, default=repr)
    )


def _read_frozen_numeric_runtime(torch_api):
    """Read every flag without coercion; unavailable getters fail explicitly."""
    getters = {
        "deterministic_algorithms": lambda: torch_api.are_deterministic_algorithms_enabled(),
        "cudnn_deterministic": lambda: torch_api.backends.cudnn.deterministic,
        "cudnn_benchmark": lambda: torch_api.backends.cudnn.benchmark,
        "float32_matmul_precision": lambda: torch_api.get_float32_matmul_precision(),
        "cuda_matmul_allow_tf32": lambda: torch_api.backends.cuda.matmul.allow_tf32,
        "cudnn_allow_tf32": lambda: torch_api.backends.cudnn.allow_tf32,
    }
    runtime = {}
    for name, getter in getters.items():
        try:
            runtime[name] = getter()
        except Exception as error:
            runtime[name] = {"read_error": f"{type(error).__name__}: {error}"}
    _require_frozen_numeric_runtime(
        runtime,
        "frozen runtime settings are not exact",
        torch_version=getattr(torch_api, "__version__", "unavailable"),
    )
    return runtime


def prepare_formal40_worker(
    context: Mapping[str, Any], *, allow_cpu: bool
) -> dict[str, Any]:
    import torch

    evaluator = _pass_context_value(context, "evaluator")
    manifest = _pass_context_value(context, "manifest")
    capability = context.get("_frozen_context_capability")
    scene_scope = _ACTIVE_WORKER_SCENE_SCOPE.get()
    if (
        not isinstance(capability, _FrozenContextCapability)
        or _ISSUED_FROZEN_CONTEXT_CAPABILITIES.get(id(capability)) is not capability
        or capability.evaluator is not evaluator
        or capability.manifest is not manifest
        or not capability.pinned_records
        or not capability.source_records
    ):
        raise DiagnosticError(
            "formal40 worker lacks verified frozen provenance capability"
        )
    _validate_frozen_capability_contents(capability)
    if capability.trust_domain == "production":
        if (
            capability.evaluator_record.get("sha256") != V4_EVALUATOR_SHA256
            or capability.manifest_record.get("sha256") != V4_MANIFEST_SHA256
            or len(capability.pinned_records) != 24
        ):
            raise DiagnosticError("production frozen provenance records are invalid")
        if allow_cpu:
            raise DiagnosticError("production formal40 worker requires CUDA runtime")
        scene_api = context.get("scene_api")
        if _ACTIVE_FROZEN_SCENE_API.get() is not scene_api or not isinstance(
            scene_api, FrozenSceneAPI
        ):
            raise DiagnosticError("production frozen scene context is not active")
        imported_source_records = tuple(scene_api.imported_source_records)
    else:
        scene_api = context.get("scene_api")
        if (
            not isinstance(scene_scope, Mapping)
            or scene_scope.get("scene_api") is not scene_api
        ):
            raise DiagnosticError("hermetic frozen scene context is not active")
        imported_source_records = tuple(scene_scope.get("imported_source_records", ()))
    if (
        not isinstance(scene_scope, Mapping)
        or scene_scope.get("scene_api") is not scene_api
        or not isinstance(scene_scope.get("nonce"), str)
        or not scene_scope["nonce"]
    ):
        raise DiagnosticError("formal40 worker scene scope is not active")
    if not imported_source_records:
        raise DiagnosticError("formal40 worker imported-source provenance is empty")
    allowed_sources = {
        (record.get("relative_path"), record.get("sha256"))
        for record in capability.source_records
    }
    if any(
        not isinstance(record, Mapping)
        or (record.get("relative_path"), record.get("sha256")) not in allowed_sources
        for record in imported_source_records
    ):
        raise DiagnosticError(
            "formal40 worker imported-source provenance is unverified"
        )
    try:
        device = evaluator._configure_runtime(allow_cpu)
    except Exception as error:
        raise DiagnosticError("frozen runtime configuration failed") from error
    _validate_frozen_capability_contents(capability)
    runtime = _read_frozen_numeric_runtime(torch)
    try:
        model, report = evaluator.strict_load_model(manifest, "formal40", device=device)
    except Exception as error:
        raise DiagnosticError("strict formal40 load failed") from error
    if capability.trust_domain == "production":
        _restore_missing_snapshot_modules_before_seal(_ACTIVE_SNAPSHOT_AUTHORITY.get())
    _validate_frozen_capability_contents(capability)
    _require_load_report(report)
    model_module_inventory = _direct_model_module_inventory(model)
    _require_registered_modules_eval(model)
    _require_frozen_direct_parameters(model_module_inventory)
    # Strict loading may import the model module lazily. Seal the complete live
    # source set only after loading and reject anything outside the frozen set.
    imported_source_records = tuple(getattr(scene_api, "imported_source_records", ()))
    identity_keys = (
        "relative_path",
        "mode",
        "size",
        "st_mtime_ns",
        "st_dev",
        "st_ino",
        "sha256",
    )
    authority_sources = {
        tuple(record.get(key) for key in identity_keys)
        for record in capability.source_records
    }
    live_identities = [
        tuple(record.get(key) for key in identity_keys)
        for record in imported_source_records
        if isinstance(record, Mapping)
    ]
    if (
        not imported_source_records
        or len(live_identities) != len(imported_source_records)
        or len(set(live_identities)) != len(live_identities)
        or live_identities != sorted(live_identities, key=lambda item: item[0])
        or any(identity not in authority_sources for identity in live_identities)
    ):
        raise DiagnosticError("formal40 worker post-load source provenance is invalid")
    imported_source_records = _deep_frozen_records(imported_source_records)
    object.__setattr__(scene_api, "imported_source_records", imported_source_records)
    load_report_sha256 = hashlib.sha256(
        _get_trace().canonical_json_bytes(report)
    ).hexdigest()
    input_context_sha256 = hashlib.sha256(
        _get_trace().canonical_json_bytes(
            {
                "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
                "v4_protocol": V4_PROTOCOL,
                "evaluator_sha256": V4_EVALUATOR_SHA256,
                "manifest_sha256": V4_MANIFEST_SHA256,
                "load_report_sha256": load_report_sha256,
                "imported_source_records": tuple(
                    dict(item) for item in imported_source_records
                ),
            }
        )
    ).hexdigest()
    evaluator_authority_callables = types.MappingProxyType(
        {
            name: getattr(evaluator, name)
            for name in V4_EVALUATOR_WHITELIST
            if callable(_static_attribute(evaluator, name))
        }
    )
    scene_callables = types.MappingProxyType(
        {
            name: getattr(scene_api, name)
            for name in ("waveform_cache_class", "raw_scene_batch", "correct_cue_batch")
            if callable(_static_attribute(scene_api, name))
        }
    )
    model_callables = types.MappingProxyType(
        {
            "forward": _static_attribute(model, "forward"),
            "model_call": _static_attribute(model, "__call__"),
            "coch_full_rep": model.coch_gram.full_rep,
        }
    )
    scene_callable_graphs = _callable_graphs(
        scene_callables, materialize_module_attributes=True
    )
    model_callable_graphs = _callable_graphs(
        _model_callable_values(model), materialize_module_attributes=True
    )
    operator_authority_items = {
        "scene_preprocess": evaluator_authority_callables[
            "singleton_native_preprocess"
        ],
        "cue_preprocess": evaluator_authority_callables["singleton_native_preprocess"],
        "scene_cochleagram": model_callables["coch_full_rep"],
        "cue_cochleagram": model_callables["coch_full_rep"],
        "model": model_callables["model_call"],
        "reference_predict": evaluator_authority_callables["predict_batch"],
    }
    if "waveform_cache_class" in scene_callables:
        operator_authority_items.update(
            {
                "reference_cache": scene_callables["waveform_cache_class"],
                "trace_cache": scene_callables["waveform_cache_class"],
            }
        )
    for boundary in ("raw_scene_batch", "correct_cue_batch"):
        if boundary in scene_callables:
            operator_authority_items[boundary] = scene_callables[boundary]
    operator_authorities = types.MappingProxyType(operator_authority_items)
    attestation = _Formal40WorkerAttestation(
        evaluator=evaluator,
        model=model,
        load_report=report,
        diagnostic_protocol=DIAGNOSTIC_PROTOCOL,
        v4_protocol=V4_PROTOCOL,
        evaluator_sha256=V4_EVALUATOR_SHA256,
        manifest_sha256=V4_MANIFEST_SHA256,
        load_report_sha256=load_report_sha256,
        worker_pid=os.getpid(),
        worker_nonce=uuid.uuid4().hex,
        model_nonce=uuid.uuid4().hex,
        input_context_sha256=input_context_sha256,
        imported_source_records=imported_source_records,
        frozen_capability=capability,
        scene_api=scene_api,
        scene_scope_nonce=scene_scope["nonce"],
        evaluator_authority_callables=evaluator_authority_callables,
        scene_callables=scene_callables,
        model_callables=model_callables,
        scene_callable_graphs=scene_callable_graphs,
        model_callable_graphs=model_callable_graphs,
        operator_authorities=operator_authorities,
        model_module_inventory=model_module_inventory,
        model_execution_fingerprint=_materialized_model_execution_fingerprint(
            model, model_module_inventory
        ),
        imported_source_snapshot=_get_trace().canonical_json_bytes(
            tuple(dict(item) for item in imported_source_records)
        ),
    )
    _ISSUED_FORMAL40_ATTESTATIONS[id(attestation)] = attestation
    _FORMAL40_ATTESTATION_RECEIPTS[id(attestation)] = (
        _formal40_attestation_issuance_receipt(attestation)
    )
    _FORMAL40_ISSUED_MODEL_STATE[id(attestation)] = _get_trace().canonical_json_bytes(
        _snapshot_model_entries(model)
    )
    import_authority = _ACTIVE_SNAPSHOT_AUTHORITY.get()
    if capability.trust_domain == "production":
        if import_authority is None:
            raise DiagnosticError("production model lacks frozen import authority")
        import_authority.seal_runtime_bindings()
    return {
        "model": model,
        "device": device,
        "load_report": report,
        "load_report_sha256": load_report_sha256,
        "runtime": runtime,
        "evaluator": evaluator,
        "manifest": manifest,
        "worker_pid": attestation.worker_pid,
        "worker_nonce": attestation.worker_nonce,
        "model_nonce": attestation.model_nonce,
        "attestation": attestation.public_record(),
        "_formal40_worker_attestation": attestation,
    }


def _payload(record: Any, name: str) -> Any:
    if not isinstance(record, Mapping) or "tensor" not in record:
        raise DiagnosticError(f"equivalence boundary {name} has no tensor payload")
    return record["tensor"]


def _aligned_order(
    reference_ids: tuple[int, ...], candidate_ids: tuple[int, ...]
) -> list[int]:
    if len(set(reference_ids)) != len(reference_ids) or len(set(candidate_ids)) != len(
        candidate_ids
    ):
        raise DiagnosticError("equivalence trial IDs are not unique")
    if set(reference_ids) != set(candidate_ids):
        raise DiagnosticError("equivalence trial ID sets differ")
    positions = {trial_id: index for index, trial_id in enumerate(candidate_ids)}
    return [positions[trial_id] for trial_id in reference_ids]


def _model_transition(snapshots: Any) -> Mapping[str, Any]:
    if not isinstance(snapshots, Mapping) or set(snapshots) != {"before", "after"}:
        raise DiagnosticError("model snapshot collection is invalid")
    before = {"entries": snapshots["before"]}
    after = {"entries": snapshots["after"]}
    try:
        return _get_trace().compare_model_snapshots(before, before, after)
    except Exception as error:
        raise DiagnosticError("model snapshot evidence is invalid") from error


def _rng_transition(snapshots: Any) -> Mapping[str, Any]:
    if not isinstance(snapshots, Mapping) or set(snapshots) != {"before", "after"}:
        raise DiagnosticError("RNG snapshot collection is invalid")
    try:
        result = _get_trace().compare_rng_snapshots(
            snapshots["before"], snapshots["before"], snapshots["after"]
        )
    except Exception as error:
        raise DiagnosticError("RNG snapshot evidence is invalid") from error
    if not result.get("schema_valid"):
        raise DiagnosticError("RNG snapshot evidence is invalid")
    return result


def _derived_correct(records: Mapping[str, Any]) -> Any:
    derived = records.get("derived")
    if not isinstance(derived, Mapping):
        raise DiagnosticError("equivalence lacks derived correctness evidence")
    if "tensor" in derived:
        return _payload(derived, "correct")
    return _payload(derived.get("correct"), "correct")


def _pass_commitment_payload(result: PassResult) -> dict[str, Any]:
    if not isinstance(result, PassResult):
        raise DiagnosticError("pass commitment requires a pass result")
    trace = _get_trace()

    def tensor_record(value: Any, name: str) -> dict[str, Any]:
        record = trace.tensor_record(value, boundary=name)
        return {
            key: record[key]
            for key in ("boundary", "shape", "dtype", "numel", "finite", "sha256")
            if key in record
        }

    def committed(value: Any, name: str) -> Any:
        """Canonicalize complete post-output evidence without retaining live tensors."""
        if isinstance(value, Mapping):
            return {
                str(key): committed(child, f"{name}.{key}")
                for key, child in sorted(value.items(), key=lambda item: str(item[0]))
                if key not in {"pass_commitment", "provenance_receipt"}
            }
        if isinstance(value, (tuple, list)):
            return [
                committed(child, f"{name}[{index}]")
                for index, child in enumerate(value)
            ]
        if isinstance(value, pathlib.Path):
            return str(value)
        module = type(value).__module__.split(".", 1)[0]
        if module in {"torch", "numpy"} and hasattr(value, "shape"):
            return tensor_record(value, name)
        return value

    outputs = {
        name: tensor_record(value, f"output.{name}")
        for name, value in sorted(result.outputs.items())
    }
    boundaries = committed(result.boundary_records, "boundary")
    return {
        "schema_version": 1,
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "v4_protocol": V4_PROTOCOL,
        "evaluation_role": EVALUATION_ROLE,
        "evaluator_sha256": V4_EVALUATOR_SHA256,
        "manifest_sha256": V4_MANIFEST_SHA256,
        "pass_id": result.pass_id,
        "batch_size": result.batch_size,
        "trial_ids": list(result.trial_ids),
        "outputs": outputs,
        "boundaries": boundaries,
        "model_snapshots": committed(result.model_snapshots, "model_snapshot"),
        "rng_snapshots": committed(result.rng_snapshots, "rng_snapshot"),
    }


def _bind_pass_commitment(result: PassResult) -> dict[str, Any]:
    digest = hashlib.sha256(
        _get_trace().canonical_json_bytes(_pass_commitment_payload(result))
    ).hexdigest()
    record = types.MappingProxyType(
        {
            "schema_version": 1,
            "binding_sha256": digest,
            "scope": "complete_pass_provenance_boundaries_outputs",
        }
    )
    if not isinstance(result.boundary_records, dict):
        raise DiagnosticError("pass boundary collection cannot hold commitment")
    result.boundary_records["pass_commitment"] = record
    return dict(record)


def _authenticate_pass_result(
    capability: _FrozenContextCapability,
    result: PassResult,
    artifact_record: Mapping[str, Any],
) -> _AuthenticatedPassEvidence:
    _validate_frozen_capability_contents(capability)
    if (
        _ISSUED_FROZEN_CONTEXT_CAPABILITIES.get(id(capability)) is not capability
        or capability.trust_domain != "hermetic-test"
        or not isinstance(artifact_record, Mapping)
        or artifact_record.get("inventory_verified") is not True
        or artifact_record.get("child_process_verified") is not True
        or artifact_record.get("canonical_path_verified") is not True
        or artifact_record.get("trust_domain") != capability.trust_domain
        or not isinstance(artifact_record.get("scene_scope_nonce"), str)
        or not artifact_record.get("scene_scope_nonce")
    ):
        raise DiagnosticError(
            "pass artifact authentication is invalid; production child "
            "authentication is coordinator-owned"
        )
    metadata = result.boundary_records.get("metadata")
    attestation_record = (
        metadata.get("attestation") if isinstance(metadata, Mapping) else None
    )
    artifact_sources = artifact_record.get("imported_source_records")
    if (
        not isinstance(metadata, Mapping)
        or not isinstance(attestation_record, Mapping)
        or not isinstance(artifact_sources, (tuple, list))
        or tuple(dict(item) for item in metadata.get("imported_source_records", ()))
        != tuple(dict(item) for item in artifact_sources)
        or attestation_record.get("trust_domain") != capability.trust_domain
        or attestation_record.get("scene_scope_nonce")
        != artifact_record["scene_scope_nonce"]
    ):
        raise DiagnosticError("pass source/scope authentication is invalid")
    source_snapshot = _get_trace().canonical_json_bytes(
        tuple(dict(item) for item in artifact_sources)
    )
    commitment = result.boundary_records.get("pass_commitment")
    current_sha = hashlib.sha256(
        _get_trace().canonical_json_bytes(_pass_commitment_payload(result))
    ).hexdigest()
    if (
        not isinstance(commitment, Mapping)
        or commitment.get("binding_sha256") != current_sha
        or artifact_record.get("binding_sha256") != current_sha
    ):
        raise DiagnosticError("pass artifact binding is invalid")
    artifact_snapshot = _get_trace().canonical_json_bytes(
        _deep_plain_record(artifact_record)
    )
    immutable_artifact = _deep_immutable(artifact_record)
    wrapper = _AuthenticatedPassEvidence(
        result=result,
        binding_sha256=current_sha,
        artifact_record=immutable_artifact,
        frozen_capability=capability,
        scene_scope_nonce=artifact_record["scene_scope_nonce"],
        imported_source_snapshot=source_snapshot,
        nonce=uuid.uuid4().hex,
    )
    _AUTHENTICATED_PASS_RESULTS[id(wrapper)] = wrapper
    _AUTHENTICATED_PASS_RECEIPTS[id(wrapper)] = (
        result,
        current_sha,
        immutable_artifact,
        artifact_snapshot,
        capability,
        wrapper.scene_scope_nonce,
        source_snapshot,
        wrapper.nonce,
    )
    return wrapper


def _authenticate_hermetic_pass_result(
    capability: _FrozenContextCapability, result: PassResult
) -> _AuthenticatedPassEvidence:
    """Private test-only authentication over a real verified hermetic capability."""
    if (
        not isinstance(capability, _FrozenContextCapability)
        or capability.trust_domain != "hermetic-test"
    ):
        raise DiagnosticError("hermetic pass authentication requires test capability")
    commitment = result.boundary_records.get("pass_commitment")
    if not isinstance(commitment, Mapping):
        commitment = _bind_pass_commitment(result)
    scope = _ACTIVE_WORKER_SCENE_SCOPE.get()
    if not isinstance(scope, Mapping) or not isinstance(scope.get("nonce"), str):
        raise DiagnosticError(
            "hermetic pass authentication requires active scene scope"
        )
    return _authenticate_pass_result(
        capability,
        result,
        {
            "binding_sha256": commitment["binding_sha256"],
            "inventory_verified": True,
            "child_process_verified": True,
            "canonical_path_verified": True,
            "trust_domain": "hermetic-test",
            "scene_scope_nonce": scope["nonce"],
            "imported_source_records": tuple(
                dict(item) for item in scope.get("imported_source_records", ())
            ),
        },
    )


def _unwrap_authenticated_pass(
    value: Any, *, trust_domain: Literal["production", "hermetic-test"]
) -> tuple[PassResult, _FrozenContextCapability, str, bytes]:
    if not isinstance(value, _AuthenticatedPassEvidence):
        raise DiagnosticError("reference equivalence requires authenticated receipt")
    receipt_id = id(value)
    if receipt_id in _REVOKED_AUTHENTICATED_PASS_RESULTS:
        raise DiagnosticError("authenticated receipt is revoked")
    try:
        issued = _AUTHENTICATED_PASS_RECEIPTS.get(receipt_id)
        if (
            _AUTHENTICATED_PASS_RESULTS.get(receipt_id) is not value
            or issued is None
            or len(issued) != 8
        ):
            raise DiagnosticError(
                "reference equivalence requires authenticated receipt"
            )
        (
            issued_result,
            issued_binding,
            issued_artifact,
            artifact_snapshot,
            issued_capability,
            issued_scope,
            issued_sources,
            issued_nonce,
        ) = issued
        if (
            value.result is not issued_result
            or value.binding_sha256 is not issued_binding
            or value.artifact_record is not issued_artifact
            or value.frozen_capability is not issued_capability
            or value.scene_scope_nonce is not issued_scope
            or value.imported_source_snapshot is not issued_sources
            or value.nonce is not issued_nonce
            or _get_trace().canonical_json_bytes(
                _deep_plain_record(value.artifact_record)
            )
            != artifact_snapshot
            or _ISSUED_FROZEN_CONTEXT_CAPABILITIES.get(id(value.frozen_capability))
            is not value.frozen_capability
            or value.frozen_capability.trust_domain != trust_domain
        ):
            raise DiagnosticError("authenticated receipt changed")
        _validate_frozen_capability_contents(value.frozen_capability)
        current_sha = hashlib.sha256(
            _get_trace().canonical_json_bytes(_pass_commitment_payload(value.result))
        ).hexdigest()
        if current_sha != value.binding_sha256:
            raise DiagnosticError("authenticated pass binding changed")
        metadata = value.result.boundary_records.get("metadata", {})
        current_sources = _get_trace().canonical_json_bytes(
            tuple(dict(item) for item in metadata.get("imported_source_records", ()))
        )
        if current_sources != value.imported_source_snapshot:
            raise DiagnosticError("authenticated pass source binding changed")
    except BaseException as error:
        _REVOKED_AUTHENTICATED_PASS_RESULTS.add(receipt_id)
        if isinstance(error, DiagnosticError):
            raise
        if not isinstance(error, Exception):
            raise
        raise DiagnosticError("authenticated receipt validation failed") from error
    return (
        value.result,
        value.frozen_capability,
        value.scene_scope_nonce,
        value.imported_source_snapshot,
    )


def _require_equivalence_metadata(
    reference: PassResult,
    candidate: PassResult,
    order: Sequence[int],
    reference_authority: tuple[_FrozenContextCapability, str] | None = None,
    candidate_authority: tuple[_FrozenContextCapability, str] | None = None,
) -> dict[str, Any]:
    left = reference.boundary_records.get("metadata")
    right = candidate.boundary_records.get("metadata")
    required = {
        "role",
        "path",
        "autocast_enabled",
        "runtime",
        "load_report",
        "load_report_sha256",
        "imported_source_records",
        "trial_bank_rows",
        "worker_pid",
        "worker_nonce",
        "model_nonce",
        "cache_nonce",
        "scratch_root",
        "cache_roots",
        "attestation",
    }
    if (
        not isinstance(left, Mapping)
        or not isinstance(right, Mapping)
        or not required.issubset(left)
        or not required.issubset(right)
    ):
        raise DiagnosticError("reference equivalence metadata is incomplete")
    if (left["role"], left["path"], left["autocast_enabled"]) != (
        "REFERENCE_COLD",
        "frozen_predict_batch",
        None,
    ) or (right["role"], right["path"], right["autocast_enabled"]) != (
        "A2",
        "traced",
        True,
    ):
        raise DiagnosticError("reference equivalence roles or autocast are invalid")
    for runtime in (left["runtime"], right["runtime"]):
        _require_frozen_numeric_runtime(
            runtime, "reference equivalence runtime is not exact"
        )
    for metadata in (left, right):
        report = metadata["load_report"]
        digest = metadata["load_report_sha256"]
        _require_load_report(report)
        if (
            not isinstance(report, Mapping)
            or not isinstance(digest, str)
            or len(digest) != 64
            or hashlib.sha256(_get_trace().canonical_json_bytes(report)).hexdigest()
            != digest
        ):
            raise DiagnosticError("reference equivalence load evidence is invalid")
    if (
        left["load_report"] != right["load_report"]
        or left["load_report_sha256"] != right["load_report_sha256"]
    ):
        raise DiagnosticError("reference equivalence load evidence differs")
    if (
        not isinstance(left["imported_source_records"], (tuple, list))
        or not left["imported_source_records"]
        or any(
            not isinstance(record, Mapping)
            or not isinstance(record.get("relative_path"), str)
            or not isinstance(record.get("sha256"), str)
            or len(record["sha256"]) != 64
            for record in left["imported_source_records"]
        )
        or left["imported_source_records"] != right["imported_source_records"]
    ):
        raise DiagnosticError("reference equivalence source evidence differs")
    for metadata, authority in (
        (left, reference_authority),
        (right, candidate_authority),
    ):
        if authority is None:
            continue
        capability, scene_scope_nonce = authority
        sealed = tuple(dict(item) for item in capability.source_records)
        observed = tuple(dict(item) for item in metadata["imported_source_records"])
        if not observed or any(item not in sealed for item in observed):
            raise DiagnosticError(
                "reference equivalence source evidence differs from capability"
            )
    left_rows = left["trial_bank_rows"]
    right_rows = right["trial_bank_rows"]
    if (
        not isinstance(left_rows, list)
        or not isinstance(right_rows, list)
        or len(left_rows) != len(reference.trial_ids)
        or len(right_rows) != len(candidate.trial_ids)
        or any(
            not isinstance(row, Mapping)
            or set(row) != {"trial_id", "bank_row_index"}
            or not isinstance(row["trial_id"], int)
            or isinstance(row["trial_id"], bool)
            or not isinstance(row["bank_row_index"], int)
            or isinstance(row["bank_row_index"], bool)
            for row in (*left_rows, *right_rows)
        )
        or [row["trial_id"] for row in left_rows] != list(reference.trial_ids)
        or [row["trial_id"] for row in right_rows] != list(candidate.trial_ids)
        or left_rows != [right_rows[index] for index in order]
    ):
        raise DiagnosticError("reference equivalence trial metadata differs")
    if (
        reference.batch_size != candidate.batch_size
        or not isinstance(reference.batch_size, int)
        or reference.batch_size <= 0
    ):
        raise DiagnosticError("reference equivalence batch size differs")
    for key in ("worker_pid", "worker_nonce", "model_nonce", "cache_nonce"):
        if not left[key] or not right[key] or left[key] == right[key]:
            raise DiagnosticError(f"reference equivalence cold isolation failed: {key}")
    left_roots, right_roots = left["cache_roots"], right["cache_roots"]
    if (
        not isinstance(left_roots, Mapping)
        or not isinstance(right_roots, Mapping)
        or not left_roots
        or set(left_roots) != set(right_roots)
        or any(
            not isinstance(value, str) or not value
            for value in (*left_roots.values(), *right_roots.values())
        )
        or set(left_roots.values()) & set(right_roots.values())
    ):
        raise DiagnosticError("reference equivalence cache roots are not isolated")
    _validate_isolated_roots(
        {"scratch": left["scratch_root"], **dict(left_roots)},
        {"scratch": right["scratch_root"], **dict(right_roots)},
    )
    for metadata in (left, right):
        record = metadata["attestation"]
        expected_input_context_sha = hashlib.sha256(
            _get_trace().canonical_json_bytes(
                {
                    "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
                    "v4_protocol": V4_PROTOCOL,
                    "evaluator_sha256": V4_EVALUATOR_SHA256,
                    "manifest_sha256": V4_MANIFEST_SHA256,
                    "load_report_sha256": metadata["load_report_sha256"],
                    "imported_source_records": tuple(
                        metadata["imported_source_records"]
                    ),
                }
            )
        ).hexdigest()
        if (
            not isinstance(record, Mapping)
            or record.get("basis") != "static_formal40_worker_attestation"
            or record.get("limitation")
            != "inference-disabled versions are not dynamic mutation detection"
            or record.get("diagnostic_protocol") != DIAGNOSTIC_PROTOCOL
            or record.get("v4_protocol") != V4_PROTOCOL
            or record.get("evaluator_sha256") != V4_EVALUATOR_SHA256
            or record.get("manifest_sha256") != V4_MANIFEST_SHA256
            or record.get("model_id") != "formal40"
            or (
                reference_authority is not None
                and record.get("trust_domain")
                != (reference_authority if metadata is left else candidate_authority)[
                    0
                ].trust_domain
            )
            or (
                reference_authority is not None
                and record.get("scene_scope_nonce")
                != (reference_authority if metadata is left else candidate_authority)[1]
            )
            or record.get("worker_pid") != metadata["worker_pid"]
            or record.get("worker_nonce") != metadata["worker_nonce"]
            or record.get("model_nonce") != metadata["model_nonce"]
            or record.get("load_report_sha256") != metadata["load_report_sha256"]
            or not isinstance(record.get("input_context_sha256"), str)
            or record["input_context_sha256"] != expected_input_context_sha
        ):
            raise DiagnosticError("reference equivalence attestation is invalid")
    return {"reference": dict(left), "a2": dict(right)}


def _validate_isolated_roots(
    reference: Mapping[str, str], a2: Mapping[str, str]
) -> dict[str, dict[str, Any]]:
    required = {"scratch", "torchinductor", "triton", "cuda"}
    if (
        not isinstance(reference, Mapping)
        or not isinstance(a2, Mapping)
        or set(reference) != required
        or set(a2) != required
    ):
        raise DiagnosticError("cold-isolation root schema is invalid")
    resolved: dict[str, dict[str, pathlib.Path]] = {"reference": {}, "a2": {}}
    for role, records in (("reference", reference), ("a2", a2)):
        for name, raw in records.items():
            if not isinstance(raw, str) or not pathlib.Path(raw).is_absolute():
                raise DiagnosticError("cold-isolation root is not absolute")
            named = pathlib.Path(raw)
            try:
                if stat.S_ISLNK(os.lstat(named).st_mode):
                    raise DiagnosticError("cold-isolation root is a symlink")
                canonical = named.resolve(strict=True)
            except OSError as error:
                raise DiagnosticError("cold-isolation root is unavailable") from error
            if str(named) != str(canonical) or not canonical.is_dir():
                raise DiagnosticError("cold-isolation root is not canonical")
            resolved[role][name] = canonical
    flattened = [
        (role, name, path)
        for role, records in resolved.items()
        for name, path in records.items()
    ]
    for index, (left_role, left_name, left_path) in enumerate(flattened):
        for right_role, right_name, right_path in flattened[index + 1 :]:
            own_scratch_contains_cache = left_role == right_role and (
                (left_name == "scratch" and left_path in right_path.parents)
                or (right_name == "scratch" and right_path in left_path.parents)
            )
            if own_scratch_contains_cache:
                continue
            try:
                same_file = os.path.samefile(left_path, right_path)
            except OSError as error:
                raise DiagnosticError(
                    "cold-isolation root identity is unavailable"
                ) from error
            if (
                same_file
                or left_path == right_path
                or left_path in right_path.parents
                or right_path in left_path.parents
            ):
                raise DiagnosticError(
                    "cold-isolation roots overlap: "
                    f"{left_role}.{left_name}/{right_role}.{right_name}"
                )
    evidence: dict[str, dict[str, Any]] = {}
    for role, records in resolved.items():
        evidence[role] = {}
        for name, path in records.items():
            info = os.stat(path, follow_symlinks=False)
            evidence[role][name] = {
                "path": str(path),
                "device": info.st_dev,
                "inode": info.st_ino,
                "mode": stat.S_IMODE(info.st_mode),
                "type": "directory",
            }
    return evidence


def _compare_reference_equivalence_core(
    reference: PassResult,
    a2: PassResult,
    reference_authority: tuple[_FrozenContextCapability, str] | None = None,
    a2_authority: tuple[_FrozenContextCapability, str] | None = None,
) -> dict[str, Any]:
    if reference.pass_id != a2.pass_id:
        raise DiagnosticError("reference and trace pass IDs differ")
    reference_ids = _validate_trial_ids(reference.trial_ids, len(reference.trial_ids))
    candidate_ids = _validate_trial_ids(a2.trial_ids, len(a2.trial_ids))
    order = _aligned_order(reference_ids, candidate_ids)
    metadata = _require_equivalence_metadata(
        reference, a2, order, reference_authority, a2_authority
    )
    comparisons: dict[str, Mapping[str, Any]] = {}
    for name in ("raw_scene", "raw_cue"):
        left = _payload(reference.boundary_records.get(name), name)
        right = _payload(a2.boundary_records.get(name), name)[order]
        try:
            comparison = _get_trace().compare_aligned_tensor(
                left, right, trial_ids=reference_ids, boundary=name
            )
        except Exception as error:
            raise DiagnosticError(f"{name} equivalence comparison failed") from error
        comparisons[name] = comparison
    reference_outputs = _validate_official_outputs(
        reference.outputs, batch_size=len(reference_ids)
    )
    candidate_outputs = _validate_official_outputs(
        a2.outputs, batch_size=len(candidate_ids)
    )
    for name in _OFFICIAL_OUTPUT_KEYS:
        try:
            comparison = _get_trace().compare_aligned_tensor(
                reference_outputs[name],
                candidate_outputs[name][order],
                trial_ids=reference_ids,
                boundary=name,
            )
        except Exception as error:
            raise DiagnosticError(f"{name} equivalence comparison failed") from error
        comparisons[name] = comparison
    try:
        comparisons["correct"] = _get_trace().compare_aligned_tensor(
            _derived_correct(reference.boundary_records),
            _derived_correct(a2.boundary_records)[order],
            trial_ids=reference_ids,
            boundary="correct",
        )
    except Exception as error:
        raise DiagnosticError("correct equivalence comparison failed") from error
    for name, comparison in comparisons.items():
        if (
            not comparison.get("schema_valid")
            or not comparison.get("finite_valid")
            or not comparison.get("bitwise_equal")
        ):
            raise DiagnosticError(f"reference equivalence failed at {name}")
    reference_model = _model_transition(reference.model_snapshots)
    trace_model = _model_transition(a2.model_snapshots)
    if not reference_model.get("state_unchanged") or not trace_model.get(
        "state_unchanged"
    ):
        raise DiagnosticError("model state mutation invalidates reference equivalence")
    reference_rng = _rng_transition(reference.rng_snapshots)
    trace_rng = _rng_transition(a2.rng_snapshots)
    return {
        "status": "REFERENCE_EQUIVALENCE_PASS",
        "trial_ids": list(reference_ids),
        "comparisons": comparisons,
        "reference_model_state_unchanged": True,
        "trace_model_state_unchanged": True,
        "reference_rng_changed": bool(reference_rng["rng_changed"]),
        "trace_rng_changed": bool(trace_rng["rng_changed"]),
        "metadata": metadata,
    }


def compare_reference_equivalence(reference: Any, a2: Any) -> dict[str, Any]:
    """Production gate: only coordinator-authenticated production wrappers."""
    left, left_capability, left_scope, _ = _unwrap_authenticated_pass(
        reference, trust_domain="production"
    )
    right, right_capability, right_scope, _ = _unwrap_authenticated_pass(
        a2, trust_domain="production"
    )
    return _compare_reference_equivalence_core(
        left,
        right,
        (left_capability, left_scope),
        (right_capability, right_scope),
    )


def _compare_reference_equivalence_hermetic(reference: Any, a2: Any) -> dict[str, Any]:
    """Private semantic-core test seam; never exposed by the production CLI."""
    left, left_capability, left_scope, _ = _unwrap_authenticated_pass(
        reference, trust_domain="hermetic-test"
    )
    right, right_capability, right_scope, _ = _unwrap_authenticated_pass(
        a2, trust_domain="hermetic-test"
    )
    return _compare_reference_equivalence_core(
        left,
        right,
        (left_capability, left_scope),
        (right_capability, right_scope),
    )


CANARY_REFERENCE_THRESHOLD = 1e-6
NONFINITE_LOCATION_LIMIT = 128
CELL_DERIVED_BOUNDARIES = (
    "target_logit",
    "logsumexp",
    "target_log_probability",
    "nll",
    "p_target",
    "p_probe_distractor",
    "pred_label",
    "correct",
)
DIVERGENCE_GROUPS = (
    ("raw", ("raw_scene", "raw_cue")),
    ("normalized_waveform", ("normalized_scene", "normalized_cue")),
    ("cochleagram", ("scene_features", "cue_features")),
    ("logits", ("native_logits",)),
    ("log_softmax_nll", ("log_probabilities", *CELL_DERIVED_BOUNDARIES)),
)


def first_divergence(comparisons: Mapping[str, Any]) -> str | None:
    """First observed bitwise difference; this is not a numerical root cause."""
    for _, names in DIVERGENCE_GROUPS:
        for name in names:
            record = comparisons.get(name)
            if (
                not isinstance(record, Mapping)
                or record.get("schema_valid") is not True
                or record.get("finite_valid") is not True
            ):
                raise DiagnosticError(
                    "first divergence requires complete valid comparisons"
                )
    for group, names in DIVERGENCE_GROUPS:
        if any(comparisons[name]["bitwise_equal"] is not True for name in names):
            return group
    return None


def classify_a2(comparison: Mapping[str, Any]) -> str:
    """Classify only valid A2 observations against the unchanged v4 threshold."""
    delta = comparison.get("nll_max_abs")
    if (
        comparison.get("cell_id") != "A2"
        or comparison.get("cell_status") not in {"PASS", "DIFF"}
        or comparison.get("identity_exact") is not True
        or type(comparison.get("pred_exact")) is not bool
        or type(delta) not in {int, float}
        or not math.isfinite(delta)
        or delta < 0
    ):
        raise DiagnosticError(
            "A2 classification requires valid aligned finite evidence"
        )
    if comparison["pred_exact"]:
        return "REPRODUCED" if delta > CANARY_REFERENCE_THRESHOLD else "NOT_REPRODUCED"
    return "DIFFERENT_NUMERIC_BEHAVIOR"


def _bounded_boundary_comparison(
    left: Any, right: Any, *, ids: tuple[int, ...], name: str
) -> dict[str, Any]:
    """Bound nonfinite diagnostics *before* the finite-only numeric helper."""
    import numpy as np
    import torch

    failure = {
        "boundary": name,
        "schema_valid": False,
        "finite_valid": False,
        "bitwise_equal": False,
        "schema_errors": [],
    }
    if (
        type(left) is not type(right)
        or type(left) not in {torch.Tensor, np.ndarray}
        or left.shape != right.shape
        or left.dtype != right.dtype
        or left.ndim == 0
        or left.shape[0] != len(ids)
    ):
        failure["schema_errors"].append("tensor type/shape/dtype/trial axis differs")
        return failure
    if (
        type(left) is np.ndarray
        and left.dtype.kind not in "biuf"
        or type(left) is torch.Tensor
        and left.is_complex()
    ):
        failure["schema_errors"].append("tensor dtype is not a real numeric type")
        return failure
    element_count = left.numel() if type(left) is torch.Tensor else left.size
    if element_count == 0:
        failure["schema_errors"].append("empty tensor is invalid")
        return failure
    left64 = (
        left.detach().cpu().to(torch.float64).numpy()
        if type(left) is torch.Tensor
        else np.asarray(left, dtype=np.float64)
    )
    right64 = (
        right.detach().cpu().to(torch.float64).numpy()
        if type(right) is torch.Tensor
        else np.asarray(right, dtype=np.float64)
    )
    left_flat, right_flat = left64.reshape(-1), right64.reshape(-1)
    count = 0
    locations = []

    def label(value):
        return (
            "NaN"
            if math.isnan(value)
            else "+Inf"
            if value == math.inf
            else "-Inf"
            if value == -math.inf
            else "finite"
        )

    for start in range(0, left_flat.size, 32768):
        stop = min(start + 32768, left_flat.size)
        bad = ~np.isfinite(left_flat[start:stop]) | ~np.isfinite(right_flat[start:stop])
        count += int(np.count_nonzero(bad))
        remaining = NONFINITE_LOCATION_LIMIT - len(locations)
        if remaining:
            for offset in np.flatnonzero(bad)[:remaining]:
                flat_index = start + int(offset)
                index = [int(i) for i in np.unravel_index(flat_index, left64.shape)]
                locations.append(
                    {
                        "index": index,
                        "trial_id": ids[index[0]],
                        "left": label(float(left_flat[flat_index])),
                        "right": label(float(right_flat[flat_index])),
                    }
                )
    if count:
        return {
            **failure,
            "schema_valid": True,
            "classification": "NONFINITE",
            "bitwise_equal": (
                _get_trace().canonical_tensor_bytes(left)
                == _get_trace().canonical_tensor_bytes(right)
            ),
            "nonfinite_count": count,
            "nonfinite_locations": locations,
            "nonfinite_truncated": count > len(locations),
            "schema_errors": ["tensor contains non-finite values"],
        }
    return _get_trace().compare_aligned_tensor(
        left,
        right,
        trial_ids=ids,
        boundary=name,
        class_axis=1 if name in {"native_logits", "log_probabilities"} else None,
    )


def _validate_cell_pass(result: PassResult, spec: CellSpec, pass_index: int) -> None:
    import numpy as np
    import torch

    if (
        type(result) is not PassResult
        or result.pass_id != f"pass{pass_index + 1}"
        or result.batch_size != spec.pass_batch_sizes[pass_index]
    ):
        raise DiagnosticError("cell pass identity/batch size differs from fixed matrix")
    ids = _validate_trial_ids(result.trial_ids, 32)
    metadata = result.boundary_records.get("metadata")
    if (
        not isinstance(metadata, Mapping)
        or metadata.get("role") != spec.cell_id
        or metadata.get("path") != "traced"
        or metadata.get("autocast_enabled") is not spec.autocast_enabled
    ):
        raise DiagnosticError("cell runtime role/path/autocast is invalid")
    _require_frozen_numeric_runtime(
        metadata.get("runtime"), "cell runtime differs from frozen v4 settings"
    )
    _require_load_report(metadata.get("load_report"))
    report_hash = hashlib.sha256(
        _get_trace().canonical_json_bytes(metadata["load_report"])
    ).hexdigest()
    if metadata.get("load_report_sha256") != report_hash:
        raise DiagnosticError("cell strict-load report binding is invalid")
    commitment = result.boundary_records.get("pass_commitment")
    digest = hashlib.sha256(
        _get_trace().canonical_json_bytes(_pass_commitment_payload(result))
    ).hexdigest()
    if (
        not isinstance(commitment, Mapping)
        or commitment.get("binding_sha256") != digest
    ):
        raise DiagnosticError("cell pass commitment changed")
    rows = metadata.get("trial_bank_rows")
    if (
        not isinstance(rows, list)
        or len(rows) != 32
        or any(
            not isinstance(row, Mapping)
            or set(row) != {"trial_id", "bank_row_index"}
            or row["trial_id"] != trial_id
            or type(row["bank_row_index"]) is not int
            or row["bank_row_index"] < 0
            for row, trial_id in zip(rows, ids)
        )
        or len({row["bank_row_index"] for row in rows}) != 32
    ):
        raise DiagnosticError("cell trial/bank alignment is invalid")
    official = _validate_official_outputs(result.outputs, batch_size=32)
    derived = result.boundary_records.get("derived")
    if not isinstance(derived, Mapping) or set(derived) != set(CELL_DERIVED_BOUNDARIES):
        raise DiagnosticError("cell derived boundary inventory is invalid")
    for name in CELL_DERIVED_BOUNDARIES:
        value = _payload(derived[name], name)
        if type(value) not in {np.ndarray, torch.Tensor} or tuple(value.shape) != (32,):
            raise DiagnosticError(f"{name} must be a scalar-per-trial vector")
        array = value.detach().cpu().numpy() if type(value) is torch.Tensor else value
        if name == "correct":
            if array.dtype != np.dtype("bool"):
                raise DiagnosticError("correct must have boolean dtype")
        elif name in official:
            if array.dtype != official[
                name
            ].dtype or _get_trace().canonical_tensor_bytes(
                array
            ) != _get_trace().canonical_tensor_bytes(official[name]):
                raise DiagnosticError(f"{name} derived/official outputs disagree")
        elif not np.issubdtype(array.dtype, np.floating):
            raise DiagnosticError(f"{name} derived boundary must be floating point")
    for name in _TRACE_BOUNDARIES:
        record = result.boundary_records.get(name)
        value = _payload(record, name)
        if type(value) is not torch.Tensor or value.ndim == 0 or value.shape[0] != 32:
            raise DiagnosticError(f"{name} must be a captured 32-trial Torch tensor")
        guards = record.get("guards")
        expected_count = (32 + result.batch_size - 1) // result.batch_size
        if not isinstance(guards, (list, tuple)) or len(guards) != expected_count:
            raise DiagnosticError(f"{name} mutation guard inventory is invalid")
        for index, guard in enumerate(guards):
            before = guard.get("before") if isinstance(guard, Mapping) else None
            after = guard.get("after") if isinstance(guard, Mapping) else None
            if (
                not isinstance(before, Mapping)
                or not isinstance(after, Mapping)
                or before != after
                or not {
                    "object_id",
                    "version",
                    "version_tracking",
                    "shape",
                    "dtype",
                    "device",
                }.issubset(before)
                or before["shape"]
                != [
                    min(result.batch_size, 32 - index * result.batch_size),
                    *value.shape[1:],
                ]
                or before["dtype"] != str(value.dtype)
                or type(before["object_id"]) is not int
                or before["object_id"] < 0
            ):
                raise DiagnosticError(
                    f"{name} mutation guard changed or has invalid schema"
                )
            if before["version_tracking"] == "enabled":
                if type(before["version"]) is not int or before["version"] < 0:
                    raise DiagnosticError(f"{name} mutation guard version is invalid")
            elif before["version_tracking"] == "inference-disabled":
                if before["version"] is not None or before.get(
                    "static_attestation"
                ) != metadata.get("attestation"):
                    raise DiagnosticError(
                        f"{name} mutation guard lacks matching attestation"
                    )
            else:
                raise DiagnosticError(f"{name} mutation guard tracking mode is invalid")
        if name in {"native_logits", "log_probabilities"} and tuple(value.shape) != (
            32,
            800,
        ):
            raise DiagnosticError(f"{name} must have shape [32,800]")


def _cell_timepoints(first: PassResult, second: PassResult) -> dict[str, Any]:
    trace = _get_trace()
    for result in (first, second):
        _model_transition(result.model_snapshots)
        _rng_transition(result.rng_snapshots)
    if trace.canonical_json_bytes(
        first.model_snapshots["after"]
    ) != trace.canonical_json_bytes(second.model_snapshots["before"]):
        raise DiagnosticError("model state between-pass discontinuity")
    if first.rng_snapshots["after"] != second.rng_snapshots["before"]:
        raise DiagnosticError("RNG between-pass discontinuity")
    model = trace.compare_model_snapshots(
        {"entries": first.model_snapshots["before"]},
        {"entries": first.model_snapshots["after"]},
        {"entries": second.model_snapshots["after"]},
    )
    if not model["state_unchanged"]:
        raise DiagnosticError("model state mutation invalidates cell")
    rng = trace.compare_rng_snapshots(
        first.rng_snapshots["before"],
        first.rng_snapshots["after"],
        second.rng_snapshots["after"],
    )
    if not rng["schema_valid"]:
        raise DiagnosticError("RNG schema invalidates cell")
    return {"model_state": model, "rng": rng}


def compare_passes(
    first: PassResult, second: PassResult, *, spec: CellSpec
) -> dict[str, Any]:
    """Observe finite differences; invalid provenance/state wins before interpretation.

    This local semantic core does not authenticate a cross-process origin.
    Persistent inventories and coordinator receipts remain separate gates.
    """
    got = {
        "schema_version": 1,
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "evaluation_role": EVALUATION_ROLE,
        "cell_id": getattr(spec, "cell_id", None),
        "cell_status": "INVALID",
        "canary_status": None,
        "a2_replay_classification": None,
        "first_divergence": None,
        "targeted_trace_required": False,
        "identity_exact": False,
        "pred_exact": None,
        "nll_max_abs": None,
        "canary_threshold": CANARY_REFERENCE_THRESHOLD,
        "comparisons": {},
        "errors": [],
    }
    try:
        if type(spec) is not CellSpec or CELL_SPECS.get(spec.cell_id) != spec:
            raise DiagnosticError("cell spec differs from the fixed matrix")
        _validate_cell_pass(first, spec, 0)
        _validate_cell_pass(second, spec, 1)
        order = _aligned_order(first.trial_ids, second.trial_ids)
        left_meta, right_meta = (
            result.boundary_records["metadata"] for result in (first, second)
        )
        equal_fields = (
            "runtime",
            "load_report",
            "load_report_sha256",
            "imported_source_records",
            "worker_pid",
            "worker_nonce",
            "model_nonce",
            "scratch_root",
            "cache_roots",
            "attestation",
        )
        if (
            any(
                key not in left_meta
                or key not in right_meta
                or left_meta[key] != right_meta[key]
                for key in equal_fields
            )
            or not left_meta.get("cache_nonce")
            or not right_meta.get("cache_nonce")
            or left_meta["cache_nonce"] == right_meta["cache_nonce"]
        ):
            raise DiagnosticError("cell worker/runtime/load/cache identity differs")
        if left_meta["trial_bank_rows"] != [
            right_meta["trial_bank_rows"][i] for i in order
        ]:
            raise DiagnosticError("cell trial/bank identities differ")
        got.update(_cell_timepoints(first, second))
        boundaries = (*_TRACE_BOUNDARIES, *CELL_DERIVED_BOUNDARIES)
        for name in boundaries:
            if name in _TRACE_BOUNDARIES:
                left = _payload(first.boundary_records.get(name), name)
                right = _payload(second.boundary_records.get(name), name)[order]
            elif name in _OFFICIAL_OUTPUT_KEYS:
                left, right = first.outputs[name], second.outputs[name][order]
            else:
                left = _payload(first.boundary_records["derived"].get(name), name)
                right = _payload(second.boundary_records["derived"].get(name), name)[
                    order
                ]
            comparison = _bounded_boundary_comparison(
                left, right, ids=first.trial_ids, name=name
            )
            got["comparisons"][name] = comparison
            if not comparison.get("schema_valid") or not comparison.get("finite_valid"):
                got["errors"].append(f"{name}: invalid schema or non-finite values")
        if got["errors"]:
            return got
        if any(
            not got["comparisons"][name]["bitwise_equal"]
            for name in ("raw_scene", "raw_cue")
        ):
            raise DiagnosticError("raw scene/cue identity differs; not a numeric DIFF")
        got["identity_exact"] = True
        comparisons = got["comparisons"]
        got["pred_exact"] = comparisons["pred_label"]["bitwise_equal"]
        got["nll_max_abs"] = comparisons["nll"]["max_abs"]
        got["cell_status"] = (
            "PASS"
            if all(item["bitwise_equal"] for item in comparisons.values())
            else "DIFF"
        )
        got["canary_status"] = (
            "PASS"
            if got["pred_exact"]
            and comparisons["correct"]["bitwise_equal"]
            and all(
                comparisons[name]["max_abs"] <= CANARY_REFERENCE_THRESHOLD
                for name in ("nll", "p_target", "p_probe_distractor")
            )
            else "DIFF"
        )
        got["first_divergence"] = first_divergence(comparisons)
        got["targeted_trace_required"] = (
            comparisons["scene_features"]["bitwise_equal"]
            and comparisons["cue_features"]["bitwise_equal"]
            and not comparisons["native_logits"]["bitwise_equal"]
        )
        if spec.cell_id == "A2":
            got["a2_replay_classification"] = classify_a2(got)
    except (
        DiagnosticError,
        KeyError,
        TypeError,
        ValueError,
        _get_trace().TraceContractError,
    ) as error:
        got.update(
            cell_status="INVALID",
            canary_status=None,
            a2_replay_classification=None,
            first_divergence=None,
            targeted_trace_required=False,
        )
        got["errors"].append(str(error))
    return got


def encode_official_outputs(outputs: Mapping[str, Any]) -> dict[str, Any]:
    """Lossless, non-pickle transport for exactly 32 frozen official outputs."""
    import numpy as np

    values = _validate_official_outputs(outputs, batch_size=32)
    records = {}
    for name in _OFFICIAL_OUTPUT_KEYS:
        value = values[name]
        if (
            type(value) is not np.ndarray
            or value.dtype.kind not in "iuf"
            or value.dtype.itemsize > 8
        ):
            raise DiagnosticError("official output encoding has unsupported dtype")
        payload = value.tobytes(order="C")
        records[name] = {
            "dtype": value.dtype.str,
            "shape": [32],
            "bytes_hex": payload.hex(),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    return {"encoding": "ndarray-hex-c-order-v1", "outputs": records}


def decode_official_outputs(record: Mapping[str, Any]) -> dict[str, Any]:
    """Reconstruct exact bytes only after fixed shape/dtype/size/hash checks."""
    import numpy as np

    if (
        not isinstance(record, Mapping)
        or set(record) != {"encoding", "outputs"}
        or record["encoding"] != "ndarray-hex-c-order-v1"
        or not isinstance(record["outputs"], Mapping)
        or set(record["outputs"]) != set(_OFFICIAL_OUTPUT_KEYS)
    ):
        raise DiagnosticError("official output encoding schema is invalid")
    checked_payloads = {}
    for name in _OFFICIAL_OUTPUT_KEYS:
        value = record["outputs"][name]
        if (
            not isinstance(value, Mapping)
            or set(value) != {"dtype", "shape", "bytes_hex", "sha256"}
            or value["shape"] != [32]
            or type(value["dtype"]) is not str
            or len(value["dtype"]) > 4
            or type(value["bytes_hex"]) is not str
            or type(value["sha256"]) is not str
        ):
            raise DiagnosticError("official output encoding field is invalid")
        try:
            dtype = np.dtype(value["dtype"])
        except (TypeError, ValueError) as error:
            raise DiagnosticError(
                "official output encoding dtype is invalid"
            ) from error
        if (
            dtype.kind not in "iuf"
            or not 1 <= dtype.itemsize <= 8
            or dtype.hasobject
            or dtype.fields is not None
            or dtype.subdtype is not None
            or dtype.str != value["dtype"]
        ):
            raise DiagnosticError("official output encoding dtype is unsupported")
        if len(value["bytes_hex"]) != 32 * dtype.itemsize * 2 or any(
            character not in "0123456789abcdef" for character in value["bytes_hex"]
        ):
            raise DiagnosticError("official output encoding byte count/hex is invalid")
        payload = bytes.fromhex(value["bytes_hex"])
        if hashlib.sha256(payload).hexdigest() != value["sha256"]:
            raise DiagnosticError("official output encoding content digest differs")
        checked_payloads[name] = (payload, dtype)
    decoded = {
        name: np.frombuffer(payload, dtype=dtype, count=32)
        for name, (payload, dtype) in checked_payloads.items()
    }
    validated = _validate_official_outputs(decoded, batch_size=32)
    for value in validated.values():
        value.flags.writeable = False
    return validated


_REFERENCE_ARTIFACT_NAMES = frozenset(
    (
        "REFERENCE_INPUTS.json",
        "RUNTIME.json",
        "TRIAL_OUTPUTS.csv",
        "STATE_BEFORE.jsonl",
        "STATE_BETWEEN.jsonl",
        "STATE_AFTER.jsonl",
        "RNG_BEFORE.json",
        "RNG_BETWEEN.json",
        "RNG_AFTER.json",
        "REFERENCE_COMPLETE.json",
    )
)
_CELL_ARTIFACT_NAMES = frozenset(
    (
        "CELL_INPUTS.json",
        "RUNTIME.json",
        "TRIAL_OUTPUTS.csv",
        "STATE_BEFORE.jsonl",
        "STATE_BETWEEN.jsonl",
        "STATE_AFTER.jsonl",
        "RNG_BEFORE.json",
        "RNG_BETWEEN.json",
        "RNG_AFTER.json",
        "BOUNDARY_DIGESTS.jsonl",
        "LOGITS_PASS1.npy",
        "LOGITS_PASS2.npy",
        "COMPARISON.json",
        "CELL_COMPLETE.json",
    )
)
_WORST_BOUNDARIES = frozenset(
    (
        "raw_scene",
        "raw_cue",
        "normalized_scene",
        "normalized_cue",
        "scene_features",
        "cue_features",
        "native_logits",
        "log_probabilities",
    )
)
_WORST_SUFFIXES = ("pass1", "pass2", "difference")
_ARTIFACT_CHUNK_BYTES = 1 << 20


def _artifact_relative_parts(
    relative: str, *, directory: bool = False
) -> tuple[str, ...]:
    if type(relative) is not str or "\x00" in relative:
        raise DiagnosticError("invalid artifact relative path")
    parts = tuple(relative.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        raise DiagnosticError("artifact path is not a fixed relative path")
    allowed = False
    if directory:
        allowed = parts in (("reference_cold",), ("cells",)) or (
            len(parts) in (2, 3)
            and parts[0] == "cells"
            and parts[1] in CELL_SPECS
            and (len(parts) == 2 or parts[2] == "WORST_CASES")
        )
    elif len(parts) == 2 and parts[0] == "reference_cold":
        allowed = parts[1] in _REFERENCE_ARTIFACT_NAMES
    elif len(parts) == 3 and parts[0] == "cells" and parts[1] in CELL_SPECS:
        allowed = parts[2] in _CELL_ARTIFACT_NAMES
    elif (
        len(parts) == 4
        and parts[0] == "cells"
        and parts[1] in CELL_SPECS
        and parts[2] == "WORST_CASES"
    ):
        tokens = parts[3].split(".")
        allowed = (
            len(tokens) == 3
            and tokens[0] in _WORST_BOUNDARIES
            and tokens[1] in _WORST_SUFFIXES
            and tokens[2] == "npy"
        )
    if not allowed:
        raise DiagnosticError("artifact path is outside the approved namespace")
    return parts


class _PinnedArtifactDirectory:
    """Pin every ancestor from /; never resolve through symlinks to gain access."""

    def __init__(self, path: pathlib.Path):
        self.path = pathlib.Path(path)
        self.chain: list[tuple[int, os.stat_result, str | None]] = []

    def __enter__(self):
        if not self.path.is_absolute() or ".." in self.path.parts:
            raise DiagnosticError(
                "artifact directory must be an absolute canonical path"
            )
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        directory = getattr(os, "O_DIRECTORY", 0)
        if not nofollow or not directory:
            raise DiagnosticError(
                "descriptor-anchored directory operations unavailable"
            )
        flags = os.O_RDONLY | nofollow | directory
        try:
            fd = os.open("/", flags)
            try:
                opened = os.fstat(fd)
            except BaseException:
                os.close(fd)
                raise
            self.chain.append((fd, opened, None))
            for component in self.path.parts[1:]:
                parent = self.chain[-1][0]
                named = os.stat(component, dir_fd=parent, follow_symlinks=False)
                fd = os.open(component, flags, dir_fd=parent)
                try:
                    opened = os.fstat(fd)
                except BaseException:
                    os.close(fd)
                    raise
                self.chain.append((fd, opened, component))
                if not _same_directory_identity(named, opened):
                    raise DiagnosticError("artifact ancestor changed while opening")
            self.check()
            return self
        except (OSError, ValueError) as error:
            self.__exit__(None, None, None)
            raise DiagnosticError(
                "cannot pin real artifact directory ancestry"
            ) from error
        except BaseException:
            self.__exit__(None, None, None)
            raise

    @property
    def fd(self) -> int:
        if not self.chain:
            raise DiagnosticError("artifact directory is closed")
        return self.chain[-1][0]

    def check(self) -> None:
        if not self.chain:
            raise DiagnosticError("artifact directory is closed")
        try:
            for index, (fd, baseline, name) in enumerate(self.chain):
                opened = os.fstat(fd)
                named = (
                    os.stat(
                        name, dir_fd=self.chain[index - 1][0], follow_symlinks=False
                    )
                    if index
                    else os.lstat("/")
                )
                if not _same_directory_identity(
                    baseline, opened
                ) or not _same_directory_identity(opened, named):
                    raise DiagnosticError("artifact directory namespace changed")
        except OSError as error:
            raise DiagnosticError(
                "artifact directory namespace is unavailable"
            ) from error

    def __exit__(self, *_):
        for fd, _, _ in reversed(self.chain):
            os.close(fd)
        self.chain.clear()


def _npy_header(array: Any) -> bytes:
    import numpy as np

    if (
        type(array) is not np.ndarray
        or array.dtype.hasobject
        or array.dtype.fields is not None
        or array.dtype.subdtype is not None
        or array.dtype.kind not in "biuf"
        or array.dtype.itemsize not in (1, 2, 4, 8)
        or not 1 <= array.ndim <= 16
        or any(size <= 0 for size in array.shape)
    ):
        raise DiagnosticError("NPY requires a nonempty plain real numeric array")
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        stream,
        {
            "descr": np.lib.format.dtype_to_descr(array.dtype),
            "fortran_order": False,
            "shape": tuple(array.shape),
        },
    )
    return stream.getvalue()


def _npy_projected_size(array: Any) -> int:
    """Only the bounded header is allocated; include every NPY framing byte."""
    return len(_npy_header(array)) + int(array.nbytes)


class _AttemptArtifactStore:
    """Internal single-writer storage kernel, not a semantic result verifier.

    Task 6 must hold exclusive workflow ownership while one child publishes.
    No process is spawned here, and no COMPLETE marker is created automatically.
    """

    def __init__(self, root: pathlib.Path):
        self.root = pathlib.Path(root)
        self.anchor: _PinnedArtifactDirectory | None = None
        self._worst_plan: dict[str, int] | None = None

    def __enter__(self):
        job_id = self.root.name.removeprefix("slurm-")
        if (
            self.root.parent.name != "attempts"
            or self.root.name != f"slurm-{job_id}"
            or not job_id.isascii()
            or not job_id.isdecimal()
            or job_id.startswith("0")
            or len(job_id) > 20
        ):
            raise DiagnosticError("invalid canonical attempt root")
        self.anchor = _PinnedArtifactDirectory(self.root).__enter__()
        return self

    def __exit__(self, *args):
        if self.anchor is not None:
            self.anchor.__exit__(*args)
            self.anchor = None

    def _check(self) -> None:
        if self.anchor is None:
            raise DiagnosticError("artifact store is closed")
        self.anchor.check()

    @staticmethod
    def _parts(relative, *, directory=False):
        return _artifact_relative_parts(relative, directory=directory)

    @contextlib.contextmanager
    def _directory(self, relative: str, *, create: bool = False):
        parts = self._parts(relative, directory=True)
        self._check()
        # Pin each newly created component before descending to the next one.
        with contextlib.ExitStack() as stack:
            current = self.anchor
            for index, component in enumerate(parts):
                current.check()
                if create:
                    try:
                        os.mkdir(component, 0o700, dir_fd=current.fd)
                    except FileExistsError:
                        pass
                    else:
                        os.fsync(current.fd)
                path = self.root.joinpath(*parts[: index + 1])
                child = stack.enter_context(_PinnedArtifactDirectory(path))
                current.check()
                current = child
            try:
                yield current
            finally:
                current.check()
                self._check()

    def _record_at(self, directory, name: str, relative: str) -> dict[str, Any]:
        directory.check()
        fd = None
        try:
            named = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(named.st_mode)
                or named.st_nlink != 1
                or stat.S_IMODE(named.st_mode) != 0o600
            ):
                raise DiagnosticError(
                    "artifact must be a mode-0600 single-link regular file"
                )
            fd = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory.fd
            )
            opened = os.fstat(fd)
            if not _same_identity(named, opened):
                raise DiagnosticError("artifact replaced before open")
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = os.read(fd, _ARTIFACT_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
            after = os.fstat(fd)
            final_named = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
            if (
                not _same_identity(opened, after)
                or not _same_identity(after, final_named)
                or size != after.st_size
            ):
                raise DiagnosticError("artifact changed during streamed verification")
            directory.check()
            self._check()
            return {
                "path": str(self.root / relative),
                "relative_path": relative,
                "type": "file",
                "mode": 0o600,
                "size": size,
                "sha256": digest.hexdigest(),
                "st_dev": after.st_dev,
                "st_ino": after.st_ino,
                "st_mtime_ns": after.st_mtime_ns,
            }
        except OSError as error:
            raise DiagnosticError("artifact streamed read failed") from error
        finally:
            if fd is not None:
                os.close(fd)

    def record(self, relative: str) -> dict[str, Any]:
        parts = self._parts(relative)
        with self._directory("/".join(parts[:-1])) as directory:
            return self._record_at(directory, parts[-1], relative)

    def verify_record(self, expected: Mapping[str, Any]) -> dict[str, Any]:
        keys = {
            "path",
            "relative_path",
            "type",
            "mode",
            "size",
            "sha256",
            "st_dev",
            "st_ino",
            "st_mtime_ns",
        }
        if not isinstance(expected, Mapping) or set(expected) != keys:
            raise DiagnosticError("artifact record schema is invalid")
        actual = self.record(expected["relative_path"])
        # Device/inode/mtime are deliberately diagnostic across invocations.
        for key in ("path", "relative_path", "type", "mode", "size", "sha256"):
            if (
                type(expected[key]) is not type(actual[key])
                or expected[key] != actual[key]
            ):
                raise DiagnosticError(f"persisted artifact {key} differs")
        return actual

    def _publish(
        self, relative: str, chunks: Iterator[Any], projected: int
    ) -> dict[str, Any]:
        parts = self._parts(relative)
        if "WORST_CASES" in parts:
            if self._worst_plan is None or self._worst_plan.get(relative) != projected:
                raise DiagnosticError(
                    "worst-case writes require a complete budget reservation"
                )
        with self._directory("/".join(parts[:-1]), create=True) as directory:
            name = parts[-1]
            private = f".{name}.{uuid.uuid4().hex}.partial"
            fd = None
            owned = None
            removed = False
            try:
                try:
                    os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise FileExistsError(f"refusing existing artifact: {relative}")
                fd = os.open(
                    private,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory.fd,
                )
                owned = os.fstat(fd)
                os.fchmod(fd, 0o600)
                digest = hashlib.sha256()
                size = 0
                for chunk in chunks:
                    view = memoryview(chunk).cast("B")
                    if size + len(view) > projected:
                        raise DiagnosticError("artifact stream exceeds projected size")
                    digest.update(view)
                    size += len(view)
                    while view:
                        written = os.write(fd, view[:_ARTIFACT_CHUNK_BYTES])
                        if written <= 0:
                            raise DiagnosticError("artifact stream short write")
                        view = view[written:]
                if size != projected:
                    raise DiagnosticError("artifact stream differs from projected size")
                os.fsync(fd)
                before_link = os.fstat(fd)
                named_private = os.stat(
                    private, dir_fd=directory.fd, follow_symlinks=False
                )
                if (
                    not _same_identity(before_link, named_private)
                    or before_link.st_nlink != 1
                ):
                    raise DiagnosticError("private artifact identity changed")
                directory.check()
                self._check()
                os.link(
                    private,
                    name,
                    src_dir_fd=directory.fd,
                    dst_dir_fd=directory.fd,
                    follow_symlinks=False,
                )
                os.unlink(private, dir_fd=directory.fd)
                removed = True
                os.fsync(directory.fd)
                directory.check()
                final = self._record_at(directory, name, relative)
                after = os.fstat(fd)
                if (
                    not _same_identity(before_link, after)
                    or (after.st_dev, after.st_ino)
                    != (final["st_dev"], final["st_ino"])
                    or final["sha256"] != digest.hexdigest()
                    or final["size"] != size
                ):
                    raise DiagnosticError(
                        "published artifact differs from private stream identity"
                    )
                return final
            finally:
                # Never unlink a foreign replacement of our private name or a final artifact.
                try:
                    if owned is not None and not removed:
                        try:
                            current = os.stat(
                                private, dir_fd=directory.fd, follow_symlinks=False
                            )
                            if (current.st_dev, current.st_ino) == (
                                owned.st_dev,
                                owned.st_ino,
                            ):
                                os.unlink(private, dir_fd=directory.fd)
                        except FileNotFoundError:
                            pass
                finally:
                    if fd is not None:
                        os.close(fd)

    def publish_bytes(self, relative: str, payload: bytes) -> dict[str, Any]:
        if type(payload) is not bytes:
            raise DiagnosticError("artifact payload must be bytes")
        self._parts(relative)
        if relative.endswith(".npy"):
            raise DiagnosticError("NPY artifacts require the typed streaming writer")
        return self._publish(relative, iter((payload,)), len(payload))

    def publish_npy(self, relative: str, array: Any) -> dict[str, Any]:
        import numpy as np

        parts = _artifact_relative_parts(relative)
        header = _npy_header(array)
        if not parts[-1].endswith(".npy"):
            raise DiagnosticError("NPY requires an approved NPY target")
        if parts[-1].startswith("LOGITS_") and array.shape != (32, 800):
            raise DiagnosticError("logits artifact must have shape [32,800]")

        def chunks():
            yield header
            with np.nditer(
                array,
                flags=["external_loop", "buffered"],
                op_flags=["readonly", "contig"],
                order="C",
                buffersize=max(1, _ARTIFACT_CHUNK_BYTES // array.dtype.itemsize),
            ) as iterator:
                for chunk in iterator:
                    yield memoryview(chunk).cast("B")

        return self._publish(relative, chunks(), len(header) + int(array.nbytes))

    def verify_inventory(
        self,
        prefix: str,
        expected: Sequence[Mapping[str, Any]],
        *,
        directories: Sequence[str],
    ) -> list[dict[str, Any]]:
        _artifact_relative_parts(prefix, directory=True)
        expected_by_path = {record["relative_path"]: record for record in expected}
        if len(expected_by_path) != len(expected) or any(
            not name.startswith(prefix + "/") for name in expected_by_path
        ):
            raise DiagnosticError(
                "artifact inventory has duplicate or out-of-scope files"
            )
        expected_dirs = {prefix + "/" + name for name in directories}
        if len(expected_dirs) != len(directories):
            raise DiagnosticError("artifact directory inventory has duplicates")
        for name in expected_dirs:
            _artifact_relative_parts(name, directory=True)
        with contextlib.ExitStack() as stack:
            opened = stack.enter_context(self._directory(prefix))
            actual = {}
            found_dirs = set()
            scans = []

            def walk(directory, path):
                names = set(os.listdir(directory.fd))
                scans.append((directory, names, os.fstat(directory.fd)))
                for name in sorted(names):
                    rel = path + "/" + name
                    info = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        if rel not in expected_dirs:
                            raise DiagnosticError(
                                "artifact inventory has unexpected directory"
                            )
                        found_dirs.add(rel)
                        child = stack.enter_context(self._directory(rel))
                        walk(child, rel)
                    else:
                        if rel not in expected_by_path:
                            raise DiagnosticError(
                                "artifact inventory has unexpected file"
                            )
                        actual[rel] = self.verify_record(expected_by_path[rel])

            walk(opened, prefix)
            if set(actual) != set(expected_by_path) or found_dirs != expected_dirs:
                raise DiagnosticError("artifact inventory is incomplete")
            # Retain directory descriptors until the complete traversal is checked.
            for directory, names, baseline in scans:
                directory.check()
                if names != set(os.listdir(directory.fd)) or not _same_identity(
                    baseline, os.fstat(directory.fd)
                ):
                    raise DiagnosticError(
                        "artifact inventory namespace changed while traversing"
                    )
            # Re-read records to catch content changes after their first visit.
            for name, baseline in actual.items():
                final = self.record(name)
                if final != baseline:
                    raise DiagnosticError(
                        "artifact inventory changed after first verification"
                    )
            for directory, names, baseline in scans:
                directory.check()
                if names != set(os.listdir(directory.fd)) or not _same_identity(
                    baseline, os.fstat(directory.fd)
                ):
                    raise DiagnosticError(
                        "artifact inventory changed at final namespace check"
                    )
            return [actual[name] for name in sorted(actual)]

    def worst_case_bytes(self) -> int:
        """Count all four fixed WORST_CASES trees, including headers and partial evidence."""
        total = 0
        self._check()
        for cell in CELL_SPECS:
            prefix = f"cells/{cell}/WORST_CASES"
            # Missing directories are normal before their serial worker starts.
            try:
                with self._directory(prefix) as directory:
                    names = set(os.listdir(directory.fd))
                    baseline = os.fstat(directory.fd)
                    for name in sorted(names):
                        relative = prefix + "/" + name
                        _artifact_relative_parts(relative)
                        total += self._record_at(directory, name, relative)["size"]
                    if names != set(os.listdir(directory.fd)) or not _same_identity(
                        baseline, os.fstat(directory.fd)
                    ):
                        raise DiagnosticError(
                            "worst-case inventory changed during budget check"
                        )
            except DiagnosticError as error:
                if not isinstance(error.__cause__, FileNotFoundError):
                    raise
        self._check()
        return total

    def publish_worst_cases(
        self, cell: str, arrays: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        import numpy as np

        if cell not in CELL_SPECS or not isinstance(arrays, Mapping) or not arrays:
            raise DiagnosticError(
                "worst-case publication requires a fixed cell and complete trios"
            )
        boundaries = set()
        projected = 0
        for name, array in arrays.items():
            _artifact_relative_parts(f"cells/{cell}/WORST_CASES/{name}")
            boundaries.add(name.split(".")[0])
            projected += _npy_projected_size(array)
        for boundary in boundaries:
            keys = tuple(f"{boundary}.{suffix}.npy" for suffix in _WORST_SUFFIXES)
            if not all(key in arrays for key in keys):
                raise DiagnosticError("worst-case publication requires an entire trio")
            left, right, delta = (arrays[key] for key in keys)
            if (
                left.shape != right.shape
                or left.shape != delta.shape
                or left.dtype != right.dtype
                or delta.dtype != np.dtype("float64")
            ):
                raise DiagnosticError(
                    "worst-case trio shape or native/difference dtype differs"
                )
        existing = self.worst_case_bytes()
        # No caller-supplied limit, no module knob, and no write before full projection.
        if existing + projected > 1_073_741_824:
            raise DiagnosticError("global worst-case artifact budget exceeds 1 GiB")
        if self._worst_plan is not None:
            raise DiagnosticError("nested worst-case reservations are forbidden")
        self._worst_plan = {
            f"cells/{cell}/WORST_CASES/{name}": _npy_projected_size(array)
            for name, array in arrays.items()
        }
        try:
            return [
                self.publish_npy(f"cells/{cell}/WORST_CASES/{name}", arrays[name])
                for name in sorted(arrays)
            ]
        finally:
            self._worst_plan = None


def write_npy_create_once(path: pathlib.Path, array: Any) -> dict[str, Any]:
    """Production entry point; no arbitrary root or output namespace override."""
    path = pathlib.Path(path)
    try:
        relative = path.relative_to(DIAGNOSTIC_ROOT)
    except ValueError as error:
        raise DiagnosticError("NPY target is outside the diagnostic root") from error
    if len(relative.parts) < 4 or relative.parts[0] != "attempts":
        raise DiagnosticError("NPY target is not inside a fixed diagnostic attempt")
    attempt = DIAGNOSTIC_ROOT.joinpath(*relative.parts[:2])
    with _AttemptArtifactStore(attempt) as store:
        return store.publish_npy("/".join(relative.parts[2:]), array)


def _require_sha256(value: Any) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise DiagnosticError("expected a canonical SHA-256 digest")


def encode_pass_evidence(result: PassResult) -> dict[str, Any]:
    """Transport original commitments, never re-sign or invent tensor payloads."""
    payload = _pass_commitment_payload(result)
    commitment = _deep_plain_record(result.boundary_records.get("pass_commitment"))
    encoded = {
        "schema_version": 1,
        "payload": payload,
        "commitment": commitment,
        "official_outputs": encode_official_outputs(result.outputs),
    }
    decode_pass_evidence(encoded)
    return encoded


def decode_pass_evidence(record: Mapping[str, Any]) -> dict[str, Any]:
    """Verify serialized self-consistency; this is NOT child-origin authentication."""
    trace = _get_trace()
    if (
        not isinstance(record, Mapping)
        or set(record)
        != {"schema_version", "payload", "commitment", "official_outputs"}
        or type(record["schema_version"]) is not int
        or record["schema_version"] != 1
    ):
        raise DiagnosticError("pass transport schema differs")
    payload, commitment = record["payload"], record["commitment"]
    payload_keys = {
        "schema_version",
        "diagnostic_protocol",
        "v4_protocol",
        "evaluation_role",
        "evaluator_sha256",
        "manifest_sha256",
        "pass_id",
        "batch_size",
        "trial_ids",
        "outputs",
        "boundaries",
        "model_snapshots",
        "rng_snapshots",
    }
    if (
        not isinstance(payload, Mapping)
        or set(payload) != payload_keys
        or not isinstance(commitment, Mapping)
        or set(commitment) != {"schema_version", "binding_sha256", "scope"}
        or commitment["schema_version"] != 1
        or commitment["scope"] != "complete_pass_provenance_boundaries_outputs"
    ):
        raise DiagnosticError("pass commitment schema differs")
    _require_sha256(commitment["binding_sha256"])
    if (
        hashlib.sha256(trace.canonical_json_bytes(payload)).hexdigest()
        != commitment["binding_sha256"]
    ):
        raise DiagnosticError("pass commitment does not match serialized evidence")
    for key, expected in (
        ("schema_version", 1),
        ("diagnostic_protocol", DIAGNOSTIC_PROTOCOL),
        ("v4_protocol", V4_PROTOCOL),
        ("evaluation_role", EVALUATION_ROLE),
        ("evaluator_sha256", V4_EVALUATOR_SHA256),
        ("manifest_sha256", V4_MANIFEST_SHA256),
    ):
        if type(payload[key]) is not type(expected) or payload[key] != expected:
            raise DiagnosticError(f"pass transport {key} differs")
    ids = _validate_trial_ids(payload["trial_ids"], 32)
    if (
        payload["pass_id"] not in ("pass1", "pass2")
        or type(payload["batch_size"]) is not int
        or payload["batch_size"] not in (1, 16)
    ):
        raise DiagnosticError("pass transport identity/batch size differs")
    outputs = decode_official_outputs(record["official_outputs"])
    expected_outputs = {}
    for name, value in sorted(outputs.items()):
        entry = trace.tensor_record(value, boundary=f"output.{name}")
        expected_outputs[name] = {
            k: entry[k] for k in ("boundary", "shape", "dtype", "sha256")
        }
    if payload["outputs"] != expected_outputs:
        raise DiagnosticError("lossless outputs disagree with original pass commitment")
    boundaries = payload["boundaries"]
    if not isinstance(boundaries, Mapping) or not isinstance(
        boundaries.get("metadata"), Mapping
    ):
        raise DiagnosticError("pass transport lacks boundary metadata")
    for name in ("raw_scene", "raw_cue"):
        boundary = boundaries.get(name)
        if not isinstance(boundary, Mapping) or set(boundary) != {
            "tensor",
            "aggregate",
            "per_trial",
            "guards",
        }:
            raise DiagnosticError("pass raw digest inventory is incomplete")
        rows = boundary["per_trial"]
        if (
            not isinstance(rows, list)
            or len(rows) != 32
            or any(
                not isinstance(row, Mapping)
                or row.get("trial_id") != ident
                or row.get("boundary") != name
                for row, ident in zip(rows, ids)
            )
        ):
            raise DiagnosticError("pass raw digest trial identity differs")
        for row in rows:
            _require_sha256(row.get("sha256"))
        for key in ("shape", "dtype", "sha256"):
            if boundary["tensor"].get(key) != boundary["aggregate"].get(key):
                raise DiagnosticError("pass raw aggregate binding differs")
    return {"payload": payload, "outputs": outputs}


def _child_location(
    path: pathlib.Path, *, reference: bool
) -> tuple[pathlib.Path, str, str | None]:
    try:
        parts = pathlib.Path(path).relative_to(DIAGNOSTIC_ROOT).parts
    except ValueError as error:
        raise DiagnosticError("child result path escapes diagnostic root") from error
    expected_length = 3 if reference else 4
    if (
        len(parts) != expected_length
        or parts[0] != "attempts"
        or (reference and parts[2] != "reference_cold")
        or (not reference and (parts[2] != "cells" or parts[3] not in CELL_SPECS))
    ):
        raise DiagnosticError("child result path differs from fixed attempt layout")
    return (
        DIAGNOSTIC_ROOT.joinpath(*parts[:2]),
        "/".join(parts[2:]),
        None if reference else parts[3],
    )


def _trial_documents(trials: Sequence[TrialSpec]) -> list[dict[str, Any]]:
    if (
        not isinstance(trials, (tuple, list))
        or len(trials) != 32
        or any(type(t) is not TrialSpec for t in trials)
    ):
        raise DiagnosticError("child evidence requires 32 frozen TrialSpec records")
    rows = [dataclasses.asdict(t) for t in trials]
    _validate_trial_documents(rows)
    return rows


def _validate_trial_documents(rows: Any) -> None:
    if (
        not isinstance(rows, list)
        or len(rows) != 32
        or any(
            not isinstance(row, Mapping)
            or set(row) != {"ordinal", "trial_id", "bank_row_index", "identity"}
            or type(row["ordinal"]) is not int
            or row["ordinal"] != i
            or type(row["trial_id"]) is not int
            or type(row["bank_row_index"]) is not int
            or row["bank_row_index"] < 0
            or not isinstance(row["identity"], Mapping)
            or row["identity"].get("trial_id") != row["trial_id"]
            for i, row in enumerate(rows)
        )
    ):
        raise DiagnosticError("frozen child trial document schema differs")
    if (
        len({row["trial_id"] for row in rows}) != 32
        or len({row["bank_row_index"] for row in rows}) != 32
    ):
        raise DiagnosticError("frozen child trial identities are not unique")


def _child_inputs(result: Mapping[str, Any], *, cell: str | None) -> dict[str, Any]:
    if (
        not isinstance(result, Mapping)
        or set(result) != {"trials", "passes", "spec", "input_freeze_sha256"}
        or not isinstance(result["passes"], (list, tuple))
        or len(result["passes"]) != 2
    ):
        raise DiagnosticError("child result input schema differs")
    spec = CELL_SPECS[cell] if cell else None
    if result["spec"] != spec:
        raise DiagnosticError("child result spec differs from directory identity")
    _require_sha256(result["input_freeze_sha256"])
    document = {
        "schema_version": 1,
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "evaluation_role": EVALUATION_ROLE,
        "kind": "cell" if cell else "reference_cold",
        "input_freeze_sha256": result["input_freeze_sha256"],
        "cell_spec": dataclasses.asdict(spec) if spec else None,
        "trials": _trial_documents(result["trials"]),
        "passes": [encode_pass_evidence(item) for item in result["passes"]],
    }
    # Normalize tuple/list representation exactly as it will be stored.
    document = json.loads(_get_trace().canonical_json_bytes(document))
    _validate_child_inputs(document, cell=cell, freeze=result["input_freeze_sha256"])
    return document


def _validate_child_inputs(
    document: Any, *, cell: str | None, freeze: str
) -> list[dict[str, Any]]:
    keys = {
        "schema_version",
        "diagnostic_protocol",
        "evaluation_role",
        "kind",
        "input_freeze_sha256",
        "cell_spec",
        "trials",
        "passes",
    }
    if not isinstance(document, Mapping) or set(document) != keys:
        raise DiagnosticError("child inputs schema differs")
    _require_sha256(freeze)
    for name, expected in (
        ("schema_version", 1),
        ("diagnostic_protocol", DIAGNOSTIC_PROTOCOL),
        ("evaluation_role", EVALUATION_ROLE),
        ("kind", "cell" if cell else "reference_cold"),
        ("input_freeze_sha256", freeze),
    ):
        if type(document[name]) is not type(expected) or document[name] != expected:
            raise DiagnosticError(f"child inputs {name} differs")
    spec = CELL_SPECS[cell] if cell else None
    expected_spec = (
        json.loads(_get_trace().canonical_json_bytes(dataclasses.asdict(spec)))
        if spec
        else None
    )
    if (
        document["cell_spec"] != expected_spec
        or not isinstance(document["passes"], list)
        or len(document["passes"]) != 2
    ):
        raise DiagnosticError("child inputs spec/pass count differs")
    _validate_trial_documents(document["trials"])
    expected_rows = {
        row["trial_id"]: row["bank_row_index"] for row in document["trials"]
    }
    decoded = [decode_pass_evidence(item) for item in document["passes"]]
    for index, item in enumerate(decoded):
        p = item["payload"]
        batches = spec.pass_batch_sizes if spec else (16, 1)
        if p["pass_id"] != f"pass{index + 1}" or p["batch_size"] != batches[index]:
            raise DiagnosticError("child pass order/batch sizes differ")
        metadata = p["boundaries"]["metadata"]
        expected_role = (
            (cell, "traced", spec.autocast_enabled)
            if spec
            else ("REFERENCE_COLD", "frozen_predict_batch", None)
        )
        if (
            tuple(metadata.get(key) for key in ("role", "path", "autocast_enabled"))
            != expected_role
        ):
            raise DiagnosticError("child pass role/path/autocast differs")
        rows = metadata.get("trial_bank_rows")
        if (
            not isinstance(rows, list)
            or len(rows) != 32
            or set(p["trial_ids"]) != set(expected_rows)
            or any(
                not isinstance(row, Mapping)
                or set(row) != {"trial_id", "bank_row_index"}
                or row["trial_id"] != ident
                or row["bank_row_index"] != expected_rows[ident]
                for ident, row in zip(p["trial_ids"], rows)
            )
        ):
            raise DiagnosticError("child pass frozen trial/bank identity differs")
        required = set(_TRACE_BOUNDARIES) if cell else {"raw_scene", "raw_cue"}
        if set(p["boundaries"]) != required | {"derived", "metadata"}:
            raise DiagnosticError("child pass boundary inventory differs")
        derived = set(CELL_DERIVED_BOUNDARIES) if cell else {"correct"}
        if set(p["boundaries"]["derived"]) != derived:
            raise DiagnosticError("child derived boundary inventory differs")
        _require_load_report(metadata.get("load_report"))
        if hashlib.sha256(
            _get_trace().canonical_json_bytes(metadata["load_report"])
        ).hexdigest() != metadata.get("load_report_sha256"):
            raise DiagnosticError("child load report binding differs")
        # Schema validation permits a changed model/RNG to be recorded as INVALID.
        _model_transition(p["model_snapshots"])
        _rng_transition(p["rng_snapshots"])
    return decoded


def _child_views(inputs: Mapping[str, Any]) -> dict[str, bytes]:
    """Recomputable human-readable views of the lossless pass documents."""
    canonical = _get_trace().canonical_json_bytes
    passes = [decode_pass_evidence(item) for item in inputs["passes"]]
    payloads = [p["payload"] for p in passes]
    files = {
        "RUNTIME.json": canonical(
            {
                "schema_version": 1,
                "passes": [p["boundaries"]["metadata"] for p in payloads],
            }
        )
    }
    for family, extension in (("model_snapshots", "jsonl"), ("rng_snapshots", "json")):
        a, b = (p[family] for p in payloads)
        between = (
            [{"observation": "between_shared", "value": a["after"]}]
            if a["after"] == b["before"]
            else [
                {"observation": "pass1_after", "value": a["after"]},
                {"observation": "pass2_before", "value": b["before"]},
            ]
        )
        observations = {
            "BEFORE": [{"observation": "pass1_before", "value": a["before"]}],
            "BETWEEN": between,
            "AFTER": [{"observation": "pass2_after", "value": b["after"]}],
        }
        for timepoint, rows in observations.items():
            label = "STATE" if family == "model_snapshots" else "RNG"
            files[f"{label}_{timepoint}.{extension}"] = (
                b"".join(canonical(row) for row in rows)
                if extension == "jsonl"
                else canonical({"observations": rows})
            )
    stream = io.StringIO(newline="")
    columns = [
        "pass_id",
        "batch_size",
        "ordinal",
        "trial_id",
        "bank_row_index",
        *_OFFICIAL_OUTPUT_KEYS,
        "correct",
    ]
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for item in passes:
        payload, outputs = item["payload"], item["outputs"]
        positions = {ident: i for i, ident in enumerate(payload["trial_ids"])}
        for trial in inputs["trials"]:
            index = positions[trial["trial_id"]]
            row = {key: trial[key] for key in ("ordinal", "trial_id", "bank_row_index")}
            row.update(pass_id=payload["pass_id"], batch_size=payload["batch_size"])
            row.update({name: value[index].item() for name, value in outputs.items()})
            target = trial["identity"].get("target_label")
            row["correct"] = "" if target is None else int(row["pred_label"] == target)
            writer.writerow(row)
    files["TRIAL_OUTPUTS.csv"] = stream.getvalue().encode("utf-8")
    if inputs["kind"] == "cell":
        rows = []
        for p in payloads:
            for name in (*_TRACE_BOUNDARIES, *CELL_DERIVED_BOUNDARIES):
                boundary = p["boundaries"].get(
                    name, p["boundaries"]["derived"].get(name)
                )
                rows.append(
                    {"pass_id": p["pass_id"], "boundary": name, "record": boundary}
                )
        files["BOUNDARY_DIGESTS.jsonl"] = b"".join(canonical(row) for row in rows)
    return files


def _cpu_artifact_array(value: Any):
    import torch

    if type(value) is not torch.Tensor or value.device.type != "cpu":
        raise DiagnosticError(
            "artifact tensors must be existing post-output CPU captures"
        )
    try:
        array = value.detach().numpy()
        _npy_header(array)
    except (TypeError, ValueError) as error:
        raise DiagnosticError("unsupported native artifact tensor") from error
    return array


def _select_child_worst(result: Mapping[str, Any], comparison: Mapping[str, Any]):
    import numpy as np

    first, second = result["passes"]
    names = {"scene_features", "cue_features"}
    for name in _TRACE_BOUNDARIES:
        record = comparison["comparisons"].get(name)
        if name in _WORST_BOUNDARIES and record and not record.get("bitwise_equal"):
            names.add(name)
    first_index = {ident: i for i, ident in enumerate(first.trial_ids)}
    second_index = {ident: i for i, ident in enumerate(second.trial_ids)}
    arrays, selected = {}, {}
    for name in sorted(names):
        left = _cpu_artifact_array(first.boundary_records[name]["tensor"])
        right = _cpu_artifact_array(second.boundary_records[name]["tensor"])
        if left.shape != right.shape or left.dtype != right.dtype:
            raise DiagnosticError(
                "cannot publish complete worst-case trio for incompatible shapes/dtypes"
            )
        worst, score = None, -1.0
        for trial in result["trials"]:
            li, ri = first_index[trial.trial_id], second_index[trial.trial_id]
            with np.errstate(invalid="ignore", over="ignore"):
                delta = right[ri].astype(np.float64) - left[li].astype(np.float64)
                current = (
                    float(np.max(np.abs(delta)))
                    if np.isfinite(delta).all()
                    else float("inf")
                )
            if current > score:
                worst, score = trial, current
        li, ri = first_index[worst.trial_id], second_index[worst.trial_id]
        with np.errstate(invalid="ignore", over="ignore"):
            triple = (
                left[li],
                right[ri],
                right[ri].astype(np.float64) - left[li].astype(np.float64),
            )
        selected[name] = {
            "trial_id": worst.trial_id,
            "ordinal": worst.ordinal,
            "pass1_index": li,
            "pass2_index": ri,
            "selection_rule": "maximum_abs_difference__nonfinite_first__frozen_ordinal_tie",
        }
        for suffix, array in zip(_WORST_SUFFIXES, triple):
            arrays[f"{name}.{suffix}.npy"] = array
    return arrays, selected


def _artifact_read_bytes(store, record) -> bytes:
    """Hash exactly the bytes returned for parsing, through a pinned descriptor."""
    actual = store.verify_record(record)
    relative = actual["relative_path"]
    parts = store._parts(relative)
    with store._directory("/".join(parts[:-1])) as directory:
        fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory.fd
        )
        try:
            before = os.fstat(fd)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                actual["st_dev"],
                actual["st_ino"],
                actual["size"],
                actual["st_mtime_ns"],
            ):
                raise DiagnosticError("artifact changed before parsing")
            chunks, size = [], 0
            while True:
                chunk = os.read(
                    fd, min(_ARTIFACT_CHUNK_BYTES, actual["size"] - size + 1)
                )
                if not chunk:
                    break
                size += len(chunk)
                if size > actual["size"]:
                    raise DiagnosticError("artifact grew while parsing")
                chunks.append(chunk)
            payload = b"".join(chunks)
            if (
                not _same_identity(before, os.fstat(fd))
                or not _same_identity(
                    before,
                    os.stat(parts[-1], dir_fd=directory.fd, follow_symlinks=False),
                )
                or size != actual["size"]
                or hashlib.sha256(payload).hexdigest() != actual["sha256"]
            ):
                raise DiagnosticError(
                    "artifact parsed bytes differ from verified record"
                )
            return payload
        finally:
            os.close(fd)


def _artifact_json(store, record):
    payload = _artifact_read_bytes(store, record)
    try:
        value = json.loads(payload)
        if _get_trace().canonical_json_bytes(value) != payload:
            raise DiagnosticError("artifact JSON is not canonical")
        return value
    except (ValueError, TypeError, UnicodeError) as error:
        raise DiagnosticError("artifact JSON cannot be parsed canonically") from error


def _array_matches_record(array, expected):
    import numpy as np

    try:
        dtype = np.dtype(expected["dtype"].removeprefix("torch."))
    except (KeyError, TypeError, ValueError) as error:
        raise DiagnosticError("artifact tensor record dtype is invalid") from error
    if (
        array.dtype != dtype
        or list(array.shape) != expected["shape"]
        or hashlib.sha256(_get_trace().canonical_tensor_bytes(array)).hexdigest()
        != expected["sha256"]
    ):
        raise DiagnosticError("NPY tensor differs from committed captured tensor")


def _artifact_npy(store, record, *, expected_shape, expected_dtype):
    import numpy as np

    actual = store.verify_record(record)
    parts = _artifact_relative_parts(actual["relative_path"])
    with store._directory("/".join(parts[:-1])) as directory:
        fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory.fd
        )
        try:
            before = os.fstat(fd)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                actual["st_dev"],
                actual["st_ino"],
                actual["size"],
                actual["st_mtime_ns"],
            ):
                raise DiagnosticError("NPY changed before read")
            with os.fdopen(os.dup(fd), "rb") as stream:
                if np.lib.format.read_magic(stream) != (1, 0):
                    raise DiagnosticError("NPY version differs from fixed format")
                shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
                if (
                    tuple(shape) != tuple(expected_shape)
                    or dtype != np.dtype(expected_dtype)
                    or dtype.hasobject
                    or dtype.fields is not None
                    or dtype.kind not in "biuf"
                    or dtype.itemsize not in (1, 2, 4, 8)
                    or fortran
                    or stream.tell() + math.prod(shape) * dtype.itemsize
                    != actual["size"]
                ):
                    raise DiagnosticError(
                        "NPY header/size differs from committed shape/dtype"
                    )
                stream.seek(0)
                array = np.load(stream, allow_pickle=False)
            if not _same_identity(before, os.fstat(fd)) or not _same_identity(
                before, os.stat(parts[-1], dir_fd=directory.fd, follow_symlinks=False)
            ):
                raise DiagnosticError("NPY identity changed while reading")
            # Exact framing/hash of the parsed array, without reading a second payload.
            digest = hashlib.sha256(_npy_header(array))
            view = memoryview(array).cast("B")
            for start in range(0, len(view), _ARTIFACT_CHUNK_BYTES):
                digest.update(view[start : start + _ARTIFACT_CHUNK_BYTES])
            if digest.hexdigest() != actual["sha256"]:
                raise DiagnosticError("NPY parsed bytes differ from verified file")
            return array
        except (ValueError, EOFError) as error:
            raise DiagnosticError("invalid NPY artifact") from error
        finally:
            os.close(fd)


def _child_marker(prefix, cell, freeze, artifacts, comparison=None):
    marker = {
        "schema_version": 1,
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "evaluation_role": EVALUATION_ROLE,
        "status": "ARTIFACTS_COMPLETE",
        "kind": "cell" if cell else "reference_cold",
        "cell_id": cell,
        "input_freeze_sha256": freeze,
        "prefix": prefix,
        "artifacts": sorted(artifacts, key=lambda r: r["relative_path"]),
        "directories": ["WORST_CASES"] if cell else [],
    }
    if cell:
        marker.update(
            {
                key: comparison[key]
                for key in ("cell_status", "canary_status", "a2_replay_classification")
            }
        )
    return marker


def _verify_persisted_canary(comparison, passes, cell):
    """Recompute the official canary; full intermediate metrics remain bound evidence."""
    if comparison["cell_status"] == "INVALID":
        if (
            comparison["canary_status"] is not None
            or comparison["a2_replay_classification"] is not None
            or not comparison.get("errors")
        ):
            raise DiagnosticError(
                "invalid cell carries a numeric interpretation or no error"
            )
        return
    first, second = (p["payload"] for p in passes)
    order = _aligned_order(tuple(first["trial_ids"]), tuple(second["trial_ids"]))
    metadata = [p["boundaries"]["metadata"] for p in (first, second)]
    for name in (
        "runtime",
        "load_report",
        "load_report_sha256",
        "imported_source_records",
        "worker_pid",
        "worker_nonce",
        "model_nonce",
        "scratch_root",
        "cache_roots",
        "attestation",
    ):
        if (
            name not in metadata[0]
            or name not in metadata[1]
            or metadata[0][name] != metadata[1][name]
        ):
            raise DiagnosticError(
                "valid persisted cell has inconsistent worker identity"
            )
    if (
        not metadata[0].get("cache_nonce")
        or not metadata[1].get("cache_nonce")
        or metadata[0]["cache_nonce"] == metadata[1]["cache_nonce"]
    ):
        raise DiagnosticError("valid persisted cell reused a pass cache")
    _cell_timepoints(
        *(
            types.SimpleNamespace(
                model_snapshots=p["model_snapshots"], rng_snapshots=p["rng_snapshots"]
            )
            for p in (first, second)
        )
    )
    for p in (first, second):
        for name in _TRACE_BOUNDARIES:
            guards = p["boundaries"][name].get("guards")
            if (
                not isinstance(guards, list)
                or len(guards) != (32 + p["batch_size"] - 1) // p["batch_size"]
                or any(
                    not isinstance(g, Mapping)
                    or not isinstance(g.get("before"), Mapping)
                    or g.get("before") != g.get("after")
                    for g in guards
                )
            ):
                raise DiagnosticError(
                    "valid persisted cell has a changed or missing tensor guard"
                )

    def trial_bits(name, *, derived=False):
        records = [
            (p["boundaries"]["derived"] if derived else p["boundaries"])[name][
                "per_trial"
            ]
            for p in (first, second)
        ]
        return all(
            all(
                left.get(key) == records[1][j].get(key)
                for key in ("trial_id", "shape", "dtype", "sha256")
            )
            for left, j in zip(records[0], order)
        )

    if (
        not all(trial_bits(name) for name in ("raw_scene", "raw_cue"))
        or comparison.get("identity_exact") is not True
    ):
        raise DiagnosticError("valid persisted cell has different raw identity")
    official = {}
    for name in _OFFICIAL_OUTPUT_KEYS:
        official[name] = _bounded_boundary_comparison(
            passes[0]["outputs"][name],
            passes[1]["outputs"][name][order],
            ids=tuple(first["trial_ids"]),
            name=name,
        )
        if official[name] != comparison["comparisons"].get(name):
            raise DiagnosticError(
                "persisted canary differs from lossless official outputs"
            )
    pred_exact = official["pred_label"]["bitwise_equal"]
    nll_max = official["nll"]["max_abs"]
    canary = (
        "PASS"
        if pred_exact
        and trial_bits("correct", derived=True)
        and all(
            official[name]["max_abs"] <= 1e-6
            for name in ("nll", "p_target", "p_probe_distractor")
        )
        else "DIFF"
    )
    if (
        comparison.get("errors") != []
        or comparison.get("pred_exact") != pred_exact
        or comparison.get("nll_max_abs") != nll_max
        or comparison["canary_status"] != canary
    ):
        raise DiagnosticError(
            "persisted canary classification contradicts exact outputs"
        )
    derived_class = classify_a2(comparison) if cell == "A2" else None
    if comparison["a2_replay_classification"] != derived_class:
        raise DiagnosticError("persisted A2 classification contradicts exact canary")
    expected_boundaries = set(_TRACE_BOUNDARIES) | set(CELL_DERIVED_BOUNDARIES)
    if set(comparison["comparisons"]) != expected_boundaries:
        raise DiagnosticError("valid comparison has incomplete boundaries")
    expected_status = (
        "PASS"
        if all(r["bitwise_equal"] for r in comparison["comparisons"].values())
        else "DIFF"
    )
    expected_targeted = (
        trial_bits("scene_features")
        and trial_bits("cue_features")
        and not trial_bits("native_logits")
    )
    if (
        comparison["cell_status"] != expected_status
        or comparison.get("first_divergence")
        != first_divergence(comparison["comparisons"])
        or comparison.get("targeted_trace_required") is not expected_targeted
    ):
        raise DiagnosticError(
            "persisted boundary interpretation contradicts committed evidence"
        )


def _verify_child_payloads(store, prefix, cell, marker, *, freeze, marker_record=None):
    _require_sha256(freeze)
    baseline = _child_marker(
        prefix,
        cell,
        freeze,
        [],
        {"cell_status": None, "canary_status": None, "a2_replay_classification": None},
    )
    if not isinstance(marker, Mapping) or set(marker) != set(baseline):
        raise DiagnosticError("complete marker schema differs")
    for name in baseline.keys() - {
        "artifacts",
        "cell_status",
        "canary_status",
        "a2_replay_classification",
    }:
        if (
            type(marker[name]) is not type(baseline[name])
            or marker[name] != baseline[name]
        ):
            raise DiagnosticError(f"complete marker {name} differs")
    records = marker["artifacts"]
    if not isinstance(records, list) or any(
        not isinstance(r, Mapping) for r in records
    ):
        raise DiagnosticError("complete marker inventory schema differs")
    by_name = {r["relative_path"]: r for r in records}
    marker_name = "CELL_COMPLETE.json" if cell else "REFERENCE_COMPLETE.json"
    required = _CELL_ARTIFACT_NAMES if cell else _REFERENCE_ARTIFACT_NAMES
    regular = {prefix + "/" + name for name in required if name != marker_name}
    extras = set(by_name) - regular
    if (
        len(by_name) != len(records)
        or not regular.issubset(by_name)
        or (not cell and extras)
        or any(not name.startswith(prefix + "/WORST_CASES/") for name in extras)
    ):
        raise DiagnosticError("complete marker lacks the exact child payload inventory")
    for name in extras:
        _artifact_relative_parts(name)
    inventory = records + ([marker_record] if marker_record else [])
    store.verify_inventory(prefix, inventory, directories=marker["directories"])
    input_name = "CELL_INPUTS.json" if cell else "REFERENCE_INPUTS.json"
    inputs = _artifact_json(store, by_name[prefix + "/" + input_name])
    passes = _validate_child_inputs(inputs, cell=cell, freeze=freeze)
    for name, expected in _child_views(inputs).items():
        if _artifact_read_bytes(store, by_name[prefix + "/" + name]) != expected:
            raise DiagnosticError(f"{name} differs from lossless pass evidence")
    comparison = None
    if cell:
        comparison = _artifact_json(store, by_name[prefix + "/COMPARISON.json"])
        if (
            not isinstance(comparison, Mapping)
            or comparison.get("cell_id") != cell
            or comparison.get("cell_status") not in ("PASS", "DIFF", "INVALID")
            or comparison.get("canary_threshold") != 1e-6
            or not isinstance(comparison.get("worst_cases"), Mapping)
        ):
            raise DiagnosticError("cell comparison schema differs")
        for name in ("cell_status", "canary_status", "a2_replay_classification"):
            if comparison[name] != marker[name]:
                raise DiagnosticError("complete marker/comparison status differs")
        if comparison["cell_status"] == "INVALID" and (
            comparison["canary_status"] is not None
            or comparison["a2_replay_classification"] is not None
        ):
            raise DiagnosticError(
                "invalid cell carries a numerical success classification"
            )
        _verify_persisted_canary(comparison, passes, cell)
        payloads = [p["payload"] for p in passes]
        for i, p in enumerate(payloads, 1):
            tensor = p["boundaries"]["native_logits"]["tensor"]
            array = _artifact_npy(
                store,
                by_name[f"{prefix}/LOGITS_PASS{i}.npy"],
                expected_shape=(32, 800),
                expected_dtype=tensor["dtype"].removeprefix("torch."),
            )
            _array_matches_record(array, tensor)
        selections = comparison["worst_cases"]
        names = set(selections)
        if not {"scene_features", "cue_features"}.issubset(names) or not names.issubset(
            _WORST_BOUNDARIES
        ):
            raise DiagnosticError("mandatory cochleagram worst-case trios are absent")
        if comparison.get("targeted_trace_required") and "native_logits" not in names:
            raise DiagnosticError("targeted trace requires logits worst-case trio")
        expected_extras = {
            f"{prefix}/WORST_CASES/{name}.{suffix}.npy"
            for name in names
            for suffix in _WORST_SUFFIXES
        }
        if extras != expected_extras:
            raise DiagnosticError(
                "worst-case files differ from selected complete trios"
            )
        import numpy as np

        for name, selection in selections.items():
            if (
                not isinstance(selection, Mapping)
                or set(selection)
                != {
                    "trial_id",
                    "ordinal",
                    "pass1_index",
                    "pass2_index",
                    "selection_rule",
                }
                or selection["selection_rule"]
                != "maximum_abs_difference__nonfinite_first__frozen_ordinal_tie"
                or type(selection["ordinal"]) is not int
                or not 0 <= selection["ordinal"] < 32
                or inputs["trials"][selection["ordinal"]]["trial_id"]
                != selection["trial_id"]
            ):
                raise DiagnosticError("worst-case frozen trial selection differs")
            arrays = []
            for i, p in enumerate(payloads, 1):
                index = selection[f"pass{i}_index"]
                if (
                    type(index) is not int
                    or not 0 <= index < 32
                    or p["trial_ids"][index] != selection["trial_id"]
                ):
                    raise DiagnosticError(
                        "worst-case pass index is not aligned to frozen trial"
                    )
                expected = p["boundaries"][name]["per_trial"][index]
                array = _artifact_npy(
                    store,
                    by_name[f"{prefix}/WORST_CASES/{name}.pass{i}.npy"],
                    expected_shape=expected["shape"],
                    expected_dtype=expected["dtype"].removeprefix("torch."),
                )
                _array_matches_record(array, expected)
                arrays.append(array)
            delta = _artifact_npy(
                store,
                by_name[f"{prefix}/WORST_CASES/{name}.difference.npy"],
                expected_shape=arrays[0].shape,
                expected_dtype="float64",
            )
            with np.errstate(invalid="ignore", over="ignore"):
                expected_delta = arrays[1].astype(np.float64) - arrays[0].astype(
                    np.float64
                )
            if delta.tobytes() != expected_delta.tobytes():
                raise DiagnosticError("worst-case difference is not pass2 minus pass1")
            boundary_comparison = comparison["comparisons"].get(name)
            if boundary_comparison and boundary_comparison.get("finite_valid"):
                if not np.isfinite(delta).all() or float(
                    np.max(np.abs(delta))
                ) != boundary_comparison.get("max_abs"):
                    raise DiagnosticError(
                        "selected worst trial does not reach reported boundary maximum"
                    )
        if store.worst_case_bytes() > 1_073_741_824:
            raise DiagnosticError("verified worst-case total exceeds 1 GiB")
    store.verify_inventory(prefix, inventory, directories=marker["directories"])
    if marker_record:
        store.verify_record(marker_record)
    return {
        "status": "ARTIFACTS_VERIFIED",
        "inputs": inputs,
        "comparison": comparison,
        "marker_record": marker_record,
        "inventory": records,
    }


def _write_child_artifacts(path, result, *, reference):
    root, prefix, cell = _child_location(path, reference=reference)
    inputs = _child_inputs(result, cell=cell)
    comparison, worst_arrays = None, {}
    if cell:
        comparison = compare_passes(*result["passes"], spec=CELL_SPECS[cell])
        worst_arrays, selections = _select_child_worst(result, comparison)
        comparison = {**comparison, "worst_cases": selections}
    canonical = _get_trace().canonical_json_bytes
    input_name = "CELL_INPUTS.json" if cell else "REFERENCE_INPUTS.json"
    with _AttemptArtifactStore(root) as store:
        # Re-entry and incomplete attempts are evidence, never an overwrite target.
        if os.path.lexists(root / prefix):
            raise FileExistsError("refusing an already-created child evidence root")
        with store._directory(prefix, create=True):
            artifacts = [
                store.publish_bytes(prefix + "/" + input_name, canonical(inputs))
            ]
            for name, value in _child_views(inputs).items():
                artifacts.append(store.publish_bytes(prefix + "/" + name, value))
            if cell:
                for i, result_pass in enumerate(result["passes"], 1):
                    array = _cpu_artifact_array(
                        result_pass.boundary_records["native_logits"]["tensor"]
                    )
                    artifacts.append(
                        store.publish_npy(f"{prefix}/LOGITS_PASS{i}.npy", array)
                    )
                artifacts.extend(store.publish_worst_cases(cell, worst_arrays))
                artifacts.append(
                    store.publish_bytes(
                        prefix + "/COMPARISON.json", canonical(comparison)
                    )
                )
            marker = _child_marker(
                prefix, cell, inputs["input_freeze_sha256"], artifacts, comparison
            )
            _verify_child_payloads(
                store, prefix, cell, marker, freeze=inputs["input_freeze_sha256"]
            )
            for record in artifacts:
                if store.record(record["relative_path"]) != record:
                    raise DiagnosticError(
                        "own published payload replaced before complete marker"
                    )
            name = "CELL_COMPLETE.json" if cell else "REFERENCE_COMPLETE.json"
            marker_record = store.publish_bytes(prefix + "/" + name, canonical(marker))
            verified = _verify_child_payloads(
                store,
                prefix,
                cell,
                marker,
                freeze=inputs["input_freeze_sha256"],
                marker_record=marker_record,
            )
            for record in (*artifacts, marker_record):
                if store.record(record["relative_path"]) != record:
                    raise DiagnosticError(
                        "own published evidence replaced during final verification"
                    )
            return verified


def write_cell_artifacts(
    cell_root: pathlib.Path, result: Mapping[str, Any]
) -> dict[str, Any]:
    return _write_child_artifacts(cell_root, result, reference=False)


def write_reference_artifacts(
    reference_root: pathlib.Path, result: Mapping[str, Any]
) -> dict[str, Any]:
    return _write_child_artifacts(reference_root, result, reference=True)


def _verify_child_artifacts(
    path, *, reference, expected_marker, expected_input_freeze_sha256
):
    root, prefix, cell = _child_location(path, reference=reference)
    name = "CELL_COMPLETE.json" if cell else "REFERENCE_COMPLETE.json"
    if (
        not isinstance(expected_marker, Mapping)
        or expected_marker.get("relative_path") != prefix + "/" + name
    ):
        raise DiagnosticError("out-of-band marker identity differs from child path")
    with _AttemptArtifactStore(root) as store:
        with store._directory(prefix):
            current_marker = store.verify_record(expected_marker)
            marker = _artifact_json(store, current_marker)
            verified = _verify_child_payloads(
                store,
                prefix,
                cell,
                marker,
                freeze=expected_input_freeze_sha256,
                marker_record=current_marker,
            )
            if store.record(current_marker["relative_path"]) != current_marker:
                raise DiagnosticError(
                    "marker replaced within child verification invocation"
                )
            return verified


def verify_cell_artifacts(
    cell_root: pathlib.Path,
    *,
    expected_marker: Mapping[str, Any],
    expected_input_freeze_sha256: str,
) -> dict[str, Any]:
    return _verify_child_artifacts(
        cell_root,
        reference=False,
        expected_marker=expected_marker,
        expected_input_freeze_sha256=expected_input_freeze_sha256,
    )


def verify_reference_artifacts(
    reference_root: pathlib.Path,
    *,
    expected_marker: Mapping[str, Any],
    expected_input_freeze_sha256: str,
) -> dict[str, Any]:
    return _verify_child_artifacts(
        reference_root,
        reference=True,
        expected_marker=expected_marker,
        expected_input_freeze_sha256=expected_input_freeze_sha256,
    )


_WORKER_PROCESS_CLAIMED = False
_WORKER_WRITE_PATHS = types.MappingProxyType(
    {
        "HOME": "home",
        "XDG_CACHE_HOME": "xdg",
        "TORCH_HOME": "torch-home",
        "TMPDIR": "tmp",
        "TMP": "tmp",
        "TEMP": "tmp",
        "MPLCONFIGDIR": "mpl",
        "NUMBA_CACHE_DIR": "numba",
        "TORCHINDUCTOR_CACHE_DIR": "torchinductor",
        "TRITON_CACHE_DIR": "triton",
        "CUDA_CACHE_PATH": "cuda",
    }
)


def _worker_job_id(args) -> str:
    job = getattr(args, "job_id", None)
    if (
        not isinstance(job, str)
        or not job.isascii()
        or not job.isdecimal()
        or job.startswith("0")
        or len(job) > 20
    ):
        raise DiagnosticError("worker job ID must be canonical positive decimal")
    _require_sha256(getattr(args, "expected_input_freeze_sha256", None))
    if os.environ.get("SLURM_JOB_ID") != job:
        raise DiagnosticError("worker job ID differs from Slurm environment")
    return job


def _require_cold_worker_interpreter() -> None:
    if (
        not sys.flags.isolated
        or not sys.flags.dont_write_bytecode
        or pathlib.Path(sys.executable).resolve() != PRODUCTION_PYTHON.resolve()
        or PACKAGE_ROOT != DIAGNOSTIC_ROOT / "tools"
        or pathlib.Path(__file__)
        != DIAGNOSTIC_ROOT / "tools/diagnose_batch_invariance.py"
        or _TRACE is not None
        or any(
            name.partition(".")[0] in {"torch", "torchaudio", "numpy", "pandas"}
            or name.startswith(("_numeric_trace", "_verified_v4"))
            for name in sys.modules
        )
    ):
        raise DiagnosticError("worker requires a fresh isolated production interpreter")
    with _PinnedArtifactDirectory(PACKAGE_ROOT) as anchor:
        anchor.check()


def _claim_worker_process() -> None:
    global _WORKER_PROCESS_CLAIMED
    if _WORKER_PROCESS_CLAIMED:
        raise DiagnosticError("a diagnostic process may execute only one cold worker")
    # A failed launch is not permission to reuse partially initialized libraries.
    _WORKER_PROCESS_CLAIMED = True
    _require_cold_worker_interpreter()


def _require_local_scratch_mount(root: pathlib.Path) -> dict[str, Any]:
    """Additional child check; the runner still owns approved-parent selection."""
    if not sys.platform.startswith("linux"):
        raise DiagnosticError("production scratch requires Linux mount evidence")
    info = os.stat(root, follow_symlinks=False)
    for protected in (V4_ROOT, DIAGNOSTIC_ROOT, pathlib.Path("/home/s2510040")):
        if (
            root == protected
            or protected in root.parents
            or root in protected.parents
            or info.st_dev == os.stat(protected, follow_symlinks=False).st_dev
        ):
            raise DiagnosticError("scratch overlaps a protected/account/NFS root")
    candidates = []
    with open("/proc/self/mountinfo", encoding="utf-8") as source:
        for line in source:
            fields = line.split()
            try:
                separator = fields.index("-")
                mount = pathlib.Path(
                    fields[4]
                    .replace(r"\040", " ")
                    .replace(r"\011", "\t")
                    .replace(r"\012", "\n")
                    .replace(r"\134", "\\")
                )
                if mount == root or mount in root.parents:
                    candidates.append(
                        (len(mount.parts), fields[2], str(mount), fields[separator + 1])
                    )
            except (ValueError, IndexError) as error:
                raise DiagnosticError("malformed Linux mount record") from error
    if not candidates:
        raise DiagnosticError("scratch mount is not identified")
    _, device, mount, filesystem = max(candidates)
    if (
        filesystem not in {"tmpfs", "ext4", "xfs", "btrfs"}
        or device != f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}"
    ):
        raise DiagnosticError("scratch is not on an approved local filesystem")
    return {"filesystem": filesystem, "mount": mount, "device": device}


class _WorkerScratch:
    def __init__(self, root, anchors, record):
        self.root, self.anchors, self.record = root, anchors, record
        self.cache_roots = {
            name: str(root / name) for name in ("torchinductor", "triton", "cuda")
        }
        self.spills: list[Mapping[str, Any]] = []
        self._maps: list[Any] = []

    def check(self):
        for anchor in self.anchors:
            anchor.check()
            info = os.fstat(anchor.fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise DiagnosticError("worker scratch ownership/mode changed")
        for key, relative in _WORKER_WRITE_PATHS.items():
            if os.environ.get(key) != str(self.root / relative):
                raise DiagnosticError("worker writable environment changed")

    def spill(self, result: PassResult) -> None:
        """Spill completed-pass CPU captures, without re-sealing their evidence."""
        import numpy as np
        import torch

        self.check()
        original = encode_pass_evidence(result)
        if result.pass_id not in {"pass1", "pass2"}:
            raise DiagnosticError("invalid scratch pass ID")
        with _PinnedArtifactDirectory(self.root / "intermediates") as directory:
            for name in ("scene_features", "cue_features"):
                record = result.boundary_records[name]
                array = _cpu_artifact_array(record["tensor"])
                header = _npy_header(array)
                filename = f"{result.pass_id}.{name}.npy"
                fd = os.open(
                    filename,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory.fd,
                )
                try:
                    with os.fdopen(os.dup(fd), "wb") as stream:
                        stream.write(header)
                        for chunk in _array_byte_chunks(array):
                            stream.write(chunk)
                        stream.flush()
                        os.fsync(stream.fileno())
                    before = os.fstat(fd)
                    expected_size = len(header) + array.nbytes
                    if before.st_size != expected_size or before.st_nlink != 1:
                        raise DiagnosticError("scratch tensor size/link changed")
                    mapping = mmap.mmap(fd, expected_size, access=mmap.ACCESS_COPY)
                    self._maps.append(mapping)
                    mapped_array = np.ndarray(
                        array.shape,
                        dtype=array.dtype,
                        buffer=mapping,
                        offset=len(header),
                    )
                    mapped_tensor = torch.from_numpy(mapped_array)
                    if (
                        _get_trace().tensor_record(mapped_tensor, boundary=name)
                        != record["aggregate"]
                    ):
                        raise DiagnosticError(
                            "scratch tensor bytes differ from captured evidence"
                        )
                    directory.check()
                    if not _same_identity(
                        before,
                        os.stat(filename, dir_fd=directory.fd, follow_symlinks=False),
                    ):
                        raise DiagnosticError("scratch tensor replaced during mapping")
                    record["tensor"] = mapped_tensor
                    actual = _get_trace().stable_file_record(
                        self.root / "intermediates" / filename, allowed_root=self.root
                    )
                    if (
                        actual["st_dev"],
                        actual["st_ino"],
                        actual["st_mtime_ns"],
                        actual["mode"],
                        actual["size"],
                    ) != (
                        before.st_dev,
                        before.st_ino,
                        before.st_mtime_ns,
                        stat.S_IMODE(before.st_mode),
                        before.st_size,
                    ):
                        raise DiagnosticError(
                            "scratch tensor replaced before baseline capture"
                        )
                    self.spills.append(actual)
                finally:
                    os.close(fd)
            os.fsync(directory.fd)
        if encode_pass_evidence(result) != original:
            raise DiagnosticError("scratch spill altered original pass commitment")
        self.check()

    def verify_spills(self):
        self.check()
        for record in self.spills:
            _get_trace().verify_file_record(record, allowed_root=self.root)


def _array_byte_chunks(array):
    """Native contiguous CPU bytes in bounded chunks, without a full bytes copy."""
    view = memoryview(array).cast("B")
    for offset in range(0, len(view), 1024 * 1024):
        yield view[offset : offset + 1024 * 1024]


@contextlib.contextmanager
def _worker_scratch(args, role):
    job = _worker_job_id(args)
    if role not in {"reference_cold", *CELL_SPECS}:
        raise DiagnosticError("unknown worker scratch role")
    raw = os.environ.get("DIAG_SCRATCH_ROOT", "")
    base = pathlib.Path(raw)
    if (
        not base.is_absolute()
        or str(base) != raw
        or ".." in base.parts
        or base.name != f"audattn_v4_numdiag_{job}"
    ):
        raise DiagnosticError("worker scratch parent is not the fixed job directory")
    root = base / role
    for key, relative in _WORKER_WRITE_PATHS.items():
        if os.environ.get(key) != str(root / relative):
            raise DiagnosticError(f"worker writable environment is not isolated: {key}")
    for key, expected in (
        ("PYTHONDONTWRITEBYTECODE", "1"),
        ("PYTHONNOUSERSITE", "1"),
        ("PYTHONHASHSEED", "0"),
    ):
        if os.environ.get(key) != expected:
            raise DiagnosticError(f"worker process environment differs: {key}")
    with contextlib.ExitStack() as stack:
        parent = stack.enter_context(_PinnedArtifactDirectory(base))
        info = os.fstat(parent.fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise DiagnosticError("scratch parent must be user-owned mode 0700")
        mount = _require_local_scratch_mount(base)
        parent.check()
        os.mkdir(role, 0o700, dir_fd=parent.fd)  # existing/partial workers never reused
        child = stack.enter_context(_PinnedArtifactDirectory(root))
        parent.check()
        anchors = [parent, child]
        for name in sorted(
            set(_WORKER_WRITE_PATHS.values()) | {"intermediates", "pycache"}
        ):
            os.mkdir(name, 0o700, dir_fd=child.fd)
            anchors.append(stack.enter_context(_PinnedArtifactDirectory(root / name)))
        if any(os.listdir(a.fd) for a in anchors[2:]):
            raise DiagnosticError("new worker cache/scratch directories are not empty")
        record = {
            "schema_version": 1,
            "worker_role": role,
            "scratch_root": str(root),
            "mount": mount,
            "caches_initially_empty": True,
            "write_paths": {
                key: str(root / value) for key, value in _WORKER_WRITE_PATHS.items()
            },
            "directories": [
                {
                    "path": str(a.path),
                    "device": os.fstat(a.fd).st_dev,
                    "inode": os.fstat(a.fd).st_ino,
                    "mode": stat.S_IMODE(os.fstat(a.fd).st_mode),
                    "uid": os.fstat(a.fd).st_uid,
                }
                for a in anchors
            ],
            "intermediate_policy": "post_pass_cpu_captures__native_npy__copy_on_write_mapping",
        }
        scratch = _WorkerScratch(root, anchors, record)
        scratch.check()
        # tempfile's cached default must not leak to the account home or /tmp.
        previous_temp, previous_prefix = tempfile.tempdir, sys.pycache_prefix
        tempfile.tempdir, sys.pycache_prefix = str(root / "tmp"), str(root / "pycache")
        try:
            yield scratch
        finally:
            tempfile.tempdir, sys.pycache_prefix = previous_temp, previous_prefix
            # Keep files as diagnostic scratch, including on failure. The owning
            # coordinator/runner controls retention. Do not invalidate tensor
            # buffers by manually closing mappings still held by a PassResult.
            scratch.check()


def _portable_worker_audit(audit):
    value = json.loads(json.dumps(audit))
    for collection in ("production_files", "clips", "snapshot_files"):
        for record in value.get(collection, []):
            for key in ("st_dev", "st_ino", "st_mtime_ns"):
                record.pop(key, None)
    return value


def _worker_historical_hashes(context):
    record = context["manifest"]["historical_evidence"]["job584990_results"]
    path = pathlib.Path(record["path"])
    payload, actual = _get_trace().read_stable_bytes(path, allowed_root=path.parent)
    if actual["size"] != record["size"] or actual["sha256"] != record["sha256"]:
        raise DiagnosticError("Job584990 results identity changed")
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8"))))
    hashes = {}
    for row in rows:
        trial = int(row["trial_id"])
        digest = row["scene_sha256"]
        _require_sha256(digest)
        if trial in hashes:
            raise DiagnosticError("duplicate historical trial identity")
        hashes[trial] = digest
    if set(hashes) != set(range(10000)):
        raise DiagnosticError("historical trial IDs are not exactly 0..9999")
    vector = hashlib.sha256(
        ("\n".join(hashes[i] for i in range(10000)) + "\n").encode("ascii")
    ).hexdigest()
    if vector != context["historical_scene_binding"]["scene_hash_vector_sha256"]:
        raise DiagnosticError("historical scene vector differs from frozen audit")
    return hashes


def _load_worker_inputs(expected_sha):
    trace = _get_trace()
    freeze, record = _read_canonical_json(
        trace, DIAGNOSTIC_ROOT / "input_freeze.json", DIAGNOSTIC_ROOT, expected_sha
    )
    _validate_freeze_value(
        freeze,
        production_contract(),
        status="INPUTS_FROZEN",
        diagnostic_root=DIAGNOSTIC_ROOT,
    )
    if (
        trace.canonical_json_bytes(freeze)
        != trace.read_stable_bytes(
            DIAGNOSTIC_ROOT / "input_freeze.json", allowed_root=DIAGNOSTIC_ROOT
        )[0]
    ):
        raise DiagnosticError("worker input freeze is not canonical")
    context = read_frozen_context()
    capability = context["_frozen_context_capability"]
    if capability.trust_domain != "production":
        raise DiagnosticError("production worker may not use hermetic provenance")
    current = audit_inputs(context=context, diagnostic_root=DIAGNOSTIC_ROOT)
    if _portable_worker_audit(freeze) != _portable_worker_audit(
        _freeze_document(current)
    ):
        raise DiagnosticError("worker frozen inputs differ from reconstructed audit")
    # Frozen ordinals, not a second sampling operation, drive both passes.
    trials = tuple(TrialSpec(**item) for item in freeze["trials"])
    context.update(
        clips_dir=pathlib.Path(context["roots"]["clips_dir"]),
        historical_scene_hashes=_worker_historical_hashes(context),
    )
    return {
        "context": context,
        "trials": trials,
        "freeze": freeze,
        "freeze_record": record,
        "audit": current,
    }


def _revalidate_worker_inputs(bundle):
    trace = _get_trace()
    trace.verify_file_record(bundle["freeze_record"], allowed_root=DIAGNOSTIC_ROOT)
    context = bundle["context"]
    _validate_frozen_capability_contents(context["_frozen_context_capability"])
    current_pinned = _verify_v4_pinned_records(
        trace, context["manifest"], production_contract()
    )
    if current_pinned != bundle["audit"]["v4"]["verified_pinned_files"]:
        raise DiagnosticError("worker bound pinned inputs changed")
    current = audit_inputs(context=context, diagnostic_root=DIAGNOSTIC_ROOT)
    if current != bundle["audit"]:
        raise DiagnosticError("worker bound inputs changed within execution")


def _worker_software_record(device):
    import platform
    import torch

    cuda = getattr(device, "type", None) == "cuda"
    return {
        "python": platform.python_version(),
        "torch": str(torch.__version__),
        "cuda_runtime": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "device": str(device),
        "gpu_name": torch.cuda.get_device_name(device) if cuda else None,
        "hostname": platform.node(),
        "worker_pid": os.getpid(),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
    }


def _execute_worker_passes(
    context, trials, spec, args, scratch, *, verify_inputs, allow_cpu=False
):
    prepared = prepare_formal40_worker(context, allow_cpu=allow_cpu)
    environment = {
        **scratch.record,
        "software": _worker_software_record(prepared.get("device")),
        "runtime_configuration_policy": "frozen_configurator_once_before_model_load__no_between_pass_reset",
    }
    run = {
        **context,
        **prepared,
        "scratch_root": str(scratch.root),
        "cache_roots": scratch.cache_roots,
        "worker_environment": environment,
    }
    if spec is not None:
        run["cell_id"] = spec.cell_id
    sizes = spec.pass_batch_sizes if spec is not None else (16, 1)
    passes = []
    for index, size in enumerate(sizes, 1):
        scratch.check()
        if spec is None:
            result = run_reference_pass(run, trials, f"pass{index}", size)
        else:
            result = run_trace_pass(
                run, trials, f"pass{index}", size, spec.autocast_enabled, scratch.root
            )
            scratch.spill(result)
        passes.append(result)
    scratch.verify_spills()
    verify_inputs()  # all bound inputs must still match before marker creation
    data = {
        "trials": trials,
        "passes": tuple(passes),
        "spec": spec,
        "input_freeze_sha256": args.expected_input_freeze_sha256,
    }
    attempt = DIAGNOSTIC_ROOT / "attempts" / f"slurm-{args.job_id}"
    if spec is None:
        receipt = write_reference_artifacts(attempt / "reference_cold", data)
    else:
        receipt = write_cell_artifacts(attempt / "cells" / spec.cell_id, data)
    scratch.verify_spills()
    verify_inputs()  # errors here invalidate the returned receipt, never retry
    return receipt


def _run_child_worker(spec, args):
    job = _worker_job_id(args)
    _claim_worker_process()
    role = spec.cell_id if spec is not None else "reference_cold"
    attempt = DIAGNOSTIC_ROOT / "attempts" / f"slurm-{job}"
    with (
        _PinnedArtifactDirectory(attempt) as attempt_anchor,
        _worker_scratch(args, role) as scratch,
    ):
        info = os.fstat(attempt_anchor.fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise DiagnosticError("coordinator attempt must be user-owned mode 0700")
        child = attempt / (
            "reference_cold" if spec is None else f"cells/{spec.cell_id}"
        )
        if os.path.lexists(child):
            raise DiagnosticError("child evidence already exists; never retry a worker")
        # No numerical/evaluator import may precede scratch/environment setup.
        with contextlib.redirect_stdout(sys.stderr):
            bundle = _load_worker_inputs(args.expected_input_freeze_sha256)
            context = bundle["context"]
            source_records = {
                item["relative_path"]: item
                for item in bundle["audit"]["snapshot_files"]
            }
            with frozen_scene_context(
                context["snapshot_files"], source_records
            ) as scene_api:
                context["scene_api"] = scene_api
                result = _execute_worker_passes(
                    context,
                    bundle["trials"],
                    spec,
                    args,
                    scratch,
                    verify_inputs=lambda: _revalidate_worker_inputs(bundle),
                    allow_cpu=False,
                )
            attempt_anchor.check()
            return result


def run_reference_cold(args):
    return _run_child_worker(None, args)


def run_cell(spec: CellSpec, args):
    if (
        type(spec) is not CellSpec
        or spec.cell_id not in CELL_SPECS
        or spec != CELL_SPECS[spec.cell_id]
    ):
        raise DiagnosticError("worker cell differs from the fixed matrix")
    return _run_child_worker(spec, args)


_CHILD_STDOUT_LIMIT = 16 * 1024
_CHILD_SLURM_ENV_KEYS = (
    "SLURM_JOB_ID",
    "SLURM_JOB_NODELIST",
    "SLURM_NNODES",
    "SLURM_NTASKS",
    "SLURM_CPUS_PER_TASK",
    "SLURM_JOB_GPUS",
    "SLURM_STEP_GPUS",
    "SLURM_TMPDIR",
)


def _child_identity(mode, job_id, cell):
    if (
        type(job_id) is not str
        or not job_id.isascii()
        or not job_id.isdecimal()
        or job_id.startswith("0")
        or len(job_id) > 20
    ):
        raise DiagnosticError("child job ID must be canonical positive decimal")
    if mode == "_child-reference" and cell is None:
        return "reference_cold"
    if mode == "_child-cell" and type(cell) is str and cell in CELL_SPECS:
        return cell
    raise DiagnosticError("child mode/cell differs from fixed protocol")


def _child_scratch_path(scratch_root, job_id):
    try:
        raw = os.fspath(scratch_root)
        if type(raw) is not str or "\0" in raw:
            raise DiagnosticError("child scratch path contains invalid bytes")
        root = pathlib.Path(raw)
        if (
            not root.is_absolute()
            or str(root) != raw
            or ".." in root.parts
            or root.name != f"audattn_v4_numdiag_{job_id}"
        ):
            raise DiagnosticError(
                "child scratch path is not the canonical job directory"
            )
        for protected in (V4_ROOT, DIAGNOSTIC_ROOT, pathlib.Path("/home/s2510040")):
            if root == protected or protected in root.parents:
                raise DiagnosticError("child scratch path is inside a protected root")
        return root
    except (TypeError, ValueError) as error:
        raise DiagnosticError("child scratch path is invalid") from error


def child_command(mode, job_id, input_freeze_sha256, cell, scratch_root):
    """Fixed argv only; no import, filesystem mutation, shell or output override."""
    _child_identity(mode, job_id, cell)
    _require_sha256(input_freeze_sha256)
    _child_scratch_path(scratch_root, job_id)
    command = [
        str(PRODUCTION_PYTHON),
        "-I",
        "-B",
        str(DIAGNOSTIC_ROOT / "tools/diagnose_batch_invariance.py"),
        mode,
        "--job-id",
        job_id,
        "--expected-input-freeze-sha256",
        input_freeze_sha256,
    ]
    if cell is not None:
        command.extend(("--cell", cell))
    return command


def child_environment(mode, job_id, cell, scratch_root, parent_environment):
    """Derive empty per-worker write locations; worker creates them create-once."""
    role = _child_identity(mode, job_id, cell)
    root = _child_scratch_path(scratch_root, job_id)
    if (
        not isinstance(parent_environment, Mapping)
        or parent_environment.get("SLURM_JOB_ID") != job_id
    ):
        raise DiagnosticError("child Slurm job does not match its parent")
    visible = parent_environment.get("CUDA_VISIBLE_DEVICES")
    if type(visible) is not str or not visible.strip() or "\0" in visible:
        raise DiagnosticError("child CUDA_VISIBLE_DEVICES is absent or invalid")
    env = {}
    for key in _CHILD_SLURM_ENV_KEYS:
        if key in parent_environment:
            value = parent_environment[key]
            if type(value) is not str or not value or "\0" in value:
                raise DiagnosticError(f"invalid child scheduler environment: {key}")
            env[key] = value
    env.update(
        {
            "CUDA_VISIBLE_DEVICES": visible,
            "DIAG_SCRATCH_ROOT": str(root),
            "PATH": f"{PRODUCTION_PYTHON.parent}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            # Fixed exports of the SHA-bound original v4 runner, not parent input.
            # Passed to exec before any coordinator/child numerical imports.
            "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
            "OMP_NUM_THREADS": "8",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    env.update(
        {
            key: str(root / role / relative)
            for key, relative in _WORKER_WRITE_PATHS.items()
        }
    )
    return env


def _check_child_marker_record(record, *, job_id, cell):
    required = {
        "path",
        "relative_path",
        "type",
        "mode",
        "size",
        "st_dev",
        "st_ino",
        "st_mtime_ns",
        "sha256",
    }
    name = (
        "reference_cold/REFERENCE_COMPLETE.json"
        if cell is None
        else f"cells/{cell}/CELL_COMPLETE.json"
    )
    path = DIAGNOSTIC_ROOT / "attempts" / f"slurm-{job_id}" / name
    if (
        not isinstance(record, Mapping)
        or set(record) != required
        or record["relative_path"] != name
        or record["path"] != str(path)
        or record["type"] != "file"
        or type(record["mode"]) is not int
        or record["mode"] != 0o600
    ):
        raise DiagnosticError("child completion marker path/type/mode differs")
    for key in ("size", "st_dev", "st_ino", "st_mtime_ns"):
        if type(record[key]) is not int or record[key] < (
            1 if key in ("size", "st_ino") else 0
        ):
            raise DiagnosticError("child completion marker scalar schema differs")
    _require_sha256(record["sha256"])


def _child_completion_document(result, args, mode, cell):
    """Emit only after the worker returns; no claim of parent artifact acceptance."""
    job = _worker_job_id(args)
    _child_identity(mode, job, cell)
    if not isinstance(result, Mapping) or result.get("status") != "ARTIFACTS_VERIFIED":
        raise DiagnosticError("child did not return a verified artifact result")
    marker = result.get("marker_record")
    _check_child_marker_record(marker, job_id=job, cell=cell)
    return {
        "schema_version": 1,
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "evaluation_role": EVALUATION_ROLE,
        "status": "CHILD_ARTIFACTS_READY",
        "job_id": job,
        "input_freeze_sha256": args.expected_input_freeze_sha256,
        "worker_pid": os.getpid(),
        "mode": mode,
        "cell": cell,
        "marker_record": dict(marker),
    }


def _decode_child_completion(payload, *, pid, mode, job_id, freeze_sha, cell):
    """No log-prefix stripping: this channel must contain one canonical object."""
    if type(payload) is not bytes or not 0 < len(payload) <= _CHILD_STDOUT_LIMIT:
        raise DiagnosticError("child completion stdout is empty or exceeds limit")
    try:
        document = json.loads(payload)
        canonical = (
            json.dumps(
                document,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("ascii")
    except (ValueError, TypeError, UnicodeError) as error:
        raise DiagnosticError("child completion is not a single JSON object") from error
    expected = {
        "schema_version": 1,
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "evaluation_role": EVALUATION_ROLE,
        "status": "CHILD_ARTIFACTS_READY",
        "job_id": job_id,
        "input_freeze_sha256": freeze_sha,
        "worker_pid": pid,
        "mode": mode,
        "cell": cell,
    }
    if not isinstance(document, dict) or set(document) != set(expected) | {
        "marker_record"
    }:
        raise DiagnosticError("child completion object schema differs")
    for key, value in expected.items():
        if type(document[key]) is not type(value) or document[key] != value:
            raise DiagnosticError(f"child completion process binding differs: {key}")
    if payload != canonical:
        raise DiagnosticError("child completion is not canonical JSON")
    _check_child_marker_record(document["marker_record"], job_id=job_id, cell=cell)
    return document


def _collect_child_stdout(process, *, timeout_seconds):
    """Bound both bytes and elapsed time, including EOF without process exit."""
    if process.stdout is None:
        raise DiagnosticError("child stdout pipe is absent")
    deadline = time.monotonic() + timeout_seconds
    result = bytearray()
    descriptor = process.stdout.fileno()
    os.set_blocking(descriptor, False)
    with selectors.DefaultSelector() as selector:
        selector.register(descriptor, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DiagnosticError("child timeout before stdout completion")
            for key, _ in selector.select(min(remaining, 0.2)):
                try:
                    chunk = os.read(
                        key.fd, min(4096, _CHILD_STDOUT_LIMIT - len(result) + 1)
                    )
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fd)
                else:
                    result.extend(chunk)
                    if len(result) > _CHILD_STDOUT_LIMIT:
                        raise DiagnosticError(
                            "child stdout exceeds completion byte limit"
                        )
    try:
        process.wait(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        raise DiagnosticError("child timeout after stdout EOF") from error
    return bytes(result)


def _stop_child_group(process):
    """Best-effort bounded TERM/KILL of the group created by this parent."""
    errors = []
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except OSError as error:
            errors.append(f"group signal {sig}: {error}")
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            if sig == signal.SIGKILL:
                errors.append("child could not be reaped after SIGKILL")
        # Even when the leader exits after TERM, remaining members must receive
        # KILL. No broad process-name or scheduler cancellation is used.
    return errors


class _ColdChildLauncher:
    """Internal transport seam, NOT a public or fully authorized coordinator.

    The future sole owner must check receipt/package/spool, hold the shared lock,
    enforce matrix order/equivalence and reverify artifacts. A successful exit
    envelope alone is deliberately named CHILD_EXIT_VERIFIED, not cell success.
    """

    def __init__(
        self, job_id, input_freeze_sha256, scratch_root, *, timeout_seconds=3000.0
    ):
        _child_identity("_child-reference", job_id, None)
        _require_sha256(input_freeze_sha256)
        self.scratch_root = _child_scratch_path(scratch_root, job_id)
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 3600
        ):
            raise DiagnosticError(
                "child timeout must be finite and within allocation limit"
            )
        self.job_id, self.freeze_sha = job_id, input_freeze_sha256
        self.timeout_seconds = timeout_seconds
        self._attempted: set[str] = set()
        self._pids: set[int] = set()
        self._active = None

    def run(self, mode, cell=None):
        role = _child_identity(mode, self.job_id, cell)
        if role in self._attempted:
            raise DiagnosticError("refusing child retry within this launcher")
        if self._active is not None:
            raise DiagnosticError("another child is active in this launcher")
        command = child_command(
            mode, self.job_id, self.freeze_sha, cell, self.scratch_root
        )
        environment = child_environment(
            mode, self.job_id, cell, self.scratch_root, os.environ
        )
        attempt = DIAGNOSTIC_ROOT / "attempts" / f"slurm-{self.job_id}"
        with (
            _PinnedArtifactDirectory(self.scratch_root) as scratch,
            _PinnedArtifactDirectory(attempt) as owner,
        ):
            for anchor in (scratch, owner):
                info = os.fstat(anchor.fd)
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise DiagnosticError("child parent must be user-owned mode 0700")
            child_path = attempt / (
                "reference_cold" if cell is None else f"cells/{cell}"
            )
            if os.path.lexists(self.scratch_root / role) or os.path.lexists(child_path):
                raise DiagnosticError(
                    "refusing existing child scratch/evidence; never retry"
                )
            self._attempted.add(role)  # consumed even if Popen itself fails
            process = subprocess.Popen(
                command,
                env=environment,
                shell=False,
                start_new_session=True,
                pass_fds=(),
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=None,
            )
            self._active = process
            try:
                if (
                    type(process.pid) is not int
                    or process.pid <= 1
                    or process.pid == os.getpid()
                    or process.pid in self._pids
                ):
                    raise DiagnosticError("child PID is not a distinct fresh process")
                self._pids.add(process.pid)
                stdout = _collect_child_stdout(
                    process, timeout_seconds=self.timeout_seconds
                )
                if process.returncode != 0:
                    raise DiagnosticError(
                        f"child exit is nonzero: {process.returncode}"
                    )
                completion = _decode_child_completion(
                    stdout,
                    pid=process.pid,
                    mode=mode,
                    job_id=self.job_id,
                    freeze_sha=self.freeze_sha,
                    cell=cell,
                )
                for anchor in (scratch, owner):
                    anchor.check()
                    info = os.fstat(anchor.fd)
                    if (
                        info.st_uid != os.getuid()
                        or stat.S_IMODE(info.st_mode) != 0o700
                    ):
                        raise DiagnosticError("child parent ownership/mode changed")
                return {
                    "status": "CHILD_EXIT_VERIFIED",
                    "pid": process.pid,
                    "returncode": 0,
                    "argv": command,
                    "environment": environment,
                    "completion": completion,
                    "stdout_bytes": len(stdout),
                    "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                }
            except BaseException as error:
                for note in _stop_child_group(process):
                    error.add_note(note)
                raise
            finally:
                if process.stdout is not None:
                    process.stdout.close()
                self._active = None


_MATRIX_ROLES = ("REFERENCE_COLD", "A2", "A1", "B1", "B2")


class _MatrixArtifactStore(_AttemptArtifactStore):
    """Owner-only fixed filenames; the child's storage namespace stays unchanged."""

    @staticmethod
    def _parts(relative, *, directory=False):
        names = {f"CHILD_EXIT_{role}.json" for role in _MATRIX_ROLES}
        names.update(
            (
                "REFERENCE_EQUIVALENCE.json",
                "INVALID_TRACE_PATH.json",
                "MATRIX_SUMMARY.json",
            )
        )
        if type(relative) is str:
            if directory and relative == "":
                return ()
            if not directory and relative in names:
                return (relative,)
        raise DiagnosticError("matrix owner artifact is outside fixed namespace")


def _validated_launch_record(launch, *, job_id, freeze_sha):
    """Validate a parent's captured transport, not an arbitrary success string.

    The outer owner supplies this from _ColdChildLauncher or a SHA-bound durable
    launch record. This helper does not grant submission or execution authority.
    """
    required = {
        "status",
        "pid",
        "returncode",
        "argv",
        "environment",
        "completion",
        "stdout_bytes",
        "stdout_sha256",
    }
    if (
        not isinstance(launch, Mapping)
        or set(launch) != required
        or launch["status"] != "CHILD_EXIT_VERIFIED"
        or type(launch["pid"]) is not int
        or launch["pid"] <= 1
        or type(launch["returncode"]) is not int
        or launch["returncode"] != 0
    ):
        raise DiagnosticError("parent child-exit receipt schema differs")
    completion = launch["completion"]
    if not isinstance(completion, Mapping):
        raise DiagnosticError("parent receipt lacks child completion")
    mode, cell = completion.get("mode"), completion.get("cell")
    _child_identity(mode, job_id, cell)
    _require_sha256(freeze_sha)
    environment = launch["environment"]
    if not isinstance(environment, Mapping):
        raise DiagnosticError("parent receipt lacks child environment")
    scratch = environment.get("DIAG_SCRATCH_ROOT")
    expected_environment = child_environment(mode, job_id, cell, scratch, environment)
    if environment != expected_environment or launch["argv"] != child_command(
        mode, job_id, freeze_sha, cell, scratch
    ):
        raise DiagnosticError(
            "parent receipt command/environment differs from fixed child"
        )
    raw = _get_trace().canonical_json_bytes(completion)
    decoded = _decode_child_completion(
        raw,
        pid=launch["pid"],
        mode=mode,
        job_id=job_id,
        freeze_sha=freeze_sha,
        cell=cell,
    )
    if (
        type(launch["stdout_bytes"]) is not int
        or launch["stdout_bytes"] != len(raw)
        or launch["stdout_sha256"] != hashlib.sha256(raw).hexdigest()
    ):
        raise DiagnosticError("parent stdout commitment differs from completion")
    return decoded


def _persisted_trial_identity(payload, boundary, *, derived=False):
    """Compare committed per-trial identities, never fabricate raw tensor bytes."""
    container = payload["boundaries"]["derived"] if derived else payload["boundaries"]
    record = container.get(boundary)
    rows = record.get("per_trial") if isinstance(record, Mapping) else None
    ids = payload["trial_ids"]
    if not isinstance(rows, list) or len(rows) != len(ids):
        raise DiagnosticError(f"persisted {boundary} trial inventory is incomplete")
    result = {}
    for ident, row in zip(ids, rows):
        if (
            not isinstance(row, Mapping)
            or row.get("trial_id") != ident
            or row.get("boundary") != boundary
            or not isinstance(row.get("shape"), list)
            or any(type(n) is not int or n < 0 for n in row["shape"])
            or not isinstance(row.get("dtype"), str)
            or not row["dtype"]
        ):
            raise DiagnosticError(f"persisted {boundary} trial record is invalid")
        _require_sha256(row.get("sha256"))
        result[ident] = {k: row[k] for k in ("shape", "dtype", "sha256")}
    return result


def _bind_persisted_worker(metadata, launch, source_records):
    """Bind actual saved pass metadata to the parent PID/env and frozen sources."""
    env, completion = launch["environment"], launch["completion"]
    cell = completion["cell"]
    role = cell or "reference_cold"
    scratch = pathlib.Path(env["DIAG_SCRATCH_ROOT"]) / role
    _require_frozen_numeric_runtime(
        metadata.get("runtime"),
        "persisted worker runtime differs from frozen v4 settings",
    )
    if (
        metadata.get("worker_pid") != launch["pid"]
        or type(metadata.get("worker_pid")) is not int
        or metadata.get("scratch_root") != str(scratch)
        or metadata.get("cache_roots")
        != {k: str(scratch / k) for k in ("torchinductor", "triton", "cuda")}
    ):
        raise DiagnosticError(
            "persisted worker PID/runtime/scratch differs from launch"
        )
    for key in ("worker_nonce", "model_nonce", "cache_nonce"):
        if type(metadata.get(key)) is not str or not metadata[key]:
            raise DiagnosticError(f"persisted worker has no {key}")
    if (
        not isinstance(source_records, (list, tuple))
        or not source_records
        or any(
            not isinstance(r, Mapping) or type(r.get("relative_path")) is not str
            for r in source_records
        )
    ):
        raise DiagnosticError("parent frozen source inventory is missing")
    source_map = {r["relative_path"]: r for r in source_records}
    if len(source_map) != len(source_records):
        raise DiagnosticError("parent frozen source inventory contains duplicates")
    observed = metadata.get("imported_source_records")
    if not isinstance(observed, list) or not observed:
        raise DiagnosticError("persisted worker source inventory is empty")
    seen = set()
    for record in observed:
        if (
            not isinstance(record, Mapping)
            or type(record.get("relative_path")) is not str
        ):
            raise DiagnosticError("persisted worker source record is malformed")
        key = record["relative_path"]
        frozen = source_map.get(key)
        if (
            key in seen
            or frozen is None
            or any(
                record.get(k) != frozen.get(k)
                for k in ("path", "relative_path", "type", "size", "sha256")
            )
        ):
            raise DiagnosticError(
                "persisted worker source is not bound by parent freeze"
            )
        _require_sha256(record.get("sha256"))
        seen.add(key)
    attestation = metadata.get("attestation")
    context_sha = hashlib.sha256(
        _get_trace().canonical_json_bytes(
            {
                "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
                "v4_protocol": V4_PROTOCOL,
                "evaluator_sha256": V4_EVALUATOR_SHA256,
                "manifest_sha256": V4_MANIFEST_SHA256,
                "load_report_sha256": metadata["load_report_sha256"],
                "imported_source_records": observed,
            }
        )
    ).hexdigest()
    required_attestation = {
        "basis": "static_formal40_worker_attestation",
        "limitation": "inference-disabled versions are not dynamic mutation detection",
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "v4_protocol": V4_PROTOCOL,
        "evaluator_sha256": V4_EVALUATOR_SHA256,
        "manifest_sha256": V4_MANIFEST_SHA256,
        "model_id": "formal40",
        "worker_pid": launch["pid"],
        "worker_nonce": metadata["worker_nonce"],
        "model_nonce": metadata["model_nonce"],
        "load_report_sha256": metadata["load_report_sha256"],
        "input_context_sha256": context_sha,
        "trust_domain": "production",
    }
    if (
        not isinstance(attestation, Mapping)
        or any(
            type(attestation.get(k)) is not type(v) or attestation[k] != v
            for k, v in required_attestation.items()
        )
        or type(attestation.get("scene_scope_nonce")) is not str
        or not attestation["scene_scope_nonce"]
    ):
        raise DiagnosticError(
            "persisted production attestation differs from launch/input binding"
        )
    worker_env = metadata.get("worker_environment")
    if (
        not isinstance(worker_env, Mapping)
        or worker_env.get("schema_version") != 1
        or worker_env.get("worker_role") != role
        or worker_env.get("scratch_root") != str(scratch)
        or worker_env.get("caches_initially_empty") is not True
        or worker_env.get("write_paths") != {k: env[k] for k in _WORKER_WRITE_PATHS}
    ):
        raise DiagnosticError("persisted worker writable-environment evidence differs")
    software = worker_env.get("software")
    required_software = {
        "python",
        "torch",
        "cuda_runtime",
        "cudnn",
        "device",
        "gpu_name",
        "hostname",
        "worker_pid",
        "slurm_job_id",
        "cuda_visible_devices",
    }
    if (
        not isinstance(software, Mapping)
        or set(software) != required_software
        or type(software["worker_pid"]) is not int
        or software["worker_pid"] != launch["pid"]
        or software["slurm_job_id"] != completion["job_id"]
        or software["cuda_visible_devices"] != env["CUDA_VISIBLE_DEVICES"]
        or any(
            type(software[k]) is not str or not software[k]
            for k in (
                "python",
                "torch",
                "cuda_runtime",
                "device",
                "gpu_name",
                "hostname",
            )
        )
        or not software["device"].startswith("cuda")
        or type(software["cudnn"]) is not int
        or software["cudnn"] <= 0
    ):
        raise DiagnosticError("persisted worker software/job/GPU binding differs")


def _read_bound_child_result(
    launch, *, job_id, freeze_sha, trials, source_records, historical_scene_hashes
):
    """Read-only parent acceptance after exit; digest metadata is not raw tensors.

    The caller must supply independently verified freeze/history records and an
    owner-captured launch receipt. No public CLI accepts these as user JSON.
    """
    completion = _validated_launch_record(launch, job_id=job_id, freeze_sha=freeze_sha)
    cell = completion["cell"]
    attempt = DIAGNOSTIC_ROOT / "attempts" / f"slurm-{job_id}"
    path = attempt / (f"cells/{cell}" if cell else "reference_cold")
    verifier = verify_cell_artifacts if cell else verify_reference_artifacts
    verified = verifier(
        path,
        expected_marker=completion["marker_record"],
        expected_input_freeze_sha256=freeze_sha,
    )
    inputs = verified["inputs"]
    _validate_trial_documents(trials)
    if inputs["trials"] != trials:
        raise DiagnosticError(
            "child trials differ from parent frozen ordinals/identities"
        )
    decoded = _validate_child_inputs(inputs, cell=cell, freeze=freeze_sha)
    payloads = [p["payload"] for p in decoded]
    metadata = [p["boundaries"]["metadata"] for p in payloads]
    for p, meta in zip(payloads, metadata):
        _bind_persisted_worker(meta, launch, source_records)
        if not _model_transition(p["model_snapshots"])["state_unchanged"]:
            raise DiagnosticError("persisted child model state changed")
        _rng_transition(p["rng_snapshots"])
        raw = _persisted_trial_identity(p, "raw_scene")
        for ident, row in raw.items():
            if historical_scene_hashes.get(ident) != row["sha256"]:
                raise DiagnosticError(
                    "persisted scene digest differs from historical frozen scene"
                )
    # Both reference and cells must retain one instance across their two passes.
    for name in (
        "runtime",
        "load_report",
        "load_report_sha256",
        "imported_source_records",
        "worker_pid",
        "worker_nonce",
        "model_nonce",
        "scratch_root",
        "cache_roots",
        "attestation",
        "worker_environment",
    ):
        if metadata[0].get(name) != metadata[1].get(name):
            raise DiagnosticError("persisted two-pass worker identity differs")
    if metadata[0]["cache_nonce"] == metadata[1]["cache_nonce"]:
        raise DiagnosticError(
            "persisted worker reused its waveform cache between passes"
        )
    _cell_timepoints(
        *(
            types.SimpleNamespace(
                model_snapshots=p["model_snapshots"], rng_snapshots=p["rng_snapshots"]
            )
            for p in payloads
        )
    )
    for name in ("raw_scene", "raw_cue"):
        if _persisted_trial_identity(payloads[0], name) != _persisted_trial_identity(
            payloads[1], name
        ):
            raise DiagnosticError("persisted two-pass raw identity differs")
    if cell and verified["comparison"]["cell_status"] == "INVALID":
        raise DiagnosticError(
            "child stored INVALID evidence, not a finite numeric DIFF"
        )
    return {
        "status": "CHILD_ORIGIN_AND_ARTIFACTS_VERIFIED",
        "job_id": job_id,
        "input_freeze_sha256": freeze_sha,
        "role": cell or "REFERENCE_COLD",
        "worker_pid": launch["pid"],
        "inputs": inputs,
        "comparison": verified["comparison"],
        "marker_record": completion["marker_record"],
        "pass_bindings": [p["commitment"]["binding_sha256"] for p in inputs["passes"]],
    }


def _check_distinct_persisted_workers(observations):
    """Portable evidence check: node-local cache directories may already be gone."""
    for key in ("job_id", "input_freeze_sha256"):
        if len({o[key] for o in observations}) != 1:
            raise DiagnosticError("matrix child job/freeze bindings differ")
    metadata = [
        o["inputs"]["passes"][0]["payload"]["boundaries"]["metadata"]
        for o in observations
    ]
    for key in ("worker_pid", "worker_nonce", "model_nonce"):
        if len({m[key] for m in metadata}) != len(metadata):
            raise DiagnosticError(f"matrix did not use distinct cold workers: {key}")
    common = ("runtime", "load_report", "load_report_sha256", "imported_source_records")
    for m in metadata[1:]:
        if any(m[k] != metadata[0][k] for k in common):
            raise DiagnosticError("matrix worker runtime/model/source evidence differs")
    software = [
        {
            k: v
            for k, v in m["worker_environment"]["software"].items()
            if k != "worker_pid"
        }
        for m in metadata
    ]
    if any(s != software[0] for s in software[1:]):
        raise DiagnosticError("matrix worker software/GPU environment differs")
    initial_states = []
    for observation in observations:
        state = observation["inputs"]["passes"][0]["payload"]["model_snapshots"]
        if not _model_transition(state)["state_unchanged"]:
            raise DiagnosticError("matrix worker state was not stable")
        # Object IDs and storage/version counters are process-local. Compare
        # the actual initial tensor inventory/content across fresh processes.
        entries = [
            {k: row[k] for k in ("kind", "name", "shape", "dtype", "device", "sha256")}
            for row in state["before"]
        ]
        if not entries:
            raise DiagnosticError("matrix worker initial model inventory is empty")
        initial_states.append(sorted(entries, key=lambda r: (r["kind"], r["name"])))
    if any(s != initial_states[0] for s in initial_states[1:]):
        raise DiagnosticError("cold workers did not start with identical model content")
    roots = [pathlib.Path(m["scratch_root"]) for m in metadata]
    for i, left in enumerate(roots):
        for right in roots[i + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise DiagnosticError("matrix worker scratch roots overlap")


def _compare_persisted_reference(reference, a2):
    """Post-origin bitwise gate over BOTH saved passes; no fabricated PassResult.

    Official outputs are decoded losslessly and recomputed. Raw/correct identity
    is compared using worker-committed shape/dtype/SHA records bound to its files.
    This does not replace the live-context API compare_reference_equivalence().
    """
    if reference.get("role") != "REFERENCE_COLD" or a2.get("role") != "A2":
        raise DiagnosticError("persisted reference equivalence roles differ")
    _check_distinct_persisted_workers([reference, a2])
    if reference["inputs"]["trials"] != a2["inputs"]["trials"]:
        raise DiagnosticError("persisted reference equivalence frozen trials differ")
    comparisons = []
    for i, (left, right) in enumerate(
        zip(reference["inputs"]["passes"], a2["inputs"]["passes"]), 1
    ):
        left_decoded = decode_pass_evidence(left)
        right_decoded = decode_pass_evidence(right)
        lp, rp = left_decoded["payload"], right_decoded["payload"]
        if lp["pass_id"] != rp["pass_id"] or lp["batch_size"] != rp["batch_size"]:
            raise DiagnosticError(
                "persisted reference equivalence pass identity differs"
            )
        order = _aligned_order(tuple(lp["trial_ids"]), tuple(rp["trial_ids"]))
        identities = {}
        for name, derived in (
            ("raw_scene", False),
            ("raw_cue", False),
            ("correct", True),
        ):
            left_identity = _persisted_trial_identity(lp, name, derived=derived)
            right_identity = _persisted_trial_identity(rp, name, derived=derived)
            if left_identity != right_identity:
                raise DiagnosticError(
                    f"persisted reference equivalence failed at pass{i}.{name}"
                )
            identities[name] = {
                "basis": "origin_bound_per_trial_shape_dtype_sha256",
                "exact": True,
            }
        outputs = {}
        for name in _OFFICIAL_OUTPUT_KEYS:
            result = _bounded_boundary_comparison(
                left_decoded["outputs"][name],
                right_decoded["outputs"][name][order],
                ids=tuple(lp["trial_ids"]),
                name=name,
            )
            if (
                not result["schema_valid"]
                or not result["finite_valid"]
                or not result["bitwise_equal"]
            ):
                raise DiagnosticError(
                    f"persisted reference equivalence failed at pass{i}.{name}"
                )
            outputs[name] = result
        comparisons.append(
            {
                "pass_id": f"pass{i}",
                "batch_size": lp["batch_size"],
                "identities": identities,
                "official_outputs": outputs,
            }
        )
    return {
        "schema_version": 1,
        "status": "REFERENCE_EQUIVALENCE_PASS",
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "evaluation_role": EVALUATION_ROLE,
        "reference_pass_bindings": reference["pass_bindings"],
        "a2_pass_bindings": a2["pass_bindings"],
        "passes": comparisons,
    }


def aggregate_matrix(cells, equivalence):
    """Semantic aggregation of reverified observations, not an origin authority."""
    if (
        not isinstance(cells, Mapping)
        or set(cells) != set(CELL_SPECS)
        or not isinstance(equivalence, Mapping)
        or equivalence.get("status") != "REFERENCE_EQUIVALENCE_PASS"
        or len(equivalence.get("passes", [])) != 2
    ):
        raise DiagnosticError(
            "matrix requires four cells and two-pass reference equivalence"
        )
    observations = [cells[k] for k in ("A2", "A1", "B1", "B2")]
    for key, obs in cells.items():
        if (
            not isinstance(obs, Mapping)
            or obs.get("status") != "CHILD_ORIGIN_AND_ARTIFACTS_VERIFIED"
            or obs.get("role") != key
            or not isinstance(obs.get("comparison"), Mapping)
            or obs["comparison"].get("cell_id") != key
            or obs["comparison"].get("cell_status") not in ("PASS", "DIFF")
            or obs["comparison"].get("canary_status") not in ("PASS", "DIFF")
        ):
            raise DiagnosticError("matrix cell is missing, misbound or invalid")
    _check_distinct_persisted_workers(observations)
    baseline = observations[0]["inputs"]
    for obs in observations:
        if obs["inputs"]["trials"] != baseline["trials"]:
            raise DiagnosticError("matrix frozen trial identities differ")
        for p in obs["inputs"]["passes"]:
            for name in ("raw_scene", "raw_cue"):
                if _persisted_trial_identity(
                    p["payload"], name
                ) != _persisted_trial_identity(baseline["passes"][0]["payload"], name):
                    raise DiagnosticError(
                        "matrix raw/cue identity differs between cells"
                    )
    if equivalence.get("a2_pass_bindings") != cells["A2"]["pass_bindings"]:
        raise DiagnosticError("reference equivalence belongs to another A2")
    summaries = {k: v["comparison"] for k, v in cells.items()}
    classification = classify_a2(summaries["A2"])
    return {
        "schema_version": 1,
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "evaluation_role": EVALUATION_ROLE,
        "status": "MATRIX_EVIDENCE_VERIFIED",
        "execution_order": list(EXECUTION_ORDER),
        "cells": summaries,
        "a2_replay_classification": classification,
        "first_divergence_by_cell": {
            k: first_divergence(c["comparisons"]) for k, c in summaries.items()
        },
        "targeted_trace_cells": [
            k
            for k in ("A2", "A1", "B1", "B2")
            if summaries[k]["targeted_trace_required"]
        ],
        "boundary_metric_basis": "origin_bound_worker_observations__official_canary_recomputed",
        "limitations": [
            "formal40_only_not_three_model_residency",
            "cold_separate_process_caches",
            "autocast_off_retains_frozen_tf32_and_compile",
            "no_scientific_ranking",
        ],
    }


def _reverify_matrix_sequence(
    launch_records,
    *,
    job_id,
    freeze_sha,
    trials,
    source_records,
    historical_scene_hashes,
):
    """Read-only recomputation from owner-bound immutable launch/file records."""
    if not isinstance(launch_records, Mapping) or set(launch_records) != set(
        _MATRIX_ROLES
    ):
        raise DiagnosticError("matrix launch record set is incomplete")
    observations = {}
    attempt = DIAGNOSTIC_ROOT / "attempts" / f"slurm-{job_id}"
    with _MatrixArtifactStore(attempt) as store:
        for role in _MATRIX_ROLES:
            record = launch_records[role]
            name = f"CHILD_EXIT_{role}.json"
            if not isinstance(record, Mapping) or record.get("relative_path") != name:
                raise DiagnosticError(
                    "matrix launch record is outside fixed owner path"
                )
            launch = _artifact_json(store, store.verify_record(record))
            observed = _read_bound_child_result(
                launch,
                job_id=job_id,
                freeze_sha=freeze_sha,
                trials=trials,
                source_records=source_records,
                historical_scene_hashes=historical_scene_hashes,
            )
            if observed["role"] != role:
                raise DiagnosticError(
                    "matrix launch role differs from receipt filename"
                )
            observations[role] = observed
        _check_distinct_persisted_workers(list(observations.values()))
        equivalence = _compare_persisted_reference(
            observations["REFERENCE_COLD"], observations["A2"]
        )
        saved = _artifact_json(store, store.record("REFERENCE_EQUIVALENCE.json"))
        if saved != equivalence:
            raise DiagnosticError(
                "saved reference equivalence differs from recomputation"
            )
        result = aggregate_matrix({k: observations[k] for k in CELL_SPECS}, equivalence)
        for record in launch_records.values():
            store.verify_record(record)
    return result


def _run_matrix_sequence(
    launcher, *, job_id, freeze_sha, trials, source_records, historical_scene_hashes
):
    """Internal owner component; NOT a public coordinator or submission entry.

    Caller must already own the attempt and shared v4 lock and authenticated
    PRE inputs. This component deliberately writes no diagnostic terminal.
    """
    _child_identity("_child-reference", job_id, None)
    _require_sha256(freeze_sha)
    attempt = DIAGNOSTIC_ROOT / "attempts" / f"slurm-{job_id}"
    launch_records, observations = {}, {}
    options = dict(
        job_id=job_id,
        freeze_sha=freeze_sha,
        trials=trials,
        source_records=source_records,
        historical_scene_hashes=historical_scene_hashes,
    )
    with _MatrixArtifactStore(attempt) as store:
        # Do not discover an earlier partial sequence only after launching work.
        reserved = [f"CHILD_EXIT_{role}.json" for role in _MATRIX_ROLES]
        reserved += [
            "reference_cold",
            "cells",
            "REFERENCE_EQUIVALENCE.json",
            "INVALID_TRACE_PATH.json",
            "MATRIX_SUMMARY.json",
        ]
        if any(os.path.lexists(attempt / name) for name in reserved):
            raise DiagnosticError("matrix evidence already exists; no automatic retry")
        for role in _MATRIX_ROLES:
            cell = None if role == "REFERENCE_COLD" else role
            launch = launcher.run(
                "_child-reference" if cell is None else "_child-cell", cell
            )
            _validated_launch_record(launch, job_id=job_id, freeze_sha=freeze_sha)
            launch_records[role] = store.publish_bytes(
                f"CHILD_EXIT_{role}.json", _get_trace().canonical_json_bytes(launch)
            )
            observations[role] = _read_bound_child_result(launch, **options)
            if observations[role]["role"] != role:
                raise DiagnosticError(
                    "returned child differs from requested matrix role"
                )
            if role == "A2":
                try:
                    equivalence = _compare_persisted_reference(
                        observations["REFERENCE_COLD"], observations["A2"]
                    )
                except DiagnosticError as error:
                    store.publish_bytes(
                        "INVALID_TRACE_PATH.json",
                        _get_trace().canonical_json_bytes(
                            {
                                "schema_version": 1,
                                "status": "INVALID_TRACE_PATH",
                                "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
                                "evaluation_role": EVALUATION_ROLE,
                                "job_id": job_id,
                                "input_freeze_sha256": freeze_sha,
                                "error": str(error),
                                "launch_records": launch_records,
                            }
                        ),
                    )
                    raise
                store.publish_bytes(
                    "REFERENCE_EQUIVALENCE.json",
                    _get_trace().canonical_json_bytes(equivalence),
                )
        # Re-read all evidence, including early children, after the last child.
        summary = _reverify_matrix_sequence(launch_records, **options)
        summary_record = store.publish_bytes(
            "MATRIX_SUMMARY.json", _get_trace().canonical_json_bytes(summary)
        )
        return {
            "status": "MATRIX_EVIDENCE_VERIFIED",
            "summary": summary,
            "summary_record": summary_record,
            "launch_records": launch_records,
        }


_COORDINATOR_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
FORBIDDEN_SCIENCE_MARKERS = (
    "SMOKE_PASS.json",
    "SAME_BANK_AUDIT_PUBLISHED.json",
    "COMPLETE.json",
)


def _owner_json_bytes(value):
    """Stdlib bootstrap encoding; same wire format as numeric_trace."""
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def _owner_read_json(path, *, root, expected_sha=None):
    with _PinnedArtifactDirectory(pathlib.Path(path).parent) as anchor:
        raw, record = _read_stable_source_bytes(path, allowed_root=root)
        anchor.check()
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or _owner_json_bytes(value) != raw:
            raise ValueError("noncanonical object")
    except (ValueError, UnicodeError) as error:
        raise DiagnosticError(f"noncanonical owner JSON: {path}") from error
    if expected_sha is not None and record["sha256"] != expected_sha:
        raise DiagnosticError(f"owner JSON hash changed: {path}")
    return value, record


def _read_v4_manifest(contract):
    """Read only the pinned historical manifest in its own v4 wire format.

    v4's SHA-bound writer uses indent=2, unlike diagnostic-owned compact JSON.
    Authenticate the original bytes before parsing; never rewrite or rebaseline
    them. This is not a permissive mode for journals, freezes or result artifacts.
    """
    _require_sha256(contract.manifest_sha256)
    root = pathlib.Path(contract.v4_root)
    path = root / "input_freeze.json"
    with _PinnedArtifactDirectory(root) as anchor:
        raw, record = _read_stable_source_bytes(path, allowed_root=root)
        anchor.check()
    if record["sha256"] != contract.manifest_sha256:
        raise DiagnosticError(f"v4 manifest hash changed: {path}")
    try:
        value = json.loads(raw)
        # Match the frozen v4 canonical_json_bytes, not _owner_json_bytes.
        canonical = (
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
        ).encode("utf-8")
        if not isinstance(value, dict) or canonical != raw:
            raise ValueError("noncanonical v4 object")
    except (ValueError, UnicodeError) as error:
        raise DiagnosticError(f"noncanonical v4 manifest JSON: {path}") from error
    return value, record


def _submission_argv(nonce, freeze_sha):
    return [
        str(SBATCH_PATH),
        "--parsable",
        "--export=NONE",
        f"--comment=audattn-v4-numdiag-{nonce[:12]}",
        str(DIAGNOSTIC_ROOT / "tools/run_numeric_diag.sbatch"),
        freeze_sha,
        nonce,
    ]


def _wait_submission_binding(
    args, runner_sha, *, monotonic=None, sleep=None, wait_for_receipt=True
):
    """Only an absent atomic receipt can be awaited; malformed evidence is final."""
    _child_identity("_child-reference", args.job_id, None)
    _require_sha256(args.expected_input_freeze_sha256)
    _require_sha256(runner_sha)
    nonce = args.intent_nonce
    if (
        not isinstance(nonce, str)
        or len(nonce) != 32
        or any(c not in "0123456789abcdef" for c in nonce)
    ):
        raise DiagnosticError("intent nonce must be 32 lowercase hex digits")
    monotonic, sleep = monotonic or time.monotonic, sleep or time.sleep
    root = DIAGNOSTIC_ROOT / "state"
    common = {
        "schema_version": 1,
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "intent_nonce": nonce,
        "input_freeze_sha256": args.expected_input_freeze_sha256,
        "runner_sha256": runner_sha,
    }
    intent, intent_record = _owner_read_json(root / "INTENT.json", root=root)
    if intent != dict(
        common,
        status="SUBMISSION_INTENT",
        argv=_submission_argv(nonce, args.expected_input_freeze_sha256),
    ):
        raise DiagnosticError("submission intent differs from fixed contract")
    deadline = monotonic() + 120.0
    while not os.path.lexists(root / "SUBMISSION_RECEIPT.json"):
        if not wait_for_receipt:
            raise DiagnosticError(
                "submission receipt absent; verification never waits or retries"
            )
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise DiagnosticError("submission receipt timeout (120 seconds)")
        sleep(min(1.0, remaining))
    receipt, receipt_record = _owner_read_json(
        root / "SUBMISSION_RECEIPT.json", root=root
    )
    response, response_record = _owner_read_json(
        root / "SBATCH_RESPONSE.json", root=root
    )
    expected_receipt = dict(
        common,
        status="SUBMITTED",
        job_id=args.job_id,
        intent_record_sha256=intent_record["sha256"],
        response_record_sha256=response_record["sha256"],
    )
    if receipt != expected_receipt:
        raise DiagnosticError("submission receipt identity differs")
    try:
        stdout = base64.b64decode(response["stdout_b64"], validate=True)
        stderr = base64.b64decode(response["stderr_b64"], validate=True)
    except (KeyError, ValueError, TypeError) as error:
        raise DiagnosticError("invalid scheduler response encoding") from error
    expected_response = dict(
        common,
        status="SBATCH_RESPONSE",
        argv=intent["argv"],
        returncode=0,
        stdout_b64=base64.b64encode(stdout).decode("ascii"),
        stderr_b64="",
    )
    if (
        type(response.get("returncode")) is not int
        or response != expected_response
        or stderr
        or stdout
        not in (args.job_id.encode("ascii"), (args.job_id + "\n").encode("ascii"))
    ):
        raise DiagnosticError("scheduler response is ambiguous or unsuccessful")
    records = {
        "INTENT.json": intent_record,
        "SBATCH_RESPONSE.json": response_record,
        "SUBMISSION_RECEIPT.json": receipt_record,
    }
    for record in records.values():
        _check_bound_record(record)
    return {"job_id": args.job_id, "intent_nonce": nonce, "records": records}


def _check_bound_record(expected):
    """Stream one pinned regular file; portable identity, bounded working memory."""
    if not isinstance(expected, Mapping):
        raise DiagnosticError("bound file record is not an object")
    path = pathlib.Path(str(expected.get("path", "")))
    if (
        not path.is_absolute()
        or str(path) != expected.get("path")
        or ".." in path.parts
        or expected.get("type") != "file"
        or type(expected.get("size")) is not int
        or expected["size"] < 0
    ):
        raise DiagnosticError("invalid canonical bound file record")
    _require_sha256(expected.get("sha256"))
    try:
        with _PinnedArtifactDirectory(path.parent) as anchor:
            before = os.stat(path.name, dir_fd=anchor.fd, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise DiagnosticError("bound file is not a single-link regular file")
            fd = os.open(
                path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=anchor.fd
            )
            try:
                opened = os.fstat(fd)
                if not _same_identity(before, opened):
                    raise DiagnosticError("bound file changed on open")
                digest = hashlib.sha256()
                while True:
                    chunk = os.read(fd, 1 << 20)
                    if not chunk:
                        break
                    digest.update(chunk)
                after = os.fstat(fd)
                named = os.stat(path.name, dir_fd=anchor.fd, follow_symlinks=False)
                if not _same_identity(opened, after) or not _same_identity(
                    after, named
                ):
                    raise DiagnosticError("bound file changed while hashing")
                actual = {
                    "path": str(path),
                    "type": "file",
                    "size": after.st_size,
                    "sha256": digest.hexdigest(),
                }
                if actual != {k: expected[k] for k in actual}:
                    raise DiagnosticError(f"bound input identity changed: {path}")
                anchor.check()
                return actual
            finally:
                os.close(fd)
    except OSError as error:
        raise DiagnosticError(f"bound input unavailable: {path}") from error


def archive_spool_runner(spool_path, job_id, expected_sha256):
    _child_identity("_child-reference", job_id, None)
    _require_sha256(expected_sha256)
    spool_path = pathlib.Path(spool_path)
    if not spool_path.is_absolute() or ".." in spool_path.parts:
        raise DiagnosticError("spool runner must be a canonical absolute file")
    with _PinnedArtifactDirectory(spool_path.parent):
        raw, record = _read_stable_source_bytes(
            spool_path, allowed_root=spool_path.parent
        )
    if record["sha256"] != expected_sha256:
        raise DiagnosticError("submitted spool bytes differ from reviewed runner")
    target = DIAGNOSTIC_ROOT / "submitted_runners" / f"{job_id}.sbatch"
    with _PinnedArtifactDirectory(target.parent) as anchor:
        atomic_create_bytes(target, raw)
        anchor.check()
    return _read_stable_source_bytes(target, allowed_root=target.parent)[1]


class _CoordinatorSignal(BaseException):
    def __init__(self, signum):
        self.signum = int(signum)
        super().__init__(f"coordinator caught signal {self.signum}")


@contextlib.contextmanager
def _coordinator_signal_scope():
    saved = {sig: signal.getsignal(sig) for sig in _COORDINATOR_SIGNALS}
    interrupted = [False]

    def handler(signum, frame):
        if not interrupted[0]:
            interrupted[0] = True  # subsequent signals cannot prevent best-effort POST
            raise _CoordinatorSignal(signum)

    try:
        for sig in saved:
            signal.signal(sig, handler)
        yield
    finally:
        for sig, previous in saved.items():
            signal.signal(sig, previous)


def _owner_error(error, phase, code="EXECUTION_FAILED"):
    result = {
        "phase": phase,
        "code": code,
        "error_type": type(error).__name__,
        "message": str(error)[:4096],
        "notes": list(getattr(error, "__notes__", ()))[:16],
    }
    if isinstance(error, _CoordinatorSignal):
        result["signal"] = error.signum
    return result


def _coordinate(args, owner):
    """Single-owner lifecycle; private injected seam, not a bypass CLI."""
    authorization = owner.authorize()  # no attempt/output before authentication
    owner.claim()  # atomic mkdir: a competing/repeated owner never writes terminals
    report = {
        "schema_version": 1,
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "evaluation_role": EVALUATION_ROLE,
        "job_id": args.job_id,
        "input_freeze_sha256": args.expected_input_freeze_sha256,
        "authorization": authorization,
        "lock_acquired": False,
        "primary_error": None,
        "post_errors": [],
        "matrix": None,
        "pre": {"tree": None, "inputs": None},
        "post": {"tree": None, "inputs": None},
    }
    with _coordinator_signal_scope(), contextlib.ExitStack() as stack:
        try:
            fd = stack.enter_context(owner.lock())
            report["lock_acquired"] = True
        except (Exception, _CoordinatorSignal) as error:
            report["primary_error"] = _owner_error(error, "lock")
        if report["lock_acquired"]:
            try:
                owner.verify_lock(fd)
                report["pre"]["tree"] = owner.fingerprint()
                report["pre"]["inputs"] = owner.inputs()
                owner.publish("PRECHECK.json", report["pre"])
                owner.publish(
                    "RUNNING.json",
                    {
                        "schema_version": 1,
                        "status": "RUNNING",
                        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
                        "evaluation_role": EVALUATION_ROLE,
                        "job_id": args.job_id,
                        "input_freeze_sha256": args.expected_input_freeze_sha256,
                    },
                )
                report["matrix"] = owner.matrix()
                if (
                    not isinstance(report["matrix"], Mapping)
                    or report["matrix"].get("status") != "MATRIX_EVIDENCE_VERIFIED"
                    or not isinstance(report["matrix"].get("summary"), Mapping)
                    or not isinstance(report["matrix"].get("summary_record"), Mapping)
                ):
                    raise DiagnosticError("matrix did not return verified evidence")
            except (Exception, _CoordinatorSignal) as error:
                report["primary_error"] = _owner_error(error, "execution")
            # Each check runs even if a sibling check or the child execution failed.
            for key, function, code in (
                ("inputs", owner.inputs, "INVALID_BOUND_INPUT_CHANGED"),
                ("tree", owner.fingerprint, "INVALID_FROZEN_ROOT_CHANGED"),
            ):
                try:
                    report["post"][key] = function()
                    if (
                        report["pre"][key] is not None
                        and report["post"][key] != report["pre"][key]
                    ):
                        raise DiagnosticError(code)
                except (Exception, _CoordinatorSignal) as error:
                    report["post_errors"].append(
                        _owner_error(error, "post_" + key, code)
                    )
            try:
                owner.verify_lock(fd)
            except (Exception, _CoordinatorSignal) as error:
                report["post_errors"].append(
                    _owner_error(error, "post_lock", "INVALID_FROZEN_ROOT_CHANGED")
                )
            try:
                owner.publish("POSTCHECK.json", report["post"])
            except (Exception, _CoordinatorSignal) as error:
                report["post_errors"].append(_owner_error(error, "post_publication"))
        report["status"] = (
            "DIAGNOSTIC_FAILED"
            if report["primary_error"] or report["post_errors"]
            else "DIAGNOSTIC_COMPLETE"
        )
        # Commit has no active child. Defer catchable signals across link/fsync so
        # a partial publication never triggers a second, contradictory terminal.
        with _defer_terminal_signals():
            owner.publish(report["status"] + ".json", report)
        return report


@contextlib.contextmanager
def _defer_terminal_signals():
    saved = {sig: signal.getsignal(sig) for sig in _COORDINATOR_SIGNALS}
    try:
        for sig in saved:
            signal.signal(sig, signal.SIG_IGN)
        yield
    finally:
        for sig, handler in saved.items():
            signal.signal(sig, handler)


def classify_diagnostic_terminal(complete, failed, *, slurm_ended):
    """Classifies already-verified markers, not arbitrary untrusted JSON files."""
    if type(slurm_ended) is not bool:
        raise DiagnosticError("scheduler terminal state must be boolean")
    if complete is not None and failed is not None:
        raise DiagnosticError("conflicting diagnostic terminal markers")
    for value, status in (
        (complete, "DIAGNOSTIC_COMPLETE"),
        (failed, "DIAGNOSTIC_FAILED"),
    ):
        if value is not None:
            if not isinstance(value, Mapping) or value.get("status") != status:
                raise DiagnosticError("terminal marker status mismatch")
            return status
    return "INCOMPLETE_UNTRAPPED_TERMINATION" if slurm_ended else "AWAITING_TERMINAL"


def _portable_record(record, *, root=None):
    if root is not None:
        relative = record.get("relative_path")
        if (
            type(relative) is not str
            or not relative
            or pathlib.PurePosixPath(relative).is_absolute()
            or any(p in (".", "..") for p in relative.split("/"))
        ):
            raise DiagnosticError("invalid relative bound file path")
        path = str(pathlib.Path(root) / relative)
    else:
        path = record.get("path")
    return {
        "path": path,
        "type": "file",
        "size": record.get("size"),
        "sha256": record.get("sha256"),
    }


def _assert_no_science_markers(root):
    """No following of links; any forbidden name, even dangling, is refused."""
    with _PinnedArtifactDirectory(root) as anchor:
        for current, dirs, files in os.walk(root, followlinks=False):
            for name in dirs + files:
                path = pathlib.Path(current) / name
                if name in FORBIDDEN_SCIENCE_MARKERS:
                    raise DiagnosticError(f"forbidden scientific marker: {path}")
                mode = os.lstat(path).st_mode
                if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                    raise DiagnosticError(
                        f"diagnostic evidence may not contain symlinks/special files: {path}"
                    )
        anchor.check()


class _CoordinatorOwner:
    """Fixed-root file adapter. Production entry must validate interpreter/env first.

    Receipt wire schema is shared with the forthcoming Task 8 submitter; no
    scheduler invocation is made by this adapter. It never changes frozen v4.
    """

    def __init__(self, args):
        self.args = args
        self.root, self.contract = DIAGNOSTIC_ROOT, production_contract()
        self.attempt = self.root / "attempts" / f"slurm-{args.job_id}"
        self.claimed = False
        self.authorization = None
        self.lock_identity = None
        self.namespace = {}
        self.execution_guard = None

    def _check_namespace(self):
        for path, expected in self.namespace.items():
            try:
                with _PinnedArtifactDirectory(path) as anchor:
                    if not _same_directory_identity(expected, os.fstat(anchor.fd)):
                        raise DiagnosticError("owner directory identity changed")
            except OSError as error:
                raise DiagnosticError("owner directory is unavailable") from error

    def authorize(self, *, verification_only=False):
        _validate_layout(self.root, require_freeze=True)
        for path in (self.root, *(self.root / name for name in DIAGNOSTIC_LAYOUT)):
            with _PinnedArtifactDirectory(path) as anchor:
                self.namespace[path] = os.fstat(anchor.fd)
        _assert_no_science_markers(self.root)
        self.freeze, freeze_record = _owner_read_json(
            self.root / "input_freeze.json",
            root=self.root,
            expected_sha=self.args.expected_input_freeze_sha256,
        )
        _validate_freeze_value(
            self.freeze,
            self.contract,
            status="INPUTS_FROZEN",
            diagnostic_root=self.root,
        )
        self.records = [_portable_record(freeze_record)]
        for record in self.freeze["production_files"]:
            self.records.append(
                _check_bound_record(_portable_record(record, root=self.root / "tools"))
            )
        self.runner_sha = next(
            r["sha256"]
            for r in self.freeze["production_files"]
            if r["relative_path"] == "run_numeric_diag.sbatch"
        )
        self.journal = _wait_submission_binding(
            self.args, self.runner_sha, wait_for_receipt=not verification_only
        )
        self.records.extend(
            _portable_record(r) for r in self.journal["records"].values()
        )
        spool = (
            self.root / "submitted_runners" / f"{self.args.job_id}.sbatch"
            if verification_only
            else pathlib.Path(self.args.spool_runner)
        )
        if not spool.is_absolute() or ".." in spool.parts:
            raise DiagnosticError("spool path is not canonical")
        with _PinnedArtifactDirectory(spool.parent):
            _, spool_record = _read_stable_source_bytes(
                spool, allowed_root=spool.parent
            )
        if spool_record["sha256"] != self.runner_sha:
            raise DiagnosticError(
                "submitted spool differs from frozen diagnostic runner"
            )
        if verification_only:
            self.archive = spool_record
        self.authorization = {
            "job_id": self.args.job_id,
            "intent_nonce": self.args.intent_nonce,
            "input_freeze_sha256": self.args.expected_input_freeze_sha256,
            "runner_sha256": self.runner_sha,
            "journal": {
                name: _portable_record(r) for name, r in self.journal["records"].items()
            },
        }
        return self.authorization

    def claim(self):
        if self.authorization is None:
            raise DiagnosticError("owner has no authenticated submission")
        self._check_namespace()
        for name in ("DIAGNOSTIC_COMPLETE.json", "DIAGNOSTIC_FAILED.json"):
            if os.path.lexists(self.root / "state" / name):
                raise FileExistsError("terminal already exists")
        # Only one attempt is allowed for this frozen diagnostic root. Empty or
        # crashed prior attempts are evidence, never permission to retry.
        with _PinnedArtifactDirectory(self.root / "attempts") as parent:
            if os.listdir(parent.fd):
                raise FileExistsError("diagnostic attempt already exists; no retry")
            if os.listdir(self.root / "submitted_runners"):
                raise FileExistsError("submitted runner evidence already exists")
            os.mkdir(self.attempt.name, 0o700, dir_fd=parent.fd)
            self.namespace[self.attempt] = os.stat(
                self.attempt.name, dir_fd=parent.fd, follow_symlinks=False
            )
            os.fsync(parent.fd)
            parent.check()
        # Only the mkdir winner may publish any owner evidence. A later archive
        # failure leaves an incomplete attempt; a second caller must not resume it.
        self.claimed = True
        self.archive = archive_spool_runner(
            self.args.spool_runner, self.args.job_id, self.runner_sha
        )
        self.publish(
            "ENVIRONMENT.json",
            {
                "schema_version": 1,
                "job_id": self.args.job_id,
                "coordinator_pid": os.getpid(),
                "python": sys.version.split()[0],
                "environment": {
                    k: os.environ[k]
                    for k in (
                        "SLURM_JOB_ID",
                        "CUDA_VISIBLE_DEVICES",
                        "DIAG_SCRATCH_ROOT",
                    )
                    if k in os.environ
                },
            },
        )

    def lock(self):
        return shared_v4_lock(self.contract.v4_root / "state/evaluation.lock")

    def verify_lock(self, fd):
        path = self.contract.v4_root / "state/evaluation.lock"
        with _PinnedArtifactDirectory(path.parent) as anchor:
            opened = os.fstat(fd)
            named = os.stat(path.name, dir_fd=anchor.fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or not _same_identity(opened, named)
                or (
                    self.lock_identity is not None
                    and not _same_identity(self.lock_identity, opened)
                )
            ):
                raise DiagnosticError("held evaluation lock identity changed")
            digest, offset = hashlib.sha256(), 0
            while True:
                chunk = os.pread(fd, 65536, offset)
                if not chunk:
                    break
                digest.update(chunk)
                offset += len(chunk)
            if (
                digest.hexdigest() != self.contract.lock_sha256
                or not _same_identity(opened, os.fstat(fd))
                or not _same_identity(
                    opened, os.stat(path.name, dir_fd=anchor.fd, follow_symlinks=False)
                )
            ):
                raise DiagnosticError("held evaluation lock bytes changed")
            self.lock_identity = opened
            anchor.check()

    def fingerprint(self):
        return _get_trace().fingerprint_tree(self.contract.v4_root)

    def inputs(self):
        if self.authorization is None:
            raise DiagnosticError("owner has no bound inputs")
        if self.execution_guard is not None:
            self.execution_guard()
        self._check_namespace()
        records = list(self.records)
        records.append(_portable_record(self.archive))
        manifest, record = _read_v4_manifest(self.contract)
        records.append(_portable_record(record))
        frozen_pinned = self.freeze["v4"]["verified_pinned_files"]
        v4_pinned = _collect_pinned_records(manifest)
        if len(v4_pinned) != 24 or [_portable_record(r) for r in frozen_pinned] != [
            _portable_record(r) for r in v4_pinned
        ]:
            raise DiagnosticError("diagnostic freeze does not match all 24 v4 bindings")
        fixed = {
            str(
                self.contract.v4_root / "tools/locked_same_bank_eval.py"
            ): self.contract.evaluator_sha256,
            str(
                self.contract.v4_root / "tools/run_locked_same_bank_eval.sbatch"
            ): self.contract.runner_sha256,
        }
        by_path = {r["path"]: r for r in frozen_pinned}
        if any(
            path not in by_path or by_path[path]["sha256"] != sha
            for path, sha in fixed.items()
        ):
            raise DiagnosticError("fixed v4 bindings are missing or changed")
        records.append(_verify_v4_layout_lock(_get_trace(), manifest, self.contract))
        formal = [
            r
            for r in frozen_pinned
            if pathlib.Path(r["path"]).name == FORMAL40_BASENAME
        ]
        if not formal or any(
            r["sha256"] != self.contract.formal40_sha256 for r in formal
        ):
            raise DiagnosticError("formal40 binding differs")
        records.extend(_portable_record(r) for r in frozen_pinned)
        for key, root_key in (
            ("clips", "clips_dir"),
            ("snapshot_files", "snapshot_files"),
        ):
            records.extend(
                _portable_record(r, root=self.freeze["roots"][root_key])
                for r in self.freeze[key]
            )
        verified = [_check_bound_record(r) for r in records]
        _assert_no_science_markers(self.root)
        return {"records": verified}

    def matrix(self):
        manifest, _ = _read_v4_manifest(self.contract)
        historical = _worker_historical_hashes(
            {
                "manifest": manifest,
                "historical_scene_binding": _historical_scene_binding(manifest),
            }
        )
        # Snapshot loader records bind a relative path, not an invented absolute
        # `path` field. Keep the exact frozen schema for persisted worker binding.
        sources = self.freeze["snapshot_files"]
        launcher = _ColdChildLauncher(
            self.args.job_id,
            self.args.expected_input_freeze_sha256,
            os.environ.get("DIAG_SCRATCH_ROOT"),
        )
        result = _run_matrix_sequence(
            launcher,
            job_id=self.args.job_id,
            freeze_sha=self.args.expected_input_freeze_sha256,
            trials=self.freeze["trials"],
            source_records=sources,
            historical_scene_hashes=historical,
        )
        cells = result["summary"]["targeted_trace_cells"]
        if cells:
            self.publish(
                "TARGETED_TRACE_REQUIRED.json",
                _targeted_trace_document(result, self.args.job_id),
            )
        return result

    def publish(self, name, value):
        if not self.claimed:
            raise DiagnosticError("only the claimed owner may publish")
        self._check_namespace()
        terminal = name in ("DIAGNOSTIC_COMPLETE.json", "DIAGNOSTIC_FAILED.json")
        if not terminal and name not in (
            "PRECHECK.json",
            "POSTCHECK.json",
            "RUNNING.json",
            "ENVIRONMENT.json",
            "TARGETED_TRACE_REQUIRED.json",
        ):
            raise DiagnosticError("owner publication outside fixed namespace")
        parent = self.root / "state" if terminal else self.attempt
        with _PinnedArtifactDirectory(parent) as anchor:
            if terminal and any(
                os.path.lexists(parent / n)
                for n in ("DIAGNOSTIC_COMPLETE.json", "DIAGNOSTIC_FAILED.json")
            ):
                raise FileExistsError("a diagnostic terminal already exists")
            if terminal:
                # Bind even partial failure evidence. Incomplete/corrupt storage
                # may prevent publication; never manufacture an opposite marker.
                value["artifact_inventory"] = _terminal_inventory(self.attempt)
                if name == "DIAGNOSTIC_COMPLETE.json":
                    _verify_complete_attempt(value, self.freeze, self.contract)
                    if (
                        value["post"]["inputs"] != self.inputs()
                        or value["post"]["tree"] != self.fingerprint()
                        or value["artifact_inventory"]
                        != _terminal_inventory(self.attempt)
                    ):
                        raise DiagnosticError(
                            "evidence changed before completion publication"
                        )
                    self._check_namespace()
            atomic_create_bytes(parent / name, _owner_json_bytes(value))
            anchor.check()


def _terminal_inventory(attempt):
    """Portable, complete attempt listing; no following links or cache reliance."""
    try:
        return _read_terminal_inventory(attempt)
    except (OSError, _get_trace().TraceContractError) as error:
        raise DiagnosticError("attempt inventory cannot be verified") from error


def _read_terminal_inventory(attempt):
    attempt = pathlib.Path(attempt)
    with _PinnedArtifactDirectory(attempt) as anchor:
        first = _get_trace().fingerprint_tree(attempt)
        files, directories = [], []
        for row in first["entries"]:
            relative = row["relative_path"]
            if row["type"] == "directory" and row["mode"] == 0o700:
                directories.append({"relative_path": relative, "mode": row["mode"]})
            elif row["type"] == "file" and row["mode"] == 0o600:
                path = attempt / relative
                # Existing byte reader is bounded to individual artifacts by the
                # child budgets; stream hash here instead of loading tensor bytes.
                with _PinnedArtifactDirectory(path.parent) as directory:
                    observed = os.stat(
                        path.name, dir_fd=directory.fd, follow_symlinks=False
                    )
                    sha = _get_trace()._tree_file_sha256(
                        path.name, observed, dir_fd=directory.fd
                    )
                    directory.check()
                files.append(
                    {
                        "relative_path": relative,
                        "type": "file",
                        "mode": 0o600,
                        "size": row["size"],
                        "sha256": sha,
                    }
                )
            else:
                raise DiagnosticError(
                    "attempt inventory contains a link, special file or unexpected permissions"
                )
        if first != _get_trace().fingerprint_tree(attempt):
            raise DiagnosticError("attempt changed while inventory was read")
        anchor.check()
    result = {"schema_version": 1, "directories": directories, "files": files}
    return dict(result, sha256=hashlib.sha256(_owner_json_bytes(result)).hexdigest())


def _portable_tree_fingerprint(value):
    """Verify recorded metadata hash, then remove only cross-node dev/inode."""
    fields = (
        "relative_path",
        "type",
        "mode",
        "size",
        "st_mtime_ns",
        "st_dev",
        "st_ino",
        "symlink_target",
    )
    if (
        not isinstance(value, Mapping)
        or set(value) != {"entries", "entry_count", "tree_sha256", "content_sha256"}
        or not isinstance(value["entries"], list)
        or type(value["entry_count"]) is not int
        or len(value["entries"]) != value["entry_count"]
    ):
        raise DiagnosticError("terminal v4 tree fingerprint schema differs")
    _require_sha256(value["tree_sha256"])
    _require_sha256(value["content_sha256"])
    paths, payload, portable = [], bytearray(), []
    for row in value["entries"]:
        if not isinstance(row, Mapping) or set(row) != set(fields):
            raise DiagnosticError("terminal v4 tree entry schema differs")
        relative = row["relative_path"]
        if (
            type(relative) is not str
            or not relative
            or relative.startswith("/")
            or any(p in ("", ".", "..") for p in relative.split("/"))
            or row["type"] not in ("file", "directory", "symlink", "other")
            or type(row["symlink_target"]) is not str
            or any(type(row[k]) is not int or row[k] < 0 for k in fields[2:7])
        ):
            raise DiagnosticError("terminal v4 tree entry is invalid")
        paths.append(relative)
        for key in fields:
            encoded = str(row[key]).encode("utf-8")
            payload.extend(len(encoded).to_bytes(8, "big") + encoded)
        portable.append({k: row[k] for k in fields if k not in ("st_dev", "st_ino")})
    if (
        paths != sorted(set(paths), key=lambda p: p.encode("utf-8"))
        or hashlib.sha256(payload).hexdigest() != value["tree_sha256"]
    ):
        raise DiagnosticError("terminal v4 tree hash or ordering differs")
    return {"entries": portable, "content_sha256": value["content_sha256"]}


def _targeted_trace_document(matrix, job_id):
    summary = matrix["summary"]
    cells = summary["targeted_trace_cells"]
    if not cells:
        return None
    return {
        "schema_version": 1,
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "evaluation_role": EVALUATION_ROLE,
        "status": "TARGETED_TRACE_REQUIRED",
        "job_id": job_id,
        "cells": cells,
        "scope": "formal40 model forward; separate reviewed follow-up required",
        "first_subgraph": "formal40 model forward (cochleagram inputs to native logits)",
        "worst_trials": {
            cell: summary["cells"][cell]["worst_cases"]["native_logits"]
            for cell in cells
        },
        "matrix_summary_record": matrix["summary_record"],
    }


def _verify_complete_attempt(report, freeze, contract):
    """Recompute from saved lossless evidence, never from the terminal's verdict."""
    job, sha = report["job_id"], report["input_freeze_sha256"]
    attempt = DIAGNOSTIC_ROOT / "attempts" / f"slurm-{job}"
    if (
        report["lock_acquired"] is not True
        or report["primary_error"] is not None
        or report["post_errors"] != []
        or report["pre"] != report["post"]
        or any(report["pre"].get(k) is None for k in ("tree", "inputs"))
    ):
        raise DiagnosticError(
            "complete terminal has failed or missing PRE/POST conditions"
        )
    for side, name in (("pre", "PRECHECK.json"), ("post", "POSTCHECK.json")):
        saved, _ = _owner_read_json(attempt / name, root=attempt)
        if saved != report[side]:
            raise DiagnosticError("terminal PRE/POST differs from saved owner check")
    running, _ = _owner_read_json(attempt / "RUNNING.json", root=attempt)
    if running != {
        "schema_version": 1,
        "status": "RUNNING",
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "evaluation_role": EVALUATION_ROLE,
        "job_id": job,
        "input_freeze_sha256": sha,
    }:
        raise DiagnosticError("owner running identity differs")
    environment, _ = _owner_read_json(attempt / "ENVIRONMENT.json", root=attempt)
    if (
        set(environment)
        != {"schema_version", "job_id", "coordinator_pid", "python", "environment"}
        or environment["schema_version"] != 1
        or environment["job_id"] != job
        or type(environment["coordinator_pid"]) is not int
        or environment["coordinator_pid"] <= 1
        or not isinstance(environment["python"], str)
        or not isinstance(environment["environment"], dict)
    ):
        raise DiagnosticError("owner environment schema differs")
    matrix = report["matrix"]
    if (
        not isinstance(matrix, Mapping)
        or set(matrix) != {"status", "summary", "summary_record", "launch_records"}
        or matrix["status"] != "MATRIX_EVIDENCE_VERIFIED"
        or not isinstance(matrix["summary_record"], Mapping)
        or matrix["summary_record"].get("relative_path") != "MATRIX_SUMMARY.json"
    ):
        raise DiagnosticError("terminal matrix binding is incomplete")
    manifest, _ = _read_v4_manifest(contract)
    history = _worker_historical_hashes(
        {
            "manifest": manifest,
            "historical_scene_binding": _historical_scene_binding(manifest),
        }
    )
    recomputed = _reverify_matrix_sequence(
        matrix["launch_records"],
        job_id=job,
        freeze_sha=sha,
        trials=freeze["trials"],
        source_records=freeze["snapshot_files"],
        historical_scene_hashes=history,
    )
    with _MatrixArtifactStore(attempt) as store:
        saved = _artifact_json(store, store.verify_record(matrix["summary_record"]))
        parent_env = environment["environment"]
        if (
            set(parent_env)
            != {"SLURM_JOB_ID", "CUDA_VISIBLE_DEVICES", "DIAG_SCRATCH_ROOT"}
            or parent_env["SLURM_JOB_ID"] != job
            or not environment["python"]
        ):
            raise DiagnosticError("coordinator environment binding is incomplete")
        for record in matrix["launch_records"].values():
            launch = _artifact_json(store, store.verify_record(record))
            if environment["coordinator_pid"] == launch["pid"] or any(
                launch["environment"].get(k) != v for k, v in parent_env.items()
            ):
                raise DiagnosticError(
                    "owner and child process/environment bindings differ"
                )
    if saved != recomputed or matrix["summary"] != recomputed:
        raise DiagnosticError(
            "terminal matrix summary differs from persisted evidence recomputation"
        )
    targeted = _targeted_trace_document(matrix, job)
    target = attempt / "TARGETED_TRACE_REQUIRED.json"
    if targeted is None:
        if os.path.lexists(target):
            raise DiagnosticError("unexpected targeted trace recommendation")
    elif _owner_read_json(target, root=attempt)[0] != targeted:
        raise DiagnosticError(
            "targeted trace selection differs from verified worst trials"
        )
    allowed = {
        "ENVIRONMENT.json",
        "PRECHECK.json",
        "POSTCHECK.json",
        "RUNNING.json",
        "MATRIX_SUMMARY.json",
        "REFERENCE_EQUIVALENCE.json",
        "reference_cold",
        "cells",
    }
    allowed.update(f"CHILD_EXIT_{r}.json" for r in _MATRIX_ROLES)
    if targeted is not None:
        allowed.add(target.name)
    if set(os.listdir(attempt)) != allowed or set(os.listdir(attempt / "cells")) != set(
        CELL_SPECS
    ):
        raise DiagnosticError(
            "complete attempt contains unexpected or missing owner/cell entries"
        )
    return recomputed


def verify_results(expected_input_freeze_sha256, job_id):
    """Read-only verification. No Slurm query, waiting, repair or retry authority.

    Missing terminals do not tell us whether Slurm is running or ended. Failure
    verification authenticates the failure record/inventory, not numeric results.
    Full success additionally rehashes live frozen inputs and recomputes all cells.
    """
    _child_identity("_child-reference", job_id, None)
    _require_sha256(expected_input_freeze_sha256)
    root = DIAGNOSTIC_ROOT
    _validate_layout(root, require_freeze=True)
    _assert_no_science_markers(root)
    names = [
        name
        for name in ("DIAGNOSTIC_COMPLETE.json", "DIAGNOSTIC_FAILED.json")
        if os.path.lexists(root / "state" / name)
    ]
    if len(names) > 1:
        raise DiagnosticError("conflicting diagnostic terminal markers")
    freeze, _ = _owner_read_json(
        root / "input_freeze.json", root=root, expected_sha=expected_input_freeze_sha256
    )
    _validate_freeze_value(
        freeze, production_contract(), status="INPUTS_FROZEN", diagnostic_root=root
    )
    base = {
        "schema_version": 1,
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "evaluation_role": EVALUATION_ROLE,
        "job_id": job_id,
        "input_freeze_sha256": expected_input_freeze_sha256,
        "results_verified": False,
    }
    if not names:
        return dict(
            base,
            status="INCOMPLETE_NO_TERMINAL",
            scheduler_state="NOT_QUERIED",
            retry_allowed=False,
        )
    report, terminal_record = _owner_read_json(root / "state" / names[0], root=root)
    required = {
        "schema_version",
        "diagnostic_protocol",
        "evaluation_role",
        "job_id",
        "input_freeze_sha256",
        "authorization",
        "lock_acquired",
        "primary_error",
        "post_errors",
        "matrix",
        "pre",
        "post",
        "status",
        "artifact_inventory",
    }
    if (
        set(report) != required
        or report["status"] + ".json" != names[0]
        or any(
            report[k] != base[k]
            for k in (
                "schema_version",
                "diagnostic_protocol",
                "evaluation_role",
                "job_id",
                "input_freeze_sha256",
            )
        )
        or type(report["lock_acquired"]) is not bool
        or not isinstance(report["authorization"], Mapping)
        or not isinstance(report["post_errors"], list)
        or any(
            not isinstance(report[side], Mapping)
            or set(report[side]) != {"tree", "inputs"}
            for side in ("pre", "post")
        )
    ):
        raise DiagnosticError("terminal envelope differs from fixed result identity")
    args = types.SimpleNamespace(
        job_id=job_id,
        expected_input_freeze_sha256=expected_input_freeze_sha256,
        intent_nonce=report["authorization"].get("intent_nonce"),
    )
    owner = _CoordinatorOwner(args)
    authorization = owner.authorize(verification_only=True)
    if authorization != report["authorization"]:
        raise DiagnosticError("terminal authorization differs from journal")
    if set(os.listdir(root / "attempts")) != {f"slurm-{job_id}"} or set(
        os.listdir(root / "submitted_runners")
    ) != {f"{job_id}.sbatch"}:
        raise DiagnosticError("result root contains another attempt or archive")
    before = _terminal_inventory(owner.attempt)
    if report["artifact_inventory"] != before:
        raise DiagnosticError("terminal artifact inventory differs")
    if report["status"] == "DIAGNOSTIC_FAILED":
        if not report["primary_error"] and not report["post_errors"]:
            raise DiagnosticError("failure marker lacks an error")
        result = dict(
            base,
            status="DIAGNOSTIC_FAILURE_RECORDED",
            primary_error=report["primary_error"],
            post_errors=report["post_errors"],
            numeric_results_interpretable=False,
        )
    else:
        with owner.lock() as fd:
            owner.verify_lock(fd)
            inputs = owner.inputs()
            tree = owner.fingerprint()
            if (
                report["pre"] != report["post"]
                or report["post"]["inputs"] != inputs
                or _portable_tree_fingerprint(report["post"]["tree"])
                != _portable_tree_fingerprint(tree)
            ):
                raise DiagnosticError(
                    "recorded or current frozen PRE/POST inputs differ"
                )
            summary = _verify_complete_attempt(report, freeze, owner.contract)
            if owner.inputs() != inputs or owner.fingerprint() != tree:
                raise DiagnosticError(
                    "frozen inputs changed during result verification"
                )
            owner.verify_lock(fd)
        result = dict(
            base,
            status="DIAGNOSTIC_RESULTS_VERIFIED",
            results_verified=True,
            matrix=summary,
            filesystem_identity_policy="cross_invocation_path_size_sha_exact__dev_inode_diagnostic",
        )
    if before != _terminal_inventory(owner.attempt):
        raise DiagnosticError("attempt changed during verification")
    _check_bound_record(terminal_record)
    _assert_no_science_markers(root)
    if [
        n
        for n in ("DIAGNOSTIC_COMPLETE.json", "DIAGNOSTIC_FAILED.json")
        if os.path.lexists(root / "state" / n)
    ] != names:
        raise DiagnosticError("terminal set changed during verification")
    return dict(
        result,
        terminal_record=_portable_record(terminal_record),
        artifact_inventory_sha256=before["sha256"],
    )


_COORDINATOR_WRITE_PATHS = types.MappingProxyType(
    {
        "HOME": "coordinator-home",
        "XDG_CACHE_HOME": "coordinator-cache",
        "TORCH_HOME": "coordinator-torch",
        "TMPDIR": "coordinator-tmp",
        "TMP": "coordinator-tmp",
        "TEMP": "coordinator-tmp",
        "MPLCONFIGDIR": "coordinator-mpl",
        "NUMBA_CACHE_DIR": "coordinator-numba",
        "TORCHINDUCTOR_CACHE_DIR": "coordinator-torchinductor",
        "TRITON_CACHE_DIR": "coordinator-triton",
        "CUDA_CACHE_PATH": "coordinator-cuda",
    }
)


def coordinator_command(args):
    _child_identity("_child-reference", args.job_id, None)
    _require_sha256(args.expected_input_freeze_sha256)
    nonce = args.intent_nonce
    if (
        type(nonce) is not str
        or len(nonce) != 32
        or any(c not in "0123456789abcdef" for c in nonce)
    ):
        raise DiagnosticError("coordinator intent nonce is invalid")
    raw = args.spool_runner
    if (
        type(raw) is not str
        or not raw
        or any(ord(c) < 32 for c in raw)
        or not pathlib.Path(raw).is_absolute()
        or str(pathlib.Path(raw)) != raw
        or ".." in pathlib.Path(raw).parts
    ):
        raise DiagnosticError("coordinator spool path must be canonical absolute")
    return [
        str(PRODUCTION_PYTHON),
        "-I",
        "-B",
        str(DIAGNOSTIC_ROOT / "tools/diagnose_batch_invariance.py"),
        "run-coordinator",
        "--job-id",
        args.job_id,
        "--intent-nonce",
        nonce,
        "--expected-input-freeze-sha256",
        args.expected_input_freeze_sha256,
        "--spool-runner",
        raw,
    ]


def coordinator_environment(job_id, scratch_root, scheduler_environment):
    env = child_environment(
        "_child-reference", job_id, None, scratch_root, scheduler_environment
    )
    root = _child_scratch_path(scratch_root, job_id)
    env.update({k: str(root / v) for k, v in _COORDINATOR_WRITE_PATHS.items()})
    return env


def _check_clean_execution_environment(expected):
    actual = dict(os.environ)
    # CPython's locale coercion may add this during an env-i Linux startup.
    if actual.get("LC_CTYPE") in ("C.UTF-8", "C.utf8"):
        actual.pop("LC_CTYPE")
    if actual != expected:
        raise DiagnosticError("execution environment differs from fixed allowlist")


@contextlib.contextmanager
def _coordinator_scratch(args):
    job = _worker_job_id(args)
    root = _child_scratch_path(os.environ.get("DIAG_SCRATCH_ROOT"), job)
    expected = coordinator_environment(job, str(root), os.environ)
    _check_clean_execution_environment(expected)
    with contextlib.ExitStack() as stack:
        anchors = [stack.enter_context(_PinnedArtifactDirectory(root))]
        _require_local_scratch_mount(root)
        if set(os.listdir(anchors[0].fd)) != set(_COORDINATOR_WRITE_PATHS.values()):
            raise DiagnosticError(
                "coordinator scratch has unexpected or previously used subtrees"
            )
        for name in sorted(set(_COORDINATOR_WRITE_PATHS.values())):
            anchor = stack.enter_context(_PinnedArtifactDirectory(root / name))
            if os.listdir(anchor.fd):
                raise DiagnosticError("coordinator cache is not initially empty")
            anchors.append(anchor)

        def check():
            _check_clean_execution_environment(expected)
            for anchor in anchors:
                anchor.check()
                info = os.fstat(anchor.fd)
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise DiagnosticError("coordinator scratch ownership/mode changed")

        check()
        previous = tempfile.tempdir
        tempfile.tempdir = expected["TMPDIR"]
        try:
            yield check
        finally:
            tempfile.tempdir = previous
            check()


def run_coordinator(args):
    """Production owner entry; the runner must first create reviewed local scratch."""
    _worker_job_id(args)
    if sys.argv != coordinator_command(args)[3:]:
        raise DiagnosticError(
            "actual coordinator invocation differs from canonical runner argv"
        )
    _claim_worker_process()  # same cold/isolated/single-use gate, before imports
    with _coordinator_scratch(args) as check, contextlib.redirect_stdout(sys.stderr):
        owner = _CoordinatorOwner(args)
        owner.execution_guard = check
        result = _coordinate(args, owner)
        check()
        return result


def _read_proc_parent_identity(proc_root, pid):
    """Bounded Linux proc observation; private fixture seam, never a CLI override."""
    if type(pid) is not int or pid <= 1:
        raise DiagnosticError("parent PID is invalid")
    path = pathlib.Path(proc_root) / str(pid)
    with _PinnedArtifactDirectory(path) as anchor:
        info = os.fstat(anchor.fd)

        def read(name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=anchor.fd)
            try:
                raw = os.read(fd, 65537)
                if not raw or len(raw) > 65536:
                    raise DiagnosticError("invalid parent proc record length")
                return raw
            finally:
                os.close(fd)

        first = read("stat")
        cmd = read("cmdline")
        executable = os.readlink("exe", dir_fd=anchor.fd)
        if first != read("stat"):
            # CPU time/state fields can change normally: compare start identity below.
            second = read("stat")
        else:
            second = first

        def started(raw):
            try:
                head, rest = raw.rsplit(b") ", 1)
                if int(head.split(b" (", 1)[0]) != pid:
                    raise ValueError("pid")
                fields = rest.split()
                start = fields[19].decode("ascii")
                if not start.isdecimal():
                    raise ValueError("start time")
                return start
            except (ValueError, IndexError, UnicodeError) as error:
                raise DiagnosticError("invalid parent proc start identity") from error

        if started(first) != started(second):
            raise DiagnosticError("parent PID was reused during authentication")
        try:
            if not cmd.endswith(b"\0"):
                raise ValueError("cmdline terminator")
            argv = [p.decode("utf-8") for p in cmd[:-1].split(b"\0")]
        except (ValueError, UnicodeError) as error:
            raise DiagnosticError("invalid parent proc argv") from error
        anchor.check()
        return {
            "pid": pid,
            "uid": info.st_uid,
            "start_time": started(first),
            "executable": executable,
            "argv": argv,
        }


def _read_parent_process(pid):
    if not sys.platform.startswith("linux"):
        raise DiagnosticError(
            "production child parent authentication requires Linux proc"
        )
    try:
        return _read_proc_parent_identity(pathlib.Path("/proc"), pid)
    except OSError as error:
        raise DiagnosticError("live coordinator parent is unavailable") from error


def _authorize_child_parent(args, cell):
    """Read-only stdlib gate before child scratch creation or numerical imports.

    This binds the live OS parent to owner files and the submission contract.
    It is an integrity check within one trusted Unix account, not a sandbox
    against a malicious process with the same UID and write access to all inputs.
    """
    job = _worker_job_id(args)
    mode = "_child-reference" if cell is None else "_child-cell"
    expected = child_environment(
        mode, job, cell, os.environ.get("DIAG_SCRATCH_ROOT"), os.environ
    )
    _check_clean_execution_environment(expected)
    root = DIAGNOSTIC_ROOT
    if any(
        os.path.lexists(root / "state" / name)
        for name in ("DIAGNOSTIC_COMPLETE.json", "DIAGNOSTIC_FAILED.json")
    ):
        raise DiagnosticError("child cannot execute after a terminal marker")
    parent_pid = os.getppid()
    proc = _read_parent_process(parent_pid)
    if (
        proc["pid"] != parent_pid
        or proc["uid"] != os.getuid()
        or proc["executable"] != str(PRODUCTION_PYTHON.resolve())
        or not isinstance(proc["argv"], list)
        or len(proc["argv"]) != 13
    ):
        raise DiagnosticError("child OS parent is not the reviewed coordinator")
    intent, _ = _owner_read_json(root / "state/INTENT.json", root=root)
    parent_args = types.SimpleNamespace(
        job_id=job,
        expected_input_freeze_sha256=args.expected_input_freeze_sha256,
        intent_nonce=intent.get("intent_nonce"),
        spool_runner=proc["argv"][-1],
    )
    if proc["argv"] != coordinator_command(parent_args):
        raise DiagnosticError("parent argv differs from fixed coordinator command")
    owner = _CoordinatorOwner(parent_args)
    owner.authorize(verification_only=True)  # archive, not another claim or flock
    attempt = root / "attempts" / f"slurm-{job}"
    environment, env_record = _owner_read_json(
        attempt / "ENVIRONMENT.json", root=attempt
    )
    running, run_record = _owner_read_json(attempt / "RUNNING.json", root=attempt)
    if (
        environment.get("coordinator_pid") != parent_pid
        or environment.get("job_id") != job
        or environment.get("environment")
        != {
            k: expected[k]
            for k in ("SLURM_JOB_ID", "CUDA_VISIBLE_DEVICES", "DIAG_SCRATCH_ROOT")
        }
    ):
        raise DiagnosticError("live parent differs from recorded owner environment")
    if running != {
        "schema_version": 1,
        "status": "RUNNING",
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "evaluation_role": EVALUATION_ROLE,
        "job_id": job,
        "input_freeze_sha256": args.expected_input_freeze_sha256,
    }:
        raise DiagnosticError("child parent RUNNING identity differs")
    if os.getppid() != parent_pid or _read_parent_process(parent_pid) != proc:
        raise DiagnosticError("child parent changed during authentication")
    _check_bound_record(env_record)
    _check_bound_record(run_record)


def _dispatch_child(args, cell):
    _require_cold_worker_interpreter()
    _authorize_child_parent(args, cell)
    with contextlib.redirect_stdout(sys.stderr):
        result = (
            run_reference_cold(args)
            if cell is None
            else run_cell(CELL_SPECS[cell], args)
        )
    return _child_completion_document(
        result, args, "_child-reference" if cell is None else "_child-cell", cell
    )


def _freeze_document(audit: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the sole permitted audit-to-freeze transformation."""
    value = json.loads(_get_trace().canonical_json_bytes(audit))
    value["status"] = "INPUTS_FROZEN"
    return value


def _load_current_audit(
    contract: FrozenContract,
    root: pathlib.Path,
    loader: Callable[..., Mapping[str, Any]] | None,
) -> dict[str, Any]:
    if loader is None:
        return audit_inputs(contract=contract, diagnostic_root=root)
    return dict(loader(contract=contract, diagnostic_root=root))


def _freeze_inputs(
    *,
    confirm_protocol: str,
    diagnostic_root: pathlib.Path,
    contract: FrozenContract,
    audit_loader: Callable[..., Mapping[str, Any]] | None,
) -> dict[str, Any]:
    if confirm_protocol != DIAGNOSTIC_PROTOCOL:
        raise DiagnosticError("diagnostic protocol confirmation mismatch")
    root = pathlib.Path(diagnostic_root)
    if os.path.lexists(root / "input_freeze.json"):
        raise FileExistsError(f"refusing existing target: {root / 'input_freeze.json'}")
    _validate_layout(root, require_freeze=False)
    audit = _load_current_audit(contract, root, audit_loader)
    _validate_freeze_value(audit, contract, status="AUDIT_PASS", diagnostic_root=root)
    trace = _get_trace()
    for record in audit["production_files"]:
        try:
            trace.verify_file_record(record, allowed_root=root / "tools")
        except Exception as error:
            raise DiagnosticError("audit production file record changed") from error
    for root_key, records in (
        ("clips_dir", audit["clips"]),
        ("snapshot_files", audit["snapshot_files"]),
    ):
        for record in records:
            identity = {
                key: record[key]
                for key in (
                    "relative_path",
                    "mode",
                    "size",
                    "st_mtime_ns",
                    "st_dev",
                    "st_ino",
                    "sha256",
                )
            }
            try:
                trace.verify_file_record(
                    identity, allowed_root=pathlib.Path(audit["roots"][root_key])
                )
            except Exception as error:
                raise DiagnosticError(f"audit {root_key} record changed") from error
    frozen = _freeze_document(audit)
    atomic_create_json(root / "input_freeze.json", frozen)
    return frozen


def freeze_inputs(*, confirm_protocol: str) -> dict[str, Any]:
    return _freeze_inputs(
        confirm_protocol=confirm_protocol,
        diagnostic_root=DIAGNOSTIC_ROOT,
        contract=production_contract(),
        audit_loader=None,
    )


def _check_only(
    *,
    expected_input_freeze_sha256: str,
    diagnostic_root: pathlib.Path,
    contract: FrozenContract,
    audit_loader: Callable[..., Mapping[str, Any]] | None,
) -> dict[str, Any]:
    if (
        not isinstance(expected_input_freeze_sha256, str)
        or len(expected_input_freeze_sha256) != 64
    ):
        raise DiagnosticError("expected input freeze SHA-256 is invalid")
    root = pathlib.Path(diagnostic_root)
    layout = _validate_layout(root, require_freeze=True)
    trace = _get_trace()
    payload, freeze_record = trace.read_stable_bytes(
        root / "input_freeze.json", allowed_root=root
    )
    if freeze_record["sha256"] != expected_input_freeze_sha256:
        raise DiagnosticError("input freeze SHA-256 mismatch")
    value = json.loads(payload)
    _validate_freeze_value(
        value, contract, status="INPUTS_FROZEN", diagnostic_root=root
    )
    if trace.canonical_json_bytes(value) != payload:
        raise DiagnosticError("input freeze is not canonical JSON")
    for record in value["production_files"]:
        try:
            trace.verify_file_record(record, allowed_root=root / "tools")
        except Exception as error:
            raise DiagnosticError("frozen production file changed") from error
    roots = value.get("roots")
    if isinstance(roots, Mapping):
        for key, collection in (
            ("clips_dir", value.get("clips", [])),
            ("snapshot_files", value.get("snapshot_files", [])),
        ):
            if key not in roots:
                continue
            allowed_root = pathlib.Path(str(roots[key]))
            for record in collection:
                identity = {
                    name: record[name]
                    for name in (
                        "relative_path",
                        "mode",
                        "size",
                        "st_mtime_ns",
                        "st_dev",
                        "st_ino",
                        "sha256",
                    )
                }
                try:
                    trace.verify_file_record(identity, allowed_root=allowed_root)
                except Exception as error:
                    raise DiagnosticError(f"frozen {key} input changed") from error
    frozen_contract = value.get("v4_contract")
    if frozen_contract is not None and frozen_contract != _contract_json(contract):
        raise DiagnosticError("input freeze v4 contract differs from compiled contract")
    current_audit = _load_current_audit(contract, root, audit_loader)
    _validate_freeze_value(
        current_audit, contract, status="AUDIT_PASS", diagnostic_root=root
    )
    if value != _freeze_document(current_audit):
        raise DiagnosticError("input freeze differs from reconstructed live audit")
    return {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "status": "CHECK_PASS",
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "input_freeze_sha256": freeze_record["sha256"],
        "layout": layout,
    }


def check_only(*, expected_input_freeze_sha256: str) -> dict[str, Any]:
    return _check_only(
        expected_input_freeze_sha256=expected_input_freeze_sha256,
        diagnostic_root=DIAGNOSTIC_ROOT,
        contract=production_contract(),
        audit_loader=None,
    )


def _emit(value: Mapping[str, Any]) -> None:
    sys.stdout.buffer.write(_owner_json_bytes(value))


def _bounded_exception_diagnostic(error):
    """Supplemental failure metadata, never raw args/messages/locals/source/env.

    Base descriptors avoid user-defined exception attribute/str hooks. Only fixed
    reason labels are emitted from bounded exact-string args. At most six linked
    errors and six frame locations each; traceback walking also has a hard cap.
    This is troubleshooting evidence, not a scientific result or acceptance gate.
    """

    def label(value):
        if type(value) is not str:
            return "unknown"
        return "".join(
            c if c.isascii() and (c.isalnum() or c in "._<>") else "_"
            for c in value[:96]
        )

    def direct_field(value, field):
        namespace = BaseException.__dict__["__dict__"].__get__(value)
        # No arbitrary attribute hooks or hash lookups against hostile keys.
        for index, (key, item) in enumerate(dict.items(namespace)):
            if index >= 64:
                break
            if type(key) is str and key == field:
                return item
        return None

    chain, seen = [], set()
    pending = [(error, "outer")]
    repeated = False
    while pending and len(chain) < 6:
        error, relation = pending.pop()
        if id(error) in seen:
            repeated = True
            continue
        seen.add(id(error))
        error_type = type(error)
        args = BaseException.args.__get__(error)
        reasons = set()
        for arg in args[:4]:
            if type(arg) is not str:
                continue
            bounded = arg[:4096]
            for needle, code in (
                ("CUBLAS_WORKSPACE_CONFIG", "CUBLAS_WORKSPACE_CONFIG"),
                ("CUDA out of memory", "CUDA_OUT_OF_MEMORY"),
                ("CUBLAS_STATUS", "CUBLAS_STATUS"),
                ("illegal memory access", "CUDA_ILLEGAL_MEMORY_ACCESS"),
                ("deterministic", "DETERMINISM_MENTIONED"),
                ("execution fingerprint", "EXECUTION_FINGERPRINT_MENTIONED"),
                ("sealed frozen module bindings", "FROZEN_MODULE_BINDING_MENTIONED"),
                ("libcuda.so", "LIBCUDA_MENTIONED"),
                ("ptxas", "PTXAS_MENTIONED"),
                ("gcc", "GCC_MENTIONED"),
                ("g++", "GXX_MENTIONED"),
                ("No such file or directory", "MISSING_PATH_MENTIONED"),
                ("Permission denied", "PERMISSION_DENIED_MENTIONED"),
                ("terminated abruptly", "PROCESS_TERMINATED_MENTIONED"),
                ("pickle", "PICKLING_MENTIONED"),
                ("ModuleNotFoundError", "MODULE_NOT_FOUND_MENTIONED"),
                ("ImportError", "IMPORT_ERROR_MENTIONED"),
                ("undefined symbol", "UNDEFINED_SYMBOL_MENTIONED"),
                ("out of resource", "RESOURCE_LIMIT_MENTIONED"),
            ):
                if needle in bounded:
                    reasons.add(code)
        tb = BaseException.__traceback__.__get__(error)
        frames, walked = [], 0
        while tb is not None and walked < 128:
            code = tb.tb_frame.f_code
            frames.append(
                {
                    "file": label(code.co_filename.rsplit("/", 1)[-1]),
                    "function": label(code.co_name),
                    "line": tb.tb_lineno,
                }
            )
            frames = frames[-6:]
            walked += 1
            tb = tb.tb_next
        record = {
            "type": label(type.__getattribute__(error_type, "__name__")),
            "module": label(type.__getattribute__(error_type, "__module__")),
            "relation": relation,
            "reason_codes": sorted(reasons),
            "frames": frames,
            "frames_truncated": walked > 6 or tb is not None,
        }
        if error_type is DiagnosticError:
            delta = direct_field(error, "_binding_delta")
            if type(delta) is tuple and len(delta) == 3:
                items = {}
                for expected, item in zip(("added", "removed", "replaced"), delta):
                    if (
                        type(item) is not tuple
                        or len(item) != 3
                        or type(item[0]) is not str
                        or item[0] != expected
                        or type(item[1]) is not int
                        or item[1] < 0
                        or type(item[2]) is not tuple
                        or len(item[2]) > 3
                        or any(type(name) is not str for name in item[2])
                    ):
                        break
                    items[expected] = {
                        "count": item[1],
                        "names": [label(name[:64]) for name in item[2]],
                    }
                if len(items) == 3:
                    record["binding_delta"] = items
        chain.append(record)
        cause = BaseException.__cause__.__get__(error)
        if cause is not None:
            pending.append((cause, "cause"))
        elif not BaseException.__suppress_context__.__get__(error):
            context = BaseException.__context__.__get__(error)
            if context is not None:
                pending.append((context, "context"))
        if (
            type.__getattribute__(error_type, "__module__") == "torch._dynamo.exc"
            and type.__getattribute__(error_type, "__name__") == "BackendCompilerFailed"
        ):
            inner = direct_field(error, "inner_exception")
            if BaseException in type.__getattribute__(type(inner), "__mro__"):
                # PyTorch keeps this edge outside the ordinary cause/context.
                # Keep any distinct ordinary edge too, within the same cap.
                if not pending or pending[-1][0] is not inner:
                    pending.append((inner, "inner_exception"))
    result = {
        "schema_version": 1,
        "chain": chain,
        "chain_truncated": bool(pending) or repeated,
    }
    # Reserve headroom for pretty/default JSON writers and the stderr prefix.
    # Prefer retaining deep cause locations over outer wrapper frames.
    while len(json.dumps(result, ensure_ascii=True, separators=(",", ":"))) > 12288:
        for record in chain:
            if record["frames"]:
                record["frames"].pop(0)
                record["frames_truncated"] = True
                break
        else:
            # Current typed/count/name caps fit without frames. Remain bounded
            # if future supplemental fields grow, without changing exit status.
            chain.pop(0)
            result["chain_truncated"] = True
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("audit-inputs")
    freeze_parser = subparsers.add_parser("freeze-inputs")
    freeze_parser.add_argument("--confirm-protocol", required=True)
    check_parser = subparsers.add_parser("check-only")
    check_parser.add_argument("--expected-input-freeze-sha256", required=True)
    verify_parser = subparsers.add_parser("verify-results")
    verify_parser.add_argument("--expected-input-freeze-sha256", required=True)
    verify_parser.add_argument("--job-id", required=True)
    for command in ("run-coordinator", "_child-reference", "_child-cell"):
        entry = subparsers.add_parser(command)
        entry.add_argument("--job-id", required=True)
        entry.add_argument("--expected-input-freeze-sha256", required=True)
        if command == "run-coordinator":
            entry.add_argument("--intent-nonce", required=True)
            entry.add_argument("--spool-runner", required=True)
        if command == "_child-cell":
            entry.add_argument("--cell", choices=tuple(CELL_SPECS), required=True)
    subparsers.add_parser("_self-test-isolated-loader")
    args = parser.parse_args(argv)
    try:
        if args.command == "_self-test-isolated-loader":
            trace = _get_trace()
            _emit(
                {
                    "status": "ISOLATED_IMPORT_PASS",
                    "package_root_on_sys_path": str(PACKAGE_ROOT) in sys.path,
                    "numeric_trace_sha256": NUMERIC_TRACE_SHA256,
                    "canonical_json_available": callable(trace.canonical_json_bytes),
                }
            )
        elif args.command == "audit-inputs":
            _emit(audit_inputs())
        elif args.command == "freeze-inputs":
            _emit(freeze_inputs(confirm_protocol=args.confirm_protocol))
        elif args.command == "verify-results":
            result = verify_results(args.expected_input_freeze_sha256, args.job_id)
            _emit(result)
            return 0 if result["status"] == "DIAGNOSTIC_RESULTS_VERIFIED" else 2
        elif args.command == "run-coordinator":
            result = run_coordinator(args)
            _emit(result)
            return 0 if result["status"] == "DIAGNOSTIC_COMPLETE" else 2
        elif args.command in ("_child-reference", "_child-cell"):
            _emit(_dispatch_child(args, getattr(args, "cell", None)))
        else:
            _emit(
                check_only(
                    expected_input_freeze_sha256=args.expected_input_freeze_sha256
                )
            )
        return 0
    except Exception as error:
        print(f"diagnostic error: {error}", file=sys.stderr)
        try:
            print(
                "DIAGNOSTIC_EXCEPTION_CHAIN="
                + json.dumps(
                    _bounded_exception_diagnostic(error),
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
                flush=True,
            )
        except Exception:
            # Troubleshooting must not replace the original failure/exit contract.
            print("DIAGNOSTIC_EXCEPTION_CHAIN_UNAVAILABLE", file=sys.stderr, flush=True)
        _emit(
            {
                "status": "ERROR",
                "error_type": type(error).__name__,
                "message": str(error),
            }
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

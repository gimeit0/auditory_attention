"""New execution identity, historical DATA oracle, and independently checked relation.

No freeze writer, authorization writer, network access, or numeric import.
The historical manifest can never serve as the execution manifest.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

import job_contract as contract

HERE = Path(__file__).resolve().parent
RELATION_PATH = HERE.parent / 'guard_scan_integration_20260915/freeze_relation.py'
RELATION_SHA = '58e2242e96a5f23feedc24b4507ed09831b66abb691e331aefa21f3f74ef8e0a'
PARENT_SHA = '95e25bde17fa8358cd20f90c2edf27a94a4ffd6f49aab8bd9fa3395b6c7c7b34'
REPLAY_PATH = HERE.parent / 'targeted_replay_20260912/parent_replay.py'
REPLAY_SHA = '6d5f784fcabd4a45e4d8ea997b230f1c5c5a22dbdde4affef359e01538e265ae'


def checked_module(path, expected, name):
    raw = contract.pinned_read(path, expected)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
    return module


relation = checked_module(RELATION_PATH, RELATION_SHA, 'v19_input_relation')


def load(input_sha):
    """Read the actual fixed v19 freeze, never invent a release hash."""
    raw = contract.pinned_read(contract.V19 / 'input_freeze.json', input_sha, limit=1024**2)
    proof = relation.verify(raw, input_sha)
    value = relation.decode(raw, input_sha)
    contract.require(proof['parent_freeze_sha256'] == contract.PARENT_FREEZE_SHA
                     and proof['candidate_protocol'] == contract.PROTOCOL,
                     'execution/data identity relation differs')
    # The physical execution path is separate from the package's checked copy.
    contract.pinned_read(contract.V19 / 'tools/diagnose_batch_invariance.py', contract.V19_SHA)
    return value, {**proof, 'diagnostic_sha256': contract.V19_SHA,
                   'scope': 'source_and_scientific_input_relation_only_not_live_worker_audit'}


def verify_audits(pre_raw, post_raw, freeze, diag):
    """Two matching but wrong audits must not pass; bind BOTH to this freeze."""
    contract.require(type(pre_raw) is bytes and pre_raw == post_raw, 'input audit bytes changed')
    value = json.loads(pre_raw)
    contract.require(value.get('status') == 'AUDIT_PASS', 'successful worker audit required')
    actual = diag._portable_worker_audit(diag._freeze_document(value))
    expected = diag._portable_worker_audit(freeze)
    contract.require(relation.canonical(actual) == relation.canonical(expected),
                     'worker audits do not match the candidate freeze')


def verify_parent_pair(archive, reference, observed, parent_wire, input_sha):
    """Retain all array/parent gates; replace only the OLD code-identity gate.

This is content verification, not execution authority. The supervisor also
requires v19 pass commitments, both live audits, actual environment and cleanup.
"""
    freeze, proof = load(input_sha)
    contract.require(type(parent_wire) is bytes and len(parent_wire) <= archive.MAX_JSON
                     and hashlib.sha256(parent_wire).hexdigest() == PARENT_SHA,
                     'reviewed Job685198 parent contract required')
    replay = checked_module(REPLAY_PATH, REPLAY_SHA, 'v19_pair_parent_data_verifier')
    parent = replay._decode_contract(parent_wire, PARENT_SHA)
    contract.require(replay.FREEZE_SHA == contract.PARENT_FREEZE_SHA,
                     'historical parent identity differs')
    contract.require(reference[2]['input_sha256'] == observed[2]['input_sha256'] == input_sha
                     and input_sha != replay.FREEZE_SHA, 'new execution freeze binding required')
    result = archive.verify_content_pair(reference, observed, contract=parent)
    contract.require(load(input_sha) == (freeze, proof), 'input relation changed during content verification')
    return {**result, 'parent_contract_sha256': PARENT_SHA, 'input_binding': proof}

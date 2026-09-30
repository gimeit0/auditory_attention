"""G2 new execution identity / unchanged scientific inputs / live worker load.

No freeze writer, scheduler, model preparation or authority bypass. The caller
must bind production_bytes to its separately reviewed execution release. This
module does not turn caller-supplied code into an approved release.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat

BRIDGE_SHA = '9b7e033ac8796e142782ea4dcc59ec527bd97538f51ccf8d4bea0caa1cd7d59d'
PARENT_SHA = 'bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178'
PARENT_PROTOCOL = 'formal40_batch_invariance_diag_20260903_v18'
PROFILE_PROTOCOL = 'formal40_numeric_profiles_20260916_v1'
ROOT = '/home/s2510040/audattn_external_eval_diag/' + PROFILE_PROTOCOL
NAMES = ('diagnose_batch_invariance.py', 'numeric_trace.py',
         'submit_numeric_diag.py', 'run_numeric_diag.sbatch')
METADATA = frozenset(('st_dev', 'st_ino', 'st_mtime_ns'))
MAX_JSON = 1024 * 1024


def require(ok, message):
    if not ok:
        raise ValueError('G2 inputs: ' + message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')


def decode(raw, digest):
    require(type(raw) is bytes and len(raw) <= MAX_JSON, 'bounded JSON bytes required')
    require(type(digest) is str and re.fullmatch('[a-f0-9]{64}', digest), 'exact SHA required')
    require(sha(raw) == digest, 'freeze bytes/SHA differ')

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=pairs)
    require(type(value) is dict and canonical(value) == raw, 'canonical diagnostic owner JSON required')
    return value


def scientific_value(value):
    """Only execution identity and cross-invocation filesystem IDs differ.

    Never drop content hash, size, mode, uses, import flag, trial metadata, model
    identity or scientific roots. Within one live worker the old exact checks
    still check inode/time, via _revalidate_worker_inputs.
    """
    result = copy.deepcopy(value)
    del result['diagnostic_protocol']
    del result['roots']['diagnostic_root']
    del result['production_files']
    for name in ('clips', 'snapshot_files'):
        for item in result[name]:
            for key in METADATA:
                require(type(item[key]) is int and item[key] >= 0, 'invalid filesystem metadata')
                del item[key]
    return result


def source_check(bridge, diag, production_bytes):
    bridge.read(bridge.__file__, BRIDGE_SHA)
    bridge._check_module(diag)
    name = diag._G2_PROFILE
    require(type(name) is str and name in ('R', 'C', 'D', 'E'), 'unknown profile')
    require(diag.DIAGNOSTIC_PROTOCOL == PROFILE_PROTOCOL + '_' + name
            and str(diag.DIAGNOSTIC_ROOT) == ROOT + '/' + name, 'profile execution identity differs')
    require(type(production_bytes) is dict and set(production_bytes) == set(NAMES),
            'four new execution sources required')
    for key, value in production_bytes.items():
        require(type(value) is bytes and 0 < len(value) <= 2 * 1024**2,
                'bounded nonempty source bytes required: ' + key)
    require(sha(production_bytes['diagnose_batch_invariance.py']) == bridge.CORE_SHAS[name]
            and sha(production_bytes['numeric_trace.py']) == bridge.TRACE_SHA,
            'new profile/trace source differs')
    return name


def verify_relation(bridge, diag, raw, digest, production_bytes, parent_raw):
    """Pure content relation only; DOES NOT certify live files or execution."""
    name = source_check(bridge, diag, production_bytes)
    parent = decode(parent_raw, PARENT_SHA)
    candidate = decode(raw, digest)
    require(digest != PARENT_SHA and parent.get('diagnostic_protocol') == PARENT_PROTOCOL,
            'historical freeze is only a data reference')
    require(set(candidate) == set(parent), 'freeze field inventory differs')
    diag._validate_freeze_value(candidate, diag.production_contract(),
                                status='INPUTS_FROZEN', diagnostic_root=diag.DIAGNOSTIC_ROOT)
    records = candidate['production_files']
    require(type(records) is list and len(records) == len(NAMES), 'new source inventory differs')
    seen = set()
    for item in records:
        require(type(item) is dict and set(item) == {'relative_path', 'mode', 'size', 'sha256', *METADATA},
                'source record schema differs')
        path = item['relative_path']
        require(type(path) is str and path in NAMES and path not in seen, 'duplicate/unknown source')
        seen.add(path)
        require(type(item['size']) is int and item['size'] == len(production_bytes[path])
                and item['sha256'] == sha(production_bytes[path])
                and type(item['mode']) is int and item['mode'] == 0o600,
                'source content/size/mode differs: ' + path)
        require(all(type(item[k]) is int and item[k] >= 0 for k in METADATA), 'source metadata invalid')
    require(canonical(scientific_value(candidate)) == canonical(scientific_value(parent)),
            'scientific input drift from fixed Job685198 parent')
    proof = dict(status='G2_SCIENTIFIC_INPUT_RELATION_PASS', profile=name,
                 parent_freeze_sha256=PARENT_SHA, candidate_freeze_sha256=digest,
                 diagnostic_protocol=diag.DIAGNOSTIC_PROTOCOL,
                 production_sources={n: sha(production_bytes[n]) for n in NAMES},
                 parent_is_data_reference_only=True, production_live_inputs_verified=False,
                 release_authorized=False, production_ready=False, jobs_submitted=0)
    return candidate, proof


def read_stable(path, limit):
    """Bounded stdlib read before numeric imports; reject aliases and changes."""
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts
            and not any(p.is_symlink() for p in (path, *path.parents)), 'absolute nonsymlink path required')
    def identity(info):
        return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode,
                info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    before = path.stat(follow_symlinks=False)
    require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
            and 0 < before.st_size <= limit, 'bounded user-owned file required')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        require(identity(opened) == identity(before), 'file changed on open')
        with os.fdopen(os.dup(descriptor), 'rb') as stream:
            raw = stream.read(limit + 1)
        require(len(raw) == before.st_size and identity(os.fstat(descriptor)) == identity(before)
                and identity(path.stat(follow_symlinks=False)) == identity(before), 'file changed during read')
        return raw
    finally:
        os.close(descriptor)


class WorkerInputs:
    """Bind original production loader to an explicitly new per-profile freeze.

    Instantiate before numeric imports. Call load once after scratch setup.
    Original production interpreter/path/cold-process claims and audits remain.
    The caller still owns the evaluation lock, release verification, job
    authorization, child supervision, source-preserving scene scope and output
    persistence. This class grants none of those authorities.
    """
    def __init__(self, bridge, diag, digest, production_bytes, parent_raw):
        self.bridge, self.diag, self.digest = bridge, diag, digest
        self.production_bytes = dict(production_bytes)
        self.parent_raw = parent_raw
        self.used, self.pid, self.bundle = False, os.getpid(), None
        require(Path(diag.__file__) == diag.DIAGNOSTIC_ROOT / 'tools/diagnose_batch_invariance.py',
                'production module must execute from its new declared root')
        self.raw = self._files()
        self.freeze, self.proof = verify_relation(bridge, diag, self.raw, digest,
                                                  self.production_bytes, parent_raw)

    def _files(self):
        source_check(self.bridge, self.diag, self.production_bytes)
        root = self.diag.DIAGNOSTIC_ROOT
        for name in NAMES:
            actual = read_stable(root / 'tools' / name, 2 * 1024**2)
            require(actual == self.production_bytes[name], 'physical execution source changed: ' + name)
        return read_stable(root / 'input_freeze.json', MAX_JSON)

    def load(self):
        require(not self.used and os.getpid() == self.pid, 'worker input loader is single-use and process-bound')
        self.used = True
        require(self._files() == self.raw, 'freeze changed before load')
        self.diag._claim_worker_process()
        bundle = self.diag._load_worker_inputs(self.digest)
        require(canonical(bundle['freeze']) == self.raw, 'loader returned another freeze')
        require(bundle['context']['_frozen_context_capability'].trust_domain == 'production',
                'live production capability required')
        # Checks full audit fields, not merely status=AUDIT_PASS or a trial list.
        audit_freeze = self.diag._freeze_document(bundle['audit'])
        require(self.diag._portable_worker_audit(audit_freeze)
                == self.diag._portable_worker_audit(self.freeze), 'loaded audit differs from new freeze')
        require(self._files() == self.raw, 'execution source/freeze changed during load')
        self.bundle = bundle
        return bundle

    def revalidate(self):
        require(self.bundle is not None and os.getpid() == self.pid, 'no live bundle in this process')
        self.diag._revalidate_worker_inputs(self.bundle)
        require(self._files() == self.raw, 'execution source/freeze changed within worker')
        verify_relation(self.bridge, self.diag, self.raw, self.digest,
                        self.production_bytes, self.parent_raw)
        return dict(self.proof, status='G2_WORKER_INPUTS_REVALIDATED', production_live_inputs_verified=True)

"""Bounded cross-process prototype archives; no pickle or production authority.

The caller MUST supply the expected manifest SHA and expected binding from an
independent supervisor. A digest stored next to its own file is not authority.
"""

from dataclasses import fields
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import uuid


PROTOTYPES = Path(__file__).resolve().parent.parent
PINS = {
    'targeted_trace_20260911/trace_observer.py':
        'dcbe162257fc130450a2f2b4a2fd5680caded503d10c67b704c6a0331ec86328',
    'targeted_stream_20260911/stream_capture.py':
        'e0a0282a80b4e68aa0c0d250a0d1383238bfc948b871b9ab05baa585d386c01e',
    'targeted_stream_20260911/stream_observer.py':
        'd939436a0cc84c84c9e56a9c927719df677008405d1545acd537bb8f9bc79474',
}
for relative, digest in PINS.items():
    source_path = PROTOTYPES / relative
    if source_path.is_symlink() or hashlib.sha256(source_path.read_bytes()).hexdigest() != digest:
        raise RuntimeError('pinned observer dependency changed')
sys.path.insert(0, str(PROTOTYPES / 'targeted_stream_20260911'))
import stream_observer as stream  # noqa: E402
import numpy as np  # noqa: E402

base = stream.base
BlobRef = stream.BlobRef
CLASSES = {c.__name__: c for c in (base.Stage, base.Plan, base.TensorCopy, base.Event, base.Batch, BlobRef)}
MAX_MANIFEST = 8 * 1024**2
MAX_TOTAL = 2 * 1024**3
CHUNK = 1024**2
DTYPES = {'torch.float16': np.dtype('<f2'), 'torch.float32': np.dtype('<f4'), 'torch.float64': np.dtype('<f8')}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                       allow_nan=False) + '\n').encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value, depth=0):
    require(depth <= 24, 'wire depth exceeded')
    if type(value) in (str, int, bool) or value is None:
        return value
    if type(value) is bytes:
        require(len(value) <= CHUNK, 'inline byte payload exceeded')
        return {'bytes': base64.b64encode(value).decode('ascii')}
    if type(value) is tuple:
        return {'tuple': [wire(v, depth + 1) for v in value]}
    require(type(value) in CLASSES.values(), 'unsupported wire object')
    return {'type': type(value).__name__, 'fields':
            {f.name: wire(getattr(value, f.name), depth + 1) for f in fields(value)}}


def unwire(value, depth=0, budget=None):
    if budget is None:
        budget = [250000]
    budget[0] -= 1
    require(depth <= 24 and budget[0] >= 0, 'wire depth/node budget exceeded')
    if type(value) in (str, int, bool) or value is None:
        require(type(value) is not str or len(value) <= 8192, 'wire string exceeded')
        return value
    require(type(value) is dict, 'invalid wire value')
    if set(value) == {'bytes'}:
        require(type(value['bytes']) is str and len(value['bytes']) <= 4 * ((CHUNK + 2) // 3),
                'inline byte payload exceeded')
        raw = base64.b64decode(value['bytes'], validate=True)
        require(len(raw) <= CHUNK, 'inline byte payload exceeded')
        return raw
    if set(value) == {'tuple'}:
        require(type(value['tuple']) is list, 'wire tuple is not an array')
        return tuple(unwire(v, depth + 1, budget) for v in value['tuple'])
    require(set(value) == {'type', 'fields'} and type(value['type']) is str
            and value['type'] in CLASSES and type(value['fields']) is dict, 'unknown wire schema')
    cls = CLASSES[value['type']]
    require(set(value['fields']) == {f.name for f in fields(cls)}, 'wire fields differ')
    return cls(**{k: unwire(v, depth + 1, budget) for k, v in value['fields'].items()})


def unique_object(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def directory(path):
    info = Path(path).lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700, 'archive directory type/owner/mode differs')
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        require(identity(os.fstat(fd)) == identity(info), 'archive directory replaced')
    except BaseException:
        os.close(fd)
        raise
    return fd


def read_chunks(parent_fd, name, size, sha):
    """Complete finite-byte verification, including metadata/path stability."""
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                and stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1
                and before.st_size == size, 'archive file metadata differs')
        remaining, hashing = size, hashlib.sha256()
        while remaining:
            wanted = min(CHUNK, remaining)
            pieces = bytearray()
            while len(pieces) < wanted:
                part = os.read(fd, wanted - len(pieces))
                require(bool(part), 'short archive read')
                pieces.extend(part)
            raw = bytes(pieces)
            del pieces
            hashing.update(raw)
            remaining -= len(raw)
            yield raw
        require(not os.read(fd, 1) and hashing.hexdigest() == sha, 'archive file digest/length differs')
        after = os.fstat(fd)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        require(identity(before) == identity(after) == identity(named), 'archive file changed during read')
    finally:
        os.close(fd)


def valid_tensor(dtype, shape, stride, size):
    require(type(dtype) is str and dtype in DTYPES and type(shape) is tuple
            and len(shape) <= 8 and all(type(x) is int and x > 0 for x in shape), 'invalid tensor schema')
    require(type(stride) is tuple and len(stride) == len(shape)
            and all(type(x) is int and x >= 0 for x in stride), 'invalid tensor stride')
    require(type(size) is int and 0 < size <= 128 * CHUNK
            and size == math.prod(shape) * DTYPES[dtype].itemsize, 'invalid tensor byte length')


def valid_records(plan, batches, refs, role):
    require(type(plan) is base.Plan and type(batches) is tuple and type(refs) is tuple,
            'invalid archive records')
    require(role in ('reference', 'observed') and len(batches) == len(plan.schedule()),
            'incomplete archive schedule')
    events = []
    for expected, batch in zip(plan.schedule(), batches):
        require(type(batch) is base.Batch and (batch.pass_id, batch.batch_index, batch.trials) == expected,
                'archive batch identity differs')
        base.endpoint_gate(batch, batch)
        tensor = batch.logits
        require(type(tensor) is base.TensorCopy and type(tensor.data) is bytes
                and len(tensor.shape) == 2 and tensor.shape[0] == len(batch.trials)
                and 1 < tensor.shape[1] <= 800, 'invalid native endpoint')
        valid_tensor(tensor.dtype, tensor.shape, tensor.stride, len(tensor.data))
        require(bool(np.isfinite(np.frombuffer(tensor.data, dtype=DTYPES[tensor.dtype])).all()),
                'nonfinite endpoint')
        if role == 'reference':
            require(batch.events == (), 'reference contains observation events')
        else:
            expected_events = tuple((i, s, t) for i, s in enumerate(plan.stages)
                                    for t in batch.trials if t in plan.targets)
            require(tuple((e.index, e.stage, e.trial_id) for e in batch.events) == expected_events,
                    'archive event schedule differs')
            for e in batch.events:
                ref = e.tensor
                require(type(e) is base.Event and type(ref) is BlobRef
                        and ref.key == (batch.pass_id, batch.batch_index, e.index, e.trial_id),
                        'archive event/ref binding differs')
                events.append(ref)
    require(tuple(events) == refs and len(refs) <= 8192, 'unreferenced/reordered capture')
    for i, ref in enumerate(refs):
        require(type(ref.ordinal) is int and ref.ordinal == i and type(ref.store_id) is str
                and re.fullmatch('[0-9a-f]{32}', ref.store_id) is not None
                and ref.store_id == refs[0].store_id, 'capture ordinal/store differs')
        require(type(ref.sha256) is str and re.fullmatch('[0-9a-f]{64}', ref.sha256) is not None,
                'invalid capture digest')
        valid_tensor(ref.dtype, ref.shape, ref.stride, ref.size)
    require(sum(r.size for r in refs) <= MAX_TOTAL, 'archive total byte budget exceeded')


def seal_archive(root, *, role, binding, plan, batches, store=None):
    """Commit once in a fresh owned leaf; preserve any failed/partial output."""
    root = Path(root)
    refs = () if store is None else tuple(store.refs)
    valid_records(plan, batches, refs, role)
    require(type(binding) is dict and len(canonical(binding)) <= 8192, 'invalid external binding')
    if role == 'observed':
        require(type(store) is stream.CaptureStore and store.root == root / 'captures', 'capture root differs')
        store._check()
        require(store.used_bytes == sum(r.size for r in refs), 'capture ledger size differs')
    else:
        require(store is None, 'reference must not have captures')
    fd = directory(root)
    try:
        require(set(os.listdir(fd)) == ({'captures'} if role == 'observed' else set()),
                'archive root not fresh or extra entry exists')
        manifest = {'schema_version': 1, 'scope': 'UNATTESTED_PROTOTYPE_ARCHIVE', 'role': role,
                    'binding': binding, 'invocation_id': uuid.uuid4().hex, 'writer_pid': os.getpid(),
                    'byte_order': sys.byteorder, 'plan': wire(plan), 'batches': wire(batches),
                    'refs': wire(refs), 'production_execution_authority_verified': False}
        raw = canonical(manifest)
        require(sys.byteorder == 'little' and len(raw) <= MAX_MANIFEST, 'manifest byte order/size differs')
        if store is not None:
            require(set(os.listdir(store.fd)) == {f'{r.ordinal:08d}.bin' for r in refs}, 'capture inventory differs')
            for ref in refs:
                for chunk in read_chunks(store.fd, f'{ref.ordinal:08d}.bin', ref.size, ref.sha256):
                    require(bool(np.isfinite(np.frombuffer(chunk, dtype=DTYPES[ref.dtype])).all()),
                            'nonfinite capture')
            os.fsync(store.fd)
        file_fd = os.open('archive.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                          0o600, dir_fd=fd)
        with os.fdopen(file_fd, 'wb') as output:
            require(output.write(raw) == len(raw), 'short manifest write')
            output.flush()
            os.fsync(output.fileno())
        os.fsync(fd)
        return {'manifest_sha256': digest(raw), 'manifest_size': len(raw), 'role': role,
                'invocation_id': manifest['invocation_id'], 'writer_pid': manifest['writer_pid']}
    finally:
        os.close(fd)


class ArchiveReader:
    def __init__(self, root, *, expected_sha256, expected_binding, expected_plan, expected_role):
        self.root, self.fd, self.capture_fd = Path(root), None, None
        try:
            self.fd = directory(self.root)
            self.root_identity = os.fstat(self.fd)
            require(type(expected_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_sha256),
                    'external expected manifest SHA required')
            info = os.stat('archive.json', dir_fd=self.fd, follow_symlinks=False)
            self.manifest_identity = identity(info)
            require(0 < info.st_size <= MAX_MANIFEST, 'manifest size exceeded')
            raw = b''.join(read_chunks(self.fd, 'archive.json', info.st_size, expected_sha256))
            value = json.loads(raw, object_pairs_hook=unique_object)
            require(canonical(value) == raw, 'manifest is not canonical')
            require(set(value) == {'schema_version', 'scope', 'role', 'binding', 'invocation_id',
                    'writer_pid', 'byte_order', 'plan', 'batches', 'refs', 'production_execution_authority_verified'},
                    'manifest schema differs')
            require(type(value['schema_version']) is int and value['schema_version'] == 1
                    and value['scope'] == 'UNATTESTED_PROTOTYPE_ARCHIVE'
                    and value['production_execution_authority_verified'] is False
                    and value['byte_order'] == sys.byteorder == 'little', 'archive scope/version differs')
            require(value['role'] == expected_role and canonical(value['binding']) == canonical(expected_binding),
                    'external binding/role differs')
            require(type(value['invocation_id']) is str and re.fullmatch('[0-9a-f]{32}', value['invocation_id'])
                    and type(value['writer_pid']) is int and value['writer_pid'] > 0, 'invalid invocation')
            self.binding, self.role = value['binding'], value['role']
            self.invocation_id, self.writer_pid = value['invocation_id'], value['writer_pid']
            self.plan, self.batches, self.refs = (unwire(value[k]) for k in ('plan', 'batches', 'refs'))
            require(self.plan == expected_plan, 'externally bound plan differs')
            valid_records(self.plan, self.batches, self.refs, self.role)
            self.used_bytes, self.peak_payload_bytes = sum(r.size for r in self.refs), 0
            if self.role == 'observed':
                self.capture_fd = directory(self.root / 'captures')
                self.capture_identity = os.fstat(self.capture_fd)
            self.check_inventory()
            for ref in self.refs:
                for chunk in self.chunks(ref):
                    require(bool(np.isfinite(np.frombuffer(chunk, dtype=DTYPES[ref.dtype])).all()), 'nonfinite capture')
            self.check_inventory()
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        for key in ('capture_fd', 'fd'):
            fd = getattr(self, key, None)
            if fd is not None:
                os.close(fd)
                setattr(self, key, None)

    def check_inventory(self):
        require(self.fd is not None and identity(self.root.lstat()) == identity(self.root_identity),
                'archive root replaced or changed')
        require(set(os.listdir(self.fd)) == ({'archive.json', 'captures'} if self.role == 'observed' else {'archive.json'}),
                'archive inventory differs')
        require(identity(os.stat('archive.json', dir_fd=self.fd, follow_symlinks=False))
                == self.manifest_identity, 'archive manifest changed after opening')
        if self.capture_fd is not None:
            require(identity((self.root / 'captures').lstat()) == identity(self.capture_identity),
                    'capture directory changed')
            require(set(os.listdir(self.capture_fd)) == {f'{r.ordinal:08d}.bin' for r in self.refs},
                    'capture inventory differs')

    def chunks(self, ref):
        require(type(ref) is BlobRef and type(ref.ordinal) is int and 0 <= ref.ordinal < len(self.refs)
                and ref == self.refs[ref.ordinal] and self.capture_fd is not None, 'unissued archive ref')
        for chunk in read_chunks(self.capture_fd, f'{ref.ordinal:08d}.bin', ref.size, ref.sha256):
            self.peak_payload_bytes = max(self.peak_payload_bytes, len(chunk))
            yield chunk

    def compare(self, left, right):
        require((left.dtype, left.shape, left.size) == (right.dtype, right.shape, right.size),
                'cross-pass tensor metadata differs')
        self.check_inventory()
        equal = True
        from itertools import zip_longest
        for one, two in zip_longest(self.chunks(left), self.chunks(right)):
            require(one is not None and two is not None, 'capture chunk lengths differ')
            equal = (one == two) and equal
        self.check_inventory()
        return equal


def compare_archives(reference, observed):
    require(reference.role == 'reference' and observed.role == 'observed'
            and reference.plan == observed.plan and canonical(reference.binding) == canonical(observed.binding),
            'archive pair differs')
    require(reference.invocation_id != observed.invocation_id and reference.writer_pid != observed.writer_pid,
            'independent writer processes required')
    reference.check_inventory()
    observed.check_inventory()
    for before, after in zip(reference.batches, observed.batches):
        require(before.logits.stride == after.logits.stride, 'endpoint layout differs')
    result = stream.compare_streamed(reference.plan, reference.batches, observed.batches, observed)
    reference.check_inventory()
    observed.check_inventory()
    return {**result, 'status': 'PROTOTYPE_CROSS_PROCESS_ENDPOINT_GATED',
            'cold_process_supervision_verified_by_archive_alone': False,
            'production_execution_authority_verified': False, 'ready_for_gpu': False}

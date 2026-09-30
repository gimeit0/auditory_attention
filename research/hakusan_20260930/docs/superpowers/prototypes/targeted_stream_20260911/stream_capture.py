"""Local prototype: disk-backed full captures, not a production evaluator.

Only tensor transfer/encoding chunks are bounded here, not total process RSS,
PyTorch allocator workspaces, inputs or model state. No numerical policy changes.
"""

from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import stat
import uuid

import torch


class CaptureError(RuntimeError):
    pass


def require(ok, message):
    if not ok:
        raise CaptureError(message)


def tensor_chunks(tensor, chunk_bytes):
    """Logical C-order bytes without flattening an entire noncontiguous tensor."""
    require(type(chunk_bytes) is int and 8 <= chunk_bytes <= 1024 * 1024,
            "invalid chunk budget")
    require(type(tensor) is torch.Tensor and tensor.layout == torch.strided
            and tensor.dtype in (torch.float16, torch.float32, torch.float64),
            "unsupported native tensor dtype/layout")
    require(tensor.device.type in ("cpu", "cuda") and tensor.numel() > 0
            and tensor.ndim <= 8, "invalid tensor device/shape")
    require(not tensor.is_conj() and not tensor.is_neg(), "unsupported lazy tensor view")
    limit = chunk_bytes // tensor.element_size()

    def pieces(view):
        if view.numel() <= limit:
            yield view
        else:
            # Group adjacent leading rows when possible; otherwise descend by
            # integer indexing. Every view remains a view until it fits the cap.
            row_numel = math.prod(view.shape[1:])
            if row_numel <= limit:
                rows = max(1, limit // row_numel)
                for start in range(0, view.shape[0], rows):
                    yield view[start:start + rows]
            else:
                for row in range(view.shape[0]):
                    yield from pieces(view[row])

    for view in pieces(tensor.detach()):
        host = view.to(device="cpu").contiguous()
        require(bool(torch.isfinite(host).all().item()), "nonfinite capture")
        payload = host.numpy().tobytes()
        require(0 < len(payload) <= chunk_bytes, "chunk size exceeded")
        yield payload
        # Drop intermediates before allocating the next chunk. Consumers must
        # also discard their previous payload instead of collecting all chunks.
        del payload, host


@dataclass(frozen=True)
class BlobRef:
    store_id: str
    ordinal: int
    key: tuple
    dtype: str
    shape: tuple
    stride: tuple
    size: int
    sha256: str


class CaptureStore:
    """Create a NEW private leaf directory. Failed partial files are preserved.

    The in-memory issuance ledger binds references for this process only. This
    is not a cross-process archive format or adversarial execution attestation.
    """

    def __init__(self, root, *, chunk_bytes=1024 * 1024,
                 total_bytes=2 * 1024**3, tensor_bytes=128 * 1024**2,
                 max_records=8192):
        for value, lower, upper in ((chunk_bytes, 8, 1024**2),
                                    (total_bytes, 1, 8 * 1024**3),
                                    (tensor_bytes, 1, 128 * 1024**2),
                                    (max_records, 1, 8192)):
            require(type(value) is int and lower <= value <= upper, "invalid store budget")
        self.root = Path(root)
        parent = self.root.parent.lstat()
        require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == os.getuid(),
                "store parent must be an owned directory, not a symlink")
        self.root.mkdir(mode=0o700, exist_ok=False)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.identity = os.fstat(self.fd)
        self.store_id = uuid.uuid4().hex
        self.chunk_bytes, self.total_bytes = chunk_bytes, total_bytes
        self.tensor_bytes, self.max_records = tensor_bytes, max_records
        self.used_bytes = self.peak_payload_bytes = 0
        self.refs, self.keys = [], set()
        self.failed = self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if not self.closed:
            os.close(self.fd)
            self.closed = True

    def _check(self):
        require(not self.closed and not self.failed, "store closed or failed")
        current = self.root.lstat()
        require(stat.S_ISDIR(current.st_mode) and current.st_uid == os.getuid()
                and stat.S_IMODE(current.st_mode) == 0o700
                and (current.st_dev, current.st_ino) ==
                (self.identity.st_dev, self.identity.st_ino), "store directory changed")

    def capture(self, tensor, key):
        try:
            self._check()
            require(type(key) is tuple and len(key) == 4 and key[0] in ("pass1", "pass2")
                    and all(type(x) is int and x >= 0 for x in key[1:]), "invalid event key")
            require(key not in self.keys, "duplicate event key")
            require(len(self.refs) < self.max_records, "record budget exceeded")
            require(type(tensor) is torch.Tensor, "native tensor required")
            size = tensor.numel() * tensor.element_size()
            require(0 < size <= self.tensor_bytes and self.used_bytes + size <= self.total_bytes,
                    "capture byte budget exceeded")
            ordinal = len(self.refs)
            fd = os.open(f"{ordinal:08d}.bin", os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            digest, written = hashlib.sha256(), 0
            with os.fdopen(fd, "wb", buffering=0) as stream:
                chunks = iter(tensor_chunks(tensor, self.chunk_bytes))
                while True:
                    payload = next(chunks, None)
                    if payload is None:
                        break
                    self.peak_payload_bytes = max(self.peak_payload_bytes, len(payload))
                    view = memoryview(payload)
                    offset = 0
                    while offset < len(view):
                        count = stream.write(view[offset:])
                        require(type(count) is int and count > 0, "short capture write")
                        offset += count
                    digest.update(payload)
                    written += len(payload)
                    del view, payload
                os.fsync(stream.fileno())
            require(written == size, "capture size differs")
            ref = BlobRef(self.store_id, ordinal, key, str(tensor.dtype), tuple(tensor.shape),
                          tuple(tensor.stride()), size, digest.hexdigest())
            self.refs.append(ref)
            self.keys.add(key)
            self.used_bytes += size
            return ref
        except BaseException:
            self.failed = True
            raise

    def _open(self, ref):
        self._check()
        require(type(ref) is BlobRef and ref.store_id == self.store_id
                and type(ref.ordinal) is int and 0 <= ref.ordinal < len(self.refs)
                and self.refs[ref.ordinal] == ref, "unissued or changed capture reference")
        fd = os.open(f"{ref.ordinal:08d}.bin", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
        info = os.fstat(fd)
        if not (stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_uid == os.getuid() and info.st_nlink == 1 and info.st_size == ref.size):
            os.close(fd)
            raise CaptureError("capture file metadata differs")
        return os.fdopen(fd, "rb", buffering=0)

    def compare(self, left, right):
        """Read every byte of both issued records, even after finding a difference."""
        try:
            require((left.dtype, left.shape, left.size) == (right.dtype, right.shape, right.size),
                    "cross-pass tensor metadata differs")
            hashes, equal = (hashlib.sha256(), hashlib.sha256()), True
            with self._open(left) as one, self._open(right) as two:
                remaining = left.size
                while remaining:
                    count = min(remaining, self.chunk_bytes)
                    a, b = one.read(count), two.read(count)
                    require(len(a) == len(b) == count, "short capture read")
                    hashes[0].update(a)
                    hashes[1].update(b)
                    equal = equal and a == b
                    remaining -= count
                    del a, b
                require(not one.read(1) and not two.read(1), "capture grew during read")
            require(hashes[0].hexdigest() == left.sha256
                    and hashes[1].hexdigest() == right.sha256, "capture digest differs")
            self._check()
            return equal
        except BaseException:
            self.failed = True
            raise

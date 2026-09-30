"""Bounded CPU-array transport for a future GPU cold pair, not a launcher.

The supervisor supplies expected binding and manifest digests independently.
This verifies artifact CONTENT, never authenticates execution or grants GPU
authority. Partial writes are retained. No pickle, casting, tolerance or retry.
"""
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat

import numpy as np

CHUNK = 1024**2
MAX_ARRAY = 128 * CHUNK
MAX_TOTAL = 2 * 1024**3
MAX_JSON = 8 * CHUNK
COARSE = ("raw_scene", "raw_cue", "normalized_scene", "normalized_cue", "scene_features",
          "cue_features", "native_logits", "log_probabilities")
DERIVED = ("target_logit", "logsumexp", "target_log_probability", "nll", "p_target",
           "p_probe_distractor", "pred_label", "correct")
OFFICIAL = ("nll", "p_target", "p_probe_distractor", "pred_label")
DTYPES = {"<f2": 2, "<f4": 4, "<f8": 8, "<i8": 8, "|b1": 1}
SHA = re.compile(r"[0-9a-f]{64}")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def directory(path):
    """No-follow every path component; hold the leaf by descriptor."""
    path = Path(path)
    require(path.is_absolute() and ".." not in path.parts, "absolute canonical archive path required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        require(stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.getuid(), "private archive leaf required")
        return fd
    except BaseException:
        os.close(fd)
        raise


def check_named_directory(path, fd):
    other = directory(path)
    try:
        one, two = os.fstat(fd), os.fstat(other)
        require((one.st_dev, one.st_ino) == (two.st_dev, two.st_ino), "archive leaf replaced")
    finally:
        os.close(other)


def chunks(fd, name, size, sha):
    require(type(name) is str and re.fullmatch(r"(?:[0-9]{3}\.bin|manifest\.json)", name), "invalid artifact name")
    require(type(size) is int and 0 < size <= max(MAX_ARRAY, MAX_JSON)
            and type(sha) is str and SHA.fullmatch(sha), "invalid artifact length/digest")
    source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        before = os.fstat(source)
        require(stat.S_ISREG(before.st_mode) and stat.S_IMODE(before.st_mode) == 0o600
                and before.st_uid == os.getuid() and before.st_nlink == 1 and before.st_size == size,
                "artifact type/owner/mode/link/size differs")
        remaining, hashing = size, hashlib.sha256()
        while remaining:
            raw = os.read(source, min(CHUNK, remaining))
            require(bool(raw), "short artifact read")
            hashing.update(raw)
            remaining -= len(raw)
            yield raw
        require(not os.read(source, 1) and hashing.hexdigest() == sha, "artifact bytes differ")
        require(identity(before) == identity(os.fstat(source))
                == identity(os.stat(name, dir_fd=fd, follow_symlinks=False)), "artifact changed during read")
    finally:
        os.close(source)


def binding_check(value):
    require(type(value) is dict and set(value) == {"pair_nonce", "role", "pid", "cell", "input_sha256", "package_sha256"},
            "binding schema differs")
    require(type(value["pair_nonce"]) is str and re.fullmatch(r"[0-9a-f]{32}", value["pair_nonce"])
            and value["role"] in ("reference", "observed") and value["cell"] == "B2"
            and type(value["pid"]) is int and value["pid"] > 0, "binding identity differs")
    require(all(type(value[k]) is str and SHA.fullmatch(value[k]) for k in ("input_sha256", "package_sha256")),
            "binding pins differ")


def metadata(record):
    require(type(record) is dict and record.get("dtype") in DTYPES, "unsupported native dtype")
    shape = record.get("shape")
    require(type(shape) is list and 1 <= len(shape) <= 8
            and all(type(n) is int and 0 < n <= 1000000 for n in shape), "invalid shape")
    size = math.prod(shape) * DTYPES[record["dtype"]]
    require(type(record.get("nbytes")) is int and record["nbytes"] == size and 0 < size <= MAX_ARRAY,
            "array byte budget/shape differs")
    require(type(record.get("sha256")) is str and SHA.fullmatch(record["sha256"]), "invalid array digest")


def array_chunks(array):
    require(type(array) is np.ndarray and array.dtype.str in DTYPES and not array.dtype.hasobject,
            "native ndarray required; no casts")
    descriptor = {"dtype": array.dtype.str, "shape": list(array.shape), "nbytes": array.nbytes, "sha256": "0" * 64}
    metadata(descriptor)  # before any copying
    iterator = np.nditer(array, flags=["external_loop", "buffered", "zerosize_ok"],
                         op_flags=["readonly"], order="C", buffersize=CHUNK // array.itemsize)
    for part in iterator:
        require(part.nbytes <= CHUNK and bool(np.isfinite(part).all()), "nonfinite/overbudget array chunk")
        yield part.tobytes(order="C")


class PassArchive:
    """Exclusive new leaf; write two passes of 16 boundaries plus four outputs.

capture_pass is a CPU artifact operation, never a new inference. A failure
poisons this writer, leaving already-written evidence untouched.
"""
    def __init__(self, root, binding):
        binding_check(binding)
        require(binding["pid"] == os.getpid(), "writer PID must be actual process")
        self.root = Path(root)
        parent = directory(self.root.parent)
        try:
            os.mkdir(self.root.name, 0o700, dir_fd=parent)
        finally:
            os.close(parent)
        self.fd = directory(self.root)
        self.binding = json.loads(canonical(binding))
        self.passes, self.names = [], []
        self.total = 0
        self.failed = self.finished = self.closed = False

    def capture_pass(self, pass_id, batch_size, trials, boundaries, outputs, original):
        try:
            require(not self.closed and not self.finished and not self.failed, "archive is not writable")
            check_named_directory(self.root, self.fd)
            require(len(self.passes) < 2 and (pass_id, batch_size) == (("pass1", 16), ("pass2", 1))[len(self.passes)],
                    "pass order differs")
            require(type(trials) is list and len(trials) == 32 and len(set(trials)) == 32
                    and all(type(i) is int for i in trials), "trial order/count differs")
            require(not self.passes or trials == self.passes[0]["trial_ids"], "between-pass trials differ")
            require(set(boundaries) == set(COARSE + DERIVED) and set(outputs) == set(OFFICIAL), "array coverage differs")
            require(type(original) is dict and len(canonical(original)) <= MAX_JSON // 3, "original evidence budget differs")
            records = {}
            for family, arrays, order in (("boundaries", boundaries, COARSE + DERIVED), ("official_outputs", outputs, OFFICIAL)):
                records[family] = {}
                for name in order:
                    array = arrays[name]
                    require(type(array) is np.ndarray and array.ndim and array.shape[0] == 32, "array trial axis differs")
                    require(family != "official_outputs" or array.shape == (32,), "official output shape differs")
                    require(0 < array.nbytes <= MAX_ARRAY and self.total + array.nbytes <= MAX_TOTAL, "archive byte budget exceeded")
                    filename = f"{len(self.names):03d}.bin"
                    target = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
                    hashing, written = hashlib.sha256(), 0
                    with os.fdopen(target, "wb") as out:
                        for raw in array_chunks(array):
                            out.write(raw)
                            hashing.update(raw)
                            written += len(raw)
                        out.flush()
                        os.fsync(out.fileno())
                    require(written == array.nbytes, "array byte count changed")
                    records[family][name] = {"file": filename, "dtype": array.dtype.str, "shape": list(array.shape),
                                             "nbytes": written, "sha256": hashing.hexdigest()}
                    self.names.append(filename)
                    self.total += written
            self.passes.append({"pass_id": pass_id, "batch_size": batch_size, "trial_ids": list(trials),
                                **records, "original_pass_evidence": json.loads(canonical(original))})
        except BaseException:
            self.failed = True
            raise

    def finish(self):
        try:
            require(not self.failed and not self.finished and not self.closed and len(self.passes) == 2,
                    "incomplete/failed/reused archive")
            check_named_directory(self.root, self.fd)
            require(set(os.listdir(self.fd)) == set(self.names) and len(self.names) == 40, "artifact inventory differs")
            for part in self.passes:
                for family in ("boundaries", "official_outputs"):
                    for record in part[family].values():
                        for _ in chunks(self.fd, record["file"], record["nbytes"], record["sha256"]):
                            pass
            value = {"schema_version": 1, "scope": "ARRAY_CONTENT_ONLY_NOT_EXECUTION_ATTESTATION",
                     "binding": self.binding, "passes": self.passes, "total_bytes": self.total}
            raw = canonical(value)
            require(len(raw) <= MAX_JSON, "manifest budget exceeded")
            fd = os.open("manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            with os.fdopen(fd, "wb") as out:
                out.write(raw)
                out.flush()
                os.fsync(out.fileno())
            os.fsync(self.fd)
            check_named_directory(self.root, self.fd)
            self.finished = True
            return {"size": len(raw), "sha256": digest(raw)}
        except BaseException:
            self.failed = True
            raise

    def close(self):
        if not self.closed:
            os.close(self.fd)
            self.closed = True


def read_array(fd, record, expected, *, rows=None):
    metadata(record)
    require({k: record[k] for k in ("dtype", "shape", "nbytes", "sha256")} == expected, "parent array descriptor differs")
    row_width = record["nbytes"] // 32
    require(record["shape"][0] == 32 and row_width * 32 == record["nbytes"], "invalid trial axis")
    hashes, offset = [hashlib.sha256() for _ in range(32)], 0
    pending = b""
    for raw in chunks(fd, record["file"], record["nbytes"], record["sha256"]):
        # os.read may return short, non-element-aligned chunks.
        data = pending + raw
        aligned = len(data) // DTYPES[record["dtype"]] * DTYPES[record["dtype"]]
        require(bool(np.isfinite(np.frombuffer(data[:aligned], dtype=record["dtype"])).all()), "nonfinite archive array")
        pending = data[aligned:]
        start = 0
        while start < len(raw):
            row, inside = divmod(offset, row_width)
            width = min(len(raw) - start, row_width - inside)
            hashes[row].update(raw[start:start + width])
            start += width
            offset += width
    require(not pending, "unaligned array length")
    if rows is not None:
        require(len(rows) == 32, "parent row coverage differs")
        for hashing, row in zip(hashes, rows):
            require(hashing.hexdigest() == row["sha256"] and row["nbytes"] == row_width
                    and row["dtype"] == record["dtype"] and row["shape"] == (record["shape"][1:] or [1]),
                    "parent per-trial bytes differ")


def verify_archive(root, expected_manifest, expected_binding, contract):
    """Independent full bytes + exact pinned-parent descriptors, no torch."""
    binding_check(expected_binding)
    require(type(expected_manifest) is dict and set(expected_manifest) == {"size", "sha256"}
            and type(expected_manifest["size"]) is int and 0 < expected_manifest["size"] <= MAX_JSON,
            "expected external manifest differs")
    fd = directory(root)
    try:
        raw = b"".join(chunks(fd, "manifest.json", expected_manifest["size"], expected_manifest["sha256"]))
        value = json.loads(raw)
        require(canonical(value) == raw and set(value) == {"schema_version", "scope", "binding", "passes", "total_bytes"}
                and value["schema_version"] == 1 and value["scope"] == "ARRAY_CONTENT_ONLY_NOT_EXECUTION_ATTESTATION",
                "manifest schema/canonical encoding differs")
        require(value["binding"] == expected_binding and len(value["passes"]) == 2, "external identity/pass count differs")
        ids = [t["trial_id"] for t in contract["trials"]]
        spec = contract["cells"][expected_binding["cell"]]
        require(len(ids) == 32 and len(set(ids)) == 32, "parent trial count differs")
        names, total = [], 0
        for i, part in enumerate(value["passes"]):
            pass_id, size = (("pass1", 16), ("pass2", 1))[i]
            require(set(part) == {"pass_id", "batch_size", "trial_ids", "boundaries", "official_outputs", "original_pass_evidence"}
                    and (part["pass_id"], part["batch_size"], part["trial_ids"]) == (pass_id, size, ids), "pass schedule differs")
            parent = spec["passes"][pass_id]
            for family, order in (("boundaries", COARSE + DERIVED), ("official_outputs", OFFICIAL)):
                require(set(part[family]) == set(order), "boundary/output coverage differs")
                for name in order:
                    record = part[family][name]
                    require(set(record) == {"file", "dtype", "shape", "nbytes", "sha256"}
                            and record["file"] == f"{len(names):03d}.bin", "artifact order/descriptor differs")
                    bound = parent["boundaries"][name]
                    expected = bound["aggregate"]
                    require([r["trial_id"] for r in bound["rows"]] == ids, "parent row order differs")
                    metadata(record)
                    total += record["nbytes"]
                    require(total <= MAX_TOTAL, "total byte budget exceeded")
                    read_array(fd, record, expected, rows=bound["rows"])
                    names.append(record["file"])
        require(type(value["total_bytes"]) is int and total == value["total_bytes"]
                and set(os.listdir(fd)) == {"manifest.json", *names}, "inventory/total differs")
        check_named_directory(root, fd)
        return value
    finally:
        os.close(fd)


def verify_content_pair(reference, observed, *, contract):
    """Each argument is (root, independently supplied digest, binding).

contract is an already-validated parent contract, NOT an execution credential.
Original pass documents are retained but need original v18 decoding by the
eventual supervisor. This content gate alone must never release a GPU result.
"""
    one = verify_archive(*reference, contract)
    two = verify_archive(*observed, contract)
    a, b = one["binding"], two["binding"]
    require(a["role"] == "reference" and b["role"] == "observed" and a["pid"] != b["pid"], "distinct cold process identities required")
    require(all(a[k] == b[k] for k in ("pair_nonce", "cell", "input_sha256", "package_sha256")), "cold pair bindings differ")
    for p, q in zip(one["passes"], two["passes"]):
        require(p["boundaries"] == q["boundaries"] and p["official_outputs"] == q["official_outputs"], "cold pair content differs")
    return {"status": "COLD_PAIR_ARRAY_CONTENT_PASS", "cell": "B2", "arrays_rehashed": 80,
            "parent_array_content_equal": True, "corresponding_pass_content_equal": True,
            "execution_authority_verified": False, "original_pass_commitments_verified": False,
            "intermediate_captures_verified": False, "production_preparation_validated": False,
            "ready_for_gpu": False, "jobs_submitted": 0}


def verify_pinned_parent_pair(reference, observed, parent_wire):
    """Fixed Job685198 parent pin; no caller-selected production oracle."""
    parent_sha = "95e25bde17fa8358cd20f90c2edf27a94a4ffd6f49aab8bd9fa3395b6c7c7b34"
    require(type(parent_wire) is bytes and len(parent_wire) <= MAX_JSON and digest(parent_wire) == parent_sha,
            "reviewed Job685198 parent contract required")
    path = Path(__file__).resolve().parent.parent / "targeted_replay_20260912/parent_replay.py"
    raw = path.read_bytes()
    require(not path.is_symlink() and digest(raw) == "6d5f784fcabd4a45e4d8ea997b230f1c5c5a22dbdde4affef359e01538e265ae",
            "original parent verifier differs")
    spec = importlib.util.spec_from_file_location("gpu_pair_parent_content", path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    contract = module._decode_contract(parent_wire, parent_sha)
    require(reference[2]["input_sha256"] == observed[2]["input_sha256"] == module.FREEZE_SHA,
            "original v18 input freeze differs")
    return {**verify_content_pair(reference, observed, contract=contract), "parent_contract_sha256": parent_sha}

"""Create original exclusive scratch BEFORE numeric imports; preserve real HOME.

No directory adoption from a prior run. A stdlib-only copy of the pinned v19
module opens the original scratch factory, retaining its Linux mount, fd,
ownership, empty-cache and no-reuse checks. After imports, an original-loader
issued v19 module supplies the execution scratch type and spill methods, while
the same live directory descriptors remain held by the bootstrap scope.
This is a candidate startup correction, not a GPU submission authorization.
"""
import contextlib
import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import types
import uuid

HERE = Path(__file__).resolve().parent
PRIOR = HERE
V19_SHA = "c1ba3af9da8fb2be6e197fddbee38a03c0ef3a8f67da75e7abc0b1a9f568b50d"
ADAPTER_SHA = "27af76b90e6991e9e74ee85132120031c7efb17700ae67cbc94494a61db17747"
NUMERIC = {"torch", "numpy", "pandas", "torchaudio", "matplotlib", "scipy"}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def checked_load(path, expected, name):
    path = Path(path)
    require(path.is_absolute() and ".." not in path.parts, "absolute pinned module path required")
    for parent in (*path.parents, path):
        require(not parent.is_symlink(), "symlink module path")
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, "pinned bootstrap module differs")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


adapter = checked_load(PRIOR / "scratch_adapter.py", ADAPTER_SHA, "gpu_startup_prior_scratch")


def cold_imports():
    found = sorted(n for n in sys.modules if n.partition(".")[0] in NUMERIC)
    require(not found, "scratch must precede numeric imports: " + ",".join(found[:5]))


class _Lease:
    def __init__(self, scratch, args, role):
        self.scratch, self.args, self.role = scratch, (args.job_id, args.expected_input_freeze_sha256), role
        self.active, self.bound = True, False
        self.owner_pid = os.getpid()
        self.home = os.environ.get("HOME")
        self.anchor_ids = tuple((a, a.fd, os.fstat(a.fd).st_dev, os.fstat(a.fd).st_ino) for a in scratch.anchors)

    def check(self):
        require(self.active and os.getpid() == self.owner_pid, "startup lease is closed or belongs to another process")
        require(os.environ.get("HOME") == self.home, "real HOME changed")
        require(tuple(a for a, *_ in self.anchor_ids) == tuple(self.scratch.anchors), "startup anchors replaced")
        for anchor, fd, dev, ino in self.anchor_ids:
            require(anchor.fd == fd and (os.fstat(fd).st_dev, os.fstat(fd).st_ino) == (dev, ino), "startup descriptor replaced")
        self.scratch.check()


@contextlib.contextmanager
def open_scratch(contract, role, input_sha):
    """No torch import or model loading occurs here. Existing roles still fail."""
    cold_imports()
    require(role in ("reference", "observed"), "unknown child role")
    args = types.SimpleNamespace(job_id=os.environ.get("SLURM_JOB_ID"),
                                 expected_input_freeze_sha256=input_sha)
    worker_role = "reference_cold" if role == "reference" else "B2"
    path = contract.V19 / "tools/diagnose_batch_invariance.py"
    contract.pinned_read(path, V19_SHA)
    # Bootstrap module is directory authority only, NEVER a model/worker issuer.
    diag = checked_load(path, V19_SHA, "gpu_startup_bootstrap_v19_" + uuid.uuid4().hex)
    cold_imports()
    _, scope, _ = adapter.build(diag)
    lease = None
    try:
        with scope(args, worker_role) as scratch:
            cold_imports()
            lease = _Lease(scratch, args, worker_role)
            lease.check()
            yield lease
            lease.check()
    finally:
        if lease is not None:
            lease.active = False


def bind_scope(lease, diag, bridge):
    """Bind fresh execution type to our still-open scratch, never mkdir/reuse."""
    require(type(lease) is _Lease, "exact in-process startup lease required")
    lease.check()
    require(not lease.bound, "startup lease already bound")
    bridge._require_module(diag)  # original pinned loader must issue execution module
    private, _, paths = adapter.build(diag)
    require(isinstance(lease.scratch.root, Path), "scratch root type differs")
    record = copy.deepcopy(lease.scratch.record)
    record.update(startup_policy="exclusive_scratch_before_numeric_imports",
                  startup_owner_pid=lease.owner_pid, bootstrap_v19_sha256=V19_SHA,
                  execution_v19_same_pinned_source=True)
    scratch = private(lease.scratch.root, lease.scratch.anchors, record)
    scratch.check()
    lease.bound = True
    entered = False

    @contextlib.contextmanager
    def scope(args, role):
        nonlocal entered
        lease.check()
        require(not entered, "execution scratch cannot be reentered")
        require((args.job_id, args.expected_input_freeze_sha256) == lease.args and role == lease.role,
                "execution scratch job/role/freeze differs")
        entered = True
        try:
            scratch.check()
            yield scratch
        finally:
            lease.check()
            scratch.check()

    return private, scope, paths

"""Restricted checkpoint load with one explicit metadata type: PosixPath.

Use only for our SHA-bound checkpoints in a disposable, single-threaded worker.
No arbitrary globals, unrestricted-pickle fallback, or on-disk modifications.
The 2.1.1 adapter restores the original private getter even when loading fails.
"""
from contextlib import contextmanager
import io
from pathlib import PosixPath
import threading
import torch

@contextmanager
def path_metadata_scope():
    if threading.active_count() != 1:
        raise RuntimeError('ISOLATED_SINGLE_THREAD_REQUIRED')
    serialization = torch.serialization
    if hasattr(serialization, 'safe_globals'):
        if serialization.get_safe_globals():
            raise RuntimeError('PREEXISTING_USER_GLOBALS')
        with serialization.safe_globals([PosixPath]):
            yield 'PUBLIC_SAFE_GLOBALS_POSIXPATH_ONLY'
        return
    if torch.__version__ != '2.1.1+cu118':
        raise RuntimeError('LEGACY_RUNTIME_NOT_AUDITED')
    import torch._weights_only_unpickler as restricted
    original = restricted._get_allowed_globals
    baseline = dict(original())
    if 'pathlib.PosixPath' in baseline:
        raise RuntimeError('UNEXPECTED_BASE_ALLOWLIST')
    allowed = dict(baseline, **{'pathlib.PosixPath': PosixPath})
    def scoped_globals(): return allowed
    restricted._get_allowed_globals = scoped_globals
    try:
        yield 'PYTORCH_2_1_1_SCOPED_POSIXPATH_ONLY'
    finally:
        restricted._get_allowed_globals = original
        if original() != baseline:
            raise RuntimeError('BASE_ALLOWLIST_CHANGED')

def restricted_checkpoint_load(raw):
    if type(raw) is not bytes or not raw or len(raw) > 1024**3:
        raise ValueError('CHECKPOINT_BYTE_BOUND')
    with path_metadata_scope():
        return torch.load(io.BytesIO(raw), map_location='cpu', weights_only=True)

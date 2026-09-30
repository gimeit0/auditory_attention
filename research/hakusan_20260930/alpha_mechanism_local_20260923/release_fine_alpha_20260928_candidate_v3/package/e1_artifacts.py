"""Small production-only artifact and process helpers; no synthetic fixtures."""
import hashlib
import json
import os
import signal

def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def write_json(path,value):
    with path.open('xb') as f:
        f.write(canonical(value));f.flush();os.fsync(f.fileno())

def identity(path):
    if not path.is_file() or path.is_symlink():raise ValueError('INVALID_ARTIFACT')
    raw=path.read_bytes()
    return dict(size=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def stop_group(process):
    try:os.killpg(process.pid,signal.SIGKILL)
    except ProcessLookupError:pass
    process.wait()

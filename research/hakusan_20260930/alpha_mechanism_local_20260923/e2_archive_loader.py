"""SHA-bound loader for our audited Lightning archives, not arbitrary uploads.

PyTorch 2.1.1 weights_only cannot BUILD numpy RNG metadata. A custom pickle
module implements an explicit global registry, preceded by a static opcode
gate. This is NOT unrestricted pickle and is not a weights_only=True claim.
No checkpoint is rewritten; model tensors and RNG metadata are preserved.
"""
from collections import OrderedDict
import hashlib
import io
from pathlib import PosixPath
import pickle
import pickletools
import types
import zipfile
import numpy as np
import torch

def latin1_bytes(value, encoding):
    if type(value) is not str or encoding != 'latin1':
        raise pickle.UnpicklingError('CODEC_REFUSED')
    return value.encode('latin1')

def posix_path(*parts):
    if len(parts)>256 or any(type(p) is not str for p in parts):
        raise pickle.UnpicklingError('PATH_PARTS_REFUSED')
    return PosixPath(*parts)

def registry():
    reconstruct=np.core.multiarray._reconstruct
    return {('collections','OrderedDict'):OrderedDict,
            ('pathlib','PosixPath'):posix_path,('_codecs','encode'):latin1_bytes,
            ('numpy','dtype'):np.dtype,('numpy','ndarray'):np.ndarray,
            ('numpy.core.multiarray','_reconstruct'):reconstruct,
            # Same NumPy constructor, modern local fixture alias only.
            ('numpy._core.multiarray','_reconstruct'):reconstruct,
            ('torch','ByteStorage'):torch.ByteStorage,
            ('torch','FloatStorage'):torch.FloatStorage,
            ('torch._utils','_rebuild_tensor_v2'):torch._utils._rebuild_tensor_v2}

class AllowlistedUnpickler(pickle.Unpickler):
    def find_class(self,module,name):
        try: return registry()[(module,name)]
        except KeyError: raise pickle.UnpicklingError('GLOBAL_REFUSED: '+module+'.'+name) from None

def static_gate(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        members=[m for m in z.infolist() if m.filename.endswith('/data.pkl')]
        if len(members)!=1 or members[0].file_size>16*1024**2:
            raise ValueError('ARCHIVE_PICKLE_MEMBER')
        data=z.read(members[0])
    seen=set()
    for op,arg,_ in pickletools.genops(data):
        if op.name in ('STACK_GLOBAL','EXT1','EXT2','EXT4','INST','OBJ','NEWOBJ_EX'):
            raise pickle.UnpicklingError('INDIRECT_GLOBAL_REFUSED')
        if op.name=='GLOBAL':
            pair=tuple(arg.split(' ',1))
            if pair not in registry(): raise pickle.UnpicklingError('GLOBAL_REFUSED: '+arg)
            seen.add(arg)
    return sorted(seen)

def load_bound_archive(raw, expected_sha256):
    if type(raw) is not bytes or not 0<len(raw)<=1024**3:
        raise ValueError('ARCHIVE_SIZE')
    if hashlib.sha256(raw).hexdigest()!=expected_sha256: raise ValueError('ARCHIVE_SHA')
    static_gate(raw)
    module=types.ModuleType('e2_explicit_pickle_registry')
    module.Unpickler=AllowlistedUnpickler
    # Explicit custom unpickler required by torch; there is no fallback branch.
    return torch.load(io.BytesIO(raw),map_location='cpu',pickle_module=module,weights_only=False)

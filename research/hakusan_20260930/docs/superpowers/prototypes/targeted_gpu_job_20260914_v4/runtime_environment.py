"""Exact v18 startup exports; stdlib only, no mutation of process environment."""
import os
import sys
from types import MappingProxyType

FIXED = MappingProxyType({'OMP_NUM_THREADS': '8', 'CUBLAS_WORKSPACE_CONFIG': ':4096:8',
                          'TOKENIZERS_PARALLELISM': 'false'})


def check(env, *, modules=None):
    if any(env.get(k) != v for k, v in FIXED.items()):
        raise RuntimeError('original v18 startup exports absent/different')
    if any(k in env for k in ('MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'OMP_DYNAMIC')):
        raise RuntimeError('unreviewed thread override in clean child environment')
    loaded = sys.modules if modules is None else modules
    if any(n.partition('.')[0] in {'torch', 'numpy', 'torchaudio', 'pandas'} for n in loaded):
        raise RuntimeError('startup exports must be checked before numerical imports')
    return dict(FIXED)


def readback(torch):
    """Whitelist only; does not configure threads, RNG, CUDA or precision."""
    if any(os.environ.get(k) != v for k, v in FIXED.items()):
        raise RuntimeError('startup exports changed after imports')
    threads = torch.get_num_threads()
    if threads != 8:
        raise RuntimeError('actual torch CPU threads differ from the fixed eight')
    return {'fixed_exports': dict(FIXED), 'torch_num_threads': threads,
            'torch_num_interop_threads': torch.get_num_interop_threads(),
            'cpu_affinity': sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
            'scope': 'environment readback, not performance or numerical acceptance'}

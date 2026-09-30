"""Read-only, stdlib-only numeric and native evidence validation."""
import base64
import math
from pathlib import Path
import struct
import common as c

def decode(row):
    c.require(row['dtype'] == 'float32' and all(type(x) is int and x > 0 for x in row['shape']), 'tensor schema differs')
    raw = base64.b64decode(row['bytes_b64'], validate=True)
    size = math.prod(row['shape'])
    c.require(size <= 4096 and len(raw) == size*4 and c.sha(raw) == row['sha256'], 'tensor hash/size differs')
    values = struct.unpack('<' + str(size) + 'f', raw)
    c.require(all(math.isfinite(x) for x in values), 'nonfinite output')
    return values

def difference(a, b):
    c.require(a['shape'] == b['shape'], 'tensor shapes differ')
    return max(abs(x-y) for x, y in zip(decode(a), decode(b)))

def child(r, role, digest, nonce, job):
    c.require(r['status'] == 'NATIVE_CPU_CHILD_PASS' and r['role'] == role and r['job_id'] == job
              and r['release_sha256'] == digest and r['nonce'] == nonce, 'child identity differs')
    c.require(r['python'] == '3.11.5' and r['torch'] == '2.1.1+cu118' and len(r['affinity']) == 1
              and r['threads'] == r['interop_threads'] == 1 and r['source_postcheck'] and r['profiler_removed']
              and not r['cuda_initialized'] and not r['production_model_loaded'] and not r['ready_for_gpu'], 'child scope differs')
    c.require(r['before'] == r['after'] and r['before']['runtime'] == [True, True, False, 'highest', False, False]
              and not any(r['before']['training']) and not any(r['before']['requires_grad']), 'state mutation')
    for t in [*r['before']['weights'].values(), *r['before']['inputs']]:
        decode(t)
    c.require(len(r['outputs']) == len(r['eager']) == 2
              and [r['outputs'][i]['shape'] for i in (0,1)] == [[16,8], [1,8]], 'batch coverage differs')
    delta = [difference(a,b) for a,b in zip(r['outputs'], r['eager'])]
    c.require(max(delta) <= 1e-6, 'compiled versus eager differs')
    if role == 'reference':
        c.require(r['backend'] is None, 'reference must be unobserved')
    else:
        b = r['backend']
        c.require(b['compiler_calls'] == b['compiler_returns'] > 0 and b['target_generated_artifacts_executed']
                  and b['production_ready'] is False and b['interference_validated'] is False and b['artifacts'], 'backend execution absent')
        for a in b['artifacts']:
            raw = base64.b64decode(a['source'], validate=True)
            c.require(c.sha(raw) == a['sha256'] and len(raw) <= 4*1024**2
                      and Path(a['path']).is_relative_to(r['cache_root']) and a['calls'] == a['returns'] > 0,
                      'artifact evidence differs')
    return delta

def pair(a,b,digest,nonce,job):
    da, db = child(a,'reference',digest,nonce,job), child(b,'observed',digest,nonce,job)
    c.require(a['pid'] != b['pid'] and a['cache_root'] != b['cache_root'], 'cold children not distinct')
    c.require(a['before'] == b['before'] and a['eager'] == b['eager'], 'matched input/state/eager baseline differs')
    d = [difference(x,y) for x,y in zip(a['outputs'],b['outputs'])]
    c.require(max(d) <= 1e-6, 'observer endpoint interference')
    return dict(status='NATIVE_SYNTHETIC_CPU_PAIR_PASS', max_abs=d, bit_exact=a['outputs']==b['outputs'],
                eager_max_abs={'reference':da,'observed':db}, target_generated_artifacts_executed=True,
                scope='two synthetic CPU forwards only; no production/GPU claim', ready_for_gpu=False,
                production_model_loaded=False, production_interference_validated=False)

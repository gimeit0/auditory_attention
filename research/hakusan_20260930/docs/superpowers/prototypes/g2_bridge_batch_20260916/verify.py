"""Read-only verification using the previously pinned CPU bridge protocol."""
import importlib.util
import json
from pathlib import Path
import sys
import common as c

HERE = Path(__file__).resolve().parent


def protocol():
    # Both local review and compute execution load their pinned caller-owned
    # copy, never an executable path provided by a downloaded result.
    path = HERE.parents[3] / c.CORE_PREFIX / 'protocol.py'
    c.require(c.sha(c.read(path)) == c.CORE_FILES[c.CORE_PREFIX + 'protocol.py'], 'core verifier changed')
    spec = importlib.util.spec_from_file_location('g2_batch_core_protocol', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def child(value, profile, role, nonce, job):
    c.require(value['allocation_job_id'] == job, 'child job binding differs')
    protocol().child(value, profile=profile, role=role, native=True, release_sha=c.CORE_SHA, nonce=nonce)
    if role == 'observed':
        backend = value['backend']
        c.require(backend['production_ready'] is False and backend['interference_validated'] is False,
                  'compiler scope overstated')
        for item in backend['artifacts']:
            path, cache = Path(item['path']), Path(value['cache_root'])
            c.require(path.is_absolute() and '..' not in path.parts and path.is_relative_to(cache),
                      'generated artifact outside bound cache')


def pair(first, second, nonce, job):
    for role, value in (('reference', first), ('observed', second)):
        child(value, first['profile'], role, nonce, job)
    return protocol().pair(first, second, native=True, release_sha=c.CORE_SHA, nonce=nonce)


def matrix(values, nonce, job):
    order = ['R-reference', 'R-observed', 'C-reference', 'C-observed']
    c.require(list(values) == order, 'four cold stages in fixed order required')
    c.require(len({r['pid'] for r in values.values()}) == 4
              and len({r['cache_root'] for r in values.values()}) == 4, 'process/cache reused across profiles')
    for stage, value in values.items():
        profile, role = stage.split('-')
        child(value, profile, role, nonce, job)
    pairs = [pair(values[n+'-reference'], values[n+'-observed'], nonce, job) for n in 'RC']
    return dict(status='NATIVE_SYNTHETIC_TWO_PASS_BRIDGE_VERIFIED', pairs=pairs,
                production_model_loaded=False, production_interference_validated=False,
                ready_for_gpu=False, scope='synthetic CPU only; no production/GPU/checkpoint comparison')

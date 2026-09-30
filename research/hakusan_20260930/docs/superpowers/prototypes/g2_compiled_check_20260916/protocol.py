"""Small CPU bridge pair protocol; numeric artifacts never authorize production."""
import base64
import hashlib
import json

import numpy as np

NATIVE_SCOPE = 'NATIVE_SYNTHETIC_G2_COMPILED_BRIDGE'
LOCAL_SCOPE = 'LOCAL_SYNTHETIC_G2_EAGER_BRIDGE'
ORDER = (('R', 'reference'), ('R', 'observed'), ('C', 'reference'), ('C', 'observed'))
LIMITS = dict(cpus=1, memory_mib=6000, gpus=0, wall_seconds=1320,
              child_seconds=300, coordinator_seconds=1260, max_jobs=1)
BOUNDARIES = ('raw_scene', 'raw_cue', 'normalized_scene', 'normalized_cue',
              'scene_features', 'cue_features', 'native_logits', 'log_probabilities')
OFFICIAL = ('pred_label', 'nll', 'p_target', 'p_probe_distractor')
COMPILER_PINS = {
    'torch': '7261130fcc9dae49bb38843604ae2d0cab8d6b7277eb57b5dbc1559e35e34be1',
    'torch._dynamo.eval_frame': 'a98df135208704b66f681646a3d9649b75cbe5a3093fc59e4650b44460c1921b',
    'torch._inductor.compile_fx': 'f59ef50fc045e4d3d6a38f1576bd4fd4f9287128cbf4b6ff5534e0d7b3fe635d',
    'torch._inductor.codecache': '6d21a794502ced94ae5bb21a82968442cb049707c5c358161cb7a37b5c98295d',
}


def trials():
    return [dict(ordinal=i, bank_row_index=20+i, trial_id=100+i,
                 identity=dict(trial_id=100+i, target_label=i, probe_distractor_label=i+1,
                     scene_kind='mixed', control_subset=0, distractor_count=1,
                     snr_bin=0, snr_db=-3., target_gender='synthetic', target_speaker='synthetic'))
            for i in range(32)]


def rng(record):
    require(set(record) == {'cuda_device_count', 'families'} and record['cuda_device_count'] == 0
            and set(record['families']) == {'python', 'numpy', 'torch_cpu'}, 'CPU RNG families differ')
    for name, item in record['families'].items():
        require(set(item) == {'family', 'encoding', 'state', 'sha256'} and item['family'] == name
                and item['encoding'] == ('base64-raw' if name == 'torch_cpu' else 'base64-pickle-v4')
                and len(item['state']) < 100000, 'RNG record schema differs')
        # Never unpickle a returned artifact.
        require(sha(base64.b64decode(item['state'], validate=True)) == item['sha256'], 'RNG digest differs')


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def encode(array):
    require(type(array) is np.ndarray and array.dtype.str in ('<f4', '<i8')
            and 0 < array.nbytes <= 1024**2 and np.isfinite(array).all(), 'bounded finite float32/int64 required')
    raw = array.tobytes(order='C')
    return dict(shape=list(array.shape), dtype=array.dtype.str, nbytes=len(raw), sha256=sha(raw),
                data=base64.b64encode(raw).decode('ascii'))


def decode(record):
    require(type(record) is dict and set(record) == {'shape', 'dtype', 'nbytes', 'sha256', 'data'}, 'array schema differs')
    shape = record['shape']
    require(type(shape) is list and 1 <= len(shape) <= 4 and all(type(n) is int and 0 < n <= 800 for n in shape),
            'array shape differs')
    require(record['dtype'] in ('<f4', '<i8') and type(record['nbytes']) is int
            and 0 < record['nbytes'] <= 1024**2 and len(record['data']) <= 1400000, 'array budget/dtype differs')
    raw = base64.b64decode(record['data'], validate=True)
    dtype = np.dtype(record['dtype'])
    require(len(raw) == record['nbytes'] == int(np.prod(shape)) * dtype.itemsize
            and sha(raw) == record['sha256'], 'array bytes differ')
    value = np.frombuffer(raw, dtype=dtype).reshape(shape)
    require(np.isfinite(value).all(), 'nonfinite array')
    return value


def child(value, *, profile, role, native, release_sha, nonce):
    require(profile in (('R', 'C') if native else ('D', 'E')) and role in ('reference', 'observed'), 'unexpected child')
    require(value['scope'] == (NATIVE_SCOPE if native else LOCAL_SCOPE) and value['profile'] == profile
            and value['role'] == role and value['release_sha256'] == release_sha and value['nonce'] == nonce,
            'child binding/scope differs')
    require(value['complete_passes'] == 2 and value['forward_calls'] == 34 and value['strict_loads'] == 1
            and value['raw_batch_sizes'] == [16, 16] + [1] * 32
            and value['amp_enabled'] is False and value['state_unchanged'] is True
            and value['rng_unchanged'] is True and value['profiler_removed'] is True,
            'incomplete or changed model execution')
    require(all(value[k] is False for k in ('production_model_loaded', 'cuda_initialized', 'ready_for_gpu',
                                           'production_interference_validated')) and value['jobs_submitted'] == 0,
            'overstated scope')
    require(type(value['pid']) is int and value['pid'] > 0 and value['source_postcheck'] is True, 'process/source binding missing')
    require(value['trials'] == trials(), 'complete synthetic trial identities differ')
    tf32 = profile in ('R', 'D')
    require(value['runtime'] == dict(deterministic_algorithms=True, cudnn_deterministic=True,
            cudnn_benchmark=False, float32_matmul_precision='high' if tf32 else 'highest',
            cuda_matmul_allow_tf32=tf32, cudnn_allow_tf32=tf32) and value['fixture_seed'] == 0,
            'runtime/seed differs')
    require(value['test_model_preinjection_used'] is True and value['production_load_chronology_validated'] is False,
            'hermetic preparation scope overstated')
    require(value['model_state'] == value['model_state_after'] and set(value['model_state']) == {'anchor'},
            'model state differs')
    require(np.array_equal(decode(value['model_state']['anchor']), np.ones(1, dtype=np.float32)), 'anchor differs')
    rng(value['rng_before']); rng(value['rng_after'])
    require(value['rng_before'] == value['rng_after'], 'RNG changed')
    passes = value['passes']
    require(len(passes) == 2, 'missing pass')
    for index, part in enumerate(passes):
        require(part['pass_id'] == 'pass' + str(index + 1) and part['batch_size'] == (16, 1)[index]
                and part['trial_ids'] == [t['trial_id'] for t in value['trials']]
                and set(part['boundaries']) == set(BOUNDARIES) and set(part['outputs']) == set(OFFICIAL), 'pass inventory differs')
        require(type(part['original_commitment']) is str and len(part['original_commitment']) == 64
                and all(c in '0123456789abcdef' for c in part['original_commitment']), 'missing original commitment')
        for name, record in {**part['boundaries'], **part['outputs']}.items():
            array = decode(record)
            expected = (32, 800) if name in ('native_logits', 'log_probabilities') else (32,) if name in OFFICIAL else (32, 2, 4)
            require(array.shape == expected and array.dtype == (np.int64 if name == 'pred_label' else np.float32),
                    'unexpected endpoint shape/dtype: ' + name)
    backend = value['backend']
    if native:
        require(value['python'] == '3.11.5' and value['torch'] == '2.1.1+cu118'
                and type(value['allocation_job_id']) is str and value['allocation_job_id'].isdigit()
                and value['compiler_lifecycle_verified'] is True and value['compiler_target_verified'] is True,
                'native compiler lifecycle/version not verified')
        if role == 'observed':
            require(type(backend) is dict and backend['target_generated_artifacts_executed'] is True
                    and type(backend['compiler_calls']) is int and backend['compiler_calls'] > 0
                    and backend['compiler_calls'] == backend['compiler_returns'] and backend['artifacts']
                    and backend['compiler_sources'] == COMPILER_PINS,
                    'missing target compiler execution')
            for item in backend['artifacts']:
                raw = base64.b64decode(item['source'], validate=True)
                require(len(raw) <= 4 * 1024**2 and sha(raw) == item['sha256']
                        and type(item['calls']) is int and item['calls'] == item['returns'] > 0, 'generated artifact evidence differs')
        else:
            require(backend is None, 'reference must not install observer')
    else:
        require(value['compiler_lifecycle_verified'] is False and value['compiler_target_verified'] is False
                and value['allocation_job_id'] is None
                and backend is None, 'local eager run must not claim native compilation')
    return value


def pair(reference, observed, *, native, release_sha, nonce):
    profile = reference['profile']
    for role, value in (('reference', reference), ('observed', observed)):
        child(value, profile=profile, role=role, native=native, release_sha=release_sha, nonce=nonce)
    require(reference['pid'] != observed['pid'] and reference['cache_root'] != observed['cache_root'], 'cold processes/caches reused')
    for key in ('runtime', 'trials', 'model_state', 'rng_before', 'rng_after', 'fixture_seed'):
        require(reference[key] == observed[key], 'pair context differs: ' + key)
    differences, exact = {}, True
    for first, second in zip(reference['passes'], observed['passes']):
        for family in ('boundaries', 'outputs'):
            for name, record in first[family].items():
                other = second[family][name]
                a, b = decode(record), decode(other)
                same = record == other
                exact = exact and same
                delta = float(np.abs(a.astype(np.float64) - b.astype(np.float64)).max())
                require(np.array_equal(a, b) if name == 'pred_label' else delta <= 1e-6,
                        'observer endpoint differs: ' + first['pass_id'] + '/' + name)
                differences[first['pass_id'] + '/' + name] = delta
    return dict(status='NATIVE_SYNTHETIC_BRIDGE_PAIR_PASS' if native else 'LOCAL_EAGER_BRIDGE_PAIR_PASS',
                profile=profile, bit_exact=exact, max_abs=differences, production_interference_validated=False,
                production_model_loaded=False, ready_for_gpu=False, jobs_submitted=0)

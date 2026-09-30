"""Fixed-source, fixed-receipt read-only review; never executes a probe."""
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBE = HERE.parent / 'prototypes/targeted_scratch_timing_20260915'
SOURCES = {
    'timing_child.py': 'db7565a07f9f20ae1bb5f1198034886af50d971770bd8d9da8003a06e5bcd133',
    'run_timing.py': 'e391227ab994db1b204a96e587d3f331f3cfdfdece786ba78c68fad451c4c20c',
    'test_timing.py': '3b2acc9793421e399ba40c2a5c3b7ca1530375e2f79282d311ae83b901ffa5ad',
}
BUNDLES = [
    ('v19-cpu-timing-local_harness-20260915T051849Z-epoxgzfd',
     '61475e02091802eb591ec3364cb8adf69e785e4197b3f62634537800067bb505', True),
    ('v19-cpu-timing-native_cpu-20260915T052238Z-ruc59wt8',
     'd45ab178c012f66053aa70de00f508477216d6a64e720e9628cbd632c140c377', False),
]


def read_sha(path, expected):
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise RuntimeError('regular non-symlink source/evidence required')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError('fixed source/evidence changed: ' + str(path))
    return raw


def main():
    for name, expected in SOURCES.items():
        read_sha(PROBE / name, expected)
    spec = importlib.util.spec_from_file_location('pinned_timing_read_only_review', PROBE / 'run_timing.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    results = []
    for name, expected, completed in BUNDLES:
        folder = HERE / name
        read_sha(folder / 'receipt.json', expected)
        result = module.verify_bundle(folder)
        if result['instrumented_tests_completed'] is not completed:
            raise RuntimeError('test completion reinterpreted')
        if not completed:
            if (result['last_outer_event']['label'] != 'fixture.expected_contract'
                    or result['last_outer_event']['edge'] != 'begin' or result['inner']
                    or '_safe_instance_dict' not in result['stack_snapshot']
                    or '_callable_graph_fingerprint_impl' not in result['stack_snapshot']):
                raise RuntimeError('native localization evidence differs')
        results.append({'receipt_sha256': expected, 'instrumented_tests_completed': completed,
            'outer_events': len(result['outer']), 'inner_events': len(result['inner']),
            'stack_snapshots': int(result['stack_snapshot'] is not None)})
    print(json.dumps({'status': 'FIXED_TIMING_EVIDENCE_REVIEW_PASS', 'bundles': results,
        'original_native_compatibility_verified': False, 'jobs_submitted': 0,
        'ready_for_gpu': False, 'read_only': True}, sort_keys=True))


if __name__ == '__main__':
    main()

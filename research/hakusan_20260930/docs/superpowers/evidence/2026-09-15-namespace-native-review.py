"""Read-only review of fixed local/native namespace subset evidence; no SSH."""
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBE = HERE.parent / 'prototypes/namespace_native_20260915'
SOURCES = {
    'child.py': '1463278097b7c24141da2347b9ea95f9028a12f0b1ebadd66a41dfb04469da0c',
    'run_native.py': '1b41600fe5fe60e280a24009dd09d04ffcba4ed57db5e41f839ae6979ec3c017',
    'test_native.py': '9982f36ec3e411046a8ecce8ba907259f99663543982b79724260d126f0af8fb',
}
BUNDLES = (
    ('namespace-local_harness-20260915T060552Z-qyhduscx',
     'a6a1a317db9785779f8fa3ffe79c590a7ef2b7e8ed5a0e6d56ac12a350720627', 'LOCAL_HARNESS'),
    ('namespace-native_cpu-20260915T060811Z-ulq1vgqg',
     '4f5be7b3a3e70e0c68745de4a9ae5bfd81684963f8020f3e5a0647697bf54fbb', 'NATIVE_CPU'),
)


def pinned(path, expected):
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise RuntimeError('regular non-symlink evidence required')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError('source/evidence changed: ' + str(path))
    return raw


def main():
    for name, digest in SOURCES.items():
        pinned(PROBE / name, digest)
    spec = importlib.util.spec_from_file_location('namespace_native_readonly_probe', PROBE / 'run_native.py')
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    checked, ids = [], None
    for name, digest, mode in BUNDLES:
        folder = HERE / name
        receipt = json.loads(pinned(folder / 'receipt.json', digest))
        result = probe.verify_bundle(folder, require_local=mode == 'LOCAL_HARNESS')
        if result['mode'] != mode or (ids is not None and result['test_ids'] != ids):
            raise RuntimeError('local/native test identities differ')
        ids = result['test_ids']
        checked.append({'mode': mode, 'receipt_sha256': digest, 'tests': result['tests'],
            'python': result['python'], 'torch': result['torch'],
            'elapsed_seconds': receipt['remote']['elapsed_seconds'],
            'temporary_directory_removed': receipt['remote']['temporary_directory_removed'],
            'microbenchmark_speedups': [r['speedup'] for r in result['microbenchmark']]})
    print(json.dumps({'status': 'FIXED_NAMESPACE_NATIVE_REVIEW_PASS', 'bundles': checked,
        'same_33_test_ids': True, 'candidate_only': True,
        'original_native_compatibility_verified': False, 'complete_inference_speedup_verified': False,
        'jobs_submitted': 0, 'ready_for_gpu': False, 'read_only': True}, sort_keys=True))


if __name__ == '__main__':
    main()

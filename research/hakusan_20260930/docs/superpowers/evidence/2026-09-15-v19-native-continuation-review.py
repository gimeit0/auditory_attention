"""Read-only review of the preserved CPU timeout and one bounded continuation."""
import ast
import base64
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE_SHA = 'c3729fb009a5b94b9fea44557fa168e4a68cf712f3d8d8481ead06382e498530'
TEST_SHA = 'f8213305bdd3fb2e201e1a9f8549325d53242cbc5d34f452c9dcd7a72125cd4a'
BUNDLES = [
    ('v19-scratch-local_harness-20260915T045750Z-_z_arfpq',
     'ba9a3fddf7fa879ecd47c8ea2ad87b8355b03287de83bb0eb0f60f85a9849b3f', 'LOCAL_HARNESS'),
    ('v19-scratch-native_cpu-20260915T050719Z-4mvl4z7h',
     '36316c36be181dce71ffd171047dbefd7795a5db5538db6684d2b2b9806db661', 'NATIVE_CPU'),
]


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink evidence')
    require(path.is_file() and path.stat().st_size <= 16 * 1024**2, 'bounded regular evidence required')
    return path.read_bytes()


def main():
    source = HERE / '2026-09-15-v19-scratch-only.py'
    require(sha(read(source)) == SOURCE_SHA, 'continuation source changed')
    require(sha(read(HERE / 'test_20260915_v19_scratch_only.py')) == TEST_SHA, 'continuation tests changed')
    loader = importlib.util.spec_from_file_location('review_only_scratch_continuation', source)
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    _, files = module.original_driver()
    parent = module.prior_evidence(files)
    derived = module.derived_payload()
    results = []
    for name, expected_sha, mode in BUNDLES:
        folder = HERE / name
        raw = read(folder / 'receipt.json')
        require(sha(raw) == expected_sha, 'receipt changed: ' + name)
        receipt = json.loads(raw)
        request = read(folder / 'request.py')
        output = read(folder / 'output.log')
        require(sha(request) == receipt['payload_sha256'] and sha(output) == receipt['output_sha256'],
                'request/output identity differs')
        first, payload = request.split(b'\n', 1)
        require(first.startswith(b'SPEC=') and payload == derived, 'derived supervisor differs')
        spec = ast.literal_eval(first[5:].decode())
        require({k: spec[k] for k in receipt['request']} == receipt['request'] and spec['mode'] == mode,
                'request binding differs')
        require(set(spec['files']) == set(files) and all(
            base64.b64decode(encoded, validate=True) == files[path] for path, encoded in spec['files'].items()),
            'exact transferred source closure differs')
        require(base64.b64decode(spec['child_source'], validate=True) == read(module.PROBE / 'child_checks.py'),
                'original child tests changed')
        lines = [s.removeprefix(module.PREFIX) for s in output.decode().splitlines() if s.startswith(module.PREFIX)]
        remote = receipt['remote']
        require(len(lines) == 1 and json.loads(lines[0]) == remote, 'result/output binding differs')
        require(all(remote[k] == spec[k] for k in receipt['request']), 'remote response identity differs')
        require(receipt['source_postcheck'] is True and receipt['followup_source_sha256'] == SOURCE_SHA
                and receipt['derived_payload_sha256'] == sha(derived)
                and receipt['parent_failed_receipt_sha256'] == module.PARENT_SHA,
                'provenance or source postcheck differs')
        require(receipt['original_attempt_status'] == 'CPU_PROBE_FAILED'
                and receipt['ready_for_gpu'] is False and receipt['jobs_submitted'] == 0
                and receipt['automatic_retry'] is False and remote['temporary_directory_removed'] is True,
                'old failure/scope/cleanup was relabeled')
        if mode == 'LOCAL_HARNESS':
            module.local_pass(folder / 'receipt.json', SOURCE_SHA)
        else:
            require(receipt['status'] == 'SCRATCH_SUBSET_FAILED' and receipt['combined_native_tests_covered'] == 78,
                    'native timeout was accepted')
            require(receipt['transport']['returncode'] == 2 and receipt['transport']['error'] is None
                    and remote['status'] == 'V19_CPU_CHECK_FAILED' and remote['elapsed_seconds'] < 90,
                    'bounded native termination differs')
            require(len(remote['groups']) == 1, 'extra/missing continuation group')
            row = remote['groups'][0]
            require(row['group'] == 'scratch_lifetime' and module.log_record(row) is None
                    and row['process']['returncode'] == -9
                    and row['process']['error'] == {'type': 'TimeoutError', 'message': 'child deadline reached'},
                    'native group not the recorded timeout')
            require(row['process']['log'] == parent['remote']['groups'][-1]['process']['log'],
                    'two timeout progress logs differ')
        results.append({'mode': mode, 'receipt_sha256': expected_sha, 'status': receipt['status']})
    print(json.dumps({'status': 'NATIVE_CPU_CONTINUATION_EVIDENCE_PASS', 'bundles': results,
        'parent_receipt_sha256': module.PARENT_SHA, 'verified_native_tests': 78, 'pending_native_tests': 2,
        'complete_native_compatibility_verified': False, 'source_files': len(files),
        'ready_for_gpu': False, 'jobs_submitted': 0, 'read_only': True}, sort_keys=True))


if __name__ == '__main__':
    main()

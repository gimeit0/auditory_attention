"""Fixed-source and fixed-receipt review. Does not run a probe or connect SSH."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = HERE.parent / 'prototypes/namespace_scan_20260915'
PINS = {
    'candidate.py': 'af92fe97d4b4af2db5490f9ab6f7fa72c1603e504f565e8180c481067c0fcbd6',
    'study.py': '874b175400ed887ee6ae0eacc838024c5b8dfcb5d9fe8c599e49cde4892d43f3',
    'test_namespace.py': 'd199bdc6683bfdf9ba2d28125a6dd9263961104e4df23c97f41940ea5690a884',
}
BUNDLES = (
    ('namespace-baseline-20260915T053416Z-s4ctklpm',
     'd5e22b9682a5b9bc5073571ab0e672dae08f87309e42ef11412ecbae5ba09369', True),
    ('namespace-candidate-20260915T053727Z-n0mcm5cb',
     '0ad220e854f18e0d5b1781d09ae3d3cdc722ea6b8c10112ca7baad4653d8b68c', False),
    ('namespace-candidate-20260915T053836Z-59jfn2mb',
     '77151872d3e431119330c17f7f3aa52642c5222612e2ba8bf129e97cb5baae81', True),
)
MANIFEST_SHA = 'c0b421d01d394f1fd3354eb74eb730e2d348cf4a37d0fb96f76a019c71c5aa20'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def read_checked(path, expected, size=None):
    require(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents)), 'regular non-symlink file required')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, 'SHA differs: ' + str(path))
    require(size is None or len(raw) == size, 'size differs: ' + str(path))
    return raw


def main():
    for name, expected in PINS.items():
        read_checked(SOURCE / name, expected)
    manifest = ROOT / 'docs/superpowers/prototypes/targeted_gpu_job_20260915_v5/SOURCE_MANIFEST.json'
    files = json.loads(read_checked(manifest, MANIFEST_SHA))['files']
    require(len(files) == 162, 'runtime inventory differs')
    for name, expected in files.items():
        path = Path(name)
        require(not path.is_absolute() and '..' not in path.parts, 'invalid source path')
        read_checked(ROOT / path, expected)
    bundles, artifacts = [], 0
    for name, digest, passed in BUNDLES:
        folder = HERE / name
        receipt = json.loads(read_checked(folder / 'receipt.json', digest))
        require((receipt['status'] == 'LOCAL_NAMESPACE_STUDY_PASS') is passed, 'historical result reinterpreted')
        require(receipt['frozen_sources_unchanged'] and receipt['new_sources_unchanged'], 'source mutation recorded')
        require(receipt['frozen_manifest_sha256'] == MANIFEST_SHA, 'frozen identity differs')
        require(receipt['jobs_submitted'] == 0 and not receipt['ready_for_gpu'] and not receipt['remote_executed'], 'scope differs')
        for relative, expected in receipt['source_sha256'].items():
            path = SOURCE / relative
            if not passed and relative == 'test_namespace.py':
                path = folder / 'test_namespace.failed-source.py'
            read_checked(path, expected)
        for relative, item in receipt['artifacts'].items():
            require(Path(relative).name == relative, 'invalid artifact path')
            read_checked(folder / relative, item['sha256'], item['size'])
            artifacts += 1
        results = []
        for process in receipt['processes']:
            label = process['label']
            record = json.loads((folder / (label + '-process.json')).read_bytes())
            require({k: v for k, v in process.items() if k != 'label'} == record, 'process binding differs')
            if passed:
                require(record['returncode'] == 0 and record['error'] is None, 'failed process accepted')
                value = json.loads((folder / (label + '-result.json')).read_bytes())
                require(value['pid'] == process['pid'] and value['label'] == label, 'child identity differs')
                require(not value['cuda_initialized'] and not value['production_model_loaded']
                        and not value['ready_for_gpu'] and value['jobs_submitted'] == 0, 'child scope differs')
                results.append(value)
        bundles.append((receipt, results))
    result = bundles[-1][1]
    tests = next(r for r in result if r['label'] == 'tests')
    require((tests['tests'], tests['new_tests'], tests['existing_tests'], tests['skips']) == (139, 15, 124, 0), 'test inventory differs')
    contracts = [r for _, group in bundles for r in group if 'contract' in r]
    require(all(r['contract'] == contracts[0]['contract'] for r in contracts), 'synthetic outputs/boundaries differ')
    for value in contracts:
        wire = (json.dumps(value['contract'], sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')
        require(hashlib.sha256(wire).hexdigest() == value['contract_sha256'], 'contract digest differs')
    spec = importlib.util.spec_from_file_location('review_namespace_overlay_only', SOURCE / 'candidate.py')
    overlay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(overlay)  # No core load, torch import or test execution.
    assembled = overlay.assemble()
    expected_assembled = hashlib.sha256(assembled.encode()).hexdigest()
    for value in result:
        expected = overlay.PARENT_SHA if value['variant'] == 'original' else expected_assembled
        require(value['assembled_sha256'] == expected, 'test implementation differs')
    nodes = [next(n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == overlay.NAME)
             for raw in (overlay.SOURCE.read_text(), assembled)]
    delta = nodes[1].end_lineno - nodes[0].end_lineno
    profiles = {r['variant']: r for r in result if r['cprofile']}
    old = {(f['function'], f['line']): (f['calls'], f['primitive_calls']) for f in profiles['original']['functions']
           if not (f['function'] == '<genexpr>' and nodes[0].lineno < f['line'] <= nodes[0].end_lineno)}
    new = {(f['function'], f['line'] - delta if f['line'] > nodes[1].end_lineno else f['line']):
           (f['calls'], f['primitive_calls']) for f in profiles['candidate']['functions']}
    # Includes duplicate method names and all OTHER anonymous guard expressions;
    # only the two deliberately lowered generator code objects are excluded.
    require(old == new and len(old) == 194, 'core code-object invocation counts differ')
    timings = {v: [r['wall_seconds'] for r in result if r['variant'] == v and 'contract' in r and not r['cprofile']]
               for v in ('original', 'candidate')}
    require(all(len(t) == 2 for t in timings.values()), 'A/B/B/A measurement inventory differs')
    median = {v: statistics.median(t) for v, t in timings.items()}
    require(median == bundles[-1][0]['summary']['medians_seconds'], 'timing summary differs')
    print(json.dumps({'status': 'FIXED_NAMESPACE_CANDIDATE_REVIEW_PASS', 'source_files': len(files),
        'artifacts': artifacts, 'tests': 139, 'unchanged_core_code_object_counts': len(old),
        'synthetic_contract_sha256': contracts[0]['contract_sha256'], 'median_unprofiled_seconds': median,
        'observed_duration_reduction_percent': 100 * (1 - median['candidate'] / median['original']),
        'failed_test_attempt_preserved': True, 'original_native_compatibility_verified': False,
        'ready_for_gpu': False, 'jobs_submitted': 0, 'read_only': True}, sort_keys=True))


if __name__ == '__main__':
    main()

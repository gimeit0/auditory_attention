"""Fixed-source temporary CPU subset; existing SSH master only, no retries or jobs."""
import argparse
import ast
import base64
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
EVIDENCE = ROOT / 'docs/superpowers/evidence'
PRIOR = HERE.parent / 'targeted_pair_native_20260915'
CANDIDATE = HERE.parent / 'namespace_scan_20260915'
REVIEW_SHA = '95f104d371d121e9478feaec756daa7483419621d6df01d770900e24720625a1'
DRIVER_SHA = 'e2f677c3067ce222e2ef4e72b0b77b300116f85110b2f6f8fda99fbbc070e6ec'
PAYLOAD_SHA = '5f634d48819f9e5a22a9de06d865c7fe0c2a47ce90b27efd61467c83f247f999'
LOCAL_CANDIDATE_SHA = '77151872d3e431119330c17f7f3aa52642c5222612e2ba8bf129e97cb5baae81'
ASSEMBLED_SHA = '6daa2ac0f4a606a681dc5acf17676afb41bc2dd79fbd9a43887a54497aef1e03'
PINS = {
    'candidate.py': 'af92fe97d4b4af2db5490f9ab6f7fa72c1603e504f565e8180c481067c0fcbd6',
    'study.py': '874b175400ed887ee6ae0eacc838024c5b8dfcb5d9fe8c599e49cde4892d43f3',
    'test_namespace.py': 'd199bdc6683bfdf9ba2d28125a6dd9263961104e4df23c97f41940ea5690a884',
}
PREFIX = 'NAMESPACE_CPU_RESULT='


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    require(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents))
            and path.stat().st_size <= 16 * 1024**2, 'bounded regular non-symlink file required')
    return path.read_bytes()


def load(path, expected, name):
    require(sha(read(path)) == expected, 'pinned helper differs: ' + path.name)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def derive_payload():
    raw = read(PRIOR / 'payload.py')
    require(sha(raw) == PAYLOAD_SHA, 'original supervisor differs')
    source = raw.decode()
    extras = {str((CANDIDATE / n).relative_to(ROOT)): s for n, s in PINS.items()}
    substitutions = (
        ("COUNTS = {'input_binding': 25, 'startup': 12, 'result_identity': 11, 'adapter_cpu': 30, 'scratch_lifetime': 2}",
         "COUNTS = {'namespace_subset': 33}\nCANDIDATE_PINS = " + repr(extras)),
        ("len(spec['files']) == 163", "len(spec['files']) == 166"),
        ("manifest = json.loads(files[MANIFEST])\n    require(set(files) == {*manifest['files'], MANIFEST}",
         "manifest = json.loads(files[MANIFEST])\n    bound = {**manifest['files'], **CANDIDATE_PINS}\n    require(set(files) == {*bound, MANIFEST}"),
        ("all(sha(files[n]) == s for n, s in manifest['files'].items())", "all(sha(files[n]) == s for n, s in bound.items())"),
        ("'v19-native-cpu-'", "'namespace-candidate-cpu-'"),
        ("'V19_CPU_CHILD='", "'NAMESPACE_CPU_CHILD='"),
        ("'V19_CPU_GROUP_BEGIN='", "'NAMESPACE_CPU_GROUP_BEGIN='"),
        ("'V19_CPU_GROUP_PASS='", "'NAMESPACE_CPU_GROUP_PASS='"),
        ("'NATIVE_V19_CPU_PASS'", "'NATIVE_NAMESPACE_SUBSET_PASS'"),
        ("'LOCAL_NATIVE_HARNESS_PASS'", "'LOCAL_NAMESPACE_SUBSET_PASS'"),
        ("'V19_CPU_CHECK_FAILED'", "'NAMESPACE_SUBSET_FAILED'"),
        ("'V19_NATIVE_RESULT='", repr(PREFIX)),
        ("'temporary synthetic CPU compatibility only; not real production/GPU/mount validation'",
         "'33 candidate CPU checks/microbenchmark only; not complete native compatibility or production/GPU validation'"),
    )
    for old, new in substitutions:
        require(source.count(old) == (2 if old == "'V19_CPU_CHILD='" else 1), 'supervisor derivation differs')
        source = source.replace(old, new)
    require('WALL_SECONDS = 90' in source and 'seconds=min(50, remaining)' in source
            and "os.sched_setaffinity(0, {min(allowed)})" in source, 'original bounds changed')
    return source.encode()


def sources():
    reviewer = load(EVIDENCE / '2026-09-15-namespace-candidate-review.py', REVIEW_SHA, 'namespace_prior_readonly')
    with contextlib.redirect_stdout(io.StringIO()):
        reviewer.main()
    driver = load(PRIOR / 'driver.py', DRIVER_SHA, 'namespace_original_cpu_driver')
    files, _ = driver.local_sources()
    for name, expected in PINS.items():
        raw = read(CANDIDATE / name)
        require(sha(raw) == expected, 'candidate source differs')
        files[str((CANDIDATE / name).relative_to(ROOT))] = raw
    require(len(files) == 166 and sum(map(len, files.values())) <= 16 * 1024**2, 'expanded test-only inventory differs')
    own = {n: read(HERE / n) for n in ('child.py', 'run_native.py', 'test_native.py')}
    return driver, files, derive_payload(), own


def response(remote, request, expected_ids=None):
    require(type(remote) is dict and remote['error'] is None, 'subset failed or incomplete')
    expected = 'NATIVE_NAMESPACE_SUBSET_PASS' if request['mode'] == 'NATIVE_CPU' else 'LOCAL_NAMESPACE_SUBSET_PASS'
    require(remote['status'] == expected, 'wrong subset status')
    for key in ('mode', 'request_id', 'package_sha256', 'child_sha256'):
        require(remote[key] == request[key], 'response identity differs: ' + key)
    require(remote['temporary_directory_removed'] is True and remote['permanent_files_written'] is False
            and remote['jobs_submitted'] == 0 and remote['production_model_loaded'] is False
            and remote['ready_for_gpu'] is False and remote['candidate_input_freeze_sha256'] is None
            and remote['automatic_retry'] is False and 0 <= remote['elapsed_seconds'] < 90, 'scope/cleanup/budget differs')
    require(len(remote['groups']) == 1, 'exactly one subset process required')
    row = remote['groups'][0]
    process, value = row['process'], row['record']
    require(row['group'] == 'namespace_subset' and process['returncode'] == 0 and process['error'] is None,
            'subset process did not complete')
    require(value['pid'] == process['pid'] and value['mode'] == request['mode']
            and value['group'] == row['group'] and value['status'] == 'SYNTHETIC_CPU_SUITE_PASS'
            and value['tests'] == 33 and value['errors'] == value['failures'] == value['skips'] == 0,
            'tests/child identity differ')
    require(value['assembled_sha256'] == ASSEMBLED_SHA and value['cuda_initialized'] is False
            and value['production_model_loaded'] is False and value['production_snapshot_loaded'] is False
            and value['full_expected_contract_executed'] is False and value['original_native_compatibility_verified'] is False
            and value['jobs_submitted'] == 0 and value['ready_for_gpu'] is False, 'candidate scope differs')
    ids = value['test_ids']
    require(type(ids) is list and all(type(i) is str for i in ids) and len(ids) == len(set(ids)) == 33, 'test identities differ')
    require(sum('.NamespaceTests.' in i for i in ids) == 15
            and sum(i.startswith('namespace_overlay_test_binding_scan.') for i in ids) == 5
            and sum(i.startswith('namespace_overlay_test_module_name_classification.') for i in ids) == 13,
            'test subset coverage differs')
    if expected_ids is not None:
        require(ids == expected_ids, 'local/native test IDs differ')
    if request['mode'] == 'NATIVE_CPU':
        require(value['python'] == '3.11.5' and value['torch'] == '2.1.1+cu118'
                and type(value['cpu_affinity']) is list and len(value['cpu_affinity']) == 1,
                'native environment differs')
    raw = base64.b64decode(row['log_base64'], validate=True)
    require(len(raw) <= 1024**2 and process['log'] == {'name': 'namespace_subset.log', 'size': len(raw), 'sha256': sha(raw)},
            'child log binding differs')
    lines = [s.removeprefix('NAMESPACE_CPU_CHILD=') for s in raw.decode().splitlines() if s.startswith('NAMESPACE_CPU_CHILD=')]
    require(len(lines) == 1 and json.loads(lines[0]) == value, 'child summary missing from log')
    timings = value['microbenchmark']
    require([r['namespace_keys'] for r in timings] == [8, 256, 3000], 'microbenchmark sizes differ')
    for r in timings:
        require(r['calls_per_repeat'] == 2000 and r['repeats'] == 6 and set(r['unprofiled_seconds']) == {'original', 'candidate'},
                'microbenchmark schedule differs')
        for variant, times in r['unprofiled_seconds'].items():
            require(len(times) == 6 and all(type(t) in (int, float) and math.isfinite(t) and t > 0 for t in times)
                    and statistics.median(times) == r['median_seconds'][variant], 'timing summary differs')
        require(r['speedup'] == r['median_seconds']['original'] / r['median_seconds']['candidate'], 'speedup differs')
    return value


def verify_bundle(folder, *, require_local=False):
    driver, files, payload, own = sources()
    receipt = json.loads(read(folder / 'receipt.json'))
    request = read(folder / 'request.py')
    first, body = request.split(b'\n', 1)
    require(first.startswith(b'SPEC=') and body == payload, 'request source differs')
    spec = ast.literal_eval(first[5:].decode())
    require(set(spec['files']) == set(files) and all(base64.b64decode(spec['files'][n], validate=True) == raw for n, raw in files.items()),
            'temporary package request differs')
    require(base64.b64decode(spec['child_source'], validate=True) == own['child.py'] and spec['child_sha256'] == sha(own['child.py']),
            'child request differs')
    require(receipt['source_sha256'] == {n: sha(raw) for n, raw in own.items()} and receipt['source_postcheck'] is True
            and receipt['candidate_receipt_sha256'] == LOCAL_CANDIDATE_SHA
            and receipt['payload_sha256'] == sha(request), 'receipt source identity differs')
    output = read(folder / 'output.log')
    require(receipt['output_sha256'] == sha(output), 'output changed')
    lines = [s.removeprefix(PREFIX) for s in output.decode().splitlines() if s.startswith(PREFIX)]
    require(len(lines) == 1 and json.loads(lines[0]) == receipt['remote'], 'transport result differs')
    require({k: spec[k] for k in receipt['request']} == receipt['request'], 'receipt request summary differs')
    value = response(receipt['remote'], spec)
    require(receipt['status'] == 'NAMESPACE_SUBSET_VERIFIED' and receipt['error'] is None
            and receipt['transport']['returncode'] == 0 and receipt['transport']['error'] is None
            and receipt['jobs_submitted'] == 0 and receipt['ready_for_gpu'] is False, 'successful bound transport required')
    if require_local:
        require(spec['mode'] == 'LOCAL_HARNESS', 'local payload verification required first')
    return value


def operate(action, local):
    if action == 'review':
        require(local is not None, 'receipt folder required')
        value = verify_bundle(local)
        print(json.dumps({'status': 'NAMESPACE_SUBSET_REVIEW_PASS', 'mode': value['mode'], 'tests': value['tests'],
                         'speedups': [r['speedup'] for r in value['microbenchmark']], 'ready_for_gpu': False, 'jobs_submitted': 0}))
        return 0
    driver, files, derived, own = sources()
    native = action == 'remote-cpu'
    expected_ids = None
    if native:
        require(local is not None, 'matching local payload receipt required')
        expected_ids = verify_bundle(local, require_local=True)['test_ids']
    sys.path.insert(0, str(driver.CONTROL))
    import control
    if native:
        control.master_check(control.SOCKET)  # No reconnection/password collection.
    spec = driver.make_spec('NATIVE_CPU' if native else 'LOCAL_HARNESS', files)
    spec.update(child_source=base64.b64encode(own['child.py']).decode(), child_sha256=sha(own['child.py']))
    request = ('SPEC=' + repr(spec) + '\n').encode() + derived
    folder = Path(tempfile.mkdtemp(prefix='namespace-' + spec['mode'].lower() + '-'
        + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-', dir=EVIDENCE))
    print('NAMESPACE_CPU_EVIDENCE=' + str(folder), flush=True)
    command = control.ssh_command(control.SOCKET) if native else [sys.executable, '-I', '-B', '-']
    transport = control.transport(command, request, folder, timeout=110, log_cap=8 * 1024**2)
    output = read(folder / 'output.log')
    remote, value, error = None, None, None
    try:
        lines = [s.removeprefix(PREFIX) for s in output.decode().splitlines() if s.startswith(PREFIX)]
        require(len(lines) == 1, 'one structured response required')
        remote = json.loads(lines[0])
        value = response(remote, spec, expected_ids)
        require(transport['returncode'] == 0 and transport['error'] is None, 'transport failed; no automatic retry')
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    _, after_files, after_payload, after_own = sources()
    stable = (files, derived, own) == (after_files, after_payload, after_own)
    require(stable, 'sources changed during check')
    receipt = {'status': 'NAMESPACE_SUBSET_VERIFIED' if error is None else 'NAMESPACE_SUBSET_NOT_VERIFIED',
        'candidate_receipt_sha256': LOCAL_CANDIDATE_SHA, 'source_sha256': {n: sha(raw) for n, raw in own.items()},
        'request': {k: spec[k] for k in ('mode', 'request_id', 'package_sha256', 'child_sha256')},
        'payload_sha256': sha(request), 'output_sha256': sha(output), 'source_postcheck': stable,
        'transport': transport, 'remote': remote, 'error': error, 'automatic_retry': False,
        'jobs_submitted': 0, 'ready_for_gpu': False, 'original_native_compatibility_verified': False}
    control.ops.write_new(folder / 'receipt.json', control.ops.wire(receipt))
    print(json.dumps({'status': receipt['status'], 'error': error, 'receipt': str(folder / 'receipt.json'),
        'tests': value['tests'] if value else None, 'jobs_submitted': 0,
        'scope': 'namespace candidate subset only; not the full v19 compatibility suite'}), flush=True)
    return 0 if error is None else 2


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('self-test', 'remote-cpu', 'review'))
    parser.add_argument('--receipt-directory', type=Path)
    args = parser.parse_args()
    raise SystemExit(operate(args.action, args.receipt_directory))

"""Explicit one-time continuation of a timed-out synthetic CPU test group.

The old failed receipt and all runtime sources remain unchanged. Derive only a
one-group CPU payload from the pinned old supervisor, with distinct subset
status names. The original 90s total / 50s child bounds are unchanged. No GPU,
production model, deployment, input freeze, reconnection, or automatic retry.
"""
import argparse
import ast
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PROBE = ROOT / 'docs/superpowers/prototypes/targeted_pair_native_20260915'
PARENT = HERE / 'v19-native_cpu-20260915T044848Z-asqdz_1u'
PARENT_SHA = 'c40a8cbc84f88fbadffdf8df077e50f41b7058c7f950faf4185aab55b5f95081'
RELEASE_SHA = '4d2f742eea588eaaea8015538f48c8122d1258ed795c276eb86272d4840128da'
DRIVER_SHA = 'e2f677c3067ce222e2ef4e72b0b77b300116f85110b2f6f8fda99fbbc070e6ec'
OLD_PAYLOAD_SHA = '5f634d48819f9e5a22a9de06d865c7fe0c2a47ce90b27efd61467c83f247f999'
OLD_COUNTS = "COUNTS = {'input_binding': 25, 'startup': 12, 'result_identity': 11, 'adapter_cpu': 30, 'scratch_lifetime': 2}"
PREFIX = 'V19_SCRATCH_ONLY_RESULT='


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink source/evidence')
    require(path.is_file() and path.stat().st_size <= 16 * 1024**2, 'bounded regular file required')
    return path.read_bytes()


def original_driver():
    require(sha(read(PROBE / 'PROBE_RELEASE.json')) == RELEASE_SHA, 'old release changed')
    source = PROBE / 'driver.py'
    require(sha(read(source)) == DRIVER_SHA, 'old driver changed')
    loader = importlib.util.spec_from_file_location('fixed_cpu_driver_for_continuation', source)
    driver = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(driver)
    files, release_sha = driver.local_sources()
    require(release_sha == RELEASE_SHA, 'fixed source closure differs')
    return driver, files


def log_record(row):
    raw = base64.b64decode(row['log_base64'], validate=True)
    require(len(raw) <= 1024**2 and row['process']['log'] == {
        'name': row['group'] + '.log', 'size': len(raw), 'sha256': sha(raw)}, 'child log identity differs')
    lines = [s.removeprefix('V19_CPU_CHILD=') for s in raw.decode().splitlines()
             if s.startswith('V19_CPU_CHILD=')]
    value = json.loads(lines[0]) if len(lines) == 1 else None
    require(len(lines) <= 1 and value == row['record'], 'child result/log binding differs')
    return value


def passed_group(row, group, count, mode):
    result = log_record(row)
    process = row['process']
    require(row['group'] == group and process['returncode'] == 0 and process['error'] is None
            and type(result) is dict and result['pid'] == process['pid'], 'child did not finish successfully')
    require(result['status'] == 'SYNTHETIC_CPU_SUITE_PASS' and result['group'] == group
            and result['mode'] == mode and result['tests'] == count
            and result['errors'] == result['failures'] == result['skips'] == 0, 'test coverage differs')
    require(result['cuda_initialized'] is False and result['production_model_loaded'] is False
            and result['jobs_submitted'] == 0, 'CPU scope exceeded')
    if mode == 'NATIVE_CPU':
        require(result['python'] == '3.11.5' and result['torch'] == '2.1.1+cu118'
                and type(result['cpu_affinity']) is list and len(result['cpu_affinity']) == 1,
                'native one-CPU environment differs')
    return result


def prior_evidence(files):
    raw = read(PARENT / 'receipt.json')
    require(sha(raw) == PARENT_SHA, 'preserved failed receipt changed')
    receipt = json.loads(raw)
    request = read(PARENT / 'request.py')
    output = read(PARENT / 'output.log')
    require(sha(request) == receipt['payload_sha256'] and sha(output) == receipt['output_sha256'],
            'old request/output changed')
    first, payload = request.split(b'\n', 1)
    require(first.startswith(b'SPEC=') and payload == read(PROBE / 'payload.py'), 'old payload differs')
    spec = ast.literal_eval(first[5:].decode())
    require(set(spec['files']) == set(files)
            and all(base64.b64decode(v, validate=True) == files[n] for n, v in spec['files'].items()),
            'old transferred runtime sources differ')
    require(base64.b64decode(spec['child_source'], validate=True) == read(PROBE / 'child_checks.py'),
            'old test source differs')
    require({k: spec[k] for k in receipt['request']} == receipt['request'], 'old request binding differs')
    lines = [s.removeprefix('V19_NATIVE_RESULT=') for s in output.decode().splitlines()
             if s.startswith('V19_NATIVE_RESULT=')]
    require(len(lines) == 1 and json.loads(lines[0]) == receipt['remote'], 'old response/log differs')
    remote = receipt['remote']
    require(receipt['status'] == 'CPU_PROBE_FAILED' and receipt['source_postcheck'] is True
            and receipt['probe_release_sha256'] == RELEASE_SHA
            and receipt['transport']['returncode'] == 2 and receipt['transport']['error'] is None
            and remote['status'] == 'V19_CPU_CHECK_FAILED' and remote['mode'] == 'NATIVE_CPU'
            and remote['temporary_directory_removed'] is True, 'not the reviewed bounded failure')
    require(all(remote[k] == spec[k] for k in receipt['request']), 'old remote binding differs')
    require(len(remote['groups']) == 5, 'prior groups missing')
    first_groups = [('input_binding', 25), ('startup', 12), ('result_identity', 11), ('adapter_cpu', 30)]
    records = [passed_group(row, name, count, 'NATIVE_CPU')
               for row, (name, count) in zip(remote['groups'][:4], first_groups)]
    last = remote['groups'][-1]
    require(last['group'] == 'scratch_lifetime' and log_record(last) is None
            and last['process']['returncode'] == -9
            and last['process']['error'] == {'type': 'TimeoutError', 'message': 'child deadline reached'},
            'prior last group was not a bounded timeout')
    require(len({r['pid'] for r in records}) == 4, 'prior cold processes differ')
    return receipt


def derived_payload():
    raw = read(PROBE / 'payload.py')
    require(sha(raw) == OLD_PAYLOAD_SHA, 'old supervisor changed')
    text = raw.decode()
    for old, new in (
        (OLD_COUNTS, "COUNTS = {'scratch_lifetime': 2}"),
        ("'NATIVE_V19_CPU_PASS'", "'NATIVE_V19_SCRATCH_ONLY_PASS'"),
        ("'LOCAL_NATIVE_HARNESS_PASS'", "'LOCAL_SCRATCH_ONLY_PASS'"),
        ("'V19_NATIVE_RESULT='", repr(PREFIX)),
        ("'temporary synthetic CPU compatibility only; not real production/GPU/mount validation'",
         "'two-test synthetic scratch subset only; not complete compatibility or production/GPU/mount validation'"),
    ):
        require(text.count(old) == 1, 'supervisor derivation is not exact')
        text = text.replace(old, new)
    require('WALL_SECONDS = 90' in text and 'seconds=min(50, remaining)' in text, 'time bounds changed')
    return text.encode()


def check_subset(remote, spec):
    expected = 'NATIVE_V19_SCRATCH_ONLY_PASS' if spec['mode'] == 'NATIVE_CPU' else 'LOCAL_SCRATCH_ONLY_PASS'
    require(remote['status'] == expected and remote['error'] is None, 'scratch subset did not pass')
    for key in ('request_id', 'mode', 'package_sha256', 'child_sha256'):
        require(remote[key] == spec[key], 'subset response identity differs')
    require(remote['temporary_directory_removed'] is True and remote['permanent_files_written'] is False
            and remote['production_model_loaded'] is False and remote['ready_for_gpu'] is False
            and remote['jobs_submitted'] == 0 and remote['automatic_retry'] is False
            and remote['candidate_input_freeze_sha256'] is None and 0 <= remote['elapsed_seconds'] < 90,
            'subset scope/deadline differs')
    require(len(remote['groups']) == 1, 'exactly one scratch group required')
    row = remote['groups'][0]
    require(0 <= row['process']['elapsed_seconds'] < 50, 'scratch child deadline exceeded')
    passed_group(row, 'scratch_lifetime', 2, spec['mode'])


def local_pass(path, source_sha):
    receipt = json.loads(read(path))
    require(receipt['status'] == 'LOCAL_SCRATCH_SUBSET_VERIFIED'
            and receipt['followup_source_sha256'] == source_sha
            and receipt['derived_payload_sha256'] == sha(derived_payload())
            and receipt['source_postcheck'] is True
            and receipt['parent_failed_receipt_sha256'] == PARENT_SHA,
            'matching local subset self-test required')
    require(receipt['request']['mode'] == 'LOCAL_HARNESS'
            and receipt['transport']['returncode'] == 0 and receipt['transport']['error'] is None,
            'local subset mode/exit differs')
    check_subset(receipt['remote'], receipt['request'])


def operate(action, local_receipt):
    driver, files = original_driver()
    parent = prior_evidence(files)
    derived = derived_payload()
    source_sha = sha(read(Path(__file__).resolve()))
    if action == 'review-parent':
        print(json.dumps({'status': 'NATIVE_FAILURE_EVIDENCE_VERIFIED', 'completed_tests': 78,
            'unfinished_tests': 2, 'parent_receipt_sha256': PARENT_SHA,
            'derived_payload_sha256': sha(derived), 'jobs_submitted': 0, 'read_only': True}))
        return 0
    native = action == 'remote-cpu'
    if native:
        require(local_receipt is not None, 'successful local subset receipt required')
        local_pass(local_receipt, source_sha)
    sys.path.insert(0, str(driver.CONTROL))
    import control
    if native:
        control.master_check(control.SOCKET)
    spec = driver.make_spec('NATIVE_CPU' if native else 'LOCAL_HARNESS', files)
    payload = ('SPEC=' + repr(spec) + '\n').encode() + derived
    folder = Path(tempfile.mkdtemp(prefix='v19-scratch-' + spec['mode'].lower() + '-'
        + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-', dir=HERE))
    print('SCRATCH_SUBSET_EVIDENCE=' + str(folder), flush=True)
    command = control.ssh_command(control.SOCKET) if native else [sys.executable, '-I', '-B', '-']
    outcome = control.transport(command, payload, folder, timeout=110, log_cap=8 * 1024**2)
    output = read(folder / 'output.log')
    remote, error = None, None
    try:
        lines = [s.removeprefix(PREFIX) for s in output.decode().splitlines() if s.startswith(PREFIX)]
        require(len(lines) == 1, 'one subset result required')
        remote = json.loads(lines[0])
        check_subset(remote, spec)
        require(outcome['returncode'] == 0 and outcome['error'] is None, 'abnormal transport exit')
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    stable = driver.local_sources()[0] == files and prior_evidence(files) == parent
    require(stable and sha(read(Path(__file__).resolve())) == source_sha, 'local sources/evidence changed')
    status = ('NATIVE_SCRATCH_SUBSET_VERIFIED' if native else 'LOCAL_SCRATCH_SUBSET_VERIFIED') if error is None else 'SCRATCH_SUBSET_FAILED'
    value = {'status': status, 'followup_source_sha256': source_sha,
        'derived_payload_sha256': sha(derived), 'parent_failed_receipt_sha256': PARENT_SHA,
        'request': {k: spec[k] for k in ('mode', 'request_id', 'package_sha256', 'child_sha256')},
        'payload_sha256': sha(payload), 'output_sha256': sha(output), 'transport': outcome,
        'remote': remote, 'error': error, 'source_postcheck': stable,
        'combined_native_tests_covered': 80 if native and error is None else 78,
        'original_attempt_status': 'CPU_PROBE_FAILED', 'ready_for_gpu': False,
        'jobs_submitted': 0, 'automatic_retry': False}
    control.ops.write_new(folder / 'receipt.json', control.ops.wire(value))
    print(json.dumps({'status': status, 'error': error, 'combined_native_tests_covered': value['combined_native_tests_covered'],
        'receipt': str(folder / 'receipt.json'), 'jobs_submitted': 0}), flush=True)
    return 0 if error is None else 2


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('review-parent', 'self-test', 'remote-cpu'))
    parser.add_argument('--local-receipt', type=Path)
    args = parser.parse_args()
    return operate(args.action, args.local_receipt)


if __name__ == '__main__':
    raise SystemExit(main())

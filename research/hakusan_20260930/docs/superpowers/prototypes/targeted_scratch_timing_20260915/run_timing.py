"""Bounded synthetic CPU localization, not a compatibility or GPU release gate."""
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
ROOT = HERE.parents[3]
EVIDENCE = ROOT / 'docs/superpowers/evidence'
PRIOR_SHA = 'c3729fb009a5b94b9fea44557fa168e4a68cf712f3d8d8481ead06382e498530'
LAST = EVIDENCE / 'v19-scratch-native_cpu-20260915T050719Z-4mvl4z7h/receipt.json'
LAST_SHA = '36316c36be181dce71ffd171047dbefd7795a5db5538db6684d2b2b9806db661'
PREFIX = 'V19_TIMING_RESULT='


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink source/evidence')
    require(path.is_file() and path.stat().st_size <= 16 * 1024**2, 'bounded regular source required')
    return path.read_bytes()


def sources():
    path = EVIDENCE / '2026-09-15-v19-scratch-only.py'
    require(sha(read(path)) == PRIOR_SHA and sha(read(LAST)) == LAST_SHA, 'prior source/failure changed')
    spec = importlib.util.spec_from_file_location('fixed_scratch_probe_for_localization', path)
    prior = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prior)
    driver, files = prior.original_driver()
    prior.prior_evidence(files)
    text = prior.derived_payload().decode()
    for old, new in (
        ("'NATIVE_V19_SCRATCH_ONLY_PASS'", "'NATIVE_TIMING_TESTS_FINISHED'"),
        ("'LOCAL_SCRATCH_ONLY_PASS'", "'LOCAL_TIMING_TESTS_FINISHED'"),
        ("'V19_SCRATCH_ONLY_RESULT='", repr(PREFIX)),
        ("'V19_CPU_CHILD='", "'CPU_LOCATE_CHILD='"),
        ("'SYNTHETIC_CPU_SUITE_PASS'", "'INSTRUMENTED_TESTS_FINISHED'"),
        ("'two-test synthetic scratch subset only; not complete compatibility or production/GPU/mount validation'",
         "'instrumented CPU localization only; not original compatibility, production, GPU, or numerical transparency'"),
    ):
        # Child record prefix occurs twice: filtering and prefix removal.
        require(text.count(old) == (2 if old == "'V19_CPU_CHILD='" else 1), 'timing derivation differs')
        text = text.replace(old, new)
    require('WALL_SECONDS = 90' in text and 'seconds=min(50, remaining)' in text, 'time bound changed')
    source_files = {name: read(HERE / name) for name in ('timing_child.py', 'run_timing.py', 'test_timing.py')}
    return driver, files, text.encode(), source_files


def parse_log(raw, pid, mode):
    text = raw.decode()
    outer = [json.loads(s.removeprefix('CPU_LOCATE_EVENT=')) for s in text.splitlines()
             if s.startswith('CPU_LOCATE_EVENT=')]
    inner = [json.loads(s.removeprefix('PHASE_TIMING=')) for s in text.splitlines()
             if s.startswith('PHASE_TIMING=')]
    require(2 <= len(outer) <= 128 and len(inner) <= 512, 'bounded phase records required')
    require([r['sequence'] for r in outer] == list(range(1, len(outer) + 1))
            and all(r['pid'] == pid for r in outer), 'outer phase sequence/PID differs')
    require(all(r['pid'] == pid for r in inner), 'inner phase PID differs')
    first = outer[0]
    require(first['edge'] == 'environment' and first['label'] == 'instrumented_cpu_only'
            and first['mode'] == mode and first['production_model_loaded'] is False
            and first['jobs_submitted'] == 0 and first['stack_after_seconds'] == 30, 'CPU scope record differs')
    if mode == 'NATIVE_CPU':
        require(first['python'] == '3.11.5' and first['torch'] == '2.1.1+cu118'
                and len(first['cpu_affinity']) == 1, 'native version/affinity differs')
    require(outer[1]['edge'] == 'prepared' and outer[1]['label'] == 'original_ast_restored',
            'original assertion preservation missing')
    for key in ('wall', 'cpu'):
        values = [r[key] for r in outer]
        require(all(isinstance(v, (int, float)) and v >= 0 for v in values)
                and values == sorted(values), 'non-monotonic phase timing')
    require(text.count('Timeout (0:00:30)!') <= 1, 'repeated stack dump not allowed')
    stack = text[text.index('Timeout (0:00:30)!'):] if 'Timeout (0:00:30)!' in text else None
    if stack:
        # Stop at a following structured event; raw full log remains authoritative.
        for marker in ('\nCPU_LOCATE_EVENT=', '\nPHASE_TIMING=', '\nCPU_LOCATE_CHILD='):
            stack = stack.split(marker, 1)[0]
    return {'environment': first, 'outer': outer, 'inner': inner,
        'stack_snapshot': stack, 'last_outer_event': outer[-1], 'last_inner_event': inner[-1] if inner else None}


def check_capture(remote, request):
    for key in ('mode', 'request_id', 'package_sha256', 'child_sha256'):
        require(remote[key] == request[key], 'capture response identity differs')
    require(remote['temporary_directory_removed'] is True and remote['permanent_files_written'] is False
            and remote['jobs_submitted'] == 0 and remote['production_model_loaded'] is False
            and remote['ready_for_gpu'] is False and remote['candidate_input_freeze_sha256'] is None
            and remote['automatic_retry'] is False and 0 <= remote['elapsed_seconds'] < 90,
            'capture scope/cleanup/deadline differs')
    require(len(remote['groups']) == 1, 'one diagnostic child required')
    row = remote['groups'][0]
    require(row['group'] == 'scratch_lifetime', 'wrong diagnostic group')
    raw = base64.b64decode(row['log_base64'], validate=True)
    process = row['process']
    require(len(raw) <= 1024**2 and process['log'] == {'name': 'scratch_lifetime.log', 'size': len(raw), 'sha256': sha(raw)},
            'capture log binding differs')
    phases = parse_log(raw, process['pid'], request['mode'])
    lines = [s.removeprefix('CPU_LOCATE_CHILD=') for s in raw.decode().splitlines() if s.startswith('CPU_LOCATE_CHILD=')]
    require(len(lines) <= 1 and (json.loads(lines[0]) if lines else None) == row['record'], 'child final record differs')
    completed = process['returncode'] == 0 and process['error'] is None
    if completed:
        record = row['record']
        require(type(record) is dict and record['status'] == 'INSTRUMENTED_TESTS_FINISHED'
                and record['pid'] == process['pid'] and record['mode'] == request['mode']
                and record['tests'] == 2 and record['errors'] == record['failures'] == record['skips'] == 0
                and record['cuda_initialized'] is False and record['diagnostic_only'] is True
                and record['original_compatibility_verified'] is False, 'instrumented test completion differs')
        require(remote['error'] is None and remote['status'] == (
            'NATIVE_TIMING_TESTS_FINISHED' if request['mode'] == 'NATIVE_CPU' else 'LOCAL_TIMING_TESTS_FINISHED'),
            'supervisor completion differs')
    else:
        require(process['returncode'] == -9 and process['error'] == {
            'type': 'TimeoutError', 'message': 'child deadline reached'} and row['record'] is None
            and remote['status'] == 'V19_CPU_CHECK_FAILED' and phases['stack_snapshot'] is not None,
            'not a fully recorded bounded timeout')
    return {**phases, 'instrumented_tests_completed': completed,
        'original_native_compatibility_verified': False, 'timing_is_diagnostic_only': True}


def verify_bundle(folder, *, require_local=False):
    driver, files, derived, source_files = sources()
    receipt = json.loads(read(folder / 'receipt.json'))
    require(receipt['source_sha256'] == {n: sha(v) for n, v in source_files.items()}
            and receipt['source_postcheck'] is True and receipt['last_failure_sha256'] == LAST_SHA,
            'timing source/predecessor binding differs')
    raw = read(folder / 'request.py')
    output = read(folder / 'output.log')
    first, payload = raw.split(b'\n', 1)
    require(first.startswith(b'SPEC=') and payload == derived and sha(raw) == receipt['payload_sha256']
            and sha(output) == receipt['output_sha256'], 'request/output/source differs')
    spec = ast.literal_eval(first[5:].decode())
    require(set(spec['files']) == set(files) and all(base64.b64decode(v, validate=True) == files[n]
        for n, v in spec['files'].items()), 'package payload differs')
    require(base64.b64decode(spec['child_source'], validate=True) == source_files['timing_child.py']
            and sha(source_files['timing_child.py']) == spec['child_sha256'], 'instrumented child identity differs')
    require({k: spec[k] for k in receipt['request']} == receipt['request'], 'request summary differs')
    lines = [s.removeprefix(PREFIX) for s in output.decode().splitlines() if s.startswith(PREFIX)]
    require(len(lines) == 1 and json.loads(lines[0]) == receipt['remote'], 'response differs')
    result = check_capture(receipt['remote'], spec)
    require(result == receipt['analysis'] and receipt['status'] == 'CPU_TIMING_EVIDENCE_CAPTURED', 'capture summary differs')
    require(receipt['transport']['error'] is None and receipt['transport']['returncode'] == (
        0 if result['instrumented_tests_completed'] else 2), 'transport termination differs')
    require(receipt['jobs_submitted'] == 0 and receipt['ready_for_gpu'] is False, 'receipt scope differs')
    if require_local:
        require(spec['mode'] == 'LOCAL_HARNESS' and result['instrumented_tests_completed'], 'local instrumentation must finish first')
    return result


def operate(action, receipt_path):
    driver, files, derived, source_files = sources()
    if action == 'review':
        require(receipt_path is not None, 'receipt directory required')
        result = verify_bundle(receipt_path)
        print(json.dumps({'status': 'TIMING_EVIDENCE_REVIEW_PASS', 'instrumented_tests_completed': result['instrumented_tests_completed'],
            'outer_events': len(result['outer']), 'inner_events': len(result['inner']),
            'stack_snapshot': result['stack_snapshot'], 'last_outer_event': result['last_outer_event'],
            'last_inner_event': result['last_inner_event'], 'jobs_submitted': 0, 'original_native_compatibility_verified': False}))
        return 0
    native = action == 'remote-cpu'
    if native:
        require(receipt_path is not None, 'passed local instrumentation receipt required')
        verify_bundle(receipt_path, require_local=True)
    sys.path.insert(0, str(driver.CONTROL))
    import control
    if native:
        control.master_check(control.SOCKET)
    spec = driver.make_spec('NATIVE_CPU' if native else 'LOCAL_HARNESS', files)
    spec['child_source'] = base64.b64encode(source_files['timing_child.py']).decode()
    spec['child_sha256'] = sha(source_files['timing_child.py'])
    payload = ('SPEC=' + repr(spec) + '\n').encode() + derived
    folder = Path(tempfile.mkdtemp(prefix='v19-cpu-timing-' + spec['mode'].lower() + '-'
        + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-', dir=EVIDENCE))
    print('CPU_TIMING_EVIDENCE=' + str(folder), flush=True)
    command = control.ssh_command(control.SOCKET) if native else [sys.executable, '-I', '-B', '-']
    transport = control.transport(command, payload, folder, timeout=110, log_cap=8 * 1024**2)
    output = read(folder / 'output.log')
    remote, analysis, error = None, None, None
    try:
        lines = [s.removeprefix(PREFIX) for s in output.decode().splitlines() if s.startswith(PREFIX)]
        require(len(lines) == 1, 'one timing response required')
        remote = json.loads(lines[0])
        analysis = check_capture(remote, spec)
        require(transport['error'] is None and transport['returncode'] == (
            0 if analysis['instrumented_tests_completed'] else 2), 'transport termination differs')
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    _, after_files, after_derived, after_sources = sources()
    stable = files == after_files and derived == after_derived and source_files == after_sources
    require(stable, 'sources changed during diagnostic')
    receipt = {'status': 'CPU_TIMING_EVIDENCE_CAPTURED' if error is None else 'CPU_TIMING_CAPTURE_FAILED',
        'last_failure_sha256': LAST_SHA, 'source_sha256': {n: sha(v) for n, v in source_files.items()},
        'request': {k: spec[k] for k in ('mode', 'request_id', 'package_sha256', 'child_sha256')},
        'payload_sha256': sha(payload), 'output_sha256': sha(output), 'source_postcheck': stable,
        'remote': remote, 'transport': transport, 'analysis': analysis, 'error': error,
        'ready_for_gpu': False, 'jobs_submitted': 0, 'automatic_retry': False}
    control.ops.write_new(folder / 'receipt.json', control.ops.wire(receipt))
    print(json.dumps({'status': receipt['status'], 'receipt': str(folder / 'receipt.json'), 'error': error,
        'instrumented_tests_completed': analysis['instrumented_tests_completed'] if analysis else False,
        'original_native_compatibility_verified': False, 'jobs_submitted': 0}), flush=True)
    return 0 if error is None else 2


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('self-test', 'remote-cpu', 'review'))
    parser.add_argument('--receipt-directory', type=Path)
    args = parser.parse_args()
    raise SystemExit(operate(args.action, args.receipt_directory))

"""Existing authenticated SSH master only; a fixed bounded CPU probe, not deployment."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
EVIDENCE = ROOT / 'docs/superpowers/evidence'
PACKAGE = ROOT / 'docs/superpowers/prototypes/targeted_gpu_job_20260915_v5'
PACKAGE_SHA = 'c0b421d01d394f1fd3354eb74eb730e2d348cf4a37d0fb96f76a019c71c5aa20'
LOCAL_RUNTIME = EVIDENCE / 'gpu-pair-v19-local-20260915T035834Z-sf4x1k2y/receipt.json'
LOCAL_RUNTIME_SHA = 'd85d45f80af2cac44a486d28416b9590f5ad7c70e1c78d9e74022f3fb0e9c437'
CONTROL = ROOT / 'docs/superpowers/prototypes/targeted_gpu_control_20260914_v4'
COUNTS = {'input_binding': 25, 'startup': 12, 'result_identity': 11, 'adapter_cpu': 30, 'scratch_lifetime': 2}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink source/evidence')
    require(path.is_file() and path.stat().st_size <= 16 * 1024**2, 'bounded regular source required')
    return path.read_bytes()


def local_sources():
    raw = read(PACKAGE / 'SOURCE_MANIFEST.json')
    require(sha(raw) == PACKAGE_SHA, 'reviewed runtime package changed')
    manifest = json.loads(raw)
    files = {str((PACKAGE / 'SOURCE_MANIFEST.json').relative_to(ROOT)): raw}
    for name, expected in manifest['files'].items():
        relative = Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts, 'source path escape')
        data = read(ROOT / relative)
        require(sha(data) == expected, 'runtime source changed: ' + name)
        files[name] = data
    require(len(files) == 163 and sum(map(len, files.values())) <= 16 * 1024**2, 'package inventory/byte budget differs')
    prior_raw = read(LOCAL_RUNTIME)
    require(sha(prior_raw) == LOCAL_RUNTIME_SHA, 'reviewed local runtime receipt changed')
    prior = json.loads(prior_raw)
    require(prior['status'] == 'LOCAL_V19_PAIR_RUNTIME_PASS' and prior['tests'] == 162
            and prior['manifest_sha256'] == PACKAGE_SHA, 'local runtime tests must pass first')
    release_raw = read(HERE / 'PROBE_RELEASE.json')
    release = json.loads(release_raw)
    require(release['package_sha256'] == PACKAGE_SHA and release['wall_seconds'] == 90
            and release['source_files'] == ['child_checks.py', 'driver.py', 'payload.py', 'test_probe.py'],
            'probe release scope differs')
    for name, expected in release['files'].items():
        require(Path(name).name == name and sha(read(HERE / name)) == expected, 'probe source changed: ' + name)
    require(set(release['files']) == set(release['source_files']), 'probe source inventory differs')
    return files, sha(release_raw)


def make_spec(mode, files):
    require(mode in ('NATIVE_CPU', 'LOCAL_HARNESS'), 'invalid probe mode')
    child = read(HERE / 'child_checks.py')
    return {'mode': mode, 'request_id': uuid.uuid4().hex, 'package_sha256': PACKAGE_SHA,
        'files': {name: base64.b64encode(raw).decode('ascii') for name, raw in files.items()},
        'child_source': base64.b64encode(child).decode('ascii'), 'child_sha256': sha(child)}


def check_response(remote, spec):
    require(type(remote) is dict, 'structured CPU result missing')
    expected = 'NATIVE_V19_CPU_PASS' if spec['mode'] == 'NATIVE_CPU' else 'LOCAL_NATIVE_HARNESS_PASS'
    require(remote['status'] == expected and remote['error'] is None, 'CPU probe did not pass')
    for key in ('request_id', 'mode', 'package_sha256', 'child_sha256'):
        require(remote[key] == spec[key], 'response binding differs: ' + key)
    require(remote['temporary_directory_removed'] is True and remote['permanent_files_written'] is False
            and remote['production_model_loaded'] is False and remote['ready_for_gpu'] is False
            and remote['jobs_submitted'] == 0 and remote['candidate_input_freeze_sha256'] is None
            and remote['automatic_retry'] is False, 'probe cleanup/scope differs')
    require(0 <= remote['elapsed_seconds'] < 90, 'remote deadline exceeded')
    require([r['group'] for r in remote['groups']] == list(COUNTS), 'test group coverage differs')
    pids = set()
    for row in remote['groups']:
        group, result, process = row['group'], row['record'], row['process']
        require(process['returncode'] == 0 and process['error'] is None and type(result) is dict,
                'test process incomplete')
        require(result['pid'] == process['pid'] and result['pid'] not in pids, 'cold child identity differs')
        pids.add(result['pid'])
        require(result['status'] == 'SYNTHETIC_CPU_SUITE_PASS' and result['mode'] == spec['mode']
                and result['group'] == group and result['tests'] == COUNTS[group]
                and result['failures'] == result['errors'] == result['skips'] == 0, 'tests not fully passed')
        require(result['cuda_initialized'] is False and result['production_model_loaded'] is False
                and result['jobs_submitted'] == 0, 'test exceeded CPU scope')
        if spec['mode'] == 'NATIVE_CPU':
            require(result['python'] == '3.11.5' and result['torch'] == '2.1.1+cu118'
                    and type(result['cpu_affinity']) is list and len(result['cpu_affinity']) == 1,
                    'native environment differs')
        log = base64.b64decode(row['log_base64'], validate=True)
        require(len(log) <= 1024**2 and process['log'] == {'name': group + '.log', 'size': len(log), 'sha256': sha(log)},
                'child log identity differs')
        lines = [line.removeprefix('V19_CPU_CHILD=') for line in log.decode().splitlines() if line.startswith('V19_CPU_CHILD=')]
        require(len(lines) == 1 and json.loads(lines[0]) == result, 'log does not contain bound child result')
    return 80


def check_local_receipt(path, probe_sha):
    receipt = json.loads(read(path))
    require(receipt['status'] == 'LOCAL_CPU_HARNESS_VERIFIED' and receipt['probe_release_sha256'] == probe_sha
            and receipt['runtime_package_sha256'] == PACKAGE_SHA and receipt['source_postcheck'] is True,
            'matching successful local harness receipt required')
    spec = receipt['request']
    require(spec['mode'] == 'LOCAL_HARNESS', 'native result cannot stand in for local harness')
    check_response(receipt['remote'], spec)
    require(receipt['transport']['returncode'] == 0 and receipt['transport']['error'] is None,
            'local harness exited abnormally')


def operate(mode, local_receipt=None):
    files, probe_sha = local_sources()
    if mode == 'NATIVE_CPU':
        require(local_receipt is not None, 'reviewed local harness receipt required')
        check_local_receipt(local_receipt, probe_sha)
    # These exact old transport sources are checked by the new runtime manifest.
    sys.path.insert(0, str(CONTROL))
    import control
    if mode == 'NATIVE_CPU':
        control.master_check(control.SOCKET)  # NEVER reconnect or collect a password
    spec = make_spec(mode, files)
    source = read(HERE / 'payload.py')
    payload = ('SPEC=' + repr(spec) + '\n').encode() + source
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = Path(tempfile.mkdtemp(prefix='v19-' + mode.lower() + '-' + stamp + '-', dir=EVIDENCE))
    print('CPU_PROBE_EVIDENCE=' + str(folder), flush=True)
    command = control.ssh_command(control.SOCKET) if mode == 'NATIVE_CPU' else [sys.executable, '-I', '-B', '-']
    outcome = control.transport(command, payload, folder, timeout=110, log_cap=8 * 1024**2)
    raw_log = read(folder / 'output.log')
    remote, error = None, None
    try:
        lines = [line.removeprefix('V19_NATIVE_RESULT=') for line in raw_log.decode(errors='replace').splitlines()
                 if line.startswith('V19_NATIVE_RESULT=')]
        require(len(lines) == 1, 'one remote response required')
        remote = json.loads(lines[0])
        check_response(remote, spec)
        require(outcome['returncode'] == 0 and outcome['error'] is None, 'transport failed; do not retry automatically')
        require(local_sources() == (files, probe_sha), 'local sources changed during probe')
    except BaseException as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    stable = local_sources() == (files, probe_sha)
    status = ('NATIVE_V19_COMPATIBILITY_VERIFIED' if mode == 'NATIVE_CPU' else 'LOCAL_CPU_HARNESS_VERIFIED') if error is None else 'CPU_PROBE_FAILED'
    receipt = {'status': status, 'probe_release_sha256': probe_sha, 'runtime_package_sha256': PACKAGE_SHA,
        'request': {k: spec[k] for k in ('mode', 'request_id', 'package_sha256', 'child_sha256')},
        'transport': outcome, 'remote': remote, 'error': error, 'payload_sha256': sha(payload),
        'output_sha256': sha(raw_log), 'source_postcheck': stable, 'jobs_submitted': 0, 'automatic_retry': False}
    control.ops.write_new(folder / 'receipt.json', control.ops.wire(receipt))
    print(json.dumps({'status': status, 'error': error, 'tests': 80 if error is None else None,
        'receipt': str(folder / 'receipt.json'), 'jobs_submitted': 0}), flush=True)
    return 0 if error is None else 2


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check-only', 'self-test', 'remote-cpu'))
    parser.add_argument('--local-receipt', type=Path)
    args = parser.parse_args()
    if args.action == 'check-only':
        files, sha = local_sources()
        print(json.dumps({'status': 'CPU_PROBE_SOURCE_PASS', 'files': len(files),
            'probe_release_sha256': sha, 'wall_seconds': 90, 'jobs_submitted': 0}))
        return 0
    return operate('NATIVE_CPU' if args.action == 'remote-cpu' else 'LOCAL_HARNESS', args.local_receipt)


if __name__ == '__main__':
    raise SystemExit(main())

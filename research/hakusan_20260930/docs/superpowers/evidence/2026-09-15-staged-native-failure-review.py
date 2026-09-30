"""Read-only verification of one fixed failed CPU attempt. Never issues a test PASS."""
import ast
import base64
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / 'docs/superpowers/evidence'
ATTEMPT = EVIDENCE / 'staged-scratch-native_cpu-20260915T130407Z-obg5o718'
SOURCE = ROOT / 'docs/superpowers/prototypes/staged_scratch_native_20260915'
RECEIPT_SHA = 'e6595cbbaff8a298f6ee3f695e15b22bed8f4e448ea91fa0f8b74e7ff748a9e4'
DRIVER_SHA = '023d55693fbba6409936d13709a048d2da1113d92e40e9c8535d0e021353eacb'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    require(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents))
            and path.stat().st_size <= 16 * 1024**2, 'bounded non-symlink evidence required')
    return path.read_bytes()


def main():
    require(sha(read(SOURCE / 'run_native.py')) == DRIVER_SHA, 'driver source changed')
    loader = importlib.util.spec_from_file_location('staged_failure_original_driver', SOURCE / 'run_native.py')
    probe = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(probe)
    task, _, files, own = probe.sources()
    raw = read(ATTEMPT / 'receipt.json')
    require(sha(raw) == RECEIPT_SHA, 'fixed failure receipt changed')
    receipt = task.decode(raw)
    require(receipt['status'] == 'STAGED_CPU_PIPELINE_FAILED' and receipt['mode'] == 'NATIVE_CPU'
            and receipt['source_postcheck'] is False and receipt['jobs_submitted'] == 0
            and receipt['ready_for_gpu'] is False and receipt['automatic_retry'] is False, 'failure scope differs')
    require(receipt['source_sha256'] == {n: sha(r) for n, r in own.items()}, 'current source differs')
    require([r['stage'] for r in receipt['stages']] == ['A2'], 'unexpected retry or later stage')
    actual = {str(p.relative_to(ATTEMPT)) for p in ATTEMPT.rglob('*') if p.is_file()}
    require(actual == {'receipt.json', 'A2/request.py', 'A2/output.log', 'A2/response.json'}, 'failure artifact inventory differs')
    row = receipt['stages'][0]
    require(task.decode(read(ATTEMPT / 'A2/response.json')) == row, 'saved response differs')
    request = read(ATTEMPT / 'A2/request.py')
    output = read(ATTEMPT / 'A2/output.log')
    require(sha(request) == row['request_sha256'] and sha(output) == row['output_sha256'], 'request/output bytes differ')
    header, body = request.split(b'\n', 1)
    require(header.startswith(b'SPEC=') and body == probe.derive_payload(), 'supervisor source differs')
    spec = ast.literal_eval(header[5:].decode())
    require(set(spec['files']) == set(files) and all(base64.b64decode(spec['files'][n], validate=True) == data
            for n, data in files.items()), 'payload source package differs')
    require(base64.b64decode(spec['child_source'], validate=True) == own['child.py']
            and spec['child_sha256'] == sha(own['child.py']) and spec['stage'] == 'A2'
            and spec['mode'] == 'NATIVE_CPU' and spec['run_id'] == receipt['run_id'], 'child/stage identity differs')
    probe.stage_request(spec, task)
    lines = [line[len(probe.PREFIX):] for line in output.decode().splitlines() if line.startswith(probe.PREFIX)]
    require(len(lines) == 1 and json.loads(lines[0]) == row['remote'], 'response log differs')
    remote = row['remote']
    require(all(remote[k] == spec[k] for k in ('request_id', 'mode', 'package_sha256', 'child_sha256')), 'remote request differs')
    require(remote['status'] == 'STAGED_COMPONENT_FAILED' and remote['temporary_directory_removed'] is True
            and remote['jobs_submitted'] == 0 and remote['automatic_retry'] is False
            and len(remote['groups']) == 1 and 50 <= remote['elapsed_seconds'] < 90, 'remote failure/cleanup differs')
    group = remote['groups'][0]
    process = group['process']
    require(group['group'] == 'A2' and group['record'] is None and group['log_base64'] == ''
            and process['returncode'] == -9 and process['error'] == {'type': 'TimeoutError', 'message': 'child deadline reached'}
            and 50 <= process['elapsed_seconds'] <= 50.5
            and process['log'] == {'name': 'A2.log', 'size': 0, 'sha256': sha(b'')}, 'child timeout evidence differs')
    require(row['transport']['returncode'] == 2 and row['transport']['error'] is None
            and row['transport']['elapsed_seconds'] <= 110, 'not the recorded remote failure transport')
    # The success verifier MUST reject this same record.
    try:
        probe.validate(remote, spec, task)
    except RuntimeError:
        pass
    else:
        raise RuntimeError('failed record incorrectly accepted as successful')
    print(json.dumps({'status': 'FAILED_CPU_EVIDENCE_VERIFIED', 'tests_passed': False,
                      'stage': 'A2', 'child_seconds': process['elapsed_seconds'],
                      'supervisor_seconds': remote['elapsed_seconds'], 'transport_seconds': row['transport']['elapsed_seconds'],
                      'B2': 'NOT_RUN', 'mmap': 'NOT_RUN', 'remote_postcheck_completed': False,
                      'current_local_sources_verified': True, 'temporary_directory_removed': True,
                      'ready_for_gpu': False, 'jobs_submitted': 0, 'automatic_retry': False,
                      'fixed_receipt_sha256': RECEIPT_SHA}, sort_keys=True))


if __name__ == '__main__':
    main()

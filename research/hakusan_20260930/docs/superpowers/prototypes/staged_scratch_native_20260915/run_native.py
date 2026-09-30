"""Three bounded synthetic CPU stages, local first; no automatic reconnect/retry or GPU jobs."""
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
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PRIOR = HERE.parent / 'targeted_pair_native_20260915'
STAGED = HERE.parent / 'staged_scratch_20260915'
EVIDENCE = ROOT / 'docs/superpowers/evidence'
# Exact already-reviewed driver, not an execution permission for its old GPU controller.
DRIVER_SHA = 'e2f677c3067ce222e2ef4e72b0b77b300116f85110b2f6f8fda99fbbc070e6ec'
PAYLOAD_SHA = '5f634d48819f9e5a22a9de06d865c7fe0c2a47ce90b27efd61467c83f247f999'
PINS = {'lifecycle.py': '9b0f2c511ed1cda9ee4cb0743795ddf50d8518e31d05e1a23e5d2af3281ca20e',
        'test_lifecycle.py': '5038f717ba5974336abf3ab3d5106b027a9798ac87e5f4ca2d5ad3c471de41e4'}
BASELINE = EVIDENCE / 'staged-scratch-local-20260915T091408Z-nobia7gy'
BASELINE_SHA = 'eabe071aed44e8f7f1dba6443d48555494bdcdbad677626434caa2143e340e6c'
STAGES = ('A2', 'B2', 'mmap')
PREFIX = 'STAGED_CPU_RESULT='


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    require(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents))
            and path.stat().st_size <= 16 * 1024**2, 'bounded non-symlink file required')
    return path.read_bytes()


def wire(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')


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
    extras = {str((STAGED / n).relative_to(ROOT)): s for n, s in PINS.items()}
    changes = (
        ("COUNTS = {'input_binding': 25, 'startup': 12, 'result_identity': 11, 'adapter_cpu': 30, 'scratch_lifetime': 2}",
         "COUNTS = {SPEC['stage']: 2 if SPEC['stage'] == 'mmap' else 0}\nEXTRA_PINS = " + repr(extras)),
        ("len(spec['files']) == 163", "len(spec['files']) == 165"),
        ("manifest = json.loads(files[MANIFEST])\n    require(set(files) == {*manifest['files'], MANIFEST}",
         "manifest = json.loads(files[MANIFEST])\n    bound = {**manifest['files'], **EXTRA_PINS}\n    require(set(files) == {*bound, MANIFEST}"),
        ("all(sha(files[n]) == s for n, s in manifest['files'].items())", "all(sha(files[n]) == s for n, s in bound.items())"),
        ("files, child, manifest = unpack(spec)", "files, child, manifest = unpack(spec)\n        request_raw, parents = stage_data(spec)"),
        ("            runner_path = package / JOB / 'process_runner.py'", """            work = root / 'work'
            stage_folder = work / spec['stage']
            stage_folder.mkdir(mode=0o700, parents=True)
            (stage_folder / 'request.json').write_bytes(request_raw)
            for name, data in parents.items():
                parent_path = work / member(name)
                parent_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                parent_path.write_bytes(data)
            runner_path = package / JOB / 'process_runner.py'"""),
        ("str(package), group, spec['mode']]", "str(package), group, spec['mode'], str(stage_folder), spec['stage_request_sha256'], spec['run_id']]"),
        ("records.append(row)", """records.append(row)
                result_path = stage_folder / 'result.json'
                if result_path.is_file() and not result_path.is_symlink():
                    require(result_path.stat().st_size <= CAP_BYTES, 'stage result budget exceeded')
                    row['stage_result_base64'] = base64.b64encode(result_path.read_bytes()).decode('ascii')"""),
        ("'v19-native-cpu-'", "'staged-scratch-cpu-'"),
        ("'V19_CPU_CHILD='", "'STAGED_CPU_CHILD='"),
        ("'V19_CPU_GROUP_BEGIN='", "'STAGED_CPU_GROUP_BEGIN='"),
        ("'V19_CPU_GROUP_PASS='", "'STAGED_CPU_GROUP_PASS='"),
        ("'SYNTHETIC_CPU_SUITE_PASS'", "'STAGED_COMPONENT_PASS'"),
        ("'NATIVE_V19_CPU_PASS'", "'NATIVE_STAGED_COMPONENT_PASS'"),
        ("'LOCAL_NATIVE_HARNESS_PASS'", "'LOCAL_STAGED_COMPONENT_PASS'"),
        ("'V19_CPU_CHECK_FAILED'", "'STAGED_COMPONENT_FAILED'"),
        ("'V19_NATIVE_RESULT='", repr(PREFIX)),
    )
    for old, new in changes:
        require(source.count(old) == (2 if old == "'V19_CPU_CHILD='" else 1), 'supervisor derivation differs: ' + old)
        source = source.replace(old, new)
    helper = '''
def stage_data(spec):
    require(spec['stage'] in ('A2', 'B2', 'mmap'), 'unknown stage')
    require(type(spec['run_id']) is str and len(spec['run_id']) == 32
            and all(c in '0123456789abcdef' for c in spec['run_id']), 'invalid run identity')
    require(type(spec['stage_request_base64']) is str and len(spec['stage_request_base64']) <= 90000, 'request budget exceeded')
    request = base64.b64decode(spec['stage_request_base64'], validate=True)
    require(len(request) <= 65536 and sha(request) == spec['stage_request_sha256'], 'stage request differs')
    value = json.loads(request)
    require(value['stage'] == spec['stage'] and value['session_id'] == spec['run_id'], 'session/stage differs')
    expected = ['A2/result.json', 'B2/result.json'] if spec['stage'] == 'mmap' else []
    require([p['name'] for p in value['parents']] == expected and set(spec['parents']) == set(expected), 'parent inventory differs')
    parents = {}
    for item in value['parents']:
        require(type(spec['parents'][item['name']]) is str and len(spec['parents'][item['name']]) <= 12 * 1024**2, 'encoded parent budget exceeded')
        raw = base64.b64decode(spec['parents'][item['name']], validate=True)
        require(len(raw) <= 8 * 1024**2 and sha(raw) == item['sha256'], 'parent digest/budget differs')
        parents[item['name']] = raw
    return request, parents

'''
    source = source.replace("if __name__ == '__main__':", helper + "if __name__ == '__main__':")
    require('WALL_SECONDS = 90' in source and 'seconds=min(50, remaining)' in source
            and 'os.sched_setaffinity(0, {min(allowed)})' in source, 'original bounds changed')
    return source.encode()


def sources():
    task = load(STAGED / 'lifecycle.py', PINS['lifecycle.py'], 'staged_original_local_fixture')
    require(sha(read(BASELINE / 'receipt.json')) == BASELINE_SHA, 'prior local receipt changed')
    task.review(BASELINE)
    driver = load(PRIOR / 'driver.py', DRIVER_SHA, 'staged_original_driver')
    files, _ = driver.local_sources()
    for name, expected in PINS.items():
        raw = read(STAGED / name)
        require(sha(raw) == expected, 'staged fixture source differs')
        files[str((STAGED / name).relative_to(ROOT))] = raw
    require(len(files) == 165 and sum(map(len, files.values())) <= 16 * 1024**2, 'temporary package budget differs')
    own = {n: read(HERE / n) for n in ('child.py', 'run_native.py', 'test_native.py')}
    return task, driver, files, own


def stage_request(spec, task):
    raw = base64.b64decode(spec['stage_request_base64'], validate=True)
    require(len(raw) <= 65536 and sha(raw) == spec['stage_request_sha256'], 'request digest/budget differs')
    request = task.decode(raw)
    require(request['source_binding'] == task.sources() and request['scope'] == task.SCOPE
            and request['stage'] == spec['stage'] and request['session_id'] == spec['run_id'], 'request source/session/scope differs')
    expected = task.parent_names(request)
    require(set(spec['parents']) == set(expected), 'parent inventory differs')
    for item in request['parents']:
        parent = base64.b64decode(spec['parents'][item['name']], validate=True)
        require(len(parent) <= 8 * 1024**2 and sha(parent) == item['sha256'], 'parent digest/budget differs')
    return request


def validate(remote, spec, task):
    request = stage_request(spec, task)
    expected = 'NATIVE_STAGED_COMPONENT_PASS' if spec['mode'] == 'NATIVE_CPU' else 'LOCAL_STAGED_COMPONENT_PASS'
    require(remote['status'] == expected and remote['error'] is None, 'stage failed or incomplete')
    for key in ('mode', 'request_id', 'package_sha256', 'child_sha256'):
        require(remote[key] == spec[key], 'response identity differs: ' + key)
    require(remote['temporary_directory_removed'] is True and remote['permanent_files_written'] is False
            and remote['production_model_loaded'] is False and remote['ready_for_gpu'] is False
            and remote['jobs_submitted'] == 0 and remote['candidate_input_freeze_sha256'] is None
            and remote['automatic_retry'] is False and 0 <= remote['elapsed_seconds'] < 90, 'scope/cleanup/deadline differs')
    require(len(remote['groups']) == 1, 'one stage per invocation required')
    row = remote['groups'][0]
    process, record = row['process'], row['record']
    require(row['group'] == spec['stage'] and process['returncode'] == 0 and process['error'] is None
            and 0 <= process['elapsed_seconds'] <= 50.5 and process['pid'] == record['pid'], 'child outcome differs')
    require(record['status'] == 'STAGED_COMPONENT_PASS' and record['mode'] == spec['mode']
            and record['stage'] == record['group'] == spec['stage'] and record['run_id'] == spec['run_id']
            and record['request_sha256'] == spec['stage_request_sha256'], 'stage child binding differs')
    require(record['tests'] == (2 if spec['stage'] == 'mmap' else 0)
            and record['errors'] == record['failures'] == record['skips'] == 0, 'stage test coverage differs')
    require(record['cuda_initialized'] is False and record['production_model_loaded'] is False
            and record['jobs_submitted'] == 0 and record['ready_for_gpu'] is False
            and record['original_native_monolithic_passed'] is False, 'child scope differs')
    if spec['mode'] == 'NATIVE_CPU':
        require(record['python'] == '3.11.5' and record['torch'] == '2.1.1+cu118'
                and len(record['cpu_affinity']) == 1, 'native environment differs')
    raw_log = base64.b64decode(row['log_base64'], validate=True)
    require(len(raw_log) <= 1024**2 and process['log'] == {'name': spec['stage'] + '.log', 'size': len(raw_log), 'sha256': sha(raw_log)}, 'child log changed')
    lines = [s.removeprefix('STAGED_CPU_CHILD=') for s in raw_log.decode().splitlines() if s.startswith('STAGED_CPU_CHILD=')]
    require(len(lines) == 1 and json.loads(lines[0]) == record, 'child log summary differs')
    raw = base64.b64decode(row['stage_result_base64'], validate=True)
    require(sha(raw) == record['result_sha256'], 'result bytes changed')
    result = task.decode(raw)
    task.validate_result(result, request, spec['stage'])
    require(result['pid'] == record['pid'] and result['parents'] == request['parents']
            and result['environment'] == {'python': record['python'], 'torch': record['torch']}, 'fixture result binding differs')
    if spec['stage'] == 'mmap':
        parents = [task.decode(base64.b64decode(spec['parents'][n], validate=True)) for n in ('A2/result.json', 'B2/result.json')]
        merged = task.merge_cells(*parents, request)
        require(all(p['environment'] == result['environment'] for p in parents), 'consumer environment differs')
        require(sha(wire(merged)) == result['consumed_contract_sha256'], 'consumed contract changed')
        require(result['tests'] == 2 and result['errors'] == result['failures'] == result['skips'] == 0, 'scratch assertions incomplete')
    else:
        require(result['parents'] == [] and sha(wire(result['contract'])) == result['contract_sha256']
                and set(result['contract']['cells']) == {spec['stage']}, 'oracle result differs')
    require(result['original_ast_restored_exactly'] is True, 'original assertions/structure not restored')
    return raw, result


def review(folder, *, local_only=False):
    context = sources()
    task = context[0]
    receipt = task.decode(read(folder / 'receipt.json'))
    return review_records(folder, receipt, context, local_only=local_only)


def review_records(folder, receipt, context, *, local_only=False):
    task, driver, files, own = context
    require(receipt['status'] == 'STAGED_CPU_PIPELINE_VERIFIED' and receipt['error'] is None
            and receipt['source_postcheck'] is True and receipt['source_sha256'] == {n: sha(r) for n, r in own.items()}, 'pipeline source/status differs')
    require(receipt['mode'] in ('LOCAL_HARNESS', 'NATIVE_CPU') and (not local_only or receipt['mode'] == 'LOCAL_HARNESS'), 'matching local pipeline required')
    require(receipt['jobs_submitted'] == 0 and receipt['ready_for_gpu'] is False and receipt['automatic_retry'] is False, 'pipeline scope differs')
    require([r['stage'] for r in receipt['stages']] == list(STAGES), 'all three stages required')
    values = {}
    for row in receipt['stages']:
        stage = row['stage']
        request_raw = read(folder / stage / 'request.py')
        first, body = request_raw.split(b'\n', 1)
        require(first.startswith(b'SPEC=') and body == derive_payload(), 'bound request source differs')
        spec = ast.literal_eval(first[5:].decode())
        require(set(spec['files']) == set(files) and all(base64.b64decode(spec['files'][n], validate=True) == raw for n, raw in files.items()), 'request package differs')
        require(spec['mode'] == receipt['mode'] and spec['run_id'] == receipt['run_id'] and spec['stage'] == stage
                and base64.b64decode(spec['child_source'], validate=True) == own['child.py']
                and spec['child_sha256'] == sha(own['child.py']), 'child request differs')
        output = read(folder / stage / 'output.log')
        require(task.decode(read(folder / stage / 'response.json')) == row, 'saved response differs')
        require(row['request_sha256'] == sha(request_raw) and row['output_sha256'] == sha(output), 'request/output hash differs')
        lines = [s.removeprefix(PREFIX) for s in output.decode().splitlines() if s.startswith(PREFIX)]
        require(len(lines) == 1 and json.loads(lines[0]) == row['remote'], 'transport response differs')
        require(row['transport']['returncode'] == 0 and row['transport']['error'] is None
                and 0 <= row['transport']['elapsed_seconds'] <= 110.5, 'transport incomplete')
        raw, value = validate(row['remote'], spec, task)
        require(read(folder / stage / 'result.json') == raw, 'local artifact differs')
        if stage == 'mmap':
            require(spec['parents'] == {s + '/result.json': base64.b64encode(read(folder / s / 'result.json')).decode() for s in ('A2', 'B2')}, 'cross-stage oracle differs')
        values[stage] = value
    require(len({v['pid'] for v in values.values()}) == 3, 'three cold children required')
    if receipt['mode'] == 'LOCAL_HARNESS':
        baseline = task.decode(read(BASELINE / 'monolithic_oracle_control/result.json'))
        require(values['mmap']['environment'] == baseline['environment']
                and values['mmap']['consumed_contract_sha256'] == baseline['contract_sha256'], 'local output differs from unchanged monolithic oracle')
    return {'status': 'STAGED_CPU_REVIEW_PASS', 'mode': receipt['mode'], 'stages': list(values),
            'contract_sha256': values['mmap']['consumed_contract_sha256'], 'tests': 2,
            'original_native_monolithic_passed': False, 'ready_for_gpu': False, 'jobs_submitted': 0}


def operate(mode, local):
    task, driver, files, own = sources()
    if mode == 'NATIVE_CPU':
        require(local is not None, 'matching local payload verification required first')
        review(local, local_only=True)
    sys.path.insert(0, str(driver.CONTROL))
    import control
    if mode == 'NATIVE_CPU':
        control.master_check(control.SOCKET)  # No reconnect/password or fallback network route.
    folder = Path(tempfile.mkdtemp(prefix='staged-scratch-' + mode.lower() + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-', dir=EVIDENCE))
    print('STAGED_CPU_EVIDENCE=' + str(folder), flush=True)
    run_id, rows, error = uuid.uuid4().hex, [], None
    try:
        for stage in STAGES:
            part = folder / stage
            part.mkdir(mode=0o700)
            parents = {s + '/result.json': read(folder / s / 'result.json') for s in ('A2', 'B2')} if stage == 'mmap' else {}
            request = {'stage': stage, 'session_id': run_id, 'scope': task.SCOPE, 'source_binding': task.sources(),
                       'parents': [{'name': n, 'sha256': sha(raw)} for n, raw in parents.items()]}
            spec = driver.make_spec(mode, files)
            spec.update(stage=stage, run_id=run_id, stage_request_sha256=sha(wire(request)),
                        stage_request_base64=base64.b64encode(wire(request)).decode(),
                        parents={n: base64.b64encode(raw).decode() for n, raw in parents.items()},
                        child_source=base64.b64encode(own['child.py']).decode(), child_sha256=sha(own['child.py']))
            payload = ('SPEC=' + repr(spec) + '\n').encode() + derive_payload()
            command = control.ssh_command(control.SOCKET) if mode == 'NATIVE_CPU' else [sys.executable, '-I', '-B', '-']
            transport = control.transport(command, payload, part, timeout=110, log_cap=8 * 1024**2)
            output = read(part / 'output.log')
            lines = [s.removeprefix(PREFIX) for s in output.decode().splitlines() if s.startswith(PREFIX)]
            remote = json.loads(lines[0]) if len(lines) == 1 else None
            row = {'stage': stage, 'transport': transport, 'remote': remote, 'request_sha256': sha(payload), 'output_sha256': sha(output)}
            rows.append(row)
            control.ops.write_new(part / 'response.json', wire(row))
            require(transport['returncode'] == 0 and transport['error'] is None and remote is not None, 'stage transport failed; no retry')
            raw, value = validate(remote, spec, task)
            control.ops.write_new(part / 'result.json', raw)
            print(json.dumps({'stage': stage, 'seconds': remote['elapsed_seconds'], 'status': 'VERIFIED'}), flush=True)
        _, _, after_files, after_own = sources()
        require(files == after_files and own == after_own, 'sources changed during pipeline')
    except BaseException as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    receipt = {'status': 'STAGED_CPU_PIPELINE_VERIFIED' if error is None else 'STAGED_CPU_PIPELINE_FAILED',
               'mode': mode, 'run_id': run_id, 'stages': rows, 'error': error,
               'source_sha256': {n: sha(raw) for n, raw in own.items()}, 'source_postcheck': error is None,
               'jobs_submitted': 0, 'ready_for_gpu': False, 'automatic_retry': False}
    checked = None
    if error is None:
        try:
            checked = review_records(folder, receipt, (task, driver, files, own))
        except BaseException as exc:
            error = {'type': type(exc).__name__, 'message': str(exc)}
            receipt.update(status='STAGED_CPU_PIPELINE_FAILED', error=error)
    control.ops.write_new(folder / 'receipt.json', wire(receipt))
    print(json.dumps(checked if error is None else {'status': receipt['status'], 'error': error}), flush=True)
    return 0 if error is None else 2


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('local', 'remote-cpu', 'review'))
    parser.add_argument('--local', type=Path)
    args = parser.parse_args()
    if args.action == 'review':
        print(json.dumps(review(args.local)))
        return 0
    return operate('NATIVE_CPU' if args.action == 'remote-cpu' else 'LOCAL_HARNESS', args.local)


if __name__ == '__main__':
    raise SystemExit(main())

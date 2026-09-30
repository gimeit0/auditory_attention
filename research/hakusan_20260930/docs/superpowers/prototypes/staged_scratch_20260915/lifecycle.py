"""Local-only, content-bound staging of the original v19 synthetic scratch test.

This is a test variant, not completion of the native monolithic deadline gate.
No candidate loader, SSH, checkpoint, scheduler, or production authority.
"""
import argparse
import ast
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
JOB = HERE.parent / 'targeted_gpu_job_20260915_v5'
WORKER = HERE.parent / 'targeted_worker_20260915_scan'
MANIFEST_SHA = 'c0b421d01d394f1fd3354eb74eb730e2d348cf4a37d0fb96f76a019c71c5aa20'
SCOPE = 'local_v19_staged_synthetic_scratch_only'
STAGES = ('A2', 'B2', 'mmap', 'monolithic_oracle_control')


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')


def read(path):
    require(not any(p.is_symlink() for p in (path, *path.parents))
            and path.is_file() and path.stat().st_size <= 16 * 1024**2, 'bounded non-symlink file required')
    return path.read_bytes()


def decode(raw):
    require(len(raw) <= 16 * 1024**2, 'JSON budget exceeded')
    value = json.loads(raw)
    require(canonical(value) == raw, 'canonical JSON required')
    return value


def sources():
    raw = read(JOB / 'SOURCE_MANIFEST.json')
    require(sha(raw) == MANIFEST_SHA, 'frozen manifest differs')
    files = json.loads(raw)['files']
    require(len(files) == 162, 'frozen inventory differs')
    for name, expected in files.items():
        relative = Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts, 'invalid source path')
        require(sha(read(ROOT / relative)) == expected, 'frozen source differs: ' + name)
    return {'frozen_manifest_sha256': MANIFEST_SHA,
            'new_sources': {n: sha(read(HERE / n)) for n in ('lifecycle.py', 'test_lifecycle.py')}}


def runner_module():
    # sources() must have verified this exact existing helper first.
    spec = importlib.util.spec_from_file_location('staged_original_runner', JOB / 'process_runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def derive_cell(raw, cell):
    require(cell in ('A2', 'B2'), 'exact cell required')
    module = ast.parse(raw)
    original = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == 'expected_contract')
    derived = copy.deepcopy(original)
    loops = [n for n in ast.walk(derived) if isinstance(n, ast.For) and ast.dump(n.iter)
             == ast.dump(ast.parse("('A2', 'B2')", mode='eval').body)]
    require(len(loops) == 1, 'one outer cell loop required')
    old = loops[0].iter
    loops[0].iter = ast.Tuple(elts=[ast.Constant(cell)], ctx=ast.Load())
    restored = copy.deepcopy(derived)
    next(n for n in ast.walk(restored) if isinstance(n, ast.For) and isinstance(n.target, ast.Name)
         and n.target.id == 'cell').iter = old
    require(ast.dump(restored) == ast.dump(original), 'cell derivation did not restore original AST')
    return ast.fix_missing_locations(ast.Module(body=[derived], type_ignores=[]))


def derive_scratch(raw):
    original = next(n for n in ast.parse(raw).body if isinstance(n, ast.ClassDef) and n.name == 'ScratchTests')
    derived = copy.deepcopy(original)
    matches = [n for n in ast.walk(derived) if isinstance(n, ast.Assign)
               and ast.dump(n.value) == ast.dump(ast.parse('fixture.expected_contract()', mode='eval').body)]
    require(len(matches) == 1, 'one expected-data preparation call required')
    old = matches[0].value
    matches[0].value = ast.Call(func=ast.Name(id='_bound_parent', ctx=ast.Load()), args=[], keywords=[])
    restored = copy.deepcopy(derived)
    next(n for n in ast.walk(restored) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
         and isinstance(n.value.func, ast.Name) and n.value.func.id == '_bound_parent').value = old
    require(ast.dump(restored) == ast.dump(original), 'scratch derivation did not restore original AST')
    return ast.fix_missing_locations(ast.Module(body=[derived], type_ignores=[]))


def read_bound(path, expected):
    raw = read(path)
    require(sha(raw) == expected, 'external artifact SHA differs')
    return decode(raw)


def validate_result(value, request, stage):
    for name in ('session_id', 'source_binding', 'scope'):
        require(value[name] == request[name], 'stage binding differs: ' + name)
    require(value['stage'] == stage and value['status'] == 'LOCAL_STAGE_PASS', 'stage identity/status differs')
    require(value['production_model_loaded'] is False and value['ready_for_gpu'] is False
            and value['jobs_submitted'] == 0 and value['cuda_initialized'] is False
            and value['home_unchanged'] is True and value['source_postcheck'] is True, 'stage scope differs')


def merge_cells(a, b, request):
    for stage, value in (('A2', a), ('B2', b)):
        validate_result(value, request, stage)
        require(value['parents'] == [], 'oracle must have no parent result')
        contract = value['contract']
        require(contract['production_authority'] is False and set(contract['cells']) == {stage}, 'oracle cell differs')
        require(len(contract['trials']) == 32
                and [t['ordinal'] for t in contract['trials']] == list(range(32)), 'trial coverage differs')
        cell = contract['cells'][stage]
        require(cell['autocast_enabled'] is (stage == 'A2') and set(cell['passes']) == {'pass1', 'pass2'}, 'cell schedule differs')
        require([cell['passes'][p]['batch_size'] for p in ('pass1', 'pass2')] == [16, 1], 'batch schedule differs')
        require(sha(canonical(contract)) == value['contract_sha256'], 'contract content binding differs')
    require(a['environment'] == b['environment'], 'oracle environments differ')
    ac, bc = a['contract'], b['contract']
    require({k: v for k, v in ac.items() if k != 'cells'} == {k: v for k, v in bc.items() if k != 'cells'},
            'oracle trial/header identities differ')
    return {**copy.deepcopy(ac), 'cells': {**copy.deepcopy(ac['cells']), **copy.deepcopy(bc['cells'])}}


def load_fixture():
    for directory in (WORKER, HERE.parent / 'targeted_gpu_pair_20260915_scan', JOB):
        sys.path.insert(0, str(directory))
    import test_scratch_integration as original
    original.fixture.torch.set_num_threads(1)
    return original


def parent_names(request):
    expected = ['A2/result.json', 'B2/result.json'] if request['stage'] == 'mmap' else []
    require(type(request['parents']) is list
            and [p['name'] for p in request['parents']] == expected, 'exact oracle parents required')
    return expected


def child(folder, request_sha):
    before = sources()
    request = read_bound(folder / 'request.json', request_sha)
    require(request['source_binding'] == before and request['scope'] == SCOPE, 'request source/scope differs')
    stage = request['stage']
    require(stage in STAGES, 'unknown stage')
    original_home = os.environ['HOME']
    parent_names(request)  # Reject arbitrary paths before reading any parent.
    parent_records = [read_bound(folder.parent / p['name'], p['sha256']) for p in request['parents']]
    if stage == 'mmap':
        require([p['name'] for p in request['parents']] == ['A2/result.json', 'B2/result.json'], 'exact oracle parents required')
        parent = merge_cells(*parent_records, request)
    else:
        require(not request['parents'], 'unexpected stage parents')
    original = load_fixture()
    fixture = original.fixture
    require(not fixture.torch.cuda.is_initialized(), 'CUDA already initialized')
    value = {k: request[k] for k in ('session_id', 'source_binding', 'scope', 'stage', 'parents')}
    value.update(pid=os.getpid(), environment={'python': sys.version.split()[0], 'torch': str(fixture.torch.__version__)})
    started = time.monotonic()
    if stage in ('A2', 'B2'):
        tree = derive_cell(read(WORKER / 'test_baseline_bridge.py'), stage)
        namespace = dict(vars(fixture))
        exec(compile(tree, '<staged-original-cell>', 'exec'), namespace)
        contract = namespace['expected_contract']()
        value.update(contract=contract, contract_sha256=sha(canonical(contract)), original_ast_restored_exactly=True)
    elif stage == 'monolithic_oracle_control':
        contract = fixture.expected_contract()
        value.update(contract=contract, contract_sha256=sha(canonical(contract)))
    else:
        require(all(v['environment'] == value['environment'] for v in parent_records), 'consumer environment differs')
        # Validate complete output bytes and all boundary descriptors before any model is created.
        wire = fixture.replay.canonical(parent)
        fixture.replay._decode_contract(wire, sha(wire))
        consumed = []

        def bound_parent():
            require(not consumed, 'expected-data loader is single use')
            consumed.append(sha(wire))
            return copy.deepcopy(parent)

        namespace = {**vars(original), '_bound_parent': bound_parent}
        tree = derive_scratch(read(JOB / 'test_scratch_integration.py'))
        exec(compile(tree, '<staged-original-scratch-test>', 'exec'), namespace)
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(namespace['ScratchTests'])
        ids = [test.id() for test in suite]
        outcome = unittest.TextTestRunner(verbosity=2).run(suite)
        require(outcome.wasSuccessful() and outcome.testsRun == 2 and not outcome.skipped, 'original scratch assertions failed')
        require(consumed == [sha(wire)], 'bound oracle not consumed exactly once')
        value.update(tests=2, test_ids=ids, errors=len(outcome.errors), failures=len(outcome.failures),
                     skips=len(outcome.skipped), consumed_contract_sha256=sha(wire), original_ast_restored_exactly=True)
    require(before == sources(), 'sources changed during stage')
    require(os.environ['HOME'] == original_home and not fixture.torch.cuda.is_initialized(), 'HOME/CUDA changed')
    value.update(status='LOCAL_STAGE_PASS', wall_seconds=time.monotonic() - started,
                 source_postcheck=True, home_unchanged=True, cuda_initialized=False,
                 production_model_loaded=False, jobs_submitted=0, ready_for_gpu=False)
    runner_module().write_once(folder / 'result.json', value)
    print('STAGED_CHILD_PASS=' + stage, flush=True)


def complete(values, request):
    require(set(values) == set(STAGES), 'four complete stages required')
    merged = merge_cells(values['A2'], values['B2'], request)
    control = values['monolithic_oracle_control']
    require(merged == control['contract'] and sha(canonical(merged)) == control['contract_sha256']
            == values['mmap']['consumed_contract_sha256'], 'staged/monolithic output bytes or boundaries differ')
    require(values['mmap']['tests'] == 2 and values['mmap']['errors'] == values['mmap']['failures']
            == values['mmap']['skips'] == 0, 'two scratch tests required')
    require(all(v['environment'] == control['environment'] for v in values.values()), 'stage environment differs')
    require(all(values[s]['original_ast_restored_exactly'] is True for s in ('A2', 'B2', 'mmap')), 'AST restoration required')
    return control['contract_sha256']


def review(folder):
    before = sources()
    receipt = decode(read(folder / 'receipt.json'))
    require(receipt['status'] == 'LOCAL_STAGED_SCRATCH_PASS' and receipt['error'] is None, 'pipeline not passed')
    require(receipt['source_binding'] == before and receipt['source_postcheck'] is True, 'pipeline source binding differs')
    runner = runner_module()
    require(set(receipt['artifacts']) == {s + '/' + n for s in STAGES for n in
                                       ('request.json', 'result.json', 'process.json', 'child.log')}, 'exact artifact set required')
    for name, expected in receipt['artifacts'].items():
        p = Path(name)
        require(not p.is_absolute() and '..' not in p.parts, 'invalid artifact path')
        require(runner.file_record(folder / p) == expected, 'artifact changed: ' + name)
    values, processes = {}, []
    for stage in STAGES:
        request = decode(read(folder / stage / 'request.json'))
        value = decode(read(folder / stage / 'result.json'))
        require(request['source_binding'] == before and request['scope'] == SCOPE
                and request['session_id'] == receipt['session_id'] and request['stage'] == stage, 'request binding differs')
        validate_result(value, request, stage)
        parent_names(request)
        require(value['parents'] == request['parents'], 'parent consumption record differs')
        for p in request['parents']:
            read_bound(folder / p['name'], p['sha256'])
        process = decode(read(folder / stage / 'process.json'))
        require(process['request_sha256'] == sha(canonical(request)), 'process request SHA differs')
        require(process['returncode'] == 0 and process['error'] is None and process['elapsed_seconds'] <= 50.5
                and value['pid'] == process['pid'], 'child outcome/budget differs')
        require(runner.file_record(folder / stage / 'child.log') == {k: v for k, v in process['log'].items() if k != 'name'},
                'process log differs')
        processes.append(process['pid'])
        values[stage] = value
    require(len(set(processes)) == 4, 'four cold processes required')
    request = decode(read(folder / 'mmap/request.json'))
    require([p['name'] for p in request['parents']] == ['A2/result.json', 'B2/result.json'], 'consumer inputs differ')
    contract_sha = complete(values, request)
    require(receipt['remote_executed'] is False and receipt['ready_for_gpu'] is False
            and receipt['jobs_submitted'] == 0 and receipt['automatic_retry'] is False
            and receipt['elapsed_seconds'] < 90, 'pipeline scope/budget differs')
    return {'status': 'LOCAL_STAGED_SCRATCH_REVIEW_PASS', 'contract_sha256': contract_sha,
            'stages': {k: v['wall_seconds'] for k, v in values.items()}, 'tests': 2,
            'native_monolithic_gate_passed': False, 'jobs_submitted': 0, 'ready_for_gpu': False}


def run_local():
    before = sources()
    runner = runner_module()
    folder = Path(tempfile.mkdtemp(prefix='staged-scratch-local-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-',
                                  dir=ROOT / 'docs/superpowers/evidence'))
    print('STAGED_LOCAL_EVIDENCE=' + str(folder), flush=True)
    session = uuid.uuid4().hex
    env = {**os.environ, 'CUDA_VISIBLE_DEVICES': '', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'PYTHONHASHSEED': '0'}
    started, error, values = time.monotonic(), None, {}
    try:
        for stage in STAGES:
            part = folder / stage
            part.mkdir(mode=0o700)
            parents = [{'name': s + '/result.json', 'sha256': sha(read(folder / s / 'result.json'))} for s in ('A2', 'B2')] if stage == 'mmap' else []
            request = {'session_id': session, 'source_binding': before, 'scope': SCOPE, 'stage': stage, 'parents': parents}
            runner.write_once(part / 'request.json', request)
            process = runner.run_process([sys.executable, '-I', '-B', str(HERE / 'lifecycle.py'), '--child', str(part),
                                          sha(canonical(request))], env, part / 'child.log',
                                         seconds=min(50, 90 - (time.monotonic() - started)), max_log_bytes=2 * 1024**2)
            process['request_sha256'] = sha(canonical(request))
            runner.write_once(part / 'process.json', process)
            require(process['error'] is None and process['returncode'] == 0, 'child failed: ' + stage)
            values[stage] = decode(read(part / 'result.json'))
            validate_result(values[stage], request, stage)
            print(json.dumps({'stage': stage, 'seconds': process['elapsed_seconds']}), flush=True)
        complete(values, decode(read(folder / 'mmap/request.json')))
        require(time.monotonic() - started < 90, 'local pipeline deadline exceeded')
    except BaseException as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    post = before == sources()
    require(post, 'source postcheck failed')
    receipt = {'status': 'LOCAL_STAGED_SCRATCH_PASS' if error is None else 'LOCAL_STAGED_SCRATCH_FAILED',
               'error': error, 'session_id': session, 'source_binding': before, 'source_postcheck': post,
               'elapsed_seconds': time.monotonic() - started, 'remote_executed': False, 'automatic_retry': False,
               'jobs_submitted': 0, 'ready_for_gpu': False,
               'artifacts': {str(p.relative_to(folder)): runner.file_record(p) for p in folder.glob('*/*') if p.is_file()}}
    runner.write_once(folder / 'receipt.json', receipt)
    if error is not None:
        print(json.dumps(receipt), flush=True)
        return 2
    print(json.dumps(review(folder)), flush=True)
    return 0


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('local', 'review', '--child'))
    parser.add_argument('folder', nargs='?', type=Path)
    parser.add_argument('request_sha', nargs='?')
    # Internal child uses a positional token without exposing any remote entry.
    args = parser.parse_args(['--', *sys.argv[1:]])
    if args.action == '--child':
        child(args.folder, args.request_sha)
        return 0
    if args.action == 'review':
        print(json.dumps(review(args.folder)))
        return 0
    return run_local()


if __name__ == '__main__':
    raise SystemExit(main())

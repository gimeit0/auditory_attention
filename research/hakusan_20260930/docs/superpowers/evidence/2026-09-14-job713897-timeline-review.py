"""Offline file-time/source review only; no torch, SSH, model, or job execution."""
import ast
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

E = Path(__file__).resolve().parent
W = E.parents[2]
D = E / 'gpu-control-20260914-v3/terminal-timeline-20260914T075202Z-lwkg2v33'
C = W / 'docs/superpowers/prototypes/targeted_gpu_control_20260914_v3'
J = W / 'docs/superpowers/prototypes/targeted_gpu_job_20260914_v3'
V = W / 'same_bank_eval_2026_09_03_v4_numeric_diag_v18/diagnose_batch_invariance.py'


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def source_environment_check():
    raw = (C / 'CONTROL_RELEASE.json').read_bytes()
    require(sha(raw) == '355f29740dfdc159402c49a80b01e79acc1b69b9000e1361edf1e680d50aec52', 'release SHA')
    release = json.loads(raw)
    for name, digest in release['files'].items():
        require(sha((W / name).read_bytes()) == digest, 'source SHA: ' + name)
    require(len(release['files']) == 55, 'fixed source count')
    old_tree = ast.parse(V.read_bytes())
    old = next(n for n in old_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'child_environment')
    exports = {}
    for n in ast.walk(old):
        if isinstance(n, ast.Dict):
            for key, value in zip(n.keys, n.values):
                if isinstance(key, ast.Constant) and isinstance(value, ast.Constant):
                    exports[key.value] = value.value
    expected = {'OMP_NUM_THREADS': '8', 'CUBLAS_WORKSPACE_CONFIG': ':4096:8', 'TOKENIZERS_PARALLELISM': 'false'}
    require(all(exports.get(k) == v for k, v in expected.items()), 'original environment contract')
    old_exit = json.loads((E / 'job-685198-v18/slurm-685198/CHILD_EXIT_B2.json').read_bytes())
    require(old_exit['status'] == 'CHILD_EXIT_VERIFIED' and old_exit['returncode'] == 0, 'old worker exit')
    require(all(old_exit['environment'].get(k) == v for k, v in expected.items()), 'old observed exports')
    tree = ast.parse((J / 'coordinator.py').read_bytes())
    paths = next(n for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'WRITE_PATHS' for t in n.targets))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'child_environment')
    ns = {'Path': Path, 'contract': SimpleNamespace(require=require)}
    # Execute only the stdlib, side-effect-free environment-construction function,
    # not the coordinator module or model-loading entry point.
    exec(compile(ast.Module(body=[paths, function], type_ignores=[]), '<fixed-environment-only>', 'exec'), ns)
    cases = []
    for role in ('reference', 'observed'):
        for parent_values in ({}, expected, {k: 'unreviewed' for k in expected}):
            parent = {'HOME': '/home/s2510040', 'PATH': '/usr/bin:/bin', **parent_values}
            value = ns['child_environment'](parent, Path('/tmp/no-directory-created'), role)
            require(value['HOME'] == parent['HOME'], 'HOME changed')
            require(all(k not in value for k in expected), 'expected omission did not reproduce')
            cases.append({'role': role, 'parent': parent_values, 'omitted_keys': sorted(expected)})
    return {'status': 'FROZEN_EXPORT_OMISSION_REPRODUCED', 'cases': cases,
            'original_fixed_exports': expected, 'published_sources_unchanged': 55,
            'historical_environment_file_sha256': sha((E / 'job-685198-v18/slurm-685198/CHILD_EXIT_B2.json').read_bytes()),
            'actual_job_torch_threads_known': False, 'timeout_causality_proven': False,
            'limitation': 'environment factory omission, not a measured runtime or speed comparison'}


def main():
    raw = (D / 'receipt.json').read_bytes()
    r = json.loads(raw)
    log = (D / 'output.log').read_bytes()
    request = (D / 'request.py').read_bytes()
    require(r['returncode'] == r['transport']['returncode'] == 0 and r['transport']['error'] is None, 'query exit')
    require(r['output'] == {'complete': True, 'sha256': sha(log), 'size': len(log)}, 'query log SHA')
    require(r['payload_sha256'] == sha(request), 'query request SHA')
    responses = [json.loads(line[len('GPU_CONTROL='):]) for line in log.decode().splitlines() if line.startswith('GPU_CONTROL=')]
    require(responses == [r['remote']] and r['remote']['ok'], 'response binding')
    spec = next(ast.literal_eval(n.value) for n in ast.parse(request).body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'SPEC' for t in n.targets))
    require(all(spec[k] == r[k] == r['remote'][k] for k in ('action', 'request_id', 'release_sha256')), 'spec binding')
    value = r['remote']['result']
    require(value['job_id'] == '713897' and value['jobs_submitted'] == 0 and value['remote_files_written'] is False, 'scope')
    require(value['terminal_sha256'] == '512a5007b6ced40af1c00d80dd984f9d10bd0b3d73c24c9141abc910c69e1bdd', 'old terminal binding')
    records = {v['path']: v for v in value['records']}
    require(len(records) == len(value['records']) == 29, 'metadata inventory')
    arrays = [records[f'artifacts/reference/arrays/{i:03d}.bin'] for i in range(20)]
    require(sum(a['size'] for a in arrays) == 522702496, 'partial array sizes')
    anchor = records['processes/STARTED.json']['mtime_ns']
    events = []
    selected = ['processes/STARTED.json', 'artifacts/reference/PRECHECK.json',
                'artifacts/reference/ENVIRONMENT.json', 'artifacts/reference/arrays/000.bin',
                'artifacts/reference/arrays/019.bin', 'processes/TERMINAL.json']
    for name in selected:
        ns = records[name]['mtime_ns']
        seconds, fraction = divmod(ns, 10**9)
        date = datetime.fromtimestamp(seconds, timezone(timedelta(hours=9)))
        events.append({'file': name, 'mtime_jst': date.strftime('%Y-%m-%dT%H:%M:%S') + f'.{fraction // 10**6:03d}+09:00',
                       'mtime_offset_seconds': round((ns - anchor) / 10**9, 3)})
    return {'status': 'TIMELINE_AND_SOURCE_REVIEW_COMPLETE_NOT_NUMERICAL_PASS', 'job_id': '713897',
            'events': events, 'first_to_last_array_mtime_seconds': round((arrays[-1]['mtime_ns'] - arrays[0]['mtime_ns']) / 10**9, 3),
            'last_array_to_terminal_mtime_seconds': round((records['processes/TERMINAL.json']['mtime_ns'] - arrays[-1]['mtime_ns']) / 10**9, 3),
            'environment_regression': source_environment_check(),
            'receipt_sha256': sha(raw), 'payload_sha256': sha(request), 'log_sha256': sha(log),
            'source_directory': str(D.relative_to(W)), 'numeric_results_verified': False,
            'phase_durations_measured': False, 'arrays_content_verified': False,
            'root_cause_proven': False, 'gpu_jobs_submitted': 0, 'remote_writes': 0}


if __name__ == '__main__':
    result = main()
    raw = (json.dumps(result, sort_keys=True, indent=2) + '\n').encode()
    destination = Path(__file__).with_suffix('.json')
    if destination.exists():
        require(destination.read_bytes() == raw, 'existing review differs; preserve it')
    else:
        with destination.open('xb') as stream:
            stream.write(raw)
    print(raw.decode(), end='')

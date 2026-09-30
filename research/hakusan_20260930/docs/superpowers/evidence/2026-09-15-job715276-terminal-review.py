"""Offline failed-job/phase-evidence checks; no numerical acceptance or writes."""
import ast
import base64
import hashlib
import json
from pathlib import Path

E = Path(__file__).resolve().parent
W = E.parents[2]
D = E / 'gpu-control-20260914-v4/terminal-evidence-20260914T161846Z-u70x17yr'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    raw = (D / 'receipt.json').read_bytes()
    receipt = json.loads(raw)
    log = (D / 'output.log').read_bytes()
    request = (D / 'request.py').read_bytes()
    assert receipt['returncode'] == receipt['transport']['returncode'] == 0
    assert receipt['transport']['error'] is None and receipt['output']['complete']
    assert sha(log) == receipt['output']['sha256'] and len(log) == receipt['output']['size']
    assert sha(request) == receipt['payload_sha256']
    rows = [json.loads(s[len('GPU_CONTROL='):]) for s in log.decode().splitlines() if s.startswith('GPU_CONTROL=')]
    assert rows == [receipt['remote']] and receipt['remote']['ok'] is True
    specs = [ast.literal_eval(n.value) for n in ast.parse(request).body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == 'SPEC' for t in n.targets)]
    assert len(specs) == 1
    for k in ('action', 'request_id', 'release_sha256'):
        assert specs[0][k] == receipt[k] == receipt['remote'][k]
    release_raw = (W / 'docs/superpowers/prototypes/targeted_gpu_control_20260914_v4/CONTROL_RELEASE.json').read_bytes()
    assert sha(release_raw) == receipt['release_sha256'] == 'abc075315541791c201ea637825a5f653253d4a0325126a63c73e560a64c6864'
    sources = json.loads(release_raw)['files']
    assert len(sources) == 58
    for name, digest in sources.items():
        assert sha((W / name).read_bytes()) == digest, name
    value = receipt['remote']['result']
    assert value['remote_files_written'] is False and value['jobs_submitted'] == 0
    assert value['fixed_sources_verified'] == 58
    files, records = {}, {}
    for name, record in value['files'].items():
        data = base64.b64decode(record['base64'], validate=True)
        assert len(data) == record['size'] and sha(data) == record['sha256']
        files[name] = data
        records[name] = {k: record[k] for k in ('sha256', 'size')}
    read = lambda name: json.loads(files[name])
    terminal = read('COORDINATOR_TERMINAL.json')
    start = read('COORDINATOR_STARTED.json')
    pair = read('processes/TERMINAL.json')
    child = read('processes/reference-process.json')
    env = read('artifacts/reference/ENVIRONMENT.json')
    assert terminal['pair'] == pair and pair['children'] == [child]
    assert terminal['status'] == 'GPU_PAIR_NOT_VERIFIED' and pair['status'] == 'PAIR_FAILED'
    assert child['role'] == 'reference' and child['returncode'] == -9
    assert child['error'] == {'type': 'TimeoutError', 'message': 'child deadline reached'}
    assert 3000 <= child['elapsed_seconds'] < 3001
    assert child['log'] == {'name': 'reference.log', **records['processes/reference.log']}
    assert terminal['job_id'] == start['job_id'] == env['slurm_job_id'] == '715276'
    assert terminal['pair_nonce'] == start['pair_nonce'] == '2afc1b76ca1f4a06b9cd921e071a0d1d'
    assert terminal['package_sha256'] == start['package_sha256'] == receipt['package_sha256']
    assert env['worker_pid'] == child['pid'] and env['gpu_name'] == 'NVIDIA A100-PCIE-40GB'
    assert start['limits']['child_seconds'] == read('processes/STARTED.json')['child_seconds'] == 3000
    assert start['limits']['wall_seconds'] == 7200
    runtime = env['startup_runtime']
    assert runtime['fixed_exports'] == {'OMP_NUM_THREADS': '8', 'CUBLAS_WORKSPACE_CONFIG': ':4096:8',
                                        'TOKENIZERS_PARALLELISM': 'false'}
    assert runtime['torch_num_threads'] == 8 and len(runtime['cpu_affinity']) == 8
    accounting = value['accounting']
    assert accounting['returncode'] == 0 and not accounting['truncated'] and not accounting['timed_out']
    row = accounting['stdout'].strip().split('|')
    assert row[:4] == ['715276', 'FAILED', '2:0', '00:50:06']
    assert row[6] == env['hostname'] == 'spcc-a100g06'
    assert row[7] == row[8] == 'billing=8,cpu=8,gres/gpu:nvidia_a100=1,mem=64G,node=1'
    reference = files['processes/reference.log'].decode()
    events = [json.loads(s[len('PHASE_TIMING='):]) for s in reference.splitlines() if s.startswith('PHASE_TIMING=')]
    assert len(events) == 32 and [e['sequence'] for e in events] == list(range(1, 33))
    assert all(e['pid'] == child['pid'] for e in events)
    assert [e['elapsed_seconds'] for e in events] == sorted(e['elapsed_seconds'] for e in events)
    opened, completed = [], []
    for event in events[1:]:
        if event['event'] == 'begin':
            opened.append(event)
        else:
            assert event['event'] == 'end' and opened
            before = opened.pop()
            assert all(event[k] == before[k] for k in ('phase', 'pass_id', 'batch_size', 'pid'))
            completed.append({'phase': event['phase'], 'pass_id': event['pass_id'],
                              'batch_size': event['batch_size'],
                              'wall_seconds': round(event['elapsed_seconds'] - before['elapsed_seconds'], 6),
                              'process_cpu_seconds': round(event['cpu_seconds'] - before['cpu_seconds'], 6)})
    assert [(e['phase'], e['pass_id']) for e in opened] == [
        ('lifetime', None), ("namespace['archived_reference']", None), ('diag.run_trace_pass', 'pass2')]
    assert opened[-1]['batch_size'] == 1
    assert reference.count('Timeout (0:40:00)!') == 1
    for text in ('line 3419 in _live_protected_module_bindings', 'line 4750 in _live_inference_attestation',
                 'line 4808 in _invoke_attested_operator', 'line 5066 in trace_predict_batch'):
        assert text in reference
    arrays = [r for r in value['inventory_metadata_only'] if r['path'].startswith('artifacts/reference/arrays/')]
    assert {r['path'] for r in arrays} == {f'artifacts/reference/arrays/{i:03d}.bin' for i in range(20)}
    assert not any(r['path'].startswith('artifacts/observed') for r in value['inventory_metadata_only'])
    assert 'artifacts/reference/CHILD.json' in value['missing']
    assert 'artifacts/reference/POSTCHECK.json' in value['missing']
    return {'status': 'FAILURE_AND_PHASE_EVIDENCE_VERIFIED_NOT_NUMERICAL_PASS', 'job_id': '715276',
            'start_jst': row[4], 'end_jst': row[5], 'slurm_state': row[1], 'elapsed': row[3], 'node': row[6],
            'direct_failure': child['error'], 'reference_seconds': child['elapsed_seconds'],
            'observed_started': False, 'environment': env, 'completed_phases': completed,
            'unfinished_phases': opened, 'single_stack_sample': 'post cue_preprocess: execution fingerprint / import-module binding validation',
            'stack_sampling_limitation': 'one point only, not a time profile or proof of the entire 44-minute cause',
            'collected_files_verified': len(records), 'files': records, 'receipt_sha256': sha(raw),
            'partial_arrays_metadata_count': len(arrays), 'partial_arrays_bytes': sum(a['size'] for a in arrays),
            'partial_array_content_verified': False, 'sources_reverified_locally': len(sources),
            'numeric_results_verified': False, 'scientific_comparison_complete': False,
            'remote_writes_this_review': 0, 'jobs_submitted_this_review': 0}


if __name__ == '__main__':
    print(json.dumps(main(), sort_keys=True, indent=2))

"""Offline validation of collected failed-job evidence; not numerical acceptance."""
import ast
import base64
import hashlib
import json
from pathlib import Path

E = Path(__file__).resolve().parent
D = E / 'gpu-control-20260914-v3/terminal-evidence-20260914T074214Z-eg9mkxdw'

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def main():
    receipt_raw = (D / 'receipt.json').read_bytes()
    receipt = json.loads(receipt_raw)
    log = (D / 'output.log').read_bytes()
    request = (D / 'request.py').read_bytes()
    assert receipt['returncode'] == 0 and receipt['transport']['error'] is None
    assert receipt['transport']['returncode'] == 0 and receipt['output']['complete']
    assert sha(log) == receipt['output']['sha256'] and len(log) == receipt['output']['size']
    assert sha(request) == receipt['payload_sha256']
    rows = [json.loads(line[len('GPU_CONTROL='):]) for line in log.decode().splitlines() if line.startswith('GPU_CONTROL=')]
    assert rows == [receipt['remote']] and receipt['remote']['ok']
    specs = [ast.literal_eval(n.value) for n in ast.parse(request).body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == 'SPEC' for t in n.targets)]
    assert len(specs) == 1
    for key in ('action', 'request_id', 'release_sha256'):
        assert specs[0][key] == receipt[key] == receipt['remote'][key]
    result = receipt['remote']['result']
    assert result['remote_files_written'] is False and result['jobs_submitted'] == 0
    files = {}
    for name, record in result['files'].items():
        raw = (D / 'download' / name).read_bytes()
        assert raw == base64.b64decode(record['base64'], validate=True)
        assert len(raw) == record['size'] and sha(raw) == record['sha256']
        files[name] = {'size': len(raw), 'sha256': sha(raw)}
    read = lambda name: json.loads((D / 'download' / name).read_bytes())
    terminal = read('COORDINATOR_TERMINAL.json')
    start = read('COORDINATOR_STARTED.json')
    pair = read('processes/TERMINAL.json')
    child = read('processes/reference-process.json')
    environment = read('artifacts/reference/ENVIRONMENT.json')
    assert terminal['pair'] == pair and pair['children'] == [child]
    assert child['role'] == 'reference' and child['returncode'] == -9
    assert child['error'] == {'type': 'TimeoutError', 'message': 'child deadline reached'}
    assert 3000 <= child['elapsed_seconds'] < 3001
    assert child['log'] == {'name': 'reference.log', **files['processes/reference.log']}
    assert terminal['status'] == 'GPU_PAIR_NOT_VERIFIED' and pair['status'] == 'PAIR_FAILED'
    assert terminal['job_id'] == start['job_id'] == environment['slurm_job_id'] == '713897'
    assert terminal['package_sha256'] == start['package_sha256'] == receipt['package_sha256']
    assert terminal['pair_nonce'] == start['pair_nonce'] == '899e59b8732346d782e54b091d6f05e6'
    assert environment['worker_pid'] == child['pid'] and environment['gpu_name'] == 'NVIDIA A100-PCIE-40GB'
    assert start['limits']['child_seconds'] == read('processes/STARTED.json')['child_seconds'] == 3000
    assert start['limits']['wall_seconds'] == 7200
    accounting = result['accounting']
    assert accounting['returncode'] == 0 and not accounting['timed_out'] and not accounting['truncated']
    row = accounting['stdout'].strip().split('|')
    assert row[:4] == ['713897', 'FAILED', '2:0', '00:50:05']
    assert row[6] == environment['hostname'] == 'spcc-a100g04'
    assert row[7] == row[8] == 'billing=8,cpu=8,gres/gpu:nvidia_a100=1,mem=64G,node=1'
    inventory = result['inventory_metadata_only']
    arrays = [r for r in inventory if r['path'].startswith('artifacts/reference/arrays/')]
    assert {r['path'] for r in arrays} == {f'artifacts/reference/arrays/{i:03d}.bin' for i in range(20)}
    assert not any(r['path'].startswith('artifacts/observed') for r in inventory)
    assert 'artifacts/reference/CHILD.json' in result['missing'] and 'artifacts/reference/POSTCHECK.json' in result['missing']
    return {'schema_version': 1, 'status': 'FAILURE_EVIDENCE_VERIFIED_NOT_NUMERICAL_PASS',
            'job_id': '713897', 'slurm_state': row[1], 'exit_code': row[2], 'elapsed': row[3],
            'start_jst': row[4], 'end_jst': row[5], 'node': row[6], 'environment': environment,
            'direct_failure': child['error'], 'reference_child_elapsed_seconds': child['elapsed_seconds'],
            'reference_child_returncode': child['returncode'], 'observed_started': False,
            'coordinator_status': terminal['status'], 'child_completion_record_present': False,
            'partial_arrays_metadata_count': len(arrays), 'partial_arrays_bytes': sum(r['size'] for r in arrays),
            'partial_arrays_content_verified': False, 'slow_operation_identified': False,
            'collected_files_verified': len(files), 'file_records': files,
            'receipt_sha256': sha(receipt_raw), 'request_sha256': sha(request), 'output_sha256': sha(log),
            'sources_checked_by_collector': 55, 'numeric_results_verified': False,
            'scientific_comparison_complete': False, 'remote_writes_this_review': 0, 'jobs_submitted_this_review': 0}

if __name__ == '__main__':
    print(json.dumps(main(), sort_keys=True, indent=2))

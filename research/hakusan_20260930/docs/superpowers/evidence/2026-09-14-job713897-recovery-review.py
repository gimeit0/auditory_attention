"""Offline review of the actual one-submit, one-update, one-release evidence."""
import ast
import hashlib
import json
from pathlib import Path
import sys

W = Path(__file__).resolve().parents[3]
C = W / 'docs/superpowers/prototypes/targeted_gpu_control_20260914_v3'
E = W / 'docs/superpowers/evidence/gpu-control-20260914-v3'
sys.path.insert(0, str(C))
import control
import repair_713897 as repair

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def receipt(name, action, rc=0):
    path = E / name / 'receipt.json'
    raw = path.read_bytes()
    value = json.loads(raw)
    output = (path.parent / 'output.log').read_bytes()
    payload = (path.parent / 'request.py').read_bytes()
    assert value['action'] == action and value['returncode'] == rc
    assert value['output']['complete'] and len(output) == value['output']['size']
    assert sha(output) == value['output']['sha256'] and sha(payload) == value['payload_sha256']
    rows = [json.loads(x[len('GPU_CONTROL='):]) for x in output.decode().splitlines() if x.startswith('GPU_CONTROL=')]
    assert rows == [value['remote']]
    assignments = [x for x in ast.parse(payload).body if isinstance(x, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'SPEC' for t in x.targets)]
    assert len(assignments) == 1
    spec = ast.literal_eval(assignments[0].value)
    for field in ('request_id', 'action', 'release_sha256'):
        assert value[field] == value['remote'][field] == spec[field]
    assert value['release_sha256'] == repair.RELEASE_SHA
    assert value['package_sha256'] == control.ops.PACKAGE_SHA
    assert value['transport']['error'] is None and value['transport']['returncode'] == rc
    assert value['remote']['ok'] == (rc == 0)
    return value, {'path': str(path.relative_to(W)), 'sha256': sha(raw),
                   'output_sha256': sha(output), 'request_sha256': sha(payload)}

def main():
    raw, release, files = control.package()
    assert sha(raw) == repair.RELEASE_SHA and len(files) == 55
    source_sha = sha((C / 'repair_713897.py').read_bytes())
    assert source_sha == 'dcc76f61a7a66a3379e9e0e76862468843d3d41231103ffd3f6b0fde57b1270c'
    tests = json.loads((W / 'docs/superpowers/evidence/2026-09-14-job713897-recovery-local.json').read_bytes())
    assert tests['source_sha256'] == source_sha and tests['tests'] == 15 and tests['process']['exit_code'] == 0
    assert tests['tests_sha256'] == sha((C / 'test_repair_713897.py').read_bytes())
    values, records = {}, []
    for key, name, action, rc in (
        ('submit', 'submit-20260914T023407Z-8zy3ngas', 'submit', 2),
        ('held', 'status-20260914T023611Z-jod13kgb', 'status', 0),
        ('inspect', 'inspect-20260914T024441Z-t17norbp', 'inspect', 0),
        ('update', 'update-20260914T024949Z-hrdv1x3f', 'update', 0),
        ('release', 'release-20260914T025722Z-ivw1d9j3', 'release', 0),
        ('latest', 'status-20260914T025952Z-ag_imzup', 'status', 0),
    ):
        values[key], record = receipt(name, action, rc)
        records.append(record)
    assert values['submit']['remote']['error']['message'] == 'held scheduler request differs'
    result = lambda key: values[key]['remote']['result']
    repair.validate_snapshot(result('inspect')['snapshot'], control.ops.REMOTE, corrected=False)
    repair.validate_snapshot(result('update')['after'], control.ops.REMOTE, corrected=True)
    assert result('update')['status'] == 'GPU_TYPE_CORRECTED_STILL_HELD'
    assert result('release')['status'] == 'SAME_JOB_RELEASED'
    for key in ('update', 'release'):
        assert result(key)['job_id'] == repair.JOB and result(key)['jobs_submitted'] == 0
        assert values[key]['remote']['repair_source_sha256'] == source_sha
    journals = result('latest')['journals']
    auth = journals['AUTHORIZATION.json']
    assert auth == journals['SUBMIT_INTENT.json'] == journals['SUBMISSION_RECEIPT.json']['authorization']
    assert auth['pair_nonce'] == repair.NONCE and auth['limits'] == control.ops.LIMITS
    assert auth['approved'] and auth['package_sha256'] == control.ops.PACKAGE_SHA and auth['scope'] == control.ops.SCOPE
    intent = json.loads((E / 'LOCAL_SUBMIT_INTENT.json').read_bytes())
    assert intent['authorization'] == auth and intent['request_id'] == values['submit']['request_id']
    assert journals['SBATCH_RESPONSE.json']['stdout'] == repair.JOB + '\n'
    assert journals['SUBMISSION_RECEIPT.json']['jobs_submitted'] == 1
    assert journals['SUBMISSION_RECEIPT.json']['job_id'] == repair.JOB
    assert len(list(E.glob('submit-*/receipt.json'))) == 1
    assert len(list(E.glob('update-*/receipt.json'))) == len(list(E.glob('release-*/receipt.json'))) == 1
    repair.validate_snapshot(journals['RELEASE_INTENT.json']['before'], control.ops.REMOTE, corrected=True)
    assert journals['RELEASE_INTENT.json']['command'] == repair.RELEASE
    assert control.ops.success(journals['RELEASE_RESPONSE.json'])
    assert journals['RELEASED.json'] == result('release')
    after = result('release')['after']
    job = repair.fields(after['job']['stdout'])
    assert job['Priority'] != '0' and job['Reason'] not in ('JobHeldUser', 'JobHeldAdmin')
    assert job['TresPerJob'] == job['TresPerNode'] == repair.GPU
    req = repair.resources(job['ReqTRES'])
    repair.validate_accounting(after['accounting']['stdout'], req)
    for key in ('squeue', 'sacct'):
        assert control.ops.success(result('latest')[key])
    assert result('latest')['squeue']['stdout'] == '713897|PENDING|0:00|(Resources)\n'
    assert '713897|PENDING|0:0|00:00:00|None assigned' in result('latest')['sacct']['stdout']
    assert 'coordinator_summary' not in result('latest')
    return {'schema_version': 1, 'status': 'ONE_SUBMIT_SAME_JOB_CORRECTION_RELEASE_REVIEW_PASS',
            'job_id': repair.JOB, 'pair_nonce': repair.NONCE, 'recovery_source_sha256': source_sha,
            'release_sha256': repair.RELEASE_SHA, 'package_sha256': control.ops.PACKAGE_SHA,
            'fixed_sources_verified': len(files), 'local_recovery_tests': 15,
            'submitted_jobs': 1, 'same_job_updates': 1, 'same_job_releases': 1,
            'repeat_submission': False, 'prior_error_records_preserved': True,
            'requested_resources': req, 'latest_snapshot_jst': '2026-09-14 12:00',
            'latest_state': 'PENDING', 'latest_reason': 'Resources', 'node_assigned': False,
            'runtime_seconds': 0, 'numeric_results_verified': False,
            'scientific_comparison_complete': False, 'receipts': records}

if __name__ == '__main__':
    print(json.dumps(main(), sort_keys=True, indent=2))

"""Read-only rehash of v3 deployment/test-only/status evidence. No SSH."""
import ast
import base64
import hashlib
import json
from pathlib import Path

W = Path(__file__).resolve().parents[3]
E = W / 'docs/superpowers/evidence'
D = E / 'gpu-control-20260914-v3'
C = W / 'docs/superpowers/prototypes/targeted_gpu_control_20260914_v3'
RELEASE = '355f29740dfdc159402c49a80b01e79acc1b69b9000e1361edf1e680d50aec52'
PACKAGE = '2adce67a2b4a0b0d38ff3bf6fbb682863b6e58fccf65743dd213b927d185c687'

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def main():
    raw = (C / 'CONTROL_RELEASE.json').read_bytes()
    assert sha(raw) == RELEASE
    release = json.loads(raw)
    assert release['package_sha256'] == PACKAGE and len(release['files']) == 55
    for name, digest in release['files'].items():
        assert sha((W / name).read_bytes()) == digest, name
    outcomes = {}
    for folder in (
        'preflight-20260914T005834Z-x6zyvfne', 'deploy-20260914T010331Z-41evwwrc',
        'test-only-20260914T010429Z-pri4e2f6', 'status-20260914T010548Z-84zr39pr',
    ):
        p = D / folder
        receipt_raw = (p / 'receipt.json').read_bytes()
        receipt = json.loads(receipt_raw)
        assert receipt['release_sha256'] == RELEASE and receipt['package_sha256'] == PACKAGE
        assert receipt['returncode'] == 0 and receipt['parse_error'] is None and not receipt['automatic_retry']
        assert receipt['transport']['returncode'] == 0 and receipt['transport']['error'] is None
        out = (p / 'output.log').read_bytes()
        assert receipt['output'] == {'complete': True, 'sha256': sha(out), 'size': len(out)}
        records = [json.loads(line[len('GPU_CONTROL='):]) for line in out.decode().splitlines()
                   if line.startswith('GPU_CONTROL=')]
        assert records == [receipt['remote']] and records[0]['ok'] is True
        payload = (p / 'request.py').read_bytes()
        assert sha(payload) == receipt['payload_sha256']
        tree = ast.parse(payload)
        spec = next(ast.literal_eval(node.value) for node in tree.body
                    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == 'SPEC')
        assert all(spec[k] == receipt[k] == records[0][k] for k in ('action', 'request_id', 'release_sha256'))
        assert 'confirm' not in spec and 'authorization' not in spec and spec['action'] != 'submit'
        if spec['action'] == 'deploy':
            assert set(spec['files']) == set(release['files'])
            for name, data in spec['files'].items():
                assert sha(base64.b64decode(data, validate=True)) == release['files'][name]
        result = records[0]['result']
        assert result['jobs_submitted'] == 0
        outcomes[spec['action']] = {'path': str((p / 'receipt.json').relative_to(W)),
                                    'sha256': sha(receipt_raw), 'result': result}
    assert outcomes['preflight']['result']['root_exists'] is False
    deployed = outcomes['deploy']['result']
    assert deployed['status'] == 'GPU_PACKAGE_DEPLOYED' and deployed['files'] == 55
    assert deployed['bytes'] == sum(len((W / name).read_bytes()) for name in release['files'])
    test = outcomes['test-only']['result']
    assert test['status'] == 'SCHEDULER_TEST_ONLY_PASS' and test['scheduler']['returncode'] == 0
    assert not test['scheduler']['timed_out'] and not test['scheduler']['truncated']
    status = outcomes['status']['result']
    assert status['journals'] == {'DEPLOYMENT.json': deployed}
    assert set(status['top_level']) == {'.upload-staging', 'CONTROL_RELEASE.json', 'DEPLOYMENT.json',
                                       'logs', 'package', 'test_only'}
    assert not (D / 'LOCAL_SUBMIT_INTENT.json').exists()
    return {'status': 'GPU_V3_DEPLOYMENT_TEST_ONLY_REVERIFIED', 'schema_version': 1,
            'control_release_sha256': RELEASE, 'package_sha256': PACKAGE, 'files': 55,
            'operations': outcomes, 'resource_authorization_present': False,
            'local_submit_intent_present': False, 'remote_submit_intent_present': False,
            'new_jobs_submitted': 0, 'old_jobs_mutated': False,
            'estimated_test_only_identifier_is_real_job': False,
            'ready_for_gpu_execution_claimed': False, 'scientific_comparison_complete': False}

if __name__ == '__main__':
    print(json.dumps(main(), indent=2, sort_keys=True))

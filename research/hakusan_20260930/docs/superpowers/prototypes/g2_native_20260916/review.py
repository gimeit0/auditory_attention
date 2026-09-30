"""Read-only review of the two fixed native results, including the failed check."""
import ast
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
EVIDENCE = ROOT / 'docs/superpowers/evidence'
sys.path.insert(0, str(HERE))
import run as api


def bound(folder, receipt_sha):
    raw = api.read(folder / 'receipt.json')
    api.require(api.sha(raw) == receipt_sha, 'fixed receipt changed')
    receipt = json.loads(raw)
    api.require({p.name for p in folder.iterdir() if p.is_file()} == set(receipt['artifacts']) | {'receipt.json'}, 'artifact inventory differs')
    for name, digest in receipt['artifacts'].items():
        api.require(Path(name).name == name and api.sha(api.read(folder / name)) == digest, 'artifact changed: ' + name)
    return receipt


def review():
    api_folder = EVIDENCE / 'g2-api-native_cpu-20260916T013120Z-7vdn9nd4'
    api_receipt = bound(api_folder, '8f5f7ad6c83f221711cb5f36d729afc21492f6ab6c6c65d38d4a04bca12428c1')
    api.require(api_receipt['status'] == 'VERIFIED' and api_receipt['mode'] == 'NATIVE_CPU', 'API result differs')
    spec = ast.literal_eval(api.read(api_folder / 'request.py').split(b'\n', 1)[0][5:].decode())
    result = json.loads(api.read(api_folder / 'result.json'))
    api.validate(result, spec)
    lines = [json.loads(line[len(api.PREFIX):]) for line in api.read(api_folder / 'stdout.log').decode().splitlines() if line.startswith(api.PREFIX)]
    api.require(lines == [result], 'API stdout/result differs')
    for name, row in result['compiler_sources'].items():
        api.require(api.read(api_folder / (name + '.source.py')) == base64.b64decode(row['source'], validate=True), 'exported source differs')

    failed_folder = EVIDENCE / 'g2-backend-native-20260916T013920Z-ngwjkwdm'
    failed_receipt = bound(failed_folder, '4301dd0c3ef8ff80aaa511db173055ce528af0e6fea9df4bd763b5db90ca2a40')
    failed = json.loads(api.read(failed_folder / 'result.json'))
    failed_spec = ast.literal_eval(api.read(failed_folder / 'request.py').split(b'\n', 1)[0][5:].decode())
    api.require(failed_receipt['status'] == 'FAILED' and failed['status'] == 'NATIVE_TOY_INDUCTOR_FAILED'
                and failed['request_id'] == failed_spec['request_id'], 'failure identity differs')
    process = failed['process']
    log = base64.b64decode(failed['log'], validate=True)
    api.require(process['error'] == dict(type='TimeoutError', message='child deadline reached')
                and process['returncode'] == -9 and 50 <= process['elapsed_seconds'] < 51
                and log == api.read(failed_folder / 'child.log') == b''
                and process['log']['sha256'] == api.sha(log) and process['log']['size'] == 0, 'timeout/log differs')
    api.require(failed['temporary_directory_removed'] is True and failed['home_unchanged'] is True
                and failed['jobs_submitted'] == 0 and failed['production_ready'] is False
                and 'child' not in failed, 'failure cannot be scientific success')
    api.require(failed['sources'] == {n: v['sha256'] for n, v in failed_spec['files'].items()}, 'child source binding differs')
    lines = [json.loads(line.split('=', 1)[1]) for line in api.read(failed_folder / 'stdout.log').decode().splitlines() if line.startswith('G2_COMPILED_RESULT=')]
    api.require(lines == [failed], 'supervisor record differs')
    return dict(status='G2_NATIVE_EVIDENCE_REVIEW_PASS', api_profiles=['R', 'C', 'D', 'E'],
                native_python=result['python'], native_torch=result['torch'], api_elapsed=result['elapsed_seconds'],
                compiled_check='TIMEOUT_NOT_VERIFIED', timeout_phase='UNKNOWN_NO_CHILD_STAGE_LOG',
                child_seconds=process['elapsed_seconds'], temporary_directory_removed=True,
                production_ready=False, jobs_submitted=0)


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))

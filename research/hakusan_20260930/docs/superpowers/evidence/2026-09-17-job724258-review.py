"""Offline replay of completed Job724258 evidence; no model or remote calls."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).absolute().parents[3]
BASE = ROOT/'docs/superpowers/evidence/g2-production-20260917'
FOLDER = BASE/'terminal-20260917T114730Z-jwssu96n'
RECEIPT_SHA = 'e1393c2ec4f1baa02071c4495e2b8aa328e15d2dc54c30e0d9c8b0ce0ade0f13'
RELEASE = '6becba7b27f8ba37657e66f0173bf991aec0136e8285afbd211eeeb65318d300'
PLAN = 'f8d8e491fe64c3430845b25d850e8e992ea71ecd79c52d744089a318b6e4e59e'
REQUEST = '7225bb609611114f84026e4eca7fc107ac5ccfb8db4946f2bceb81db9565e309'
ENTRY = '31e3594d66bf6da52d7a35873322df4b20eac16640cf75b6050e563005a99125'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    assert not any(p.is_symlink() for p in (path, *path.parents))
    return path.read_bytes()


def transport(folder):
    raw = read(folder/'RECEIPT.json')
    value = json.loads(raw)
    assert value['returncode'] == value['transport']['returncode'] == 0 and value['transport']['error'] is None
    assert sha(read(folder/'request.py')) == value['payload_sha256']
    assert sha(read(folder/'output.log')) == value['output_sha256']
    return value


assert sha(read(FOLDER/'RECEIPT.json')) == RECEIPT_SHA
receipt = transport(FOLDER)
result = receipt['result']['result']
assert receipt['result']['ok'] and result['job_id'] == '724258'
raw_message = json.loads(read(FOLDER/'output.log').decode().split('G2_COLLECT=', 1)[1])
download = FOLDER/'download'
actual = {str(p.relative_to(download)) for p in download.rglob('*') if not p.is_dir()}
assert actual == set(result['files']) == set(raw_message['result']['files']) and len(actual) == 80
for name, record in result['files'].items():
    raw = read(download/name)
    assert sha(raw) == record['sha256'] and len(raw) == record['size']
    assert raw == base64.b64decode(raw_message['result']['files'][name]['data'], validate=True)
assert sum(v['size'] for v in result['files'].values()) == result['total_bytes'] == 3248939

for name, expected in (('RELEASE.json',RELEASE), ('EXECUTION_PLAN.json',PLAN), ('RUN_REQUEST.json',REQUEST)):
    assert sha(read(download/name)) == expected
source = json.loads(read(download/'RELEASE.json'))
assert len(source['files']) == 32
candidate = ROOT/'docs/superpowers/evidence/g2-entry-local-20260917T063951Z-zcygp8in/candidate'
for name, expected in source['files'].items():
    assert sha(read(download/name)) == expected and read(download/name) == read(candidate/name)
request = json.loads(read(download/'RUN_REQUEST.json'))
for p, expected in request['freezes'].items():
    assert sha(read(download/p/'input_freeze.json')) == expected

path = download/'package/docs/superpowers/prototypes/g2_runtime_20260917/entry.py'
assert sha(read(path)) == ENTRY
spec = importlib.util.spec_from_file_location('review_entry', path)
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)  # standard-library-only import, never run main
entry.validate_request(request)
top = download/'attempts/slurm-724258'
entry.check_scheduler(read(top/'ALLOCATION_BEFORE.log').decode(), request)
allocation = json.loads(read(top/'ALLOCATION_BEFORE.json'))
assert allocation['returncode'] == 0 and allocation['error'] is None
assert allocation['log']['sha256'] == sha(read(top/'ALLOCATION_BEFORE.log'))
parent = json.loads(read(top/'TERMINAL.json'))
worker = json.loads(read(download/'R/attempts/slurm-724258/TERMINAL.json'))
launch = json.loads(read(top/'R/LAUNCH.json'))
assert parent['job_id'] == worker['job_id'] == request['job_id'] == '724258'
assert parent['request_sha256'] == launch['request_sha256'] == REQUEST
assert parent['status'] == worker['status'] == 'EXECUTION_INVALID'
assert worker['pid'] == launch['pid'] == 852000 and launch['returncode'] == 2 and launch['error'] is None
assert launch['environment']['CUBLAS_WORKSPACE_CONFIG'] == ':4096:8'
assert launch['log']['sha256'] == sha(read(top/'R/worker.log'))
assert worker['source_postcheck'] is True and worker['result'] is None
assert 'CUDA already initialized before CUBLAS configuration check' in worker['error']['message']
assert parent['result']['decision'] == 'STOP_EXECUTION_INVALID'
assert all(parent['result']['cells'][p]['status'] == 'NOT_RUN' for p in ('C','D','E'))
assert not any(n.endswith('ARCHIVE_RECEIPT.json') or '/arrays/' in n for n in actual)
accounting = result['accounting']['stdout'].strip().split('|')
assert accounting[:4] == ['724258','FAILED','2:0','00:00:34'] and accounting[-1] == 'spcc-a100g06'
assert 'gres/gpu:nvidia_a100=1' in accounting[6] and 'gres/gpu:nvidia_a100=1' in accounting[7]

for folder, status in (('repair-update-20260917T102452Z-9k201rwc','A100_CORRECTED_STILL_HELD'),
                       ('repair-release-20260917T102700Z-et0hqfb_','SAME_JOB_RELEASED')):
    op = transport(BASE/folder)['result']['result']
    assert op['status'] == status and op['job_id'] == '724258' and op['jobs_submitted'] == 0
submitted = json.loads(read(download/'state/SBATCH_RESPONSE.json'))
assert submitted['stdout'].strip() == '724258' and submitted['returncode'] == 0
assert '--gres=gpu:nvidia_a100:1' in submitted['argv'] and '--hold' in submitted['argv']
print(json.dumps(dict(status='RECORDED_EXECUTION_FAILURE_VERIFIED', job_id='724258',
    files_verified=80, execution_sources_unchanged=32, input_freezes_verified=4,
    actual_allocation='1 A100 / 8 CPU / 64 GiB', recorded_execution_seconds=34,
    error=worker['error']['message'], profiles_not_run=['C','D','E'],
    numeric_results_available=False, full_comparison_complete=False, remote_calls=0), sort_keys=True))

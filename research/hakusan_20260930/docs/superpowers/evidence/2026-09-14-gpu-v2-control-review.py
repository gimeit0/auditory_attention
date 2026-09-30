"""Independent read-only source, test-artifact and historical-format recheck."""
import hashlib
import json
from pathlib import Path
import re
import sys

W = Path('/Users/gigi/发表/超算')
E = W / 'docs/superpowers/evidence'
H = W / 'docs/superpowers/prototypes/targeted_gpu_control_20260914'
sys.path.insert(0, str(H))
import remote_ops as ops

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def read_json(path):
    return json.loads(path.read_bytes())

releases = []
for version, expected, count in (
    ('20260913', '22d8b009c314bed3255e3332b29821655bac597b8032cad3640bddeb34022646', 51),
    ('20260914', '42da7aec12a2b64a7a9608d1f047cdddf1230d5b949ce12401947eb3cbab5b67', 55),
):
    p = W / ('docs/superpowers/prototypes/targeted_gpu_control_' + version) / 'CONTROL_RELEASE.json'
    raw = p.read_bytes()
    value = json.loads(raw)
    assert sha(raw) == expected and len(value['files']) == count
    for name, digest in value['files'].items():
        assert sha((W / name).read_bytes()) == digest, name
    releases.append({'path': str(p.relative_to(W)), 'sha256': expected, 'files_checked': count})

tests = []
for dirname, expected_tests, release_sha in (
    ('gpu-control-v2-local-20260913T185915Z-3mbpu883', 45, releases[1]['sha256']),
    ('gpu-control-local-20260913T190002Z-lgd9vm4s', 34, releases[0]['sha256']),
):
    folder = E / dirname
    value = read_json(folder / 'receipt.json')
    assert value['status'] == 'LOCAL_GPU_CONTROL_VERIFIED'
    assert value['control_release_sha256'] == release_sha
    assert value['child']['tests'] == expected_tests and value['child']['skips'] == 0
    assert value['process']['pid'] == value['child']['pid']
    assert value['process']['returncode'] == 0 and value['process']['error'] is None
    assert value['jobs_submitted'] == 0 and not value['remote_executed']
    for name, record in value['artifacts'].items():
        raw = (folder / name).read_bytes()
        assert len(raw) == record['size'] and sha(raw) == record['sha256']
    assert read_json(folder / 'child-result.json') == value['child']
    tests.append({'path': str((folder / 'receipt.json').relative_to(W)),
                  'sha256': sha((folder / 'receipt.json').read_bytes()), 'tests': expected_tests})

# Real archived HAKUSAN syntax, not a new scheduler query or allocation.
base = E / 'gpu-control-20260913-v1'
good_path = base / 'update-20260913T093954Z-5gjz49so/receipt.json'
good = read_json(good_path)
log = (good_path.parent / 'output.log').read_bytes()
assert sha(log) == good['output']['sha256'] and len(log) == good['output']['size']
line = [x[len('GPU_CONTROL='):] for x in log.decode().splitlines() if x.startswith('GPU_CONTROL=')]
assert len(line) == 1 and json.loads(line[0]) == good['remote']
assert good['remote']['ok'] and good['returncode'] == 0
after = good['remote']['result']['after']
nonce = 'b2a68a80c4fb4717901cc76230af53e8'
old_root = '/home/s2510040/audattn_external_eval_diag/gpu_pair_2026-09-13_v1'
def relabel_only_paths(text):
    return text.replace(old_root, str(ops.REMOTE)).replace('targeted_gpu_job_20260913/', 'targeted_gpu_job_20260914/')
requested = ops.held_request_matches(relabel_only_paths(after['job']['stdout']), '705468', nonce, ops.REMOTE)
ops.held_accounting_matches(after['accounting']['stdout'], '705468', requested)
assert 'gres/gpu' not in requested and requested['gres/gpu:nvidia_a100'] == '1'
bad_path = base / 'HELD_ALLOCATION_READBACK.json'
try:
    ops.held_request_matches(relabel_only_paths(read_json(bad_path)['stdout']), '705468', nonce, ops.REMOTE)
except RuntimeError:
    rejected = True
else:
    raise AssertionError('historical H100/generic mismatch accepted')

probe_path = E / 'startup-probe-remote-20260913T190003Z-666g_w9r/receipt.json'
probe = read_json(probe_path)
assert not probe['self_test'] and probe['process'] is None and probe['result'] is None
assert probe['status'] == 'STARTUP_CPU_PROBE_NOT_VERIFIED' and probe['jobs_submitted'] == 0
assert probe['error']['type'] == 'FileNotFoundError' and 'master.sock' in probe['error']['message']

result = {
    'schema_version': 1, 'status': 'LOCAL_GPU_V2_CONTROL_REVIEW_PASS',
    'sources': releases, 'tests': tests,
    'historical_scheduler_format': {
        'scope': 'offline replay, only root/runner paths relabelled; no resource values changed',
        'job_id': '705468', 'actual_typed_only_A100_record_accepted': True,
        'actual_H100_generic_mismatch_rejected': rejected,
        'inputs': {str(p.relative_to(W)): sha(p.read_bytes()) for p in (good_path, bad_path)},
    },
    'native_startup_probe': {'path': str(probe_path.relative_to(W)), 'sha256': sha(probe_path.read_bytes()),
                             'status': probe['status'], 'payload_sent': False, 'error': probe['error']},
    'remote_deployed_this_run': False, 'jobs_submitted': 0, 'resources_authorized': False,
    'scientific_comparison_complete': False,
}
print(json.dumps(result, indent=2, sort_keys=True))

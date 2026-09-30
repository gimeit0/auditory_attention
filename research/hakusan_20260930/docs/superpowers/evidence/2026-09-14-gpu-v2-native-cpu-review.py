"""Read-only independent recheck of the native CPU startup evidence, no SSH."""
import base64
import hashlib
import json
from pathlib import Path

W = Path(__file__).resolve().parents[3]
E = W / 'docs/superpowers/evidence'
D = E / 'startup-probe-remote-20260914T002026Z-9etqy2ka'
P = W / 'docs/superpowers/prototypes/targeted_gpu_startup_probe_20260914'
PACKAGE = '8ddf8cc8ece27a14c49336b60fd1a45ffa295f57fb45778a66c559514d6d04f5'

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def checked_file(path, record):
    raw = path.read_bytes()
    assert len(raw) == record['size'] and digest(raw) == record['sha256'], str(path)
    return raw

def main():
    raw = (D / 'receipt.json').read_bytes()
    receipt = json.loads(raw)
    assert receipt['status'] == 'STARTUP_CPU_PROBE_VERIFIED' and receipt['self_test'] is False
    assert receipt['package_sha256'] == PACKAGE and receipt['error'] is None
    process = receipt['process']
    assert process['returncode'] == 0 and process['error'] is None and 0 < process['elapsed_seconds'] < 115
    assert receipt['jobs_submitted'] == 0 and receipt['ready_for_gpu'] is False
    assert digest((P / 'run_probe.py').read_bytes()) == receipt['driver_sha256']
    assert digest((P / 'probe_parent.py').read_bytes()) == receipt['parent_sha256']
    manifest_path = 'docs/superpowers/prototypes/targeted_gpu_job_20260914/SOURCE_MANIFEST.json'
    manifest_raw = (W / manifest_path).read_bytes()
    assert digest(manifest_raw) == PACKAGE
    expected = dict(json.loads(manifest_raw)['files'])
    assert len(expected) == 49
    expected[manifest_path] = PACKAGE
    child_path = str((P / 'probe_child.py').relative_to(W))
    expected[child_path] = digest((P / 'probe_child.py').read_bytes())
    assert receipt['source_sha256'] == expected and len(expected) == 51
    for name, sha in expected.items():
        assert digest((W / name).read_bytes()) == sha, name
    for name, record in receipt['artifacts'].items():
        assert Path(name).name == name
        checked_file(D / name, record)
    output = checked_file(D / 'output.log', receipt['artifacts']['output.log'])
    records = [json.loads(line)['startup_cpu_result'] for line in output.decode().splitlines()
               if line.startswith('{"startup_cpu_result":')]
    assert len(records) == 1 and records[0] == receipt['result']
    remote = records[0]
    assert remote['status'] == 'HAKUSAN_STARTUP_CPU_PASS' and remote['local_test'] is False
    assert remote['error'] is None and remote['source_files'] == 51 and remote['sources_unchanged'] is True
    assert remote['temporary_directory_removed'] is True and remote['package_sha256'] == PACKAGE
    assert remote['jobs_submitted'] == remote['forward_calls'] == 0 and not remote['production_model_loaded']
    assert remote['ready_for_gpu'] is False
    assert len(remote['cases']) == 3
    assert {c['case'] for c in remote['cases']} == {'old-reference', 'new-reference', 'new-observed'}
    assert len({c['process']['pid'] for c in remote['cases']}) == 3
    assert sum(c['process']['elapsed_seconds'] for c in remote['cases']) < 85
    summary = []
    for c in remote['cases']:
        p, r = c['process'], c['result']
        assert p['returncode'] == 0 and p['error'] is None and 0 < p['elapsed_seconds'] <= 45
        assert r['pid'] == p['pid'] and c['case'] == r['mode'] + '-' + r['role']
        assert r['status'] == 'HAKUSAN_STARTUP_IMPORT_PASS' and r['error'] is None
        assert r['python'] == '3.11.5' and r['torch'] == '2.1.1+cu118' and r['local_test'] is False
        assert r['package_sha256'] == PACKAGE and r['home_preserved'] is True
        assert r['forward_calls'] == r['jobs_submitted'] == 0
        assert not any(r[k] for k in ('cuda_initialized', 'production_model_loaded', 'allocation_claimed', 'ready_for_gpu'))
        log = base64.b64decode(c['log_base64'], validate=True)
        assert log == checked_file(D / (c['case'] + '.log'), p['log'])
        assert json.loads((D / (c['case'] + '.json')).read_bytes()) == r
        if r['mode'] == 'new':
            assert all(r[k] is True for k in ('torch_absent_before_scratch', 'caches_initially_empty',
                                              'anchors_closed', 'original_loader_binding_checked'))
            assert r['mount']['filesystem'] == 'xfs' and r['mount']['mount'] == '/tmp'
        else:
            assert r['collision_reproduced'] is False and r['role_exists_before_factory'] is False
        summary.append({k: r[k] for k in ('mode', 'role', 'pid', 'python', 'torch', 'mount')})
    releases = []
    for version, sha, count in (
        ('20260913', '22d8b009c314bed3255e3332b29821655bac597b8032cad3640bddeb34022646', 51),
        ('20260914', '42da7aec12a2b64a7a9608d1f047cdddf1230d5b949ce12401947eb3cbab5b67', 55),
    ):
        path = W / ('docs/superpowers/prototypes/targeted_gpu_control_' + version) / 'CONTROL_RELEASE.json'
        value = path.read_bytes()
        assert digest(value) == sha
        files = json.loads(value)['files']
        assert len(files) == count
        for name, pinned in files.items():
            assert digest((W / name).read_bytes()) == pinned, name
        releases.append({'sha256': sha, 'source_files': count})
    return {'schema_version': 1, 'status': 'NATIVE_CPU_STARTUP_EVIDENCE_REVERIFIED',
            'receipt_path': str((D / 'receipt.json').relative_to(W)), 'receipt_sha256': digest(raw),
            'package_sha256': PACKAGE, 'cases': summary, 'source_files_rechecked': 51,
            'artifact_files_rechecked': len(receipt['artifacts']), 'control_releases': releases,
            'old_failure_reproduced_on_native_cpu': False,
            'scope': 'Native HAKUSAN CPU import/scratch/binding/cleanup only; no model load, forward or CUDA',
            'jobs_submitted': 0, 'ready_for_gpu': False, 'scientific_comparison_complete': False}

if __name__ == '__main__':
    print(json.dumps(main(), sort_keys=True, indent=2))

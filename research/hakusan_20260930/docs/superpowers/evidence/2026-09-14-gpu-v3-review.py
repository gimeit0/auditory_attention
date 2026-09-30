"""Independent local source/artifact and historical scheduler-format review."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

W = Path(__file__).resolve().parents[3]
E = W / 'docs/superpowers/evidence'
B = W / 'docs/superpowers/prototypes'
J = B / 'targeted_gpu_job_20260914_v3'
C = B / 'targeted_gpu_control_20260914_v3'
sys.path.insert(0, str(C))
import remote_ops as ops

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def json_file(path):
    return json.loads(path.read_bytes())

def checked(path, record):
    raw = path.read_bytes()
    assert len(raw) == record['size'] and sha(raw) == record['sha256'], str(path)
    return raw

def main():
    releases = []
    for version, pin, count in (
        ('20260913', '22d8b009c314bed3255e3332b29821655bac597b8032cad3640bddeb34022646', 51),
        ('20260914', '42da7aec12a2b64a7a9608d1f047cdddf1230d5b949ce12401947eb3cbab5b67', 55),
        ('20260914_v3', '355f29740dfdc159402c49a80b01e79acc1b69b9000e1361edf1e680d50aec52', 55),
    ):
        p = B / ('targeted_gpu_control_' + version) / 'CONTROL_RELEASE.json'
        raw = p.read_bytes()
        assert sha(raw) == pin
        value = json.loads(raw)
        assert len(value['files']) == count
        for name, digest in value['files'].items():
            assert sha((W / name).read_bytes()) == digest, name
        releases.append({'path': str(p.relative_to(W)), 'sha256': pin, 'files': count})
    oldj = B / 'targeted_gpu_job_20260914'
    old = json_file(oldj / 'SOURCE_MANIFEST.json')
    new = json_file(J / 'SOURCE_MANIFEST.json')
    prefix = str(oldj.relative_to(W)) + '/'
    newprefix = str(J.relative_to(W)) + '/'
    assert len(old['files']) == len(new['files']) == 49
    same, changed, shared = [], [], []
    for name, digest in old['files'].items():
        if name.startswith(prefix):
            name2 = name.replace(prefix, newprefix)
            (same if digest == new['files'][name2] else changed).append(Path(name).name)
        else:
            assert new['files'][name] == digest
            shared.append(name)
    assert set(changed) == {'README.md', 'coordinator.py', 'job_contract.py',
                            'run_gpu.sbatch', 'test_job_control.py', 'validate_local.py'}
    assert 'gpu_child.py' in same and 'verify_results.py' in same and len(shared) == 35
    for name in ('coordinator.py', 'job_contract.py'):
        content = (oldj / name).read_text()
        content = content.replace('targeted_gpu_job_20260914/', 'targeted_gpu_job_20260914_v3/')
        content = content.replace('gpu_pair_2026-09-14_v2', 'gpu_pair_2026-09-14_v3')
        assert content == (J / name).read_text(), name
    runner = (J / 'run_gpu.sbatch').read_text()
    expected = (oldj / 'run_gpu.sbatch').read_text()
    expected = expected.replace('#SBATCH --gpus=nvidia_a100:1\n#SBATCH --gpus-per-node=nvidia_a100:1\n',
                                '#SBATCH --gres=gpu:nvidia_a100:1\n')
    expected = expected.replace('gpu_pair_2026-09-14_v2', 'gpu_pair_2026-09-14_v3')
    expected = expected.replace('targeted_gpu_job_20260914"', 'targeted_gpu_job_20260914_v3"')
    assert runner == expected
    assert json_file(C / 'CONTROL_RELEASE.json')['package_sha256'] == sha((J / 'SOURCE_MANIFEST.json').read_bytes()) == ops.PACKAGE_SHA
    tests = []
    for dirname, status in (
        ('gpu-job-v3-local-20260914T005558Z-jfz34p6x', 'LOCAL_GPU_JOB_CANDIDATE_VERIFIED'),
        ('gpu-control-v3-local-20260914T005558Z-v8_dzbzo', 'LOCAL_GPU_CONTROL_VERIFIED'),
    ):
        folder = E / dirname
        value = json_file(folder / 'receipt.json')
        assert value['status'] == status and value['error'] is None
        assert value['process']['returncode'] == 0 and value['process']['error'] is None
        assert value['process']['pid'] == value['child']['pid']
        assert value['jobs_submitted'] == 0 and not value['remote_executed']
        assert not value['child']['production_model_loaded']
        for name, record in value['artifacts'].items():
            checked(folder / name, record)
        assert json_file(folder / 'child-result.json') == value['child']
        if 'manifest_sha256' in value:
            assert value['manifest_sha256'] == ops.PACKAGE_SHA and value['sources_unchanged']
            assert value['child']['groups'] == [
                {'group': 'new', 'passed': True, 'skips': 0, 'tests': 45},
                {'group': 'regression', 'passed': True, 'skips': 0, 'tests': 38}]
        else:
            assert value['control_release_sha256'] == releases[-1]['sha256']
            assert value['child']['tests'] == 47 and value['child']['skips'] == 0
        tests.append({'path': str((folder / 'receipt.json').relative_to(W)),
                      'sha256': sha((folder / 'receipt.json').read_bytes()), 'child': value['child']})
    # Re-evaluate the existing native CPU evidence, not a new CPU/GPU execution.
    p = E / '2026-09-14-gpu-v2-native-cpu-review.py'
    spec = importlib.util.spec_from_file_location('native_startup_review', p)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    native = module.main()
    assert native == json_file(E / '2026-09-14-gpu-v2-native-cpu-review.json')
    # Existing real typed record remains acceptable without inventing allocation.
    path = E / 'gpu-control-20260913-v1/update-20260913T093954Z-5gjz49so/receipt.json'
    previous = json_file(path)
    checked(path.parent / 'output.log', previous['output'])
    after = previous['remote']['result']['after']
    text = after['job']['stdout'].replace('gpu_pair_2026-09-13_v1', 'gpu_pair_2026-09-14_v3')
    text = text.replace('targeted_gpu_job_20260913/', 'targeted_gpu_job_20260914_v3/')
    tres = ops.held_request_matches(text, '705468', 'b2a68a80c4fb4717901cc76230af53e8', ops.REMOTE)
    ops.held_accounting_matches(after['accounting']['stdout'], '705468', tres)
    return {'schema_version': 1, 'status': 'GPU_V3_LOCAL_REVIEW_PASS',
            'releases': releases, 'tests': tests,
            'byte_identical_own_files': sorted(same), 'changed_own_files': sorted(changed),
            'unchanged_shared_sources': len(shared), 'coordinator_and_contract_changes': 'paths only',
            'runner_changes': 'paths and one per-node typed A100 directive only',
            'native_cpu_scope': 'v2 source evidence reused; identical v3 GPU child/startup; not an exact v3 native execution',
            'native_cpu_receipt_sha256': native['receipt_sha256'],
            'historical_typed_scheduler_record_accepted': True,
            'runner_sha256': sha((J / 'run_gpu.sbatch').read_bytes()),
            'resources_authorized': False, 'jobs_submitted': 0,
            'ready_for_gpu': False, 'scientific_comparison_complete': False}

if __name__ == '__main__':
    print(json.dumps(main(), indent=2, sort_keys=True))

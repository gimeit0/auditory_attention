"""Sequential fresh reference/observed processes plus an independent reader.

Synthetic CPU only; outputs go to a new owned leaf. Never reuse a failed pair.
Each child has private caches and at most 60 seconds. No shell, reset or GPU job.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trace_archive as archive  # noqa: E402
from cold_worker import plan  # noqa: E402
import torch  # noqa: E402


def run_pair(root, case='dependent'):
    root = Path(root)
    root.mkdir(mode=0o700, exist_ok=False)
    here = Path(__file__).resolve().parent
    before = {p.name: archive.digest(p.read_bytes()) for p in sorted(here.glob('*.py'))}
    binding = {'scope': 'SYNTHETIC_COLD_PAIR', 'pair_id': uuid.uuid4().hex, 'case': case,
               'python': sys.version.split()[0], 'torch': str(torch.__version__), 'backend': 'eager',
               'source_sha256': before, 'dependencies': archive.PINS}
    receipts = {}
    for role in ('reference', 'observed'):
        scratch = root / (role + '-scratch')
        scratch.mkdir(mode=0o700)
        env = dict(os.environ)
        for key in ('MPLCONFIGDIR', 'XDG_CACHE_HOME', 'TORCHINDUCTOR_CACHE_DIR', 'TRITON_CACHE_DIR',
                    'CUDA_CACHE_PATH', 'NUMBA_CACHE_DIR', 'TMPDIR'):
            cache = scratch / key.lower()
            cache.mkdir(mode=0o700)
            env[key] = str(cache)
        env.update(CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
                   OPENBLAS_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
        command = [sys.executable, '-I', '-B', str(here / 'cold_worker.py'), '--role', role,
                   '--case', case, '--root', str(root / role), '--binding', json.dumps(binding)]
        with (root / (role + '.log')).open('xb') as output:
            process = subprocess.Popen(command, env=env, stdout=output, stderr=subprocess.STDOUT)
            try:
                code = process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise RuntimeError('cold child exceeded 60 seconds; no retry') from None
        raw = (root / (role + '.log')).read_bytes()
        values = [json.loads(line) for line in raw.decode().splitlines()
                  if line.startswith('{"child_kind":')]
        archive.require(code == 0 and len(values) == 1, 'cold child failed: ' + role)
        child = values[0]
        archive.require(child['pid'] == child['writer_pid'] == process.pid and child['role'] == role
                        and child['worker_sha256'] == before['cold_worker.py']
                        and child['cuda_initialized'] is False and child['batches'] == 34
                        and child['checkpoint_loaded'] is False and child['jobs_submitted'] == 0,
                        'supervised child receipt differs')
        receipts[role] = {**child, 'log_sha256': hashlib.sha256(raw).hexdigest()}
        print(json.dumps({'supervised_child': role, 'pid': process.pid, 'returncode': code}), flush=True)
    archive.require(receipts['reference']['pid'] != receipts['observed']['pid'], 'child pid reused')
    readers = {}
    try:
        for role in ('reference', 'observed'):
            readers[role] = archive.ArchiveReader(root / role,
                expected_sha256=receipts[role]['manifest_sha256'], expected_binding=binding,
                expected_plan=plan(), expected_role=role)
            archive.require(readers[role].writer_pid == receipts[role]['pid']
                            and readers[role].invocation_id == receipts[role]['invocation_id'],
                            'manifest/supervised child differs')
        if case == 'interference':
            try:
                archive.compare_archives(readers['reference'], readers['observed'])
            except archive.base.TraceError as error:
                archive.require('OBSERVATION_INTERFERENCE' in str(error), 'wrong rejection reason')
                result = {'status': 'EXPECTED_OBSERVATION_INTERFERENCE_REJECTED', 'targets': None}
            else:
                raise RuntimeError('injected observation interference was accepted')
        else:
            result = archive.compare_archives(readers['reference'], readers['observed'])
            for target in result['targets']:
                expected = None if case == 'invariant' else {'index': 2,
                    'module': 'model._orig_mod.gain', 'branch': 'mixture'}
                archive.require(target['first_observed_boundary'] == expected, 'wrong synthetic boundary')
        archive.require(before == {p.name: archive.digest(p.read_bytes()) for p in sorted(here.glob('*.py'))},
                        'source changed during pair')
    finally:
        for reader in readers.values():
            reader.close()
    result = {'case_status': 'SUPERVISED_SYNTHETIC_COLD_PAIR_PASS', 'case': case,
              'binding': binding, 'children': receipts, 'comparison': result,
              'separate_processes_supervised': True, 'compiler_cache_directories_separate': True,
              'dynamo_reset_used': False, 'production_model_loaded': False,
              'production_execution_authority_verified': False, 'jobs_submitted': 0, 'ready_for_gpu': False}
    with (root / 'PAIR_RECEIPT.json').open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps(result), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--case', choices=('dependent', 'invariant', 'interference'), default='dependent')
    args = parser.parse_args()
    run_pair(args.root, args.case)

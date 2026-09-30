"""Cold synthetic stages in a bounded CPU allocation; no production inference."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c

STAGES = ('A2', 'B2', 'mmap')
CACHES = ('TMPDIR', 'TMP', 'TEMP', 'XDG_CACHE_HOME', 'TORCH_HOME', 'MPLCONFIGDIR',
          'NUMBA_CACHE_DIR', 'TORCHINDUCTOR_CACHE_DIR', 'TRITON_CACHE_DIR', 'CUDA_CACHE_PATH')


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def native_environment():
    c.require(sys.platform == 'linux' and sys.version.split()[0] == '3.11.5', 'native Python differs')
    c.require(socket.gethostname() != 'hakusan1' and not socket.gethostname().startswith('hakusan'), 'compute node required')
    c.require(os.environ.get('SLURM_CPUS_PER_TASK') == '1'
              and os.environ.get('SLURM_CPUS_ON_NODE') == '1'
              and os.environ.get('SLURM_MEM_PER_NODE') == '6000', 'allocation environment differs')
    c.require(len(os.sched_getaffinity(0)) == 1, 'one bound CPU required')
    c.require(all(not os.environ.get(k) for k in ('SLURM_JOB_GPUS', 'SLURM_STEP_GPUS', 'SLURM_GPUS')), 'unexpected GPU allocation')


def child(root, digest, nonce, mode, stage, request_sha):
    c.require(mode in ('LOCAL_HARNESS', 'NATIVE_BATCH') and stage in STAGES, 'child mode/stage differs')
    c.require(sys.flags.isolated and sys.dont_write_bytecode and os.environ.get('CUDA_VISIBLE_DEVICES') == '', 'isolated CPU child required')
    package = root / 'package'
    manifest = c.release(c.read(root / 'RELEASE.json'), digest)
    c.source_check(package, manifest)
    if mode == 'NATIVE_BATCH':
        native_environment()
    job = os.environ['SLURM_JOB_ID'] if mode == 'NATIVE_BATCH' else 'local'
    part = root / 'attempts' / ('slurm-' + job) / stage
    print('CHILD_PHASE=before_torch_import', flush=True)
    import faulthandler
    faulthandler.dump_traceback_later(120, repeat=False)
    import torch
    print('CHILD_PHASE=after_torch_import', flush=True)
    if mode == 'NATIVE_BATCH':
        c.require(str(torch.__version__) == '2.1.1+cu118', 'native Torch differs')
    task = load(package / c.STAGED / 'lifecycle.py', 'unchanged_staged_fixture')
    request = task.read_bound(part / 'request.json', request_sha)
    c.require(request['session_id'] == nonce and request['stage'] == stage, 'child request differs')
    print('CHILD_PHASE=before_unchanged_fixture', flush=True)
    task.child(part, request_sha)
    faulthandler.cancel_dump_traceback_later()
    print('CHILD_PHASE=after_unchanged_fixture', flush=True)
    c.require(not torch.cuda.is_initialized(), 'CUDA initialized')
    c.source_check(package, manifest)
    c.write(part / 'CHILD.json', c.wire(dict(mode=mode, job_id=job, nonce=nonce, pid=os.getpid(),
        request_sha256=request_sha, result_sha256=c.sha(c.read(part / 'result.json')),
        release_sha256=digest, source_postcheck=True, cuda_initialized=False, production_model_loaded=False,
        affinity=sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
        python=sys.version.split()[0], torch=str(torch.__version__))))


def review(root, digest, nonce, mode, job):
    manifest = c.release(c.read(root / 'RELEASE.json'), digest)
    c.source_check(root / 'package', manifest)
    folder = root / 'attempts' / ('slurm-' + job)
    terminal = json.loads(c.read(folder / 'TERMINAL.json'))
    c.require(terminal['status'] == 'SYNTHETIC_CPU_BATCH_PASS' and terminal['error'] is None
              and terminal['mode'] == mode and terminal['job_id'] == job and terminal['nonce'] == nonce
              and terminal['release_sha256'] == digest and terminal['source_postcheck']
              and terminal['temporary_directory_removed'] and terminal['home_unchanged']
              and terminal['ready_for_gpu'] is False and terminal['production_model_loaded'] is False
              and terminal['original_50_second_gate_passed'] is False
              and terminal['elapsed_seconds'] < c.LIMITS['coordinator_seconds'], 'terminal scope/outcome differs')
    task = load(root / 'package' / c.STAGED / 'lifecycle.py', 'review_staged_fixture')
    values = {}
    expected_names = {s + '/' + n for s in STAGES for n in ('request.json', 'result.json', 'process.json', 'child.log', 'CHILD.json')}
    c.require(set(terminal['artifacts']) == expected_names | {'ENVIRONMENT.json'}, 'artifact inventory differs')
    for name, expected in terminal['artifacts'].items():
        raw = c.read(folder / c.member(name))
        c.require(expected == {'sha256': c.sha(raw), 'size': len(raw)}, 'artifact changed: ' + name)
    env_record = json.loads(c.read(folder / 'ENVIRONMENT.json'))
    if mode == 'NATIVE_BATCH':
        c.job_check(env_record['scheduler']['stdout'], job, nonce, c.REMOTE, held=False)
        c.require(env_record['scheduler']['returncode'] == 0 and len(env_record['affinity']) == 1, 'native scheduler evidence differs')
    for stage in STAGES:
        part = folder / stage
        request = task.decode(c.read(part / 'request.json'))
        c.require(request['source_binding'] == task.sources() and request['session_id'] == nonce
                  and request['scope'] == task.SCOPE and request['stage'] == stage, 'fixture request binding differs')
        task.parent_names(request)
        for item in request['parents']:
            c.require(c.sha(c.read(folder / item['name'])) == item['sha256'], 'parent changed')
        result = task.decode(c.read(part / 'result.json'))
        task.validate_result(result, request, stage)
        p = json.loads(c.read(part / 'process.json'))
        log = c.read(part / 'child.log')
        cr = json.loads(c.read(part / 'CHILD.json'))
        c.require(p['returncode'] == 0 and p['error'] is None and p['elapsed_seconds'] <= 180.5
                  and p['pid'] == result['pid'] == cr['pid'] and result['parents'] == request['parents']
                  and p['request_sha256'] == cr['request_sha256'] == c.sha(c.read(part / 'request.json'))
                  and p['log'] == dict(name='child.log', size=len(log), sha256=c.sha(log)), 'process/result identity differs')
        c.require(cr['mode'] == mode and cr['job_id'] == job and cr['nonce'] == nonce
                  and cr['release_sha256'] == digest and cr['result_sha256'] == c.sha(c.read(part / 'result.json'))
                  and cr['source_postcheck'] and not cr['cuda_initialized'] and not cr['production_model_loaded']
                  and result['environment'] == dict(python=cr['python'], torch=cr['torch'])
                  and result['original_ast_restored_exactly'], 'child scope/source differs')
        if mode == 'NATIVE_BATCH':
            c.require(cr['python'] == '3.11.5' and cr['torch'] == '2.1.1+cu118' and len(cr['affinity']) == 1, 'native child environment differs')
        else:
            c.require(mode == 'LOCAL_HARNESS' and job == 'local', 'review mode differs')
        values[stage] = result
    merged = task.merge_cells(values['A2'], values['B2'], request)
    m = values['mmap']
    c.require(len({v['pid'] for v in values.values()}) == 3 and all(v['environment'] == m['environment'] for v in values.values())
              and m['tests'] == 2 and m['errors'] == m['failures'] == m['skips'] == 0
              and c.sha(c.wire(merged)) == m['consumed_contract_sha256'], 'cold-stage coverage/consumption differs')
    if mode == 'LOCAL_HARNESS':
        c.require(m['consumed_contract_sha256'] == 'cdfe21ec7eb65f72a6fd11f76fc3c975a67c6a7d01f4c121de1f3c98dd271000', 'unchanged local oracle differs')
    return dict(status='SYNTHETIC_CPU_BATCH_VERIFIED', mode=mode, job_id=job, stages=list(STAGES),
                contract_sha256=m['consumed_contract_sha256'], ready_for_gpu=False, production_model_loaded=False)


def run(root, digest, nonce, mode):
    c.require(mode in ('LOCAL_HARNESS', 'NATIVE_BATCH'), 'invalid execution mode')
    c.require(len(nonce) == 32 and all(x in '0123456789abcdef' for x in nonce), 'invalid nonce')
    c.directory(root)
    manifest = c.release(c.read(root / 'RELEASE.json'), digest)
    c.source_check(root / 'package', manifest)
    job = os.environ['SLURM_JOB_ID'] if mode == 'NATIVE_BATCH' else 'local'
    if mode == 'NATIVE_BATCH':
        c.require(root == c.REMOTE and job.isdigit(), 'native root/job differs')
        native_environment()
    folder = root / 'attempts' / ('slurm-' + job)
    folder.mkdir(mode=0o700)
    scheduler = c.command(['/usr/bin/scontrol', '-o', 'show', 'job', job]) if mode == 'NATIVE_BATCH' else None
    c.write(folder / 'ENVIRONMENT.json', c.wire(dict(hostname=socket.gethostname(), scheduler=scheduler,
        affinity=sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None)))
    task = load(root / 'package' / c.STAGED / 'lifecycle.py', 'cpu_coordinator_fixture')
    runner = task.runner_module()
    started, original_home, error, post, scratch = time.monotonic(), os.environ.get('HOME'), None, False, None
    try:
        if mode == 'NATIVE_BATCH':
            c.require(scheduler['returncode'] == 0, 'cannot inspect own allocation')
            c.job_check(scheduler['stdout'], job, nonce, root, held=False)
        with runner.verification_deadline(c.LIMITS['coordinator_seconds']):
            with tempfile.TemporaryDirectory(prefix='staged-cpu-' + job + '-') as temporary:
                scratch = Path(temporary)
                for stage in STAGES:
                    part = folder / stage
                    part.mkdir(mode=0o700)
                    parents = [dict(name=s + '/result.json', sha256=c.sha(c.read(folder / s / 'result.json'))) for s in ('A2', 'B2')] if stage == 'mmap' else []
                    request = dict(stage=stage, session_id=nonce, scope=task.SCOPE, source_binding=task.sources(), parents=parents)
                    request_sha = c.write(part / 'request.json', c.wire(request))
                    env = {k: os.environ[k] for k in ('HOME', 'PATH', 'USER', 'LOGNAME', 'LANG') if k in os.environ}
                    env.update({k: v for k, v in os.environ.items() if k.startswith('SLURM_')})
                    env.update(CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
                               PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', PYTHONHASHSEED='0')
                    for key in CACHES:
                        cache = scratch / (stage + '-' + key.lower())
                        cache.mkdir(mode=0o700)
                        env[key] = str(cache)
                    print('CPU_STAGE_BEGIN=' + stage, flush=True)
                    process = runner.run_process([sys.executable, '-I', '-B', str(Path(__file__).resolve()), 'child', str(root), digest,
                        nonce, mode, stage, request_sha], env, part / 'child.log', seconds=min(180, 560 - (time.monotonic() - started)), max_log_bytes=2 * 1024**2)
                    process['request_sha256'] = request_sha
                    c.write(part / 'process.json', c.wire(process))
                    c.require(process['returncode'] == 0 and process['error'] is None, 'child failed: ' + stage)
                    task.validate_result(task.decode(c.read(part / 'result.json')), request, stage)
                    print('CPU_STAGE_PASS=' + stage, flush=True)
                c.source_check(root / 'package', manifest)
                post = True
    except BaseException as exc:
        error = dict(type=type(exc).__name__, message=str(exc))
    files = {str(p.relative_to(folder)): dict(sha256=c.sha(c.read(p)), size=p.stat().st_size) for p in folder.rglob('*') if p.is_file()}
    terminal = dict(status='SYNTHETIC_CPU_BATCH_PASS' if error is None else 'SYNTHETIC_CPU_BATCH_FAILED', error=error,
        mode=mode, job_id=job, nonce=nonce, release_sha256=digest, artifacts=files, source_postcheck=post,
        temporary_directory_removed=scratch is not None and not scratch.exists(), home_unchanged=os.environ.get('HOME') == original_home,
        elapsed_seconds=time.monotonic() - started, ready_for_gpu=False, production_model_loaded=False, original_50_second_gate_passed=False)
    c.write(folder / 'TERMINAL.json', c.wire(terminal))
    if error is None:
        print(json.dumps(review(root, digest, nonce, mode, job)), flush=True)
        return 0
    print(json.dumps(terminal), flush=True)
    return 2


if __name__ == '__main__':
    os.umask(0o077)
    action, raw_root, digest, nonce, mode, *extra = sys.argv[1:]
    if action == 'child':
        child(Path(raw_root), digest, nonce, mode, *extra)
    else:
        c.require(action == 'run' and not extra, 'invalid action')
        raise SystemExit(run(Path(raw_root), digest, nonce, mode))

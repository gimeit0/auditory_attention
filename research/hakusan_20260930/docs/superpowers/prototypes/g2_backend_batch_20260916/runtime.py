"""One CPU allocation, two cold children; fail fast with durable evidence."""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common as c
import verify

CACHES = ('TMPDIR','TMP','TEMP','XDG_CACHE_HOME','TORCH_HOME','MPLCONFIGDIR','NUMBA_CACHE_DIR',
          'TORCHINDUCTOR_CACHE_DIR','TRITON_CACHE_DIR','CUDA_CACHE_PATH')

def review(root, digest, nonce, job):
    c.source_check(root / 'package', c.release(c.read(root / 'RELEASE.json'), digest))
    folder = root / 'attempts' / ('slurm-' + job)
    terminal = json.loads(c.read(folder / 'TERMINAL.json'))
    c.require(terminal['job_id'] == job and terminal['nonce'] == nonce and terminal['release_sha256'] == digest
              and terminal['home_unchanged'] and terminal['temporary_directory_removed'] and terminal['source_postcheck']
              and terminal['elapsed_seconds'] < 540 and terminal['ready_for_gpu'] is False
              and terminal['production_model_loaded'] is False, 'terminal scope differs')
    actual = {str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file()} - {'TERMINAL.json'}
    c.require(actual == set(terminal['artifacts']), 'terminal inventory differs')
    for name, record in terminal['artifacts'].items():
        raw = c.read(folder / c.member(name))
        c.require(record == dict(sha256=c.sha(raw), size=len(raw)), 'artifact changed: ' + name)
    env = json.loads(c.read(folder / 'ENVIRONMENT.json'))
    c.require(env['scheduler']['returncode'] == 0 and len(env['affinity']) == 1, 'scheduler evidence missing')
    c.job_check(env['scheduler']['stdout'], job, nonce, c.REMOTE, held=False)
    if terminal['status'] != 'NATIVE_CPU_PAIR_PASS':
        c.require(terminal['status'] == 'NATIVE_CPU_PAIR_FAILED' and terminal['error'], 'failure must explain stop')
        return dict(status='CPU_FAILURE_EVIDENCE_VERIFIED', job_id=job, error=terminal['error'],
                    numeric_results_interpretable=False, ready_for_gpu=False)
    c.require(terminal['error'] is None, 'success with error')
    values = {}
    for role in ('reference', 'observed'):
        part = folder / role
        p = json.loads(c.read(part / 'process.json'))
        r = json.loads(c.read(part / 'result.json'))
        log = c.read(part / 'child.log')
        c.require(p['returncode'] == 0 and p['error'] is None and p['elapsed_seconds'] <= 240.5
                  and p['pid'] == r['pid'] and p['log'] == dict(name='child.log', size=len(log), sha256=c.sha(log)), 'process evidence differs')
        values[role] = r
    result = verify.pair(values['reference'],values['observed'],digest,nonce,job)
    c.require(json.loads(c.read(folder / 'PAIR.json')) == result, 'pair result differs')
    return dict(status='NATIVE_CPU_PAIR_VERIFIED', job_id=job, pair=result)

def run(root, digest, nonce):
    started, original_home = time.monotonic(), os.environ.get('HOME')
    c.require(root == c.REMOTE and len(nonce) == 32 and all(x in '0123456789abcdef' for x in nonce), 'job request differs')
    manifest = c.release(c.read(root / 'RELEASE.json'),digest)
    c.source_check(root / 'package',manifest)
    sys.path.insert(0,str(root / 'package'))
    import process_runner as runner
    job = os.environ['SLURM_JOB_ID']
    c.require(job.isdigit(), 'job id differs')
    receipt = json.loads(c.read(root / 'SUBMISSION_RECEIPT.json'))
    c.require(receipt['job_id'] == job and receipt['nonce'] == nonce and receipt['release_sha256'] == digest, 'submission binding differs')
    folder = root / 'attempts' / ('slurm-' + job)
    folder.mkdir(mode=0o700)
    error, scratch, post = None, None, False
    try:
        with runner.verification_deadline(540):
            scheduler = c.command(['/usr/bin/scontrol','-o','show','job',job])
            env_record = dict(hostname=socket.gethostname(),affinity=sorted(os.sched_getaffinity(0)), scheduler=scheduler)
            c.write(folder / 'ENVIRONMENT.json',c.wire(env_record))
            c.require(sys.platform == 'linux' and sys.version.split()[0] == '3.11.5'
                      and not socket.gethostname().startswith('hakusan') and len(env_record['affinity']) == 1
                      and os.environ.get('SLURM_CPUS_PER_TASK') == '1' and os.environ.get('SLURM_MEM_PER_NODE') == '6000'
                      and all(not os.environ.get(k) for k in ('SLURM_JOB_GPUS','SLURM_STEP_GPUS','SLURM_GPUS')), 'native allocation differs')
            c.require(scheduler['returncode'] == 0,'allocation inspection failed')
            c.job_check(scheduler['stdout'],job,nonce,root,held=False)
            values = {}
            with tempfile.TemporaryDirectory(prefix='g2-backend-cpu-' + job + '-') as temporary:
                scratch = Path(temporary)
                for role in ('reference','observed'):
                    part = folder / role
                    part.mkdir(mode=0o700)
                    env = {k:os.environ[k] for k in ('HOME','PATH','USER','LOGNAME','LANG') if k in os.environ}
                    env.update({k:v for k,v in os.environ.items() if k.startswith('SLURM_')})
                    env.update(CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',
                               TORCHINDUCTOR_COMPILE_THREADS='1',PYTHONHASHSEED='0',PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1')
                    for key in CACHES:
                        cache = scratch / (role + '-' + key.lower())
                        cache.mkdir(mode=0o700)
                        env[key] = str(cache)
                    print('CPU_STAGE_BEGIN=' + role,flush=True)
                    process = runner.run_process([sys.executable,'-I','-B',str(HERE/'child.py'),role,str(root),digest,nonce,job,str(part)],
                        env,part/'child.log',seconds=min(240,520-(time.monotonic()-started)),max_log_bytes=2*1024**2)
                    c.write(part / 'process.json',c.wire(process))
                    c.require(process['returncode'] == 0 and process['error'] is None,'child failed: ' + role)
                    value = json.loads(c.read(part/'result.json'))
                    verify.child(value,role,digest,nonce,job)
                    values[role] = value
                    print('CPU_STAGE_PASS=' + role,flush=True)
                result = verify.pair(values['reference'],values['observed'],digest,nonce,job)
                c.write(folder/'PAIR.json',c.wire(result))
    except BaseException as exc:
        error = dict(type=type(exc).__name__,message=str(exc))
    try:
        c.source_check(root/'package',manifest)
        post = True
    except BaseException as exc:
        error = dict(type=type(exc).__name__,message=str(exc),prior=error)
    files = {str(p.relative_to(folder)):dict(sha256=c.sha(c.read(p)),size=p.stat().st_size) for p in folder.rglob('*') if p.is_file()}
    terminal = dict(status='NATIVE_CPU_PAIR_PASS' if error is None else 'NATIVE_CPU_PAIR_FAILED',error=error,
        job_id=job,nonce=nonce,release_sha256=digest,artifacts=files,source_postcheck=post,
        temporary_directory_removed=scratch is not None and not scratch.exists(),home_unchanged=os.environ.get('HOME')==original_home,
        elapsed_seconds=time.monotonic()-started,ready_for_gpu=False,production_model_loaded=False)
    c.write(folder/'TERMINAL.json',c.wire(terminal))
    print(json.dumps(dict(status=terminal['status'],error=error)),flush=True)
    return 0 if error is None else 2

if __name__ == '__main__':
    os.umask(0o077)
    raise SystemExit(run(Path(sys.argv[1]),sys.argv[2],sys.argv[3]))

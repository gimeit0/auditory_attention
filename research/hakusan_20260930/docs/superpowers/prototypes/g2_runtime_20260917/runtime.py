"""Bounded G2 worker and four-cell orchestration core, not a submitter.

The deployment layer still owns the reviewed release, request/freeze, scheduler
allocation, source_check and supervised launch/verification. No API here grants
that authorization. Old releases and the original production guards are intact.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import sys
import time

HERE=Path(__file__).resolve().parent
ORDER=('R','C','D','E')
PREFERENCE=('E','C','D','R')
CHILD_SECONDS=1800
TOTAL_SECONDS=10000
PINS={
    'g2_lifetime_20260917/production_cell.py':'602d90cc26ee5900ed801e45a15b4f30ebbbe3bd9edf5f9ccb65a93f8982be24',
    'g2_archive_20260917/pass_store.py':'1b21505669bbc29b9072548f0134f582b3a3534cb7109e5a7b41e04e4dbc6a10',
    'targeted_gpu_job_20260915_v5/process_runner.py':'189495e7af4fe5537df560909de456b8ca95acdf0c9f9d6603435e6230b5411a',
}


def require(ok,message):
    if not ok: raise RuntimeError('G2 runtime: '+message)


def load(relative):
    path=HERE.parent/relative
    require(path.is_file() and not any(p.is_symlink() for p in (path,*path.parents)),'source path differs')
    raw=path.read_bytes()
    require(hashlib.sha256(raw).hexdigest()==PINS[relative],'component source changed')
    spec=importlib.util.spec_from_file_location('g2_runtime_'+path.stem,path)
    module=importlib.util.module_from_spec(spec)
    exec(compile(raw,str(path),'exec',dont_inherit=True),vars(module))
    return module


cell_api=load('g2_lifetime_20260917/production_cell.py')
store=load('g2_archive_20260917/pass_store.py')
process_api=load('targeted_gpu_job_20260915_v5/process_runner.py')


def error_record(error):
    return dict(type=type(error).__name__,message=str(error)[:8192])


def worker_environment(binding, source, scratch, job):
    """Only declared scheduler/user variables, real HOME and isolated caches."""
    env={k:source[k] for k in ('HOME','PATH','USER','LOGNAME','LANG','CUDA_VISIBLE_DEVICES') if k in source}
    env.update({k:v for k,v in source.items() if k.startswith('SLURM_')})
    require(source.get('SLURM_JOB_ID')==job and source.get('SLURM_CPUS_PER_TASK')=='8'
            and source.get('CUDA_VISIBLE_DEVICES') not in (None,''),'GPU worker allocation environment missing')
    env.update(OMP_NUM_THREADS='8',MKL_NUM_THREADS='8',OPENBLAS_NUM_THREADS='8',NUMEXPR_NUM_THREADS='8',
               TORCHINDUCTOR_COMPILE_THREADS='1',CUBLAS_WORKSPACE_CONFIG=':4096:8')
    return binding.environment(env,Path(scratch),job,'observed')


def run_worker(bridge,diag,*,job,freeze_sha,production_bytes,parent_path,release_sha,source_check):
    """Real production call path. Must be invoked in a newly supervised worker.

source_check is the reviewed launcher's release/request check, not an approval
boolean from child output. No hermetic/CPU bypass is offered by this API.
"""
    cell_api.scratch_api.cold()
    require(callable(source_check),'launcher release check required')
    source_check()
    require(sys.platform=='linux' and sys.version.split()[0]=='3.11.5'
            and sys.flags.isolated and sys.dont_write_bytecode,'isolated production interpreter required')
    require(type(job) is str and store.re.fullmatch('[1-9][0-9]{0,19}',job)
            and os.environ.get('SLURM_JOB_ID')==job,'actual job differs')
    require(type(release_sha) is str and store.SHA.fullmatch(release_sha),'release digest required')
    output=diag.DIAGNOSTIC_ROOT/'attempts'/('slurm-'+job)
    # Exclusive attempt: no edits to an old/partial attempt and no second run.
    require(not any(p.is_symlink() for p in (output.parent,*output.parent.parents)), 'attempt parent aliases')
    info=output.parent.stat()
    require(info.st_uid==os.getuid() and info.st_mode & 0o777 == 0o700,'private attempt parent required')
    output.mkdir(mode=0o700)
    started=time.monotonic()
    phases={}
    result,error,post,receipt=None,None,False,None
    process_api.write_once(output/'STARTED.json',dict(job_id=job,profile=diag._G2_PROFILE,pid=os.getpid(),
        input_freeze_sha256=freeze_sha,release_sha256=release_sha,automatic_retry=False))
    try:
        cell=cell_api.ProductionCell(bridge,diag,job=job,freeze_sha=freeze_sha,
             production_bytes=production_bytes,parent_path=parent_path)
        phases['constructed_seconds']=time.monotonic()-started

        def consume(value,metadata):
            nonlocal receipt
            phases['passes_ready_seconds']=time.monotonic()-started
            require(receipt is None and value['trust_domain']=='production','exactly one production archive required')
            binding=store.bind(metadata,cell.inputs.freeze['trials'],release_sha,'production')
            sink=store.Consumer(output/'arrays',bridge,diag,binding=binding,trials=cell.inputs.freeze['trials'])
            receipt=sink(value,metadata)
            process_api.write_once(output/'ARCHIVE_RECEIPT.json',receipt)
            phases['archive_stored_seconds']=time.monotonic()-started
            return receipt

        result=cell.run(consume)  # all scopes must close before a success terminal
        phases['lifetime_closed_seconds']=time.monotonic()-started
        require(result['status']=='G2_PRODUCTION_CELL_STORED_CANDIDATE' and receipt is not None
                and result['archive_receipt']==receipt,'lifetime result/receipt differs')
    except BaseException as exc:
        error=error_record(exc)
    try:
        source_check()
        post=True
    except BaseException as exc:
        error=dict(**error_record(exc),prior=error)
    elapsed=time.monotonic()-started
    if elapsed>=CHILD_SECONDS:
        error=dict(type='TimeoutError',message='worker exceeded fixed cell budget',prior=error)
    # Peaks are whole worker measurements, not per-layer cost claims.
    peak_gpu=None
    torch=sys.modules.get('torch')
    if torch is not None and torch.cuda.is_initialized():
        try:
            peak_gpu=dict(allocated_bytes=torch.cuda.max_memory_allocated(),
                          reserved_bytes=torch.cuda.max_memory_reserved())
        except BaseException as exc:
            error=dict(**error_record(exc),prior=error)
    inventory={}
    for name in ('STARTED.json','ARCHIVE_RECEIPT.json','arrays/manifest.json'):
        path=output/name
        if path.exists(): inventory[name]=process_api.file_record(path)
    terminal=dict(status='G2_WORKER_STORED' if error is None else 'EXECUTION_INVALID',
        job_id=job,profile=diag._G2_PROFILE,pid=os.getpid(),release_sha256=release_sha,
        input_freeze_sha256=freeze_sha,error=error,result=result if error is None else None,
        source_postcheck=post,elapsed_seconds=elapsed,phases=phases,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,gpu_peak=peak_gpu,
        inventory=inventory,independent_results_verified=False,ready_for_gpu=False,automatic_retry=False)
    process_api.write_once(output/'TERMINAL.json',terminal)
    return terminal


def validate_observation(value,profile,*,job,release_sha,freeze_sha):
    """Only an independent worker-evidence gate, not archive-content-only, may enter."""
    require(type(value) is dict and value.get('status')=='G2_WORKER_EVIDENCE_VERIFIED'
            and value.get('execution_valid') is True,'independent execution evidence missing')
    require((value.get('profile'),value.get('job_id'),value.get('release_sha256'),value.get('input_freeze_sha256'))
            ==(profile,job,release_sha,freeze_sha),'matrix worker identity differs')
    require(type(value.get('pid')) is int and value['pid']>0
            and type(value.get('trial_identity_sha256')) is str and store.SHA.fullmatch(value['trial_identity_sha256']),
            'worker PID/full-trial digest missing')
    numeric=value.get('numeric',{})
    require(numeric.get('status') in ('NUMERIC_ACCEPT','NUMERIC_DIFF') and numeric.get('atol')==1e-6
            and numeric.get('scientific_acceptance') is False,'numeric evidence differs')
    require(value.get('production_interference_validated') is False and value.get('ready_for_full_evaluation') is False,
            'matrix prerequisite overclaim')


def run_matrix(*,job,release_sha,freezes,launch,verify,persist):
    """Fixed R,C,D,E, no retry. Launch/verify must enforce the supplied deadlines.

The source-pinned deployment caller owns real process launch, receipt capture,
independent verification and immutable persistence. Synthetic callback tests do
not claim any production execution or scheduler approval.
"""
    require(type(freezes) is dict and set(freezes)==set(ORDER)
            and all(type(x) is str and store.SHA.fullmatch(x) for x in freezes.values()), 'four freezes required')
    require(type(release_sha) is str and store.SHA.fullmatch(release_sha)
            and type(job) is str and store.re.fullmatch('[1-9][0-9]{0,19}',job),'matrix binding differs')
    require(all(callable(f) for f in (launch,verify,persist)),'reviewed orchestration callbacks required')
    started=time.monotonic()
    cells={p:dict(status='NOT_RUN') for p in ORDER}
    verified={}
    error=None
    for profile in ORDER:
        try:
            remaining=TOTAL_SECONDS-(time.monotonic()-started)
            require(remaining>0,'matrix total deadline reached')
            process=launch(profile,min(CHILD_SECONDS,remaining))
            require(type(process) is dict and process.get('returncode')==0 and process.get('error') is None
                    and 0<=process.get('elapsed_seconds',float('inf'))<CHILD_SECONDS,
                    'worker failed or exceeded cell deadline')
            remaining=TOTAL_SECONDS-(time.monotonic()-started)
            require(remaining>0,'no verification budget remains')
            observation=verify(profile,process,remaining)
            validate_observation(observation,profile,job=job,release_sha=release_sha,freeze_sha=freezes[profile])
            require(observation['pid']==process.get('pid'),'supervised worker PID differs')
            require(all(v['pid']!=observation['pid'] for v in verified.values()),'cold PID reused')
            require(all(v['trial_identity_sha256']==observation['trial_identity_sha256'] for v in verified.values()),
                    'matrix full trial identities differ')
            require(time.monotonic()-started<TOTAL_SECONDS,'matrix verification deadline exceeded')
            persist(profile,observation)
            verified[profile]=observation
            cells[profile]=dict(status=observation['numeric']['status'],evidence=observation)
        except BaseException as exc:
            error=dict(profile=profile,**error_record(exc))
            cells[profile]=dict(status='EXECUTION_INVALID',error=error)
            break
    candidate=next((p for p in PREFERENCE if p in verified and
                    verified[p]['numeric']['status']=='NUMERIC_ACCEPT'),None) if error is None else None
    summary=dict(status='EXECUTION_INVALID' if error else 'G2_MATRIX_EVIDENCE_COLLECTED',
        job_id=job,release_sha256=release_sha,input_freezes=freezes,cells=cells,error=error,
        execution_valid=error is None and len(verified)==4,candidate=candidate,
        decision='STOP_EXECUTION_INVALID' if error else 'CANDIDATE_REQUIRES_CONFIRMATION' if candidate else 'NO_NUMERIC_CANDIDATE',
        preference=list(PREFERENCE),elapsed_seconds=time.monotonic()-started,
        old_B2_relation_reviewed=False,cold_repeats_verified=False,
        production_interference_validated=False,ready_for_full_evaluation=False,
        automatic_retry=False,jobs_submitted=0)
    persist('MATRIX',summary)
    return summary

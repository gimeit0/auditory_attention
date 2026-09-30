"""Production session seam and hashed archive verifier; bootstrap still required."""
import json
import os
from pathlib import Path
import numpy as np
from e1_artifacts import identity,write_json
from e0_layout_reference import canonical,require
from e1_execution import inventory,execute_loaded,verify_arrays
from e1_audited_session import audited_e1_session
from loaded_model_adapter import accept_loaded_formal40
import hashlib
import math
import datetime
import platform
import torch
from architecture_adapter import NAMES
from e1_execution import PROVENANCE_FIELDS_REQUIRED,ENVIRONMENT_KEYS,PASS_RESOURCE_KEYS

def environment_record():
    """P1/P2 provenance values (doc 27 §7); gates elsewhere only test them."""
    # TorchVersion is a str subclass. Normalize at the producer boundary,
    # before the live-object validator, not only as a side effect of JSON IO.
    # Do not coerce None, numbers, or arbitrary objects into plausible versions.
    version = torch.__version__
    require(isinstance(version, str), 'PROVENANCE_TORCH_VERSION')
    cuda=torch.cuda.is_available()
    return dict(python=platform.python_version(),torch=str(version),cuda=torch.version.cuda,
                cudnn=torch.backends.cudnn.version() if cuda else None,
                device_name=torch.cuda.get_device_name(0) if cuda else None,hostname=platform.node(),
                slurm_job_id=os.environ.get('SLURM_JOB_ID'),slurm_cpus_per_task=os.environ.get('SLURM_CPUS_PER_TASK'))

EXPECTED_RUNTIME=dict(deterministic_algorithms=True,cudnn_deterministic=True,
    cudnn_benchmark=False,matmul_precision='highest',matmul_tf32=False,cudnn_tf32=False)

def parse_utc(value):
    require(type(value) is str,'PROVENANCE_TIMESTAMPS')
    try:
        stamp=datetime.datetime.fromisoformat(value)
        require(stamp.utcoffset()==datetime.timedelta(0),'PROVENANCE_TIMESTAMPS')
    except (ValueError,TypeError):
        raise ValueError('PROVENANCE_TIMESTAMPS') from None
    return stamp

def verify_environment(metadata, *, production=True):
    """Same strict environment gate for pre-inference and final archive checks."""
    env=metadata.get('environment')
    require(type(env) is dict and set(env)==set(ENVIRONMENT_KEYS) and
            all(v is None or type(v) in (str,int) for v in env.values()) and
            type(env['python']) is str and type(env['torch']) is str and type(env['hostname']) is str,'PROVENANCE_ENVIRONMENT')
    if production:
        require(all(type(env[k]) is str and bool(env[k].strip()) for k in
                    ('python','torch','cuda','device_name','hostname','slurm_job_id','slurm_cpus_per_task')) and
                type(env['cudnn']) is int and env['cudnn']>0 and
                'A100' in env['device_name'] and env['slurm_job_id'].isdigit() and
                env['slurm_job_id']==metadata.get('job_id') and env['slurm_cpus_per_task']=='8',
                'PROVENANCE_PRODUCTION_ENVIRONMENT')

def verify_runtime(runtime):
    require(type(runtime) is dict and set(runtime)==set(EXPECTED_RUNTIME) and
            all(type(runtime[k]) is type(v) and runtime[k]==v for k,v in EXPECTED_RUNTIME.items()),
            'PROVENANCE_RUNTIME')

def verify_provenance(metadata,summary,wanted_passes,*,production=True):
    # Production callers never select the relaxed CPU fixture mode.
    verify_environment(metadata, production=production)
    require(all(k in summary for k in PROVENANCE_FIELDS_REQUIRED if k!='environment'),'PROVENANCE_FIELDS')
    start=parse_utc(summary['process_started_utc']); end=parse_utc(summary['process_finished_utc'])
    require(start<=end,'PROVENANCE_TIME_ORDER')
    if production:
        verify_runtime(summary['runtime_values'])
    rows=summary['pass_resources']
    require(type(rows) is list and len(rows)==len(wanted_passes) and
            {(r.get('domain'),r.get('pass_name')) for r in rows}==wanted_passes,'PASS_RESOURCES')
    for r in rows:
        require(set(r)==set(PASS_RESOURCE_KEYS),'PASS_RESOURCE_KEYS')
        require(start<=parse_utc(r['started_utc'])<=parse_utc(r['finished_utc'])<=end,'PASS_RESOURCE_TIME')
        require(type(r['elapsed_seconds']) in (int,float) and math.isfinite(r['elapsed_seconds']) and r['elapsed_seconds']>=0,'PASS_RESOURCE_ELAPSED')
        for k in ('cuda_max_memory_allocated_bytes','cuda_max_memory_reserved_bytes'):
            require(r[k] is None or (type(r[k]) is int and r[k]>=0),'PASS_RESOURCE_MEMORY')
            if production:
                require(type(r[k]) is int and r[k]>0,'PASS_RESOURCE_PRODUCTION_MEMORY')
        if production:
            require(r['cuda_max_memory_reserved_bytes']>=r['cuda_max_memory_allocated_bytes'],
                    'PASS_RESOURCE_MEMORY_ORDER')
        require(type(r['host_max_rss_ru_maxrss']) is int and r['host_max_rss_ru_maxrss']>=0 and
                r['ru_maxrss_unit'] in ('KiB','bytes'),'PASS_RESOURCE_RSS')

def verify_g5_report(report,pass_name):
    require(report.get('status')=='G5_FIXED_FEATURE_PASS' and
            report.get('pass_name')==pass_name and
            report.get('reference')=='numpy_float64_independent' and
            report.get('atol')==report.get('rtol')==2e-6,'G5_REPORT')
    rows=report.get('checks',[])
    wanted={('model_dict.'+n,m,b) for n in NAMES for m in ('ones','signed') for b in (False,True)}
    require(len(rows)==len(wanted),'G5_CHECK_COUNT')
    seen=set()
    for r in rows:
        require(type(r.get('masked')) is bool,'G5_MASK_TYPE')
        key=(r.get('path'),r.get('mixture'),r['masked'])
        require(key in wanted and key not in seen,'G5_CHECK_IDENTITY')
        seen.add(key)
        for field in ('max_abs','mean_max_abs'):
            value=r.get(field)
            require(type(value) in (float,int) and math.isfinite(value) and value>=0,'G5_ERROR_VALUE')
    # Relative tolerance requires the reference tensors; aggregate errors alone
    # cannot independently re-prove the formula result.

def worker(directory,c,process,*,seconds=9000,release_sha256=None):
    directory=Path(directory)
    require(process in ('A','B'),'PROCESS')
    rows=[]
    def sink(key,p):
        name=f'{len(rows):03d}.npz'
        with (directory/name).open('xb') as f:
            np.savez(f,trial_ids=np.array(p['trial_ids'],dtype=np.int64),logits=p['logits'],nll=p['nll'])
        rows.append(dict(key=list(key),file=name,**identity(directory/name)))
    with audited_e1_session(c) as ctx:
        accept_loaded_formal40(ctx['core'],ctx['outer'],ctx['load_report'],'formal40',ctx['checkpoint_sha'],ctx['architecture_type'],ctx['gain_type'])
        summary=execute_loaded(c,process,ctx['core'],ctx['base'],ctx['outer'],ctx['architecture_type'],
            ctx['gain_type'],ctx['batch_provider'],ctx['device'],sink,seconds=seconds)
        report=ctx['load_report']
    # Only publish success after the session's source/input postchecks.
    write_json(directory/'STAGES.json',summary)
    write_json(directory/'WORKER.json',dict(process=process,pid=os.getpid(),job_id=os.environ['SLURM_JOB_ID'],
        contract_sha256=hashlib.sha256(canonical(c)).hexdigest(),checkpoint_sha256=c['checkpoint_sha256'],
        postchecks_completed=True,load_report=report,outputs=rows,stages=identity(directory/'STAGES.json'),
        release_sha256=release_sha256,launch=identity(directory/'LAUNCH.json'),
        environment=environment_record()))

def verify_archive(root,c,workers,job_id):
    root=Path(root); require([w['label'] for w in workers]==['A','B'],'WORKER_LABELS')
    require(workers[0]['pid']!=workers[1]['pid'] and all(w['returncode']==0 for w in workers),'WORKER_PROCESSES')
    records={}; expected=inventory(c)
    for w in workers:
        directory=root/w['label']
        require(directory.is_dir() and not directory.is_symlink(),'ARCHIVE_DIRECTORY')
        require(all(p.is_file() and not p.is_symlink() for p in directory.iterdir()),'ARCHIVE_FILE_TYPE')
        require(sum(p.stat().st_size for p in directory.iterdir())<512*1024**2,'ARCHIVE_SIZE')
        m=json.loads((directory/'WORKER.json').read_text())
        require(m['process']==w['label'] and m['pid']==w['pid'] and m['job_id']==job_id,'WORKER_BINDING')
        require(m['contract_sha256']==hashlib.sha256(canonical(c)).hexdigest() and
                m['checkpoint_sha256']==c['checkpoint_sha256'] and m['postchecks_completed'] is True,'PROVENANCE')
        load=m['load_report']
        require(load['loaded_trainable_numel_ratio']==1 and load['trainable_numel']>0 and
                load['loaded_trainable_numel']==load['trainable_numel'],'LOAD_COVERAGE')
        require(identity(directory/'STAGES.json')==m['stages'],'STAGES_SHA')
        summary=json.loads((directory/'STAGES.json').read_text())
        wanted={k for k in expected if k[0]==w['label']}
        require(len(m['outputs'])==len(wanted),'OUTPUT_COUNT')
        names={'WORKER.json','STAGES.json','stdout.log','stderr.log','LAUNCH.json'}
        for i,r in enumerate(m['outputs']):
            key=tuple(r['key']); name=f'{i:03d}.npz'
            require(key in wanted and key not in records and r['file']==name,'OUTPUT_KEY')
            names.add(name)
            require(identity(directory/name)=={k:r[k] for k in ('size','sha256')},'OUTPUT_SHA')
            with np.load(directory/name,allow_pickle=False) as z:
                require(set(z.files)=={'trial_ids','logits','nll'} and z['trial_ids'].dtype==np.int64,'ARRAY_KEYS_IDS')
                records[key]=dict(trial_ids=z['trial_ids'].tolist(),logits=z['logits'],nll=z['nll'])
        require({p.name for p in directory.iterdir()}==names,'ARCHIVE_INVENTORY')
        require(summary['predictions']==sum(len(expected[k]) for k in wanted),'STAGE_COUNT')
        wanted_passes={(k[1],k[2]) for k in wanted}
        formulas=summary['gain_formula_reports']
        require(len(formulas)==len(wanted_passes) and {(g['domain'],g['pass_name']) for g in formulas}==wanted_passes,'G5_PASSES')
        for g in formulas:
            verify_g5_report(g['report'],g['pass_name'])
        verify_provenance(m,summary,wanted_passes)
    result=verify_arrays(c,records)
    return dict(verified=True,status='E1_ARCHIVE_VERIFIED_NOT_SCIENCE_QUALIFIED',job_id=job_id,
                contract_sha256=hashlib.sha256(canonical(c)).hexdigest(),array_verification=result)

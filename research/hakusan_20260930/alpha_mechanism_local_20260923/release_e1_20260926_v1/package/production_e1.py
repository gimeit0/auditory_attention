"""E1 orchestration invoked through the verified bootstrap; no scheduler calls."""
import json
import os
from pathlib import Path
import signal
import sys
import math
from e1_entry import canonical,identity,require,verify_package
from e0_archive_harness import write_json
from e1_worker_archive import worker as run_worker,verify_archive
from e1_supervisor import run_e1

def worker(package,directory,c,label,release,digest):
    try:
        run_worker(directory,c,label,seconds=release['budget']['worker_deadline_seconds'],
                   release_sha256=digest)
        verify_package(package,digest)
    except BaseException as e:
        write_json(directory/'WORKER_FAILED.json',dict(error_type=type(e).__name__,error=str(e)))
        raise

def verify_bound_archive(root,c,records,package,release,digest,job):
    require(not (root/'FAILED.json').exists(),'FAILED_ATTEMPT')
    require([r['label'] for r in records]==['A','B'],'PROCESS_ORDER')
    for r in records:
        d=root/r['label']
        launch=json.loads((d/'LAUNCH.json').read_bytes())
        require(launch=={k:r[k] for k in ('label','pid','argv')},'LAUNCH_BINDING')
        # Archive may be downloaded: compare against frozen remote deployment, not local copy.
        from e1_entry import REMOTE_ROOT
        expected=[ '/home/s2510040/miniconda3/envs/attn/bin/python','-I','-B','-u',
                   str(REMOTE_ROOT/'package/e1_entry.py'),'worker',digest,r['label']]
        require(r['argv']==expected,'WORKER_ARGV')
        m=json.loads((d/'WORKER.json').read_bytes())
        require(m.get('release_sha256')==digest and m.get('launch')==identity(d/'LAUNCH.json'),'WORKER_RELEASE')
        require(m['load_report'].get('native_preprocessing')=='selftrain_singleton_per_example_leveling','PREPROCESSING_REPORT')
    result=verify_archive(root,c,records,job)
    verify_package(package,digest)
    return dict(result,release_sha256=digest,evaluation_role='REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST')

def verifier(package,attempt,c,release,digest,job):
    request=json.loads((attempt/'VERIFY_REQUEST.json').read_bytes())
    require(request['release_sha256']==digest and request['job_id']==job,'VERIFY_REQUEST')
    result=verify_bound_archive(attempt,c,request['records'],package,release,digest,job)
    write_json(attempt/'VERIFY/VERIFIED.json',result)
    return result

def coordinator(package,attempt,c,release,digest,job):
    def argv(mode,*args):
        return [sys.executable,'-I','-B','-u',str(package/'e1_entry.py'),mode,digest,*args]
    def verifier_command(root,d,records):
        write_json(root/'VERIFY_REQUEST.json',dict(records=records,release_sha256=digest,job_id=job))
        return argv('verify')
    def terminate(signum,frame): raise RuntimeError('COORDINATOR_SIGNAL_'+str(signum))
    previous=signal.signal(signal.SIGTERM,terminate)
    try:
        result=run_e1(attempt,lambda label,d:argv('worker',label),verifier_command,
                      seconds=release['budget']['coordinator_deadline_seconds'])
        verify_package(package,digest)
        write_json(attempt/'E1_COMPLETE.json',dict(status='E1_EXECUTION_VERIFIED_ANALYSIS_PENDING',
            job_id=job,release_sha256=digest,contract_sha256=release['contract_sha256'],
            pipeline=identity(attempt/'PROCESS_COMPLETE.json'),verification=result['verification'],
            scientific_conclusion=False))
    except BaseException as e:
        if attempt.is_dir() and not (attempt/'FAILED.json').exists():
            write_json(attempt/'FAILED.json',dict(error_type=type(e).__name__,error=str(e),retry_attempted=False))
        raise
    finally: signal.signal(signal.SIGTERM,previous)

def verify_completed(root,c,package,release,digest,job):
    require(root.is_dir() and not root.is_symlink(),'ATTEMPT_DIRECTORY')
    require(not any(p.is_symlink() for p in root.rglob('*')),'ATTEMPT_SYMLINK')
    complete=json.loads((root/'E1_COMPLETE.json').read_bytes())
    require(complete['job_id']==job and complete['release_sha256']==digest and
            complete['contract_sha256']==release['contract_sha256'] and
            complete['status']=='E1_EXECUTION_VERIFIED_ANALYSIS_PENDING','COMPLETE_BINDING')
    require(complete['pipeline']==identity(root/'PROCESS_COMPLETE.json'),'PIPELINE_SHA')
    pipeline=json.loads((root/'PROCESS_COMPLETE.json').read_bytes())
    records=pipeline['records']
    require([r['label'] for r in records]==['A','B','VERIFY'] and
            len({r['pid'] for r in records})==3 and all(r['returncode']==0 for r in records),'PIPELINE_PROCESSES')
    elapsed=pipeline['elapsed_seconds']
    require(type(elapsed) in (int,float) and math.isfinite(elapsed) and
            0<=elapsed<release['budget']['coordinator_deadline_seconds'],'PIPELINE_DEADLINE')
    request=json.loads((root/'VERIFY_REQUEST.json').read_bytes())
    require(request==dict(records=records[:2],release_sha256=digest,job_id=job),'VERIFY_REQUEST_BINDING')
    launch=json.loads((root/'VERIFY/LAUNCH.json').read_bytes())
    require(launch=={k:records[2][k] for k in ('label','pid','argv')},'VERIFIER_LAUNCH')
    from e1_entry import REMOTE_ROOT
    require(records[2]['argv']==['/home/s2510040/miniconda3/envs/attn/bin/python','-I','-B','-u',
            str(REMOTE_ROOT/'package/e1_entry.py'),'verify',digest],'VERIFIER_ARGV')
    result=verify_bound_archive(root,c,records[:2],package,release,digest,job)
    require(canonical(result)==canonical(complete['verification'])==canonical(pipeline['verification'])==
            canonical(json.loads((root/'VERIFY/VERIFIED.json').read_bytes())),'OFFLINE_REPORT')
    return result

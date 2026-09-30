"""Allocated E2 stage worker candidate. Not a deployment/submission CLI."""
import os
from pathlib import Path
from e1_inputs import build_contract
from e1_artifacts import write_json
from e1_worker_archive import environment_record,verify_provenance
from e2_catalog import stage_record
from e2_audited_session import audited_e2_session
from e2_execution import execute_stage
from e2_stage_archive import archive_stage,verify_stage_archive
from e2_history_bridge import verify_history
from e2_endpoint import check_endpoint
import numpy as np
from e1_artifacts import identity

def run_stage(directory,completed_epochs,*,seconds=9000,reference_root=None,mode='matrix'):
    record=stage_record(completed_epochs)
    layout=build_contract()
    root=Path(directory); root.mkdir(mode=0o700,exist_ok=False)
    records={}; report=None; endpoint_files=[]
    endpoint_root=root/'endpoint'; endpoint_root.mkdir(mode=0o700)
    try:
        with audited_e2_session(layout,completed_epochs) as ctx:
            report=ctx['load_report']
            if ctx['stage_record']!=record or ctx['checkpoint_sha']!=record['sha256']:
                raise ValueError('WORKER_STAGE_IDENTITY')
            def endpoint_sink(key,payload):
                path=endpoint_root/f'{len(endpoint_files):02d}.npz'
                with path.open('xb') as f:
                    np.savez(f,trial_ids=np.array(payload['trial_ids'],dtype=np.int64),logits=payload['logits'],nll=payload['nll'])
                endpoint_files.append(dict(file=path.name,key=list(key),**identity(path)))
            endpoint=check_endpoint(layout,ctx,endpoint_sink)
            ctx['core'].configure_runtime()  # Same reset as E1 before scientific passes.
            def sink(key,payload):
                if key in records: raise ValueError('WORKER_DUPLICATE_RECORD')
                records[key]=payload
            summary=execute_stage(layout,completed_epochs,ctx['core'],ctx['base'],ctx['outer'],
                                  ctx['architecture_type'],ctx['gain_type'],ctx['batch_provider'],
                                  ctx['device'],sink,seconds=seconds,mode=mode)
            env=environment_record()
            wanted_passes={(k[1],k[2]) for k in records}
            verify_provenance(dict(environment=env,job_id=os.environ['SLURM_JOB_ID']),summary,wanted_passes)
        # Only archive success after source/input/stage postchecks exit cleanly.
        archived=archive_stage(root/'archive',layout,completed_epochs,records,report,summary,mode)
        verified,reread=verify_stage_archive(root/'archive',layout,completed_epochs,mode)
        bridge=verify_history(reread,reference_root,pilot=mode in ('pilot','pilot_cold')) if completed_epochs==40 else None
        result=dict(status='E2_STAGE_WORKER_COMPLETE_NOT_EXPERIMENT_VERIFIED',
                    stage=record,environment=env,array_check=verified,history_bridge=bridge,
                    endpoint=endpoint,endpoint_files=endpoint_files,mode=mode)
        write_json(root/'RESULT.json',result)
        return result
    except BaseException as exc:
        write_json(root/'FAILED.json',dict(status='E2_STAGE_FAILED',stage=record,
                   error_type=type(exc).__name__,error=str(exc),records_completed=len(records),
                   automatic_retry=False))
        raise

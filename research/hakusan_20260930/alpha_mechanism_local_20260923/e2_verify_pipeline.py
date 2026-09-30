"""Independent archive/provenance reread. Parent launcher binding required."""
import json
from pathlib import Path
from e1_worker_archive import verify_provenance,parse_utc,verify_g5_report
from e2_catalog import stage_record
from e2_pipeline import WORKERS,PILOT_WORKERS
from e2_matrix import expected_records
from e2_stage_archive import verify_stage_archive
from e2_history_bridge import verify_history
from e2_endpoint import probe_spec,verify_saved_endpoint

def verify_lifecycle(record,launch,expected_argv):
    if record.get('argv')!=expected_argv or launch.get('argv')!=expected_argv:
        raise ValueError('LIFECYCLE_ARGV')
    if type(record.get('pid')) is not int or record['pid']<=0 or record['pid']!=launch.get('pid'):
        raise ValueError('LIFECYCLE_PID')
    if record.get('returncode')!=0 or record.get('status')!='CHILD_COMPLETE' or record.get('automatic_retry') is not False:
        raise ValueError('LIFECYCLE_EXIT')
    if record.get('launch_requested_utc')!=launch.get('launch_requested_utc'):
        raise ValueError('LIFECYCLE_START')
    if parse_utc(record['launch_requested_utc'])>parse_utc(record['exit_observed_utc']):
        raise ValueError('LIFECYCLE_TIME')
    if type(record.get('elapsed_seconds')) not in (int,float) or not 0<=record['elapsed_seconds']<=14400:
        raise ValueError('LIFECYCLE_ELAPSED')

def verify_pipeline(root,layout,worker_command,*,job_id,reference_root=None,pilot=False):
    root=Path(root)
    if root.is_symlink() or not root.is_dir() or (root/'FAILED.json').exists(): raise ValueError('FAILED_PIPELINE')
    if any(p.is_symlink() for p in root.rglob('*')): raise ValueError('PIPELINE_SYMLINK')
    workers=PILOT_WORKERS if pilot else WORKERS
    request=json.loads((root/'VERIFY_REQUEST.json').read_text())
    if len(request['workers'])!=len(workers): raise ValueError('WORKER_COUNT')
    total=0; formal=None; cold=None; summaries=[]
    endpoint_count=2*sum(len(ids) for *_,ids in probe_spec(layout))
    for submitted,(label,rounds,mode) in zip(request['workers'],workers):
        d=root/label; output=d/'output'
        if {p.name for p in d.iterdir()}!={'PROCESS.json','LAUNCH.json','stdout.log','stderr.log','output'}:
            raise ValueError('WORKER_FILE_INVENTORY')
        if {p.name for p in output.iterdir()}!={'RESULT.json','archive','endpoint'}:
            raise ValueError('OUTPUT_FILE_INVENTORY')
        if (submitted['label'],submitted['completed_epochs'],submitted['mode'])!=(label,rounds,mode):
            raise ValueError('WORKER_ORDER')
        if (output/'FAILED.json').exists(): raise ValueError('FAILED_STAGE')
        process=json.loads((d/'PROCESS.json').read_text()); launch=json.loads((d/'LAUNCH.json').read_text())
        if process!=submitted['lifecycle']: raise ValueError('PROCESS_BINDING')
        verify_lifecycle(process,launch,worker_command(rounds,mode,output))
        result=json.loads((output/'RESULT.json').read_text())
        if result.get('status')!='E2_STAGE_WORKER_COMPLETE_NOT_EXPERIMENT_VERIFIED': raise ValueError('RESULT_STATUS')
        if result.get('stage')!=stage_record(rounds) or result.get('mode')!=mode:
            raise ValueError('RESULT_STAGE')
        if result.get('environment',{}).get('slurm_job_id')!=job_id: raise ValueError('RESULT_JOB')
        check,records=verify_stage_archive(output/'archive',layout,rounds,mode)
        metadata=json.loads((output/'archive'/'STAGE.json').read_text())
        if metadata.get('array_check')!=check: raise ValueError('ARCHIVE_ARRAY_REPORT')
        load=metadata['load_report']; execution=metadata['execution']
        if load.get('production_provenance_verified') is not True or load.get('loaded_trainable_numel_ratio')!=1.0:
            raise ValueError('LOAD_PROVENANCE')
        if load.get('trainable_numel')!=62622520 or load.get('loaded_trainable_numel')!=62622520:
            raise ValueError('LOAD_COVERAGE')
        if load.get('strict') is not True or load.get('key_rewrite') is not False:
            raise ValueError('LOAD_STRICT')
        passes={(k[1],k[2]) for k in records}
        verify_provenance(dict(environment=result['environment'],job_id=job_id),execution,passes)
        if not (parse_utc(process['launch_requested_utc'])<=parse_utc(execution['process_started_utc'])<=
                parse_utc(execution['process_finished_utc'])<=parse_utc(process['exit_observed_utc'])):
            raise ValueError('PROCESS_WINDOW')
        formulas=execution['gain_formula_reports']
        if len(formulas)!=len(passes) or {(f['domain'],f['pass_name']) for f in formulas}!=passes:
            raise ValueError('FORMULA_INVENTORY')
        for f in formulas: verify_g5_report(f['report'],f['pass_name'])
        endpoint=result['endpoint']
        verify_saved_endpoint(output/'endpoint',layout,result['endpoint_files'])
        expected_batches=[dict(domain=d,batch_index=b,condition=c,trial_ids=ids) for d,b,c,ids in probe_spec(layout)]
        if endpoint.get('status')!='E2_STAGE_ENDPOINT_BITS_PASS' or endpoint.get('predictions')!=endpoint_count or endpoint.get('batches')!=expected_batches:
            raise ValueError('ENDPOINT_REPORT')
        if result['array_check']!=check or execution['predictions']!=check['predictions']:
            raise ValueError('PREDICTION_COUNT')
        total+=check['predictions']+endpoint_count
        if rounds==40:
            bridge=verify_history(records,reference_root,pilot=pilot)
            if bridge!=result['history_bridge']: raise ValueError('BRIDGE_REPORT')
            if mode in ('matrix','pilot'): formal=records
            else: cold=records
        summaries.append(dict(label=label,arrays=check,endpoint_predictions=endpoint_count))
    for key,row in cold.items():
        if row['trial_ids']!=formal[key]['trial_ids']: raise ValueError('COLD_IDS')
        for field in ('logits','nll'):
            a=row[field]; b=formal[key][field]
            if a.dtype!=b.dtype or a.shape!=b.shape or a.tobytes()!=b.tobytes(): raise ValueError('COLD_BITS')
    analysis=sum(len(ids) for _,r,m in workers[:-1] for ids in expected_records(layout,r,m).values())
    cold_count=sum(len(ids) for ids in expected_records(layout,40,workers[-1][2]).values())
    if total!=analysis+cold_count+len(workers)*endpoint_count: raise ValueError('E2_TOTAL_PREDICTIONS')
    return dict(status='E2_ARTIFACTS_VERIFIED',predictions=total,analysis_predictions=analysis,
                cold_predictions=cold_count,endpoint_predictions=len(workers)*endpoint_count,workers=summaries,
                scope='native_pilot_not_trajectory' if pilot else 'full_matrix',
                scientific_report_complete=False)

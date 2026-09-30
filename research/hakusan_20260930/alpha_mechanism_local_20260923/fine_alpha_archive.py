"""Strict-loaded worker and independent archive reread for the fine grid."""
import hashlib
import json
import os
from pathlib import Path
import numpy as np
from e0_layout_reference import require
from e1_artifacts import canonical, identity, write_json
from e1_inputs import build_contract, FORMAL_SHA
from e1_worker_archive import (environment_record, verify_environment, verify_runtime,
                              verify_provenance, verify_g5_report, parse_utc)
from fine_alpha_contract import contract, inventory, BLOCKS, BUDGET
from fine_alpha_execution import execute, verify_arrays

def contract_sha(layout):
    return hashlib.sha256(canonical(contract(layout))).hexdigest()

def read_arrays(directory, rows, expected):
    directory = Path(directory); records = {}; names = set()
    for i, row in enumerate(rows):
        key = tuple(row['key']); filename = f'{i:03d}.npz'
        require(row['file'] == filename and key in expected and key not in records, 'FINE_OUTPUT_INVENTORY')
        path = directory/filename
        require(identity(path) == {k: row[k] for k in ('size', 'sha256')}, 'FINE_OUTPUT_SHA')
        with np.load(path, allow_pickle=False) as data:
            require(set(data.files) == {'trial_ids', 'logits', 'nll'}, 'FINE_ARRAY_KEYS')
            require(data['trial_ids'].dtype == np.int64, 'FINE_IDS_DTYPE')
            records[key] = dict(trial_ids=data['trial_ids'].tolist(), logits=data['logits'], nll=data['nll'])
        names.add(filename)
    require(set(records) == set(expected), 'FINE_MISSING_OUTPUTS')
    return records, names

def run_worker(directory, block, digest, reference_root):
    from e1_audited_session import audited_e1_session
    from loaded_model_adapter import accept_loaded_formal40
    from e2_history_bridge import read_reference
    layout = build_contract(); expected = inventory(layout, block)
    root = Path(directory); root.mkdir(mode=0o700, exist_ok=False)
    rows = []; phase = 'reference_and_load'
    try:
        reference = read_reference(reference_root)
        def sink(key, p):
            require(key in expected and key not in {tuple(r['key']) for r in rows}, 'FINE_SINK_KEY')
            path = root/f'{len(rows):03d}.npz'
            with path.open('xb') as f:
                np.savez(f, trial_ids=np.array(p['trial_ids'], dtype=np.int64), logits=p['logits'], nll=p['nll'])
            rows.append(dict(key=list(key), file=path.name, **identity(path)))
        with audited_e1_session(layout) as ctx:
            accept_loaded_formal40(ctx['core'], ctx['outer'], ctx['load_report'], 'formal40',
                                  ctx['checkpoint_sha'], ctx['architecture_type'], ctx['gain_type'])
            # The session must enter first: its launch gate requires uninitialized
            # CUDA. Check provenance before any forward/science pass, not after hours.
            phase = 'environment_precheck'
            env = environment_record(); runtime = ctx['core'].runtime_values()
            verify_environment(dict(environment=env, job_id=os.environ['SLURM_JOB_ID']))
            verify_runtime(runtime)
            write_json(root/'ENVIRONMENT_PRECHECK.json', dict(
                status='FINE_ENVIRONMENT_PRECHECK_PASS_NOT_INFERENCE_VERIFIED',
                job_id=os.environ['SLURM_JOB_ID'], pid=os.getpid(), release_sha256=digest,
                environment=env, runtime_values=runtime))
            phase = 'execution'
            summary = execute(layout, block, ctx, sink, reference=reference, seconds=7200)
            phase = 'environment_postcheck'
            after = environment_record()
            verify_environment(dict(environment=after, job_id=os.environ['SLURM_JOB_ID']))
            require(after == env, 'FINE_ENVIRONMENT_CHANGED')
            load = ctx['load_report']; phase = 'session_postcheck'
        # This file is never emitted unless input/source/session postchecks completed.
        phase = 'archive_validation'
        records, _ = read_arrays(root, rows, expected)
        array_check = verify_arrays(layout, records, block, reference=reference)
        verify_provenance(dict(environment=env, job_id=os.environ['SLURM_JOB_ID']), summary,
                          {(k[1], k[2]) for k in expected})
        write_json(root/'WORKER.json', dict(status='FINE_WORKER_FINISHED_NOT_JOB_VERIFIED', block=block,
            job_id=os.environ['SLURM_JOB_ID'], pid=os.getpid(), release_sha256=digest,
            checkpoint_sha256=FORMAL_SHA, contract_sha256=contract_sha(layout),
            source_input_postchecks_completed=True, outputs=rows, execution=summary,
            environment=env, environment_precheck=identity(root/'ENVIRONMENT_PRECHECK.json'),
            load_report=load, array_check=array_check))
    except BaseException as exc:
        write_json(root/'FAILED.json', dict(status='FINE_WORKER_FAILED', error_type=type(exc).__name__,
                    error=str(exc), phase=phase, completed_records=len(rows), automatic_retry=False))
        raise

def verify_lifecycle(process, launch, argv):
    require(process.get('argv') == launch.get('argv') == argv, 'FINE_LIFECYCLE_ARGV')
    require(type(process.get('pid')) is int and process['pid'] > 0 and process['pid'] == launch.get('pid'), 'FINE_PID')
    require(process.get('status') == 'CHILD_COMPLETE' and process.get('returncode') == 0 and
            process.get('automatic_retry') is False, 'FINE_PROCESS_EXIT')
    require(process.get('launch_requested_utc') == launch.get('launch_requested_utc'), 'FINE_LAUNCH_TIME')
    require(parse_utc(process['launch_requested_utc']) <= parse_utc(process['exit_observed_utc']), 'FINE_PROCESS_TIME')
    require(type(process.get('elapsed_seconds')) in (int, float) and 0 <= process['elapsed_seconds'] <= 7800,
            'FINE_PROCESS_ELAPSED')

def verify(root, layout, digest, job_id, command, reference, *, production=True):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink() and not (root/'FAILED.json').exists(), 'FINE_FAILED_ROOT')
    require(not any(p.is_symlink() for p in root.rglob('*')), 'FINE_ARCHIVE_SYMLINK')
    run = json.loads((root/'RUN.json').read_text())
    require(run.get('status') == 'FINE_ALPHA_RUNNING' and run.get('release_sha256') == digest and
            run.get('job_id') == job_id and run.get('budget') == BUDGET and run.get('blocks') == list(BLOCKS) and
            run.get('automatic_retry') is False, 'FINE_RUN_BINDING')
    request = json.loads((root/'VERIFY_REQUEST.json').read_text())
    require(request.get('release_sha256') == digest and request.get('job_id') == job_id and
            request.get('blocks') == list(BLOCKS), 'FINE_VERIFY_REQUEST')
    require(type(request.get('workers')) is list and len(request['workers']) == len(BLOCKS), 'FINE_REQUEST_WORKERS')
    allowed = set(BLOCKS) | {'RUN.json', 'VERIFY_REQUEST.json', 'VERIFY', 'COMPLETE.json'}
    require({p.name for p in root.iterdir()} <= allowed, 'FINE_ROOT_INVENTORY')
    all_records = {}; pids = []; input_hashes = []; windows = []
    for block in BLOCKS:
        d = root/block; output = d/'output'
        require({p.name for p in d.iterdir()} == {'LAUNCH.json', 'PROCESS.json', 'stdout.log', 'stderr.log', 'output'},
                'FINE_PROCESS_INVENTORY')
        process = json.loads((d/'PROCESS.json').read_text()); launch = json.loads((d/'LAUNCH.json').read_text())
        verify_lifecycle(process, launch, command(block))
        require(request['workers'][BLOCKS.index(block)] == dict(block=block, lifecycle=process), 'FINE_PROCESS_BINDING')
        pids.append(process['pid']); windows.append((parse_utc(process['launch_requested_utc']), parse_utc(process['exit_observed_utc'])))
        metadata = json.loads((output/'WORKER.json').read_text())
        require(metadata.get('status') == 'FINE_WORKER_FINISHED_NOT_JOB_VERIFIED' and metadata.get('block') == block,
                'FINE_WORKER_IDENTITY')
        require(metadata.get('job_id') == job_id and metadata.get('pid') == process['pid'] and
                metadata.get('release_sha256') == digest and metadata.get('contract_sha256') == contract_sha(layout) and
                metadata.get('checkpoint_sha256') == FORMAL_SHA and metadata.get('source_input_postchecks_completed') is True,
                'FINE_WORKER_BINDING')
        load = metadata['load_report']
        require(load.get('loaded_trainable_numel_ratio') == 1 and load.get('trainable_numel') == 62622520 and
                load.get('loaded_trainable_numel') == 62622520 and load.get('prefix_rule') == 'exact' and
                load.get('missing_keys') == load.get('unexpected_keys') == [] and
                load.get('shape_mismatches') == load.get('dtype_mismatches') == {} and
                load.get('native_preprocessing') == 'selftrain_singleton_per_example_leveling', 'FINE_LOAD_COVERAGE')
        expected = inventory(layout, block)
        records, names = read_arrays(output, metadata['outputs'], expected)
        require({p.name for p in output.iterdir()} == names | {'WORKER.json', 'ENVIRONMENT_PRECHECK.json'},
                'FINE_OUTPUT_FILES')
        check = verify_arrays(layout, records, block, reference=reference)
        summary = metadata['execution']
        require(check == metadata['array_check'] and summary.get('predictions') == check['predictions'] and
                summary.get('historical_bridge_completed') is True, 'FINE_EXECUTION_REPORT')
        wanted = {(k[1], k[2]) for k in expected}
        verify_provenance(metadata, summary, wanted, production=production)
        precheck_path = output/'ENVIRONMENT_PRECHECK.json'
        require(identity(precheck_path) == metadata.get('environment_precheck'), 'FINE_PRECHECK_SHA')
        precheck = json.loads(precheck_path.read_text())
        require(precheck == dict(status='FINE_ENVIRONMENT_PRECHECK_PASS_NOT_INFERENCE_VERIFIED',
                job_id=job_id, pid=process['pid'], release_sha256=digest,
                environment=metadata['environment'], runtime_values=summary['runtime_values']),
                'FINE_PRECHECK_BINDING')
        require(windows[-1][0] <= parse_utc(summary['process_started_utc']) <=
                parse_utc(summary['process_finished_utc']) <= windows[-1][1], 'FINE_PROCESS_WINDOW')
        formulas = summary['gain_formula_reports']
        require(len(formulas) == len(wanted) and {(f['domain'], f['pass_name']) for f in formulas} == wanted, 'FINE_FORMULA_INVENTORY')
        for row in formulas: verify_g5_report(row['report'], row['pass_name'])
        observed = summary.get('input_identity_sha256')
        require(type(observed) is str and len(observed) == 64 and all(c in '0123456789abcdef' for c in observed), 'FINE_INPUT_IDENTITY')
        input_hashes.append(observed); all_records.update(records)
    require(len(set(pids)) == len(BLOCKS) and len(set(input_hashes)) == 1, 'FINE_COLD_PROCESS_OR_INPUTS')
    require(all(windows[i][1] <= windows[i+1][0] for i in range(len(BLOCKS)-1)), 'FINE_PROCESS_ORDER')
    require(parse_utc(run['started_utc']) <= windows[0][0], 'FINE_RUN_TIME')
    checked = verify_arrays(layout, all_records, reference=reference)
    require(checked['predictions'] == contract(layout)['predictions'], 'FINE_TOTAL_COUNT')
    return dict(status='FINE_ALPHA_ARTIFACTS_VERIFIED' if production else 'SYNTHETIC_FINE_ALPHA_ARCHIVE_PASS',
                release_sha256=digest, contract_sha256=contract_sha(layout), job_id=job_id,
                predictions=checked['predictions'], science_predictions=contract(layout)['science_predictions'],
                cold_processes=len(BLOCKS), historical_job='750474',
                anchor_job='756262', anchor_check='NOT_IN_JOB_OFFLINE_PENDING',
                scientific_report_complete=False, age_mapping_validated=False), all_records

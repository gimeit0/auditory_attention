"""Offline G2 pass semantics and parent-captured worker binding.

Reuses original validators; never issues live model authority. The supervisor
must check release/scheduler and provide its OWN PID/env/receipt pins. A child
manifest alone cannot produce an accepted production observation.
"""
import ast
import copy
import json
import mmap
import os
from pathlib import Path
import sys
import types

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import runtime as r


def _binder(bridge,diag):
    """Only role suffix and no-HOME scratch policy differ from the old binder."""
    raw=bridge.read(diag.__file__,bridge.CORE_SHAS[diag._G2_PROFILE])
    tree=ast.parse(raw)
    original=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_bind_persisted_worker')
    copied=copy.deepcopy(original)
    assignments=[n for n in copied.body if isinstance(n,ast.Assign) and len(n.targets)==1
                 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='role']
    r.require(len(assignments)==1 and ast.unparse(assignments[0].value)=="cell or 'reference_cold'",'binder source differs')
    prior=assignments[0].value
    assignments[0].value=ast.parse("cell + '-observed'",mode='eval').body
    code=compile(ast.fix_missing_locations(ast.Module(body=[copied],type_ignores=[])),
                 '<g2-original-persisted-worker-binding>','exec',dont_inherit=True)
    assignments[0].value=prior
    r.require(ast.dump(copied)==ast.dump(original),'binder changed other checks')
    namespace=dict(vars(diag),_WORKER_WRITE_PATHS={k:v for k,v in diag._WORKER_WRITE_PATHS.items() if k!='HOME'})
    exec(code,namespace)
    return namespace['_bind_persisted_worker']


def pass_semantics(root,receipt,*,bridge,diag):
    """Data-only core also tested on real saved synthetic artifacts.

Reconstruct existing CPU captures using copy-on-write maps, not inference. The
original pass validator rechecks runtime/load report/shape/mutation guards and
the complete commitment; the original two-pass state/RNG check is preserved.
"""
    import numpy as np
    import torch
    codec=r.store.build_codec()
    fd=codec.directory(root)
    maps=[]
    results=[]
    try:
        raw=b''.join(codec.chunks(fd,'manifest.json',receipt['archive_manifest_size'],receipt['archive_manifest_sha256']))
        manifest=json.loads(raw)
        r.require(codec.canonical(manifest)==raw and len(manifest['passes'])==2,'manifest differs')
        for i,part in enumerate(manifest['passes']):
            original=part['original_pass_evidence']
            decoded=diag.decode_pass_evidence(original)
            payload=decoded['payload']
            boundaries=copy.deepcopy(payload['boundaries'])
            for name in codec.COARSE+codec.DERIVED:
                record=part['boundaries'][name]
                codec.metadata(record)
                r.require(type(record['file']) is str and r.store.re.fullmatch('[0-9]{3}\\.bin',record['file']),
                          'mapping artifact name differs')
                handle=os.open(record['file'],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                try:
                    info=os.fstat(handle)
                    r.require(info.st_size==record['nbytes'] and info.st_nlink==1,'mapping size/link differs')
                    mapping=mmap.mmap(handle,record['nbytes'],access=mmap.ACCESS_COPY)
                finally: os.close(handle)
                maps.append(mapping)
                array=np.ndarray(record['shape'],dtype=record['dtype'],buffer=mapping)
                container=boundaries if name in codec.COARSE else boundaries['derived']
                container[name]['tensor']=torch.from_numpy(array)
            boundaries['pass_commitment']=original['commitment']
            result=diag.PassResult(pass_id=payload['pass_id'],batch_size=payload['batch_size'],
                trial_ids=tuple(payload['trial_ids']),outputs=decoded['outputs'],boundary_records=boundaries,
                model_snapshots=payload['model_snapshots'],rng_snapshots=payload['rng_snapshots'])
            diag._validate_cell_pass(result,diag.CellSpec(diag._G2_PROFILE,False,(16,1)),i)
            r.require(bridge._commitment(diag,result)==receipt['pass_commitments'][i], 'reconstructed commitment differs')
            results.append(result)
        timepoints=diag._cell_timepoints(*results)
        r.require(timepoints['model_state']['state_unchanged'] and not timepoints['rng']['rng_changed']
                and timepoints==receipt['cell_summary']['state'],'stored state/RNG decision differs')
        metadata=[p.boundary_records['metadata'] for p in results]
        for key in ('runtime','load_report','load_report_sha256','imported_source_records','worker_pid',
                    'worker_nonce','model_nonce','scratch_root','cache_roots','attestation','worker_environment'):
            r.require(metadata[0].get(key)==metadata[1].get(key),'two-pass worker identity differs: '+key)
        r.require(metadata[0]['cache_nonce']!=metadata[1]['cache_nonce'],'waveform cache reused between passes')
        codec.check_named_directory(root,fd)
        # All file content is checked again independently after the mmap checks.
        for part in manifest['passes']:
            for record in part['boundaries'].values():
                for _ in codec.chunks(fd,record['file'],record['nbytes'],record['sha256']): pass
        return dict(status='G2_ORIGINAL_PASS_SEMANTICS_VERIFIED',metadata=json.loads(r.store.canonical(metadata)),
                    state=timepoints,pass_commitments=list(receipt['pass_commitments']),
                    live_model_authority_issued=False,production_model_loaded=False)
    finally:
        os.close(fd)
        # Tensor borrowers retain the mappings until these local results leave
        # scope; do not forcibly unmap storage still referenced by a Tensor.


def verify_worker(root,*,terminal,terminal_sha,receipt,receipt_sha,launch,bridge,diag,freeze,
                  production_bytes,release_sha,source_check):
    """Call only with source-pinned parent launch evidence, never child claims alone."""
    source_check()
    r.require(r.store.sha(r.store.canonical(terminal))==terminal_sha,'terminal digest differs')
    r.require(terminal['status']=='G2_WORKER_STORED' and terminal['error'] is None
              and terminal['source_postcheck'] is True and terminal['automatic_retry'] is False
              and terminal['independent_results_verified'] is False and terminal['ready_for_gpu'] is False
              and 0<=terminal['elapsed_seconds']<r.CHILD_SECONDS,'worker is not a complete candidate')
    pid,env=launch['pid'],launch['environment']
    profile,job=diag._G2_PROFILE,env['SLURM_JOB_ID']
    r.require(launch['returncode']==0 and launch['error'] is None
              and 0<=launch['elapsed_seconds']<r.CHILD_SECONDS
              and type(pid) is int and pid==terminal['pid']==receipt['pid']
              and terminal['job_id']==job==receipt['job_id'] and terminal['profile']==profile==receipt['profile']
              and terminal['release_sha256']==release_sha==receipt['binding']['release_sha256'], 'parent launch binding differs')
    freeze_sha=r.store.sha(r.store.canonical(freeze))
    _,relation=r.cell_api.input_api.verify_relation(bridge,diag,r.store.canonical(freeze),freeze_sha,
                 production_bytes,r.store.pinned(r.store.PARENT,r.store.PARENT_SHA))
    r.require(terminal['input_freeze_sha256']==receipt['input_freeze_sha256']==freeze_sha
              and terminal['result']['archive_receipt']==receipt
              and receipt['metadata']['input_relation']==relation,'freeze/scientific relation/terminal archive differs')
    r.require(env.get('CUBLAS_WORKSPACE_CONFIG')==':4096:8'
              and env.get('PYTHONDONTWRITEBYTECODE')==env.get('PYTHONNOUSERSITE')=='1'
              and env.get('PYTHONHASHSEED')=='0' and env.get('SLURM_CPUS_PER_TASK')=='8',
              'pre-import execution environment differs')
    binding=r.store.bind(receipt['metadata'],freeze['trials'],release_sha,'production')
    content=r.store.verify(root/'arrays',receipt,receipt_sha=receipt_sha,expected_binding=binding,
                           trials=freeze['trials'],bridge=bridge,diag=diag)
    for name,expected in terminal['inventory'].items():
        r.require(name in ('STARTED.json','ARCHIVE_RECEIPT.json','arrays/manifest.json')
                  and r.process_api.file_record(root/name)==expected,'terminal artifact inventory differs')
    r.require(set(terminal['inventory'])=={'STARTED.json','ARCHIVE_RECEIPT.json','arrays/manifest.json'},
              'required worker evidence missing')
    semantics=pass_semantics(root/'arrays',receipt,bridge=bridge,diag=diag)
    codec=r.store.build_codec()
    descriptor=codec.directory(root/'arrays')
    try:
        raw=b''.join(codec.chunks(descriptor,'manifest.json',receipt['archive_manifest_size'],receipt['archive_manifest_sha256']))
        saved=json.loads(raw)
    finally: os.close(descriptor)
    historical=json.loads(r.store.pinned(r.store.GEOMETRY,r.store.GEOMETRY_SHA))['cells']['B2']['passes']['pass1']
    for part in saved['passes']:
        for name in ('raw_scene','raw_cue'):
            rows=part['original_pass_evidence']['payload']['boundaries'][name]['per_trial']
            expected=historical['boundaries'][name]['rows']
            r.require(len(rows)==len(expected)==32 and all(
                one['trial_id']==two['trial_id'] and r.store.descriptor(one,scalar=True)==
                {k:two[k] for k in ('dtype','shape','nbytes','sha256')} for one,two in zip(rows,expected)),
                'raw inputs differ from historical frozen B2')
    sources=[dict(item,path=str(Path(freeze['roots']['snapshot_files'])/item['relative_path']))
             for item in freeze['snapshot_files']]
    bound_launch=dict(pid=pid,environment=env,completion=dict(cell=profile,job_id=job))
    bind_original=_binder(bridge,diag)
    rows=[dict(trial_id=t['trial_id'],bank_row_index=t['bank_row_index']) for t in freeze['trials']]
    for meta in semantics['metadata']:
        bind_original(meta,bound_launch,sources)
        software=meta['worker_environment']['software']
        r.require(software['python']=='3.11.5' and software['torch']=='2.1.1+cu118'
                  and 'A100' in software['gpu_name'] and meta['trial_bank_rows']==rows
                  and meta['attestation']==receipt['metadata']['preparation'],'production runtime/preparation differs')
    backend=receipt['cell_summary']['backend']
    if profile in ('R','C'):
        r.require(backend.get('target_generated_artifacts_executed') is True
                  and type(backend.get('compiler_calls')) is int
                  and backend['compiler_calls']==backend['compiler_returns']>0 and backend.get('artifacts'),
                  'compiled target evidence missing')
        cache=Path(semantics['metadata'][0]['cache_roots']['torchinductor'])
        for artifact in backend['artifacts']:
            r.require(type(artifact['calls']) is int and artifact['calls']==artifact['returns']>0
                      and Path(artifact['path']).is_relative_to(cache)
                      and r.store.SHA.fullmatch(artifact['sha256']),'generated artifact evidence differs')
    else:
        r.require(backend==dict(compiled=False,observer_installed=False,native_cold_state_verified=True),
                  'eager cell has unexpected compiler evidence')
    source_check()
    return dict(status='G2_WORKER_EVIDENCE_VERIFIED',execution_valid=True,job_id=job,profile=profile,pid=pid,
        release_sha256=release_sha,input_freeze_sha256=freeze_sha,trial_identity_sha256=binding['trial_identity_sha256'],
        numeric=content['numeric'],pass_commitments=content['pass_commitments'],
        original_pass_semantics_verified=True,parent_launch_binding_verified=True,
        production_interference_validated=False,ready_for_full_evaluation=False)

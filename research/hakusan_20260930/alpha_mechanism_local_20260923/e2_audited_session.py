"""E2 stage-specific allocated-worker loading session candidate, not a CLI or submission tool.

Not exercised with checkpoints locally. Deployment/import inventory and final
archive qualification remain separate gates. Owns no retry or SSH connection.
"""
from contextlib import contextmanager
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import platform
import sys
import torch
from loaded_model_adapter import pinned_core,FORMAL_SHA
from e2_catalog import stage_record
from e2_stage_loading import load_stage
from e0_layout_reference import require,canonical
from e1_execution import contract as e1_contract
from e1_provider import E1Provider
from native_batch_provider import NativeBatchProvider
from snapshot_source_import import source_only_imports

ARCH_SHA='84e68e051f2a2a7a2373aab5c510b72e626aa3b11a9d54f5ec9e35ddbe570eed'
CALLBACK_SHAS={
    'selftrain/data/diotic_attention.py':'26b5cf965aec1652f2d77be517f867bb284a2f53c2f53706b2c5aa2cc0ad9e8a',
    'selftrain/scripts/eval_full_pilot.py':'29414207e3fac53ff8805e61fcf4cee48fb155c4c60d0e736e35526c80dfae5b',
}
SNAPSHOT_SHA='8febb19f3c183333adfc0f7543ba7a017a3c5d4d5ae2132ffa72e701da955dcb'

def snapshot_manifest(base,snapshot):
    return base.read_json(snapshot.parent/'manifest.json','snapshot manifest',SNAPSHOT_SHA)

def verify_snapshot(base,snapshot):
    manifest=snapshot_manifest(base,snapshot)
    records=manifest['provenance_files']
    wanted=set()
    for row in records:
        relative=Path(row['path'])
        require(not relative.is_absolute() and '..' not in relative.parts,'SNAPSHOT_RELATIVE_PATH')
        require(str(relative) not in wanted,'SNAPSHOT_DUPLICATE')
        wanted.add(str(relative))
        actual=base.pinned_file(snapshot/relative,'snapshot file',row['sha256'])
        require(actual['size']==row['size'],'SNAPSHOT_SIZE')
    # Existing caches are inert ONLY with source_only_imports around snapshot imports.
    # Presence is diagnostic, not proof that cached code was executed.
    caches=list(snapshot.rglob('*.pyc'))
    require(not any(p.is_symlink() for p in snapshot.rglob('*')),'SNAPSHOT_SYMLINK')
    require({str(p.relative_to(snapshot)) for p in snapshot.rglob('*.py')}==
            {p for p in wanted if p.endswith('.py')},'SNAPSHOT_PYTHON_INVENTORY')
    return dict(manifest_sha256=SNAPSHOT_SHA,files=len(records),existing_bytecode_files=len(caches),
                required_import_policy='hash_checked_source_only')

def launch_gate():
    require(sys.platform=='linux' and os.environ.get('SLURM_JOB_ID','').isdigit(),'ALLOCATED_LINUX_REQUIRED')
    require(sys.flags.isolated and sys.dont_write_bytecode,'ISOLATED_WORKER_REQUIRED')
    require(platform.python_version()=='3.11.5' and torch.__version__=='2.1.1+cu118','NATIVE_RUNTIME_REQUIRED')
    require(os.environ.get('CUBLAS_WORKSPACE_CONFIG')==':4096:8','CUBLAS_CONTRACT')
    require(not torch.cuda.is_initialized(),'CUDA_ALREADY_INITIALIZED')

def native_source_preflight():
    """Read-only native import probe, no checkpoints, model construction or job."""
    require(sys.platform=='linux' and sys.flags.isolated and sys.dont_write_bytecode,'NATIVE_ISOLATED_PREFLIGHT')
    require(platform.python_version()=='3.11.5' and torch.__version__=='2.1.1+cu118','NATIVE_RUNTIME_REQUIRED')
    require(not torch.cuda.is_initialized(),'CUDA_ALREADY_INITIALIZED')
    core=pinned_core()
    base=core.load_v4(core.V4_ROOT/'tools/locked_same_bank_eval.py')
    manifest,_=base._validate_manifest_hash(core.V4_ROOT/'input_freeze.json',core.MANIFEST_SHA)
    snapshot=Path(manifest['roots']['snapshot_files'])
    before=verify_snapshot(base,snapshot)
    source_hashes={r['path']:r['sha256'] for r in snapshot_manifest(base,snapshot)['provenance_files'] if r['path'].endswith('.py')}
    def read(path,sha): return base.read_pinned_bytes(path,'source-only preflight',sha)[0]
    with source_only_imports(snapshot,source_hashes,read),base._frozen_import_context(snapshot):
        for name in ('selftrain.data.diotic_attention','selftrain.scripts.eval_full_pilot'):
            module=importlib.import_module(name)
            source=base.safe_file(inspect.getfile(module),'preflight source')
            relative=str(source.relative_to(snapshot))
            require(relative in CALLBACK_SHAS and base.sha256_file(source)==CALLBACK_SHAS[relative],'PREFLIGHT_SOURCE')
    verify_snapshot(base,snapshot)
    require(not torch.cuda.is_initialized(),'PREFLIGHT_INITIALIZED_CUDA')
    return dict(status='NATIVE_SOURCE_ONLY_IMPORT_PASS',snapshot=before,checkpoint_loaded=False,
                cuda_initialized=False,jobs_submitted=0)

@contextmanager
def audited_e2_session(layout, completed_epochs):
    stage = stage_record(completed_epochs)
    launch_gate()  # Before checkpoint reads or CUDA initialization.
    require(canonical(layout)==canonical(e1_contract()),'E1_SESSION_CONTRACT')
    core=pinned_core()
    base=core.load_v4(core.V4_ROOT/'tools/locked_same_bank_eval.py')
    manifest,_=base._validate_manifest_hash(core.V4_ROOT/'input_freeze.json',core.MANIFEST_SHA)
    require(manifest['models']['formal40']['sha256']==FORMAL_SHA,'CHECKPOINT_SHA')
    from e1_inputs import frozen_inputs
    frozen=frozen_inputs()
    def verify_e1_audio():
        root=Path(manifest['roots']['clips_dir'])
        require(str(root)==frozen['remote_audio_root'],'E1_CLIPS_ROOT')
        for row in frozen['audio_files']:
            require(Path(row['name']).name==row['name'],'E1_CLIP_NAME')
            info=base.pinned_file(root/row['name'],'E1 audio',row['sha256'])
            require(info['size']==row['size'],'E1_CLIP_SIZE')
    verify_e1_audio()
    runtime=core.configure_runtime()
    require(torch.cuda.is_available() and 'A100' in torch.cuda.get_device_name(0),'A100_REQUIRED')
    require(torch.cuda.device_count()==1 and os.environ.get('SLURM_CPUS_PER_TASK')=='8','ALLOCATION_SIZE')
    require(torch.version.cuda=='11.8' and torch.backends.cudnn.version()==8700,'CUDA_CUDNN_CONTRACT')
    device=torch.device('cuda:0')
    with base.evaluation_lock(core.V4_ROOT):
        base.validate_frozen_layout(core.V4_ROOT,manifest)
        base.verify_frozen_manifest(manifest,core.V4_ROOT)
        bank,_=base.read_csv_pinned(Path(manifest['inputs']['bank']['path']),'bank',
                                  manifest['inputs']['bank']['sha256'],sep='\t',
                                  dtype={f'{r}_speaker':str for r in base.ROLE_NAMES})
        h=manifest['historical_evidence']['job584990_results']
        historical,_=base.read_csv_pinned(Path(h['path']),'historical',h['sha256'],dtype={'target_speaker':str})
        base.validate_historical_scene_binding(bank,historical)
        hashes=dict(zip(historical.trial_id.astype(int),historical.scene_sha256.astype(str)))
        snapshot=Path(manifest['roots']['snapshot_files'])
        snapshot_check=verify_snapshot(base,snapshot)
        for relative,sha in CALLBACK_SHAS.items():
            base.pinned_file(snapshot/relative,'native callback source',sha)
        source_hashes={r['path']:r['sha256'] for r in snapshot_manifest(base,snapshot)['provenance_files'] if r['path'].endswith('.py')}
        def source_bytes(path,sha):
            return base.read_pinned_bytes(path,'source-only import',sha)[0]
        with source_only_imports(snapshot,source_hashes,source_bytes), base._frozen_import_context(snapshot):
            data=importlib.import_module('selftrain.data.diotic_attention')
            scene=importlib.import_module('selftrain.scripts.eval_full_pilot')
            for m,relative in zip((data,scene),CALLBACK_SHAS):
                source=base.safe_file(inspect.getfile(m),'native callback source')
                require(source==snapshot/relative,'CALLBACK_SOURCE_ROOT')
                require(base.sha256_file(source)==CALLBACK_SHAS[relative],'CALLBACK_SOURCE_SHA')
                # Snapshot manifest/import inventory is still a deployment gate.
            # Construct under the verified frozen-import scope, load BEFORE eager unwrap.
            config_record=manifest['inputs'][manifest['models']['formal40']['config_key']]
            config=base._read_yaml(Path(config_record['path']),config_record['sha256'])
            model_module=importlib.import_module('src.spatial_attn_lightning')
            source=base.safe_file(inspect.getfile(model_module),'E2 model module')
            require(source==snapshot/'src/spatial_attn_lightning.py','E2_MODEL_SOURCE')
            relative=str(source.relative_to(snapshot))
            require(base.sha256_file(source)==source_hashes[relative],'E2_MODEL_SOURCE_SHA')
            stage_info=base.pinned_file(Path(stage['path']),'E2 stage',stage['sha256'])
            require(stage_info['size']==stage['size'],'E2_STAGE_SIZE')
            stage_raw,_=base.read_pinned_bytes(Path(stage['path']),'E2 stage',stage['sha256'])
            model,report=load_stage(stage_raw,stage,lambda:model_module.BinauralAttentionModule(config=config))
            del stage_raw
            report['production_provenance_verified']=True
            report['eager_unwrap']=core.unwrap_eager(model)
            arch_type=type(model.model)
            gain_type=type(model.model.model_dict['attn0'])
            for cls in (arch_type,gain_type):
                # strict_load's nested frozen import restores sys.modules; use
                # the function code filename rather than re-resolving its class module.
                source=base.safe_file(inspect.getfile(cls.forward),'architecture source')
                require(source==snapshot/'src/spatial_attn_architecture.py','ARCHITECTURE_SOURCE_PATH')
                require(base.sha256_file(source)==ARCH_SHA,'ARCHITECTURE_SOURCE_SHA')
            model.to(device)
            require(core.runtime_values()==runtime,'LOAD_CHANGED_RUNTIME')
            core.configure_runtime()  # Construction consumed RNG; reset before inference.
            provider=E1Provider(base,bank,hashes,layout,Path(manifest['roots']['clips_dir']),
                         data.WaveformCache,scene._raw_scene_batch,scene._correct_cue_batch,scene._role_batch)
            execution_error=None
            try:
                yield dict(core=core,base=base,outer=model,load_report=report,checkpoint_sha=stage['sha256'],stage_record=dict(stage),
                           architecture_type=arch_type,gain_type=gain_type,batch_provider=provider,device=device)
            except BaseException as error:
                execution_error=error
                raise
            finally:
                try:
                    base.pinned_file(Path(stage['path']),'E2 stage postcheck',stage['sha256'])
                    verify_e1_audio()
                    base.verify_frozen_manifest(manifest,core.V4_ROOT)
                    verify_snapshot(base,snapshot)
                except BaseException as post_error:
                    if execution_error is not None:
                        raise RuntimeError('EXECUTION_AND_POSTCHECK_FAILED: '+repr(execution_error)+'; '+repr(post_error)) from execution_error
                    raise


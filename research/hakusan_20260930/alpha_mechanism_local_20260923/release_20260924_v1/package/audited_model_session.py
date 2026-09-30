"""Allocated-worker loading session candidate, not a CLI or submission tool.

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
from e0_layout_reference import require,canonical
from model_stage_driver import LAYOUT_SHA
from native_batch_provider import NativeBatchProvider

ARCH_SHA='84e68e051f2a2a7a2373aab5c510b72e626aa3b11a9d54f5ec9e35ddbe570eed'
CALLBACK_SHAS={
    'selftrain/data/diotic_attention.py':'26b5cf965aec1652f2d77be517f867bb284a2f53c2f53706b2c5aa2cc0ad9e8a',
    'selftrain/scripts/eval_full_pilot.py':'29414207e3fac53ff8805e61fcf4cee48fb155c4c60d0e736e35526c80dfae5b',
}
SNAPSHOT_SHA='8febb19f3c183333adfc0f7543ba7a017a3c5d4d5ae2132ffa72e701da955dcb'

def verify_snapshot(base,snapshot):
    manifest=base.read_json(snapshot.parent/'manifest.json','snapshot manifest',SNAPSHOT_SHA)
    records=manifest['provenance_files']
    wanted=set()
    for row in records:
        relative=Path(row['path'])
        require(not relative.is_absolute() and '..' not in relative.parts,'SNAPSHOT_RELATIVE_PATH')
        require(str(relative) not in wanted,'SNAPSHOT_DUPLICATE')
        wanted.add(str(relative))
        actual=base.pinned_file(snapshot/relative,'snapshot file',row['sha256'])
        require(actual['size']==row['size'],'SNAPSHOT_SIZE')
    require(not list(snapshot.rglob('*.pyc')),'SNAPSHOT_BYTECODE')
    require({str(p.relative_to(snapshot)) for p in snapshot.rglob('*.py')}==
            {p for p in wanted if p.endswith('.py')},'SNAPSHOT_PYTHON_INVENTORY')
    return dict(manifest_sha256=SNAPSHOT_SHA,files=len(records))

def launch_gate():
    require(sys.platform=='linux' and os.environ.get('SLURM_JOB_ID','').isdigit(),'ALLOCATED_LINUX_REQUIRED')
    require(sys.flags.isolated and sys.dont_write_bytecode,'ISOLATED_WORKER_REQUIRED')
    require(platform.python_version()=='3.11.5' and torch.__version__=='2.1.1+cu118','NATIVE_RUNTIME_REQUIRED')
    require(os.environ.get('CUBLAS_WORKSPACE_CONFIG')==':4096:8','CUBLAS_CONTRACT')
    require(not torch.cuda.is_initialized(),'CUDA_ALREADY_INITIALIZED')

@contextmanager
def audited_session(layout):
    launch_gate()  # Before checkpoint reads or CUDA initialization.
    require(hashlib.sha256(canonical(layout)).hexdigest()==LAYOUT_SHA,'SESSION_LAYOUT')
    core=pinned_core()
    base=core.load_v4(core.V4_ROOT/'tools/locked_same_bank_eval.py')
    manifest,_=base._validate_manifest_hash(core.V4_ROOT/'input_freeze.json',core.MANIFEST_SHA)
    require(manifest['models']['formal40']['sha256']==FORMAL_SHA,'CHECKPOINT_SHA')
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
        with base._frozen_import_context(snapshot):
            data=importlib.import_module('selftrain.data.diotic_attention')
            scene=importlib.import_module('selftrain.scripts.eval_full_pilot')
            for m,relative in zip((data,scene),CALLBACK_SHAS):
                source=base.safe_file(inspect.getfile(m),'native callback source')
                require(source==snapshot/relative,'CALLBACK_SOURCE_ROOT')
                require(base.sha256_file(source)==CALLBACK_SHAS[relative],'CALLBACK_SOURCE_SHA')
                # Snapshot manifest/import inventory is still a deployment gate.
            model,report=base.strict_load_model(manifest,'formal40',device=torch.device('cpu'))
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
            provider=NativeBatchProvider(base,bank,hashes,layout,Path(manifest['roots']['clips_dir']),
                         data.WaveformCache,scene._raw_scene_batch,scene._correct_cue_batch,scene._role_batch)
            execution_error=None
            try:
                yield dict(base=base,outer=model,load_report=report,checkpoint_sha=FORMAL_SHA,
                           architecture_type=arch_type,gain_type=gain_type,batch_provider=provider,device=device)
            except BaseException as error:
                execution_error=error
                raise
            finally:
                try:
                    base.verify_frozen_manifest(manifest,core.V4_ROOT)
                    verify_snapshot(base,snapshot)
                except BaseException as post_error:
                    if execution_error is not None:
                        raise RuntimeError('EXECUTION_AND_POSTCHECK_FAILED: '+repr(execution_error)+'; '+repr(post_error)) from execution_error
                    raise

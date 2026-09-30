"""Stage archive identity/array gates, not a full experiment acceptance."""
import hashlib
import json
from pathlib import Path
import numpy as np
from e1_artifacts import write_json,identity
from e2_catalog import stage_record,validate_record
from e2_matrix import expected_records,verify_stage_arrays

def layout_sha(layout):
    return hashlib.sha256(json.dumps(layout,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def archive_stage(root,layout,rounds,records,load_report,execution_summary,mode='matrix'):
    root=Path(root); root.mkdir(mode=0o700,exist_ok=False)
    checked=verify_stage_arrays(layout,rounds,records,mode)
    stage=stage_record(rounds)
    if load_report.get('checkpoint_sha256')!=stage['sha256'] or load_report.get('completed_epochs')!=rounds:
        raise ValueError('ARCHIVE_STAGE_LOAD_BINDING')
    files=[]
    for index,(key,row) in enumerate(records.items()):
        path=root/f'record-{index:03d}.npz'
        with path.open('xb') as f:
            np.savez(f,trial_ids=np.asarray(row['trial_ids'],dtype=np.int64),logits=row['logits'],nll=row['nll'])
        files.append(dict(name=path.name,key=list(key),**identity(path)))
    metadata=dict(status='E2_STAGE_ARCHIVED_NOT_EXPERIMENT_VERIFIED',stage=stage,
                  layout_sha256=layout_sha(layout),mode=mode,files=files,load_report=load_report,
                  execution=execution_summary,array_check=checked)
    write_json(root/'STAGE.json',metadata)
    return metadata

def verify_stage_archive(root,layout,rounds,mode='matrix'):
    root=Path(root)
    if root.is_symlink() or not root.is_dir(): raise ValueError('ARCHIVE_ROOT')
    path=root/'STAGE.json'
    if path.is_symlink() or not path.is_file(): raise ValueError('ARCHIVE_METADATA')
    metadata=json.loads(path.read_text())
    if metadata.get('mode')!=mode: raise ValueError('ARCHIVE_MODE')
    validate_record(metadata['stage'])
    if metadata['stage']!=stage_record(rounds) or metadata['layout_sha256']!=layout_sha(layout):
        raise ValueError('ARCHIVE_IDENTITY')
    loaded=metadata['load_report']
    if loaded.get('checkpoint_sha256')!=stage_record(rounds)['sha256'] or loaded.get('completed_epochs')!=rounds:
        raise ValueError('ARCHIVE_LOAD_IDENTITY')
    records={}; seen=set()
    for item in metadata['files']:
        name=item['name']
        if not isinstance(name,str) or Path(name).name!=name or not name.endswith('.npz') or name in seen:
            raise ValueError('ARCHIVE_FILE_NAME')
        seen.add(name); path=root/name
        if identity(path)!={'size':item['size'],'sha256':item['sha256']}: raise ValueError('ARCHIVE_SHA')
        key=tuple(item['key'])
        if key in records or key not in expected_records(layout,rounds,mode): raise ValueError('ARCHIVE_KEY')
        with np.load(path,allow_pickle=False) as z:
            if set(z.files)!={'trial_ids','logits','nll'} or z['trial_ids'].dtype!=np.int64 or z['trial_ids'].ndim!=1:
                raise ValueError('ARCHIVE_ARRAY_SCHEMA')
            records[key]=dict(trial_ids=z['trial_ids'].tolist(),logits=z['logits'],nll=z['nll'])
    if {p.name for p in root.iterdir()}!=seen|{'STAGE.json'}: raise ValueError('ARCHIVE_EXTRA_FILE')
    result=verify_stage_arrays(layout,rounds,records,mode)
    return result,records

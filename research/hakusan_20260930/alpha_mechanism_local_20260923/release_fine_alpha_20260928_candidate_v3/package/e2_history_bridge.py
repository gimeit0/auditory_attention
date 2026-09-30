"""Exact-layout formal40 alpha=1 bridge to immutable E1 job 750474."""
import hashlib
import json
from pathlib import Path
import numpy as np
from e1_inputs import build_contract,FORMAL_SHA
from e2_matrix import expected_records
from e0_layout_reference import validate_logits

WORKER_SHA='073755f2d0aba58502c76614971d6e613440f6e13ba5d6b2ea4e418e74557da5'
DEFAULT_ROOT=Path(__file__).resolve().parent/'release_e1_20260927_v3/collected-750474-_rosoog2/state/attempt/A'

def checked(path,sha):
    if path.is_symlink() or not path.is_file(): raise ValueError('BRIDGE_FILE')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=sha: raise ValueError('BRIDGE_SHA')
    return raw

def read_reference(root=None):
    root=DEFAULT_ROOT if root is None else Path(root)
    if root.is_symlink() or not root.is_dir(): raise ValueError('BRIDGE_ROOT')
    metadata=json.loads(checked(root/'WORKER.json',WORKER_SHA))
    if metadata['job_id']!='750474' or metadata['checkpoint_sha256']!=FORMAL_SHA:
        raise ValueError('BRIDGE_IDENTITY')
    layout=build_contract(); expected=expected_records(layout,40); result={}
    for row in metadata['outputs']:
        if row['key'][2]!='alpha_1': continue
        key=('completed_epochs_40',*row['key'][1:])
        if key not in expected or key in result: raise ValueError('BRIDGE_KEYS')
        if Path(row['file']).name!=row['file']: raise ValueError('BRIDGE_PATH')
        raw=checked(root/row['file'],row['sha256'])
        if len(raw)!=row['size']: raise ValueError('BRIDGE_SIZE')
        import io
        with np.load(io.BytesIO(raw),allow_pickle=False) as z:
            ids=z['trial_ids'].tolist(); logits=z['logits']; nll=z['nll']
        if ids!=expected[key]: raise ValueError('BRIDGE_LAYOUT')
        validate_logits(logits,ids,np.array([layout['labels'][str(i)] for i in ids]),nll)
        result[key]=dict(trial_ids=ids,logits=logits,nll=nll)
    if len(result)!=6: raise ValueError('BRIDGE_CONDITIONS')
    return result

def verify_history(records,reference_root=None,*,pilot=False):
    reference=read_reference(reference_root)
    if pilot:
        expected=expected_records(build_contract(),40,'pilot_cold')
        for key,wanted in reference.items():
            indices=[wanted['trial_ids'].index(i) for i in expected[key]]
            reference[key]=dict(trial_ids=expected[key],logits=wanted['logits'][indices],nll=wanted['nll'][indices])
    for key,wanted in reference.items():
        if key not in records: raise ValueError('BRIDGE_MISSING')
        actual=records[key]
        if actual['trial_ids']!=wanted['trial_ids']: raise ValueError('BRIDGE_TRIALS')
        for name in ('logits','nll'):
            a=actual[name]; b=wanted[name]
            if a.dtype!=b.dtype or a.shape!=b.shape or a.tobytes()!=b.tobytes():
                raise ValueError('BRIDGE_BITS: '+repr((key,name)))
    return dict(status='E2_FORMAL40_ALPHA1_HISTORY_BITS_PASS',reference_job='750474',
                reference_worker_sha256=WORKER_SHA,conditions=6,
                predictions=sum(len(v['trial_ids']) for v in reference.values()),
                scope='fixed_original_batches' if pilot else 'full_e1_layout')

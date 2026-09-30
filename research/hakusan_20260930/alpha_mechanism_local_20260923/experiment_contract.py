"""Offline synthetic contract/output binding; not a production RUN authorizer."""
import hashlib
import json
import re
import torch
from alpha_gain import validate_alpha
from architecture_adapter import MODES, NAMES

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
                                     allow_nan=False).encode()).hexdigest()

def contract(*, alpha, mode, source_sha256, config_sha256, layout_sha256,
             synthetic_state_sha256, torch_version):
    if mode not in MODES:
        raise ValueError('MODE')
    identities=dict(source_sha256=source_sha256,config_sha256=config_sha256,
                    layout_sha256=layout_sha256,synthetic_state_sha256=synthetic_state_sha256)
    if any(not isinstance(v,str) or re.fullmatch('[0-9a-f]{64}',v) is None for v in identities.values()):
        raise ValueError('SHA256')
    if not isinstance(torch_version,str) or not torch_version:
        raise ValueError('RUNTIME')
    paths=NAMES[:-1] if mode=='conv_only' else NAMES
    return dict(schema_version=1,scope='LOCAL_SYNTHETIC_ONLY',production_authorized=False,
                alpha=validate_alpha(alpha),mode=mode,identities=identities,
                runtime={'torch':torch_version,'device':'cpu','backend':'eager'},
                paths=['model_dict.'+n for n in paths],formula_version='alpha_controls_v1',
                mean_denominator_abs_min=1e-8)

def validate(c):
    if not isinstance(c,dict): raise ValueError('CONTRACT')
    try:
        rebuilt=contract(alpha=c['alpha'],mode=c['mode'],**c['identities'],
                         torch_version=c['runtime']['torch'])
    except (KeyError,TypeError) as error:
        raise ValueError('CONTRACT_SCHEMA') from error
    if digest(c)!=digest(rebuilt): raise ValueError('CONTRACT_SCHEMA')

def trial_order(ids):
    if not isinstance(ids,list) or not ids or any(type(i) is not int or i<0 for i in ids):
        raise ValueError('TRIAL_IDS')
    if len(set(ids))!=len(ids): raise ValueError('DUPLICATE_TRIAL')

def logits_identity(logits, ids):
    trial_order(ids)
    if (not isinstance(logits,torch.Tensor) or logits.device.type!='cpu'
        or logits.dtype not in (torch.float32,torch.float64) or logits.ndim!=2
        or logits.shape[0]!=len(ids) or logits.shape[1]<2 or not torch.isfinite(logits).all()):
        raise ValueError('LOGITS')
    array=logits.detach().contiguous().numpy()
    return dict(shape=list(logits.shape),dtype=str(logits.dtype),
                sha256=hashlib.sha256(array.tobytes()).hexdigest())

def bind(c, ids, logits):
    validate(c)
    result=dict(contract_sha256=digest(c),trial_ids=list(ids),
                logits=logits_identity(logits,ids))
    result['record_sha256']=digest(result)
    return result

def verify(record, expected_contract, expected_trial_ids, logits):
    # Independent expected contract/order must come from the caller, not this record.
    if digest(record)!=digest(bind(expected_contract,expected_trial_ids,logits)):
        raise ValueError('OUTPUT_BINDING_MISMATCH')
    return 'LOCAL_OUTPUT_BINDING_PASS'

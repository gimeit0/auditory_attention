"""Candidate seam for an already strict-loaded model; no checkpoint loading.

Reuses the SHA-pinned historical predict/unwrap/state routines without edits.
Caller still owns frozen imports, manifest verification, runtime, allocation and
artifact gates. Synthetic tests of this seam are NOT production authorization.
"""
from contextlib import contextmanager, nullcontext
import hashlib
import importlib.util
from pathlib import Path
from torch import nn
from architecture_adapter import intervention, validated_gains

CORE_SHA='09cb0c4816d001d172215ead49a1a0c9efde07b794125da4980dd822883a4d5b'
FORMAL_SHA='2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff'
PASS_MAP={'alpha_0':(0,'alpha'),'alpha_1':(1,'alpha'),
          'alpha_025':(.25,'alpha'),'alpha_05':(.5,'alpha'),'alpha_075':(.75,'alpha'),
          'uniform_05':(.5,'uniform'),'conv_only_05':(.5,'conv_only'),
          'fc_mean_preserved_05':(.5,'fc_mean_preserved')}

def pinned_core():
    here=Path(__file__).resolve().parent
    path=here/'eager_compare.py'
    if not path.exists():
        path=here.parent/'same_bank_compare_2026_09_19_full_v3/eager_compare.py'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=CORE_SHA:
        raise ValueError('CORE_SOURCE_CHANGED')
    spec=importlib.util.spec_from_file_location('e0_pinned_eager_core',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class BypassGain(nn.Module):
    """Independent endpoint: never evaluates alpha, sigmoid, cue or gain formula."""
    def __init__(self, original):
        super().__init__()
        self.bias,self.slope,self.threshold=original.bias,original.slope,original.threshold
        self.train(original.training)

    def forward(self,cue,mixture,cue_mask_ixs=None):
        return mixture

@contextmanager
def explicit_bypass(model,architecture_type,gain_type):
    originals=validated_gains(model,architecture_type,gain_type)
    replacements={name:BypassGain(value) for name,value in originals.items()}
    try:
        for name,value in replacements.items(): model.model_dict[name]=value
        yield
    finally:
        for name,value in originals.items(): model.model_dict[name]=value

def accept_loaded_formal40(core,model,report,model_id,checkpoint_sha,architecture_type,gain_type):
    """Checks supplied load metadata; does not prove checkpoint file provenance."""
    if model_id!='formal40' or checkpoint_sha!=FORMAL_SHA:
        raise ValueError('MODEL_IDENTITY')
    count=sum(p.numel() for p in model.parameters())
    if (report.get('loaded_trainable_numel_ratio')!=1.0 or count<=0
        or report.get('trainable_numel')!=count or report.get('loaded_trainable_numel')!=count
        or report.get('native_preprocessing')!='selftrain_singleton_per_example_leveling'):
        raise ValueError('STRICT_LOAD_REPORT')
    unwrap=core.unwrap_eager(model)
    validated_gains(model.model,architecture_type,gain_type)
    return dict(model_id=model_id,checkpoint_sha256=checkpoint_sha,eager_unwrap=unwrap,
                production_provenance_verified=False)

@contextmanager
def pass_context(core,outer,architecture_type,gain_type,name):
    if name not in PASS_MAP and name not in ('original','explicit_bypass'):
        raise ValueError('UNSUPPORTED_PASS')
    validated_gains(outer.model,architecture_type,gain_type)
    before=core.state_digest(outer)
    rng=core.rng_digest()
    runtime=core.runtime_values()
    context=(nullcontext() if name=='original' else
             explicit_bypass(outer.model,architecture_type,gain_type) if name=='explicit_bypass' else
             intervention(outer.model,architecture_type,gain_type,*PASS_MAP[name]))
    with context:
        if core.state_digest(outer)!=before: raise ValueError('INSTALL_CHANGED_STATE')
        yield
    if core.state_digest(outer)!=before: raise ValueError('STATE_CHANGED')
    if core.rng_digest()!=rng: raise ValueError('RNG_CHANGED')
    if core.runtime_values()!=runtime: raise ValueError('RUNTIME_CHANGED')

def predict_loaded_pass(core,base,outer,architecture_type,gain_type,name,scene,cue,labels,probes,device):
    # No rewritten preprocessing or logits path: call exactly the pinned function.
    # Future coordinator should use pass_context once around the whole pass rather
    # than paying full state-hash cost for each batch.
    with pass_context(core,outer,architecture_type,gain_type,name):
        return core.predict(base,outer,scene,cue,labels,probes,device)

"""Temporary eager-only intervention on an explicitly pinned word architecture.

No global patch; reuses Parameter identities and restores original modules on exit.
Not concurrency-safe; do not compile, train or change architecture inside context.
"""
from contextlib import contextmanager
import torch
from torch import nn
from alpha_gain import validate_alpha

NAMES = tuple('attn'+str(i) for i in range(7)) + ('attnfc',)
MODES = ('alpha','uniform','conv_only','fc_mean_preserved')

class InterventionGain(nn.Module):
    def __init__(self, original, alpha, mode):
        super().__init__()
        object.__setattr__(self,'_original',original)
        self.bias,self.slope,self.threshold=original.bias,original.slope,original.threshold
        self.time_dim=original.time_dim
        self.alpha,self.mode=validate_alpha(alpha),mode
        self.train(original.training)

    def forward(self,cue,mixture,cue_mask_ixs=None):
        a=validate_alpha(self.alpha)
        if self.mode not in ('alpha','uniform','mean_preserved'):
            raise ValueError('INVALID_GAIN_MODE')
        if self.mode != 'uniform' and a == 1:
            return self._original(cue,mixture,cue_mask_ixs)
        if self.mode == 'alpha' and a == 0:
            return mixture
        cue=(cue.mean(axis=self.time_dim,keepdim=True)-self.threshold)*self.slope
        g=self.bias+(1-self.bias)*torch.sigmoid(cue)
        effective=g if a==1 else 1-a*(1-g)
        dims=tuple(range(1,g.ndim))
        if self.mode=='uniform':
            effective=effective.mean(dims,keepdim=True).expand_as(g)
        elif self.mode=='mean_preserved':
            denom=effective.mean(dims,keepdim=True)
            if not torch.isfinite(denom).all() or (denom.abs()<=1e-8).any():
                raise ValueError('MEAN_GAIN_DENOMINATOR')
            effective=effective*(g.mean(dims,keepdim=True)/denom)
        if not torch.isfinite(effective).all():
            raise ValueError('NONFINITE_GAIN')
        if cue_mask_ixs is not None:
            effective=effective.clone()
            effective[cue_mask_ixs,:]=1
        return mixture*effective

def validated_gains(model, architecture_type, gain_type):
    if type(model) is not architecture_type:
        raise ValueError('UNSUPPORTED_ARCHITECTURE')
    if any(m.training for m in model.modules()) or any(p.requires_grad for p in model.parameters()):
        raise ValueError('FROZEN_EVAL_REQUIRED')
    if model.residual_attn or model.cue_loc_task or model.dual_task or model.per_kernel_gain:
        raise ValueError('UNSUPPORTED_CUE_OR_RESIDUAL_PATH')
    if model.n_layers!=7 or list(model.attn)!=[1]*7 or not model.v08 or not model.fc_attn:
        raise ValueError('UNSUPPORTED_LAYOUT')
    if 'forward' in model.__dict__:
        raise ValueError('INSTANCE_FORWARD_OVERRIDE')
    modules=list(model.named_modules(remove_duplicate=False))
    if len({id(m) for _,m in modules}) != len(modules):
        raise ValueError('ALIASED_MODULE')
    if any(m._forward_hooks or m._forward_pre_hooks or m._backward_hooks or 'forward' in m.__dict__ for _,m in modules):
        raise ValueError('HOOK_OR_FORWARD_OVERRIDE')
    actual={name for name,m in modules if isinstance(m,gain_type)}
    if actual != {'model_dict.'+n for n in NAMES}:
        raise ValueError('GAIN_PATH_MISMATCH')
    originals={n:model.model_dict[n] for n in NAMES}
    if any(type(m) is not gain_type or m.additive or m.time_dim!=-1 for m in originals.values()):
        raise ValueError('UNSUPPORTED_GAIN')
    return originals

@contextmanager
def intervention(model, architecture_type, gain_type, alpha, mode='alpha'):
    a=validate_alpha(alpha)
    if mode not in MODES:
        raise ValueError('UNSUPPORTED_MODE')
    originals=validated_gains(model,architecture_type,gain_type)
    replacements={}
    for name,original in originals.items():
        if mode=='conv_only' and name=='attnfc':
            continue
        local_mode='uniform' if mode=='uniform' else 'mean_preserved' if mode=='fc_mean_preserved' and name=='attnfc' else 'alpha'
        replacements[name]=InterventionGain(original,a,local_mode)
    contract={'alpha':a,'mode':mode,'replaced_paths':['model_dict.'+n for n in replacements],
              'scope':'LOCAL_EAGER_FROZEN_WORD_ARCHITECTURE','production_validated':False}
    try:
        for name,replacement in replacements.items(): model.model_dict[name]=replacement
        yield contract
    finally:
        for name,original in originals.items(): model.model_dict[name]=original

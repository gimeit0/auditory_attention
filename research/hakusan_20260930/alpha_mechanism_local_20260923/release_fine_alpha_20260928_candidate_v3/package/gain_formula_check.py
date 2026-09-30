"""G5 fixed-feature checks: independent NumPy float64 reference, no RNG.

Calls installed gain modules only; no checkpoint/audio loading or model forward.
The proposed tolerances are fixed here, never inferred from observed errors.
"""
import numpy as np
import torch
from architecture_adapter import NAMES

ATOL=2e-6
RTOL=2e-6

def reference(cue, mixture, bias, slope, threshold, alpha, mode, mask):
    x=(cue.astype(np.float64).mean(axis=-1,keepdims=True)-threshold)*slope
    sigmoid=np.exp(-np.logaddexp(0.,-x))
    gain=bias+(1.-bias)*sigmoid
    effective=(1.-alpha)+alpha*gain
    if mode=='uniform': effective=np.broadcast_to(effective.mean((1,2,3),keepdims=True),gain.shape).copy()
    if mode=='mean_preserved':
        denominator=effective.mean((1,2,3),keepdims=True)
        if not np.isfinite(denominator).all() or (np.abs(denominator)<=1e-8).any():
            raise ValueError('E0_CONTROL_UNDEFINED')
        effective=effective*(gain.mean((1,2,3),keepdims=True)/denominator)
    effective=effective.copy()
    if mask is not None: effective[mask]=1.
    return mixture.astype(np.float64)*effective, effective

def check_installed_gains(model,pass_name):
    """Fixed two-example features with nonuniform channels/frequency/time.

    Ones mixture exposes effective gain directly, including means and mask rows.
    Scalar gain parameters are the only supported pinned architecture contract.
    """
    config={'original':(1.,'alpha'),'alpha_1':(1.,'alpha'),
            'explicit_bypass':(0.,'alpha'),'alpha_0':(0.,'alpha'),
            'alpha_025':(.25,'alpha'),'alpha_05':(.5,'alpha'),
            'alpha_075':(.75,'alpha'),'alpha_875':(.875,'alpha'),'uniform_05':(.5,'uniform'),
            'conv_only_05':(.5,'conv_only'),'fc_mean_preserved_05':(.5,'fc')}
    if pass_name not in config: raise ValueError('G5_PASS')
    alpha,mode=config[pass_name]
    rows=[]
    with torch.inference_mode():
        for name in NAMES:
            module=model.model_dict[name]
            parameters=[getattr(module,p) for p in ('bias','slope','threshold')]
            if any(p.numel()!=1 or p.dtype!=torch.float32 or not torch.isfinite(p).all() for p in parameters):
                raise ValueError('G5_PARAMETER_CONTRACT')
            a=1. if mode=='conv_only' and name=='attnfc' else alpha
            local_mode='uniform' if mode=='uniform' else 'mean_preserved' if mode=='fc' and name=='attnfc' else 'alpha'
            cue=np.linspace(-3.,4.,60,dtype=np.float32).reshape(2,2,3,5)
            for mixture_kind in ('ones','signed'):
                mix=np.ones_like(cue) if mixture_kind=='ones' else np.linspace(-2.,2.,60,dtype=np.float32).reshape(cue.shape)
                for masked in (False,True):
                    mask=np.array([False,True]) if masked else None
                    expected,effective=reference(cue,mix,*[float(p) for p in parameters],a,local_mode,mask)
                    tcue=torch.tensor(cue,device=parameters[0].device)
                    tmix=torch.tensor(mix,device=parameters[0].device)
                    actual=module(tcue,tmix,None if mask is None else torch.tensor(mask,device=tcue.device))
                    actual=actual.detach().cpu().numpy()
                    if actual.shape!=expected.shape or actual.dtype!=np.float32 or not np.isfinite(actual).all():
                        raise ValueError('G5_OUTPUT_CONTRACT')
                    error=np.abs(actual.astype(np.float64)-expected)
                    if not np.all(error<=ATOL+RTOL*np.abs(expected)):
                        raise ValueError('G5_FORMULA_MISMATCH: '+name+'/'+pass_name)
                    mean_error=float(np.max(np.abs(actual.mean((1,2,3),dtype=np.float64)-expected.mean((1,2,3)))))
                    if not np.allclose(actual.mean((1,2,3),dtype=np.float64),expected.mean((1,2,3)),atol=ATOL,rtol=RTOL):
                        raise ValueError('G5_MEAN_MISMATCH')
                    if masked and not np.array_equal(actual[1],mix[1]): raise ValueError('G5_MASK_IDENTITY')
                    rows.append(dict(path='model_dict.'+name,mixture=mixture_kind,masked=masked,
                                     max_abs=float(error.max()),mean_max_abs=mean_error))
    return dict(status='G5_FIXED_FEATURE_PASS',pass_name=pass_name,atol=ATOL,rtol=RTOL,
                reference='numpy_float64_independent',checks=rows,production_verified=False)

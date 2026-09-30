"""Explicit fine-grid adapter. No mutation of legacy pass maps or hooks."""
from contextlib import contextmanager
import numpy as np
import torch
from architecture_adapter import intervention, validated_gains, NAMES
from loaded_model_adapter import pass_context
from gain_formula_check import reference, check_installed_gains, ATOL, RTOL
from fine_alpha_contract import decode

@contextmanager
def context(core, outer, architecture_type, gain_type, pass_name):
    if pass_name in ('original', 'reference', 'explicit_bypass'):
        with pass_context(core, outer, architecture_type, gain_type,
                          'alpha_1' if pass_name == 'reference' else pass_name):
            yield
        return
    alpha = decode(pass_name)
    validated_gains(outer.model, architecture_type, gain_type)
    before = core.state_digest(outer), core.rng_digest(), core.runtime_values()
    try:
        with intervention(outer.model, architecture_type, gain_type, alpha):
            if core.state_digest(outer) != before[0]:
                raise ValueError('FINE_PARAMETER_CHANGED_ON_INSTALL')
            yield
    finally:
        after = core.state_digest(outer), core.rng_digest(), core.runtime_values()
        if after != before:
            raise ValueError('FINE_STATE_RNG_RUNTIME_CHANGED')

def check_formula(model, pass_name):
    if pass_name in ('original', 'reference', 'explicit_bypass'):
        report = check_installed_gains(model, 'alpha_1' if pass_name == 'reference' else pass_name)
        return dict(report, pass_name=pass_name)
    alpha = decode(pass_name)
    rows = []
    cue = np.linspace(-3., 4., 60, dtype=np.float32).reshape(2, 2, 3, 5)
    with torch.inference_mode():
        for path in NAMES:
            module = model.model_dict[path]
            params = [getattr(module, k) for k in ('bias', 'slope', 'threshold')]
            if any(p.numel() != 1 or p.dtype != torch.float32 or not torch.isfinite(p).all() for p in params):
                raise ValueError('G5_PARAMETER_CONTRACT')
            for kind in ('ones', 'signed'):
                mix = np.ones_like(cue) if kind == 'ones' else np.linspace(-2., 2., 60, dtype=np.float32).reshape(cue.shape)
                for masked in (False, True):
                    mask = np.array([False, True]) if masked else None
                    expected, _ = reference(cue, mix, *[float(p) for p in params], alpha, 'alpha', mask)
                    device = params[0].device
                    actual = module(torch.tensor(cue, device=device), torch.tensor(mix, device=device),
                                    None if mask is None else torch.tensor(mask, device=device)).detach().cpu().numpy()
                    if actual.shape != expected.shape or actual.dtype != np.float32 or not np.isfinite(actual).all():
                        raise ValueError('G5_OUTPUT_CONTRACT')
                    error = np.abs(actual.astype(np.float64) - expected)
                    if not np.all(error <= ATOL + RTOL*np.abs(expected)):
                        raise ValueError('G5_FORMULA_MISMATCH: ' + path + '/' + pass_name)
                    delta = np.abs(actual.mean((1, 2, 3), dtype=np.float64) - expected.mean((1, 2, 3)))
                    if not np.allclose(actual.mean((1, 2, 3), dtype=np.float64), expected.mean((1, 2, 3)), atol=ATOL, rtol=RTOL):
                        raise ValueError('G5_MEAN_MISMATCH')
                    if masked and not np.array_equal(actual[1], mix[1]):
                        raise ValueError('G5_MASK_IDENTITY')
                    rows.append(dict(path='model_dict.'+path, mixture=kind, masked=masked,
                                     max_abs=float(error.max()), mean_max_abs=float(delta.max())))
    return dict(status='G5_FIXED_FEATURE_PASS', pass_name=pass_name, atol=ATOL, rtol=RTOL,
                reference='numpy_float64_independent', checks=rows, production_verified=False)

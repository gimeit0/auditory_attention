"""CPU-testable gain candidate. Not a production evaluator or GPU release.

Original gain class is AST-loaded only after exact source identity verification.
No edits to the original architecture, no hooks or global monkey-patching.
"""
import ast
import hashlib
import math
from pathlib import Path
import torch
from torch import nn

SOURCE_SHA = '84e68e051f2a2a7a2373aab5c510b72e626aa3b11a9d54f5ec9e35ddbe570eed'

def original_gain_class(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError('ARCHITECTURE_SHA_MISMATCH')
    nodes = [n for n in ast.parse(raw).body if isinstance(n, ast.ClassDef) and n.name == 'SimpleAttentionalGain']
    if len(nodes) != 1:
        raise ValueError('GAIN_CLASS_MISSING')
    scope = {'torch': torch, 'nn': nn}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<pinned-gain>', 'exec'), scope)
    return scope['SimpleAttentionalGain']

def validate_alpha(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('ALPHA_MUST_BE_FIXED_SCALAR')
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('ALPHA_OUT_OF_RANGE')
    return value

def alpha_gain_class(original):
    class AlphaGain(original):
        def __init__(self, *args, alpha=1.0, **kwargs):
            super().__init__(*args, **kwargs)
            if self.additive:
                raise ValueError('ADDITIVE_GAIN_UNSUPPORTED')
            self.alpha = validate_alpha(alpha)

        def forward(self, cue, mixture, cue_mask_ixs=None):
            alpha = validate_alpha(self.alpha)
            if self.additive:
                raise ValueError('ADDITIVE_GAIN_UNSUPPORTED')
            if alpha == 1.0:
                # Preserve the arithmetic and original mask behavior exactly.
                return super().forward(cue, mixture, cue_mask_ixs)
            if alpha == 0.0:
                # Explicit bypass. No cue or gain-parameter computation.
                return mixture
            cue = cue.mean(axis=self.time_dim, keepdim=True)
            cue = cue - self.threshold
            cue = cue * self.slope
            gain = self.bias + (1-self.bias) * torch.sigmoid(cue)
            effective = 1 - alpha * (1 - gain)
            if cue_mask_ixs is not None:
                effective = effective.clone()
                effective[cue_mask_ixs, :] = 1
            return torch.mul(mixture, effective)
    return AlphaGain

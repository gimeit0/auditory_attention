"""Isolated definitions from hash-pinned files; no project imports or checkpoints."""
import ast
import hashlib
import math
from pathlib import Path
from types import SimpleNamespace
from typing import List, Tuple, Optional
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from alpha_gain import SOURCE_SHA

def definitions(path, sha, scope, names=None):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError('SOURCE_SHA_MISMATCH: ' + str(path))
    nodes = [n for n in ast.parse(raw).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
             and (names is None or n.name in names)]
    if names is not None and {n.name for n in nodes} != set(names):
        raise ValueError('MISSING_DEFINITION')
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),scope)
    return scope

def load(project):
    src = Path(project) / 'src'
    base = dict(torch=torch, ch=torch, nn=nn, np=np, F=F, math=math, List=List, Tuple=Tuple, Optional=Optional)
    pad = definitions(src/'layers/padding.py','4fbca19c54a30696c4dc8b27314e58ca2cc3c451ab8a9192dadea4eb07302213',dict(base))
    conv = definitions(src/'layers/conv2d_same.py','826e2882b489157c578af68241303526079a529cd6d1dc04c1961b5a7e9cab1f',dict(base,pad_same=pad['pad_same'],get_padding_value=pad['get_padding_value']))
    pool = definitions(src/'custom_modules.py','98f0d393ee7a1a5fe1a8a8bd1302b0d6b574a4ef846946e30cf176adf860adad',dict(base),{'HannPooling2d'})
    scope = dict(base,conv2d_same=SimpleNamespace(create_conv2d_pad=conv['create_conv2d_pad']),
                 pad_utils=SimpleNamespace(get_padding_value=pad['get_padding_value']),HannPooling2d=pool['HannPooling2d'])
    definitions(src/'spatial_attn_architecture.py',SOURCE_SHA,scope,{'SimpleAttentionalGain','BinauralAuditoryAttentionCNN'})
    return scope['BinauralAuditoryAttentionCNN'],scope['SimpleAttentionalGain']

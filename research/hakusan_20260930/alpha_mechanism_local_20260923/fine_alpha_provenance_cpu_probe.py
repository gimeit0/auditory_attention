"""In-memory CPU type regression using exact selected candidate function ASTs.

No sibling imports, files written, checkpoint load, model forward, or scheduler.
This is deliberately NOT a production/A100 validation or a whole-package import.
"""
import ast
import hashlib
import json
import os
import platform
import sys
from unittest.mock import patch


def select(source, names):
    tree = ast.parse(source)
    selected = []
    found = set()
    for node in tree.body:
        name = node.name if isinstance(node, ast.FunctionDef) else (
            node.targets[0].id if isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name) else None)
        if name in names:
            if name in found: raise ValueError('DUPLICATE_PROBE_DEFINITION')
            found.add(name); selected.append(node)
    if found != set(names): raise ValueError('MISSING_PROBE_DEFINITION')
    return ast.Module(body=selected, type_ignores=[])


def probe(payload):
    import torch
    if torch.cuda.is_initialized(): raise ValueError('PROBE_CUDA_ALREADY_INITIALIZED')
    specs = {
        'e0_layout_reference.py': ('require',),
        'e1_execution.py': ('ENVIRONMENT_KEYS',),
        'e1_worker_archive.py': ('environment_record', 'verify_environment'),
    }
    # No model/evaluator imports: only the exact environment schema/functions.
    if set(payload['sources']) != set(specs): raise ValueError('PROBE_SOURCE_SET')
    namespace = dict(torch=torch, os=os, platform=platform)
    identities = {}
    for name, definitions in specs.items():
        row = payload['sources'][name]; source = row['source']; raw = source.encode()
        identity = dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        if identity != row['identity']: raise ValueError('PROBE_SOURCE_SHA')
        identities[name] = identity
        exec(compile(select(source, definitions), '<candidate:'+name+'>', 'exec'), namespace)
    version_type = type(torch.__version__).__module__+'.'+type(torch.__version__).__qualname__
    with patch.object(torch.cuda, 'is_available', return_value=False):
        env = namespace['environment_record']()
    if type(env['torch']) is not str or env['torch'] != str(torch.__version__):
        raise ValueError('VERSION_NOT_NORMALIZED')
    # Check the live object BEFORE serialization; this is where 753729 failed.
    namespace['verify_environment'](dict(environment=env), production=False)
    namespace['verify_environment'](dict(environment=json.loads(json.dumps(env))), production=False)
    for bad in (None, 211, True, []):
        with patch.object(torch, '__version__', bad), patch.object(torch.cuda, 'is_available', return_value=False):
            try: namespace['environment_record']()
            except ValueError as error:
                if str(error) != 'PROVENANCE_TORCH_VERSION': raise
            else: raise ValueError('INVALID_VERSION_ACCEPTED')
    try: namespace['verify_environment'](dict(environment=env), production=True)
    except ValueError as error:
        if str(error) != 'PROVENANCE_PRODUCTION_ENVIRONMENT': raise
    else: raise ValueError('CPU_PROBE_FALSE_PRODUCTION_PASS')
    if torch.cuda.is_initialized(): raise ValueError('PROBE_INITIALIZED_CUDA')
    return dict(status='FINE_ALPHA_PROVENANCE_CPU_TYPE_CHECK_PASS', release_sha256=payload['release_sha256'],
                python=platform.python_version(), torch=str(torch.__version__), raw_version_type=version_type,
                recorded_version_type=type(env['torch']).__name__, source_identities=identities,
                live_object_verified=True, json_roundtrip_verified=True, invalid_versions_rejected=4,
                cpu_cannot_pass_production=True, cuda_initialized=False, production_checkpoint_loaded=False,
                jobs_submitted=0, remote_source_files_written=False, production_validated=False,
                scope='selected candidate environment functions only; not whole-worker/A100 validation')


if __name__ == '__main__':
    print(json.dumps(probe(json.load(sys.stdin)), sort_keys=True))

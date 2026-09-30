"""Bounded, reversible G2 preparation derivation. No remote or scheduler actions."""
import ast
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import profiles

PARENT = ROOT / 'same_bank_eval_2026_09_03_v4_numeric_diag_v19'
PARENT_SHA = 'c1ba3af9da8fb2be6e197fddbee38a03c0ef3a8f67da75e7abc0b1a9f568b50d'
TRACE_SHA = 'fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b'
MODEL = Path('/Users/gigi/projects/auditory_attention/src/spatial_attn_lightning.py')
MODEL_SHA = '6531a6548cc24dcdcffdb14c8b6b1d7040bc6f1f7ea53dd870d4d021327467c9'
EVALUATOR = ROOT / 'same_bank_eval_2026_08_29_v4/locked_same_bank_eval.py'
EVALUATOR_SHA = '31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, expected=None):
    require(path.is_file() and path.stat().st_size < 2 * 1024**2
            and not any(p.is_symlink() for p in (path, *path.parents)), 'bounded nonsymlink source required')
    raw = path.read_bytes()
    require(expected is None or sha(raw) == expected, 'source SHA differs: ' + str(path))
    return raw


def wire(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def source_audit():
    model = read(MODEL, MODEL_SHA).decode()
    evaluator = read(EVALUATOR, EVALUATOR_SHA).decode()
    m = ast.parse(model)
    calls = [n for n in ast.walk(m) if isinstance(n, ast.Call) and ast.unparse(n.func) == 'torch.compile']
    require(len(calls) == 1 and ast.unparse(calls[0]) == "torch.compile(self.model, mode='default')", 'constructor compile target changed')
    require('allow_compile_wrapper_rewrite=(model_id == "author_external")' in evaluator, 'strict loader mapping policy differs')
    cls = next(n for n in m.body if isinstance(n, ast.ClassDef) and n.name == 'BinauralAttentionModule')
    forward = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'forward')
    require(ast.unparse(forward.body[0]) == 'outputs = self.model(cue, scene, cue_mask_ixs)', 'forward target changed')
    return dict(model_sha256=MODEL_SHA, evaluator_sha256=EVALUATOR_SHA, parent_sha256=PARENT_SHA,
                compile_target='BinauralAttentionModule.model', original_target='model._orig_mod',
                strict_formal40_prefix_policy='exact; only author_external permits rewrite',
                adaptation_order=['frozen_runtime_configuration', 'profile_precision', 'unchanged_strict_load',
                                  'profile_dispatch_binding', 'new_inventory_and_attestation', 'first_forward'],
                production_ready=False, jobs_submitted=0)


def derive(name):
    profile = profiles.profile(name)
    source_audit()
    original = read(PARENT / 'diagnose_batch_invariance.py', PARENT_SHA).decode()
    helper = read(HERE / 'adapter.py').decode()
    require('_g2_' not in original and '_G2_PROFILE' not in original, 'new namespace collides')
    tree = ast.parse(original)
    runtime_node = next(n for n in tree.body if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == '_FROZEN_NUMERIC_RUNTIME' for t in n.targets))
    old_runtime = ast.get_source_segment(original, runtime_node)
    changes = [
        ('DIAGNOSTIC_PROTOCOL = "formal40_batch_invariance_diag_20260903_v19"',
         'DIAGNOSTIC_PROTOCOL = ' + repr(profile.document()['protocol']) + '\n_G2_PROFILE = ' + repr(name)),
        ('"/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v19"',
         repr('/home/s2510040/audattn_external_eval_diag/formal40_numeric_profiles_20260916_v1/' + name)),
        (old_runtime, '_FROZEN_NUMERIC_RUNTIME = types.MappingProxyType(' + repr(profile.runtime()) + ')'),
        ('    try:\n        device = evaluator._configure_runtime(allow_cpu)',
         '    _g2_before_configuration(torch, capability.trust_domain)\n    try:\n        device = evaluator._configure_runtime(allow_cpu)\n        _g2_apply_runtime(torch, _G2_PROFILE)'),
        ('    _require_load_report(report)\n    model_module_inventory = _direct_model_module_inventory(model)',
         '    _require_load_report(report)\n    report = {**report, "g2_adaptation": _g2_adapt_loaded_model(\n        model, report, _G2_PROFILE, capability.trust_domain)}\n    model_module_inventory = _direct_model_module_inventory(model)'),
        ('def main(argv: Sequence[str] | None = None) -> int:\n',
         'def main(argv: Sequence[str] | None = None) -> int:\n    raise DiagnosticError("G2 preparation candidate only: no freeze, worker, or scheduler CLI is released")\n'),
        ('\n\nif __name__ == "__main__":\n', '\n\n# Embedded SHA-bound G2 preparation helpers; new source identity.\n' + helper + '\n\nif __name__ == "__main__":\n'),
    ]
    source = original
    for before, after in changes:
        require(source.count(before) == 1, 'derivation anchor not unique: ' + before[:70])
        source = source.replace(before, after, 1)
    restored = source
    for before, after in reversed(changes):
        require(restored.count(after) == 1, 'reverse anchor differs')
        restored = restored.replace(after, before, 1)
    require(restored == original, 'parent source not restored exactly')
    before_defs = {n.name: ast.dump(n, include_attributes=False) for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    after_defs = {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(source).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    unchanged = sorted(set(before_defs) - {'prepare_formal40_worker', 'main'})
    require(all(before_defs[n] == after_defs[n] for n in unchanged), 'non-preparation inference/guard AST changed')
    recipe = dict(profile=profile.document(), parent_sha256=PARENT_SHA, adapter_sha256=sha(helper.encode()),
                  candidate_sha256=sha(source.encode()), exact_parent_restoration=True,
                  unchanged_top_level_definitions=unchanged, unchanged_definition_count=len(unchanged),
                  changes=[dict(before_sha256=sha(a.encode()), after_sha256=sha(b.encode())) for a, b in changes],
                  production_ready=False, cli_released=False)
    return source.encode(), recipe


def materialize(root, name):
    raw, recipe = derive(name)
    root.mkdir(mode=0o700, exist_ok=False)
    files = {'diagnose_batch_invariance.py': raw, 'numeric_trace.py': read(PARENT / 'numeric_trace.py', TRACE_SHA),
             'RECIPE.json': wire(recipe)}
    for filename, data in files.items():
        with (root / filename).open('xb') as stream:
            stream.write(data)
    return recipe


if __name__ == '__main__':
    print(json.dumps(dict(source_audit=source_audit(), candidates={name: derive(name)[1] for name in profiles.ORDER}), sort_keys=True))

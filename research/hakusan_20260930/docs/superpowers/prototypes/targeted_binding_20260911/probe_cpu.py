"""Frozen formal40 CPU loading/binding probe; no scientific forward or GPU job.

Uses the unchanged v18 verified source loader and v4 strict checkpoint loader.
This is NOT prepare_formal40_worker / production CUDA capability issuance.
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys


V4 = Path('/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4')
V18 = Path('/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v18')
FREEZE_SHA = 'bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178'
PLAN_SHA = '727dce6b20292d9eaf61807b80b79cf95080c182916b529d8684ef0598aa70e8'
DIAG_SHA = '7ba4d1f143fd1b957639588b209600377d745bf34e1207768cdd577e3f1d5a7b'
STATE_SHA = '018ff20279396599cef17f54550bc758d1a75a9726d35f74319573ea098c292c'
LOCK_SHA = '63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def pinned(path, sha, limit=2 * 1024 * 1024):
    """Owned regular no-follow files, exact bytes; no writes to frozen inputs."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                and before.st_size <= limit, 'pinned file type/owner/size differs')
        with os.fdopen(os.dup(descriptor), 'rb') as source:
            raw = source.read(limit + 1)
        after = os.fstat(descriptor)
        def identity(s):
            return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_size,
                    s.st_mtime_ns, s.st_ctime_ns)
        require(identity(before) == identity(after) and len(raw) == before.st_size
                and hashlib.sha256(raw).hexdigest() == sha, 'pinned file digest/stability differs')
        named = os.stat(path, follow_symlinks=False)
        require((named.st_dev, named.st_ino) == (before.st_dev, before.st_ino),
                'pinned path replaced')
        return raw
    finally:
        os.close(descriptor)


def validate_plan(plan, freeze):
    require(plan['parent_job_id'] == '685198' and plan['freeze_sha256'] == FREEZE_SHA,
            'parent evidence differs')
    require(freeze['diagnostic_protocol'] == 'formal40_batch_invariance_diag_20260903_v18',
            'frozen protocol differs')
    trials = plan['trials']
    require(trials == freeze['trials'] and len(trials) == 32
            and [t['ordinal'] for t in trials] == list(range(32)), 'trial sequence differs')
    ids = tuple(t['trial_id'] for t in trials)
    require(all(type(t) is int and t >= 0 for t in ids) and len(set(ids)) == 32,
            'trial identity differs')
    expected = [{'module': 'model_dict.norm_coch_rep', 'branch': b}
                for b in ('cue', 'mixture')]
    for i in range(7):
        expected.append({'module': f'model_dict.attn{i}', 'branch': 'mixture'})
        for kind in ('conv_block', 'hann_pool'):
            expected.extend({'module': f'model_dict.{kind}_{i}', 'branch': b}
                            for b in ('cue', 'mixture'))
    expected.append({'module': 'model_dict.attnfc', 'branch': 'mixture'})
    expected.extend({'module': name, 'branch': 'logits' if name == 'classification' else 'mixture'}
                    for name in ('fullyconnected', 'relufc', 'dropout', 'classification'))
    require(plan['post_hook_stages'] == expected and plan['post_hook_stage_count'] == 42,
            'stage/branch sequence differs')
    require(plan['pass_batch_sizes'] == [16, 1]
            and plan['autocast_enabled'] == {'A2': True, 'B2': False}, 'pass policy differs')
    require(set(plan['targets']) == {'A2', 'B2'}, 'target cells differ')
    for cell, targets in (('A2', (9000, 4126)), ('B2', (1428, 2698))):
        selection = plan['targets'][cell]
        require([t['metric'] for t in selection] == ['native_logits', 'nll']
                and tuple(t['trial']['trial_id'] for t in selection) == targets,
                'target metric/identity differs')
        require(all(t['trial'] == trials[ids.index(t['trial']['trial_id'])] for t in selection),
                'target trial metadata differs')
    return ids


def comparable_state(entries):
    """Compare bytes/shape/type by registry name, not cross-process ids/devices."""
    fields = ('kind', 'name', 'shape', 'dtype', 'sha256')
    normalized = [{key: e[key] for key in fields} for e in entries]
    keys = [(e['kind'], e['name']) for e in normalized]
    require(len(keys) == len(set(keys)), 'duplicate state name')
    return sorted(normalized, key=lambda e: (e['kind'], e['name']))


def event(stage, **fields):
    print(json.dumps({'stage': stage, **fields}, sort_keys=True), flush=True)


def main():
    import fcntl
    import pwd
    import socket
    import subprocess

    require(pwd.getpwuid(os.getuid()).pw_name == 's2510040'
            and socket.gethostname().split('.')[0] == 'hakusan1', 'wrong CPU probe host/account')
    require(sys.version.split()[0] == '3.11.5' and sys.flags.isolated
            and sys.dont_write_bytecode, 'Python isolation/version differs')
    for name in ('audattn_samebank_v4', 'audattn_v4_numdiag'):
        queue = subprocess.run(['/usr/bin/squeue', '-h', '-u', 's2510040', '-n', name],
                               check=True, capture_output=True, text=True, timeout=15)
        require(not queue.stdout.strip(), 'related active job; do not run probe')
    lock = os.open(V4 / 'state/evaluation.lock', os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        require(hashlib.sha256(os.read(lock, 8192)).hexdigest() == LOCK_SHA, 'lock changed')
        run_with_lock()
    finally:
        os.close(lock)


def run_with_lock():
    root = Path(__file__).resolve().parent.parent
    plan = json.loads(pinned(root / 'targeted_trace_20260911/FORMAL40_PLAN_CANDIDATE.json', PLAN_SHA))
    freeze = json.loads(pinned(V18 / 'input_freeze.json', FREEZE_SHA))
    trial_ids = validate_plan(plan, freeze)
    archived = json.loads(pinned(V18 / 'attempts/slurm-685198/cells/A2/STATE_BEFORE.jsonl', STATE_SHA))
    require(archived['observation'] == 'pass1_before', 'parent state phase differs')
    diag_path = V18 / 'tools/diagnose_batch_invariance.py'
    source = pinned(diag_path, DIAG_SHA)
    sys.path.insert(0, str(root / 'targeted_stream_20260911'))
    import stream_observer as stream
    import torch
    require(torch.__version__ == '2.1.1+cu118' and not torch.cuda.is_initialized()
            and not torch.cuda.is_available(), 'CPU-only matching torch required')
    torch.set_num_threads(1)
    spec = importlib.util.spec_from_file_location('v18_real_binding_probe', diag_path)
    diag = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = diag
    exec(compile(source, str(diag_path), 'exec'), diag.__dict__)
    event('verified_context_begin')
    context = diag.read_frozen_context()
    capability = context['_frozen_context_capability']
    records = {r['relative_path']: r for r in capability.source_records}
    event('verified_context', pinned_files=len(capability.pinned_records), snapshot_files=len(records))
    with diag.frozen_scene_context(context['snapshot_files'], records):
        device = context['evaluator']._configure_runtime(True)
        require(device.type == 'cpu', 'unexpected inference device')
        runtime = diag._read_frozen_numeric_runtime(torch)
        event('strict_load_begin', model='formal40', forward_executed=False)
        model, report = context['evaluator'].strict_load_model(context['manifest'], 'formal40', device=device)
        diag._require_load_report(report)
        authority = diag._ACTIVE_SNAPSHOT_AUTHORITY.get()
        restored = diag._restore_missing_snapshot_modules_before_seal(authority)
        diag._validate_frozen_capability_contents(capability)
        outer_module = sys.modules['src.spatial_attn_lightning']
        cnn_module = sys.modules['src.spatial_attn_architecture']
        custom_module = sys.modules['src.custom_modules']
        for module in (outer_module, cnn_module, custom_module):
            path = Path(module.__file__)
            relative = path.relative_to(context['snapshot_files']).as_posix()
            pinned(path, records[relative]['sha256'])
            require(any(issued[0] is module for issued in authority.issued_modules[module.__name__]),
                    'live module was not issued by frozen loader')
        inventory = diag._direct_model_module_inventory(model)
        diag._require_registered_modules_eval(model)
        diag._require_frozen_direct_parameters(inventory)
        lifecycle = diag._issue_compiler_lifecycle(model, inventory)
        require(lifecycle is not None and len(lifecycle.contexts) == 1 and not lifecycle.entered,
                'unexpected compile lifecycle')
        authority.seal_runtime_bindings()
        before = diag._snapshot_model_entries(model)
        require(comparable_state(before) == comparable_state(archived['value']),
                'CPU loaded state differs from verified v18 A2 pre-forward state')
        rng = diag._get_trace().snapshot_rng_state()
        bindings = {}
        for cell in ('A2', 'B2'):
            relative_plan = stream.base.Plan(
                trial_ids, tuple(t['trial']['trial_id'] for t in plan['targets'][cell]),
                tuple(stream.base.Stage(s['module'], s['branch']) for s in plan['post_hook_stages']))
            binding = stream.bind_compiled_outer(model, relative_plan,
                expected_outer_type=outer_module.BinauralAttentionModule,
                expected_cnn_type=cnn_module.BinauralAuditoryAttentionCNN)
            require(len(binding.modules) == 27 and len(binding.plan.schedule()) == 34,
                    'module inventory/schedule differs')
            for path, module in binding.modules:
                name = path.removeprefix('model._orig_mod.')
                if name == 'model_dict.norm_coch_rep':
                    expected = torch.nn.LayerNorm
                elif name.startswith('model_dict.attn'):
                    expected = cnn_module.SimpleAttentionalGain
                elif name.startswith('model_dict.conv_block_'):
                    expected = torch.nn.Sequential
                elif name.startswith('model_dict.hann_pool_'):
                    expected = custom_module.HannPooling2d
                else:
                    expected = {'fullyconnected': torch.nn.Linear, 'relufc': torch.nn.ReLU,
                                'dropout': torch.nn.Dropout, 'classification': torch.nn.Linear}[name]
                require(type(module) is expected, 'live stage class differs: ' + path)
            bindings[cell] = binding
        event('real_stage_binding', status='PASS', stages=42, unique_modules=27,
              cells=list(bindings), trials=32, batch_sizes=[16, 1], batches_per_cell=34)
        # Admission/lifecycle test only. No record() or model call occurs here.
        store = stream.CaptureStore(root / 'empty-capture-admission')
        observer = stream.StreamObserver(model, bindings['A2'].plan, store, bindings['A2'])
        try:
            with observer:
                observer._check_hooks()
                require(len(observer.handles) == 27 and store.used_bytes == 0, 'hook admission differs')
        finally:
            store.close()
        require(not any(m._forward_hooks or m._forward_pre_hooks for _, m, _, _ in inventory),
                'probe hooks not removed')
        for binding in bindings.values():
            binding.check()
        after = diag._snapshot_model_entries(model)
        require(before == after, 'registered state changed during binding/admission')
        require(rng == diag._get_trace().snapshot_rng_state(), 'RNG changed during binding/admission')
        require(runtime == diag._read_frozen_numeric_runtime(torch), 'numeric settings changed')
        diag._validate_model_module_inventory(model, inventory)
        authority.verify_runtime_bindings()
        lifecycle.verify()
        require(not lifecycle.entered and not torch.cuda.is_initialized(), 'forward/CUDA entered')
        summary = {'binding_kind': 'REAL_FORMAL40_CPU_BINDING_PASS', 'parent_job_id': '685198',
                   'plan_sha256': PLAN_SHA, 'input_freeze_sha256': FREEZE_SHA,
                   'checkpoint_sha256': context['manifest']['models']['formal40']['sha256'],
                   'diagnostic_sha256': DIAG_SHA, 'parent_state_sha256': STATE_SHA,
                   'strict_load_report': report, 'runtime': runtime,
                   'registered_state_entries': len(before), 'parent_state_bytes_equal': True,
                   'source_objects_restored': list(restored), 'source_reexecuted_for_restoration': False,
                   'outer_class': type(model).__module__ + '.' + type(model).__qualname__,
                   'wrapper_class': type(model.model).__module__ + '.' + type(model.model).__qualname__,
                   'stage_modules': [{'path': p, 'type': type(m).__module__ + '.' + type(m).__qualname__}
                                     for p, m in bindings['A2'].modules],
                   'stages': 42, 'unique_modules': 27, 'targets': {'A2': [9000, 4126], 'B2': [1428, 2698]},
                   'hook_admission_and_cleanup': True, 'state_unchanged': True, 'rng_unchanged': True,
                   'production_model_loaded': True, 'scientific_forward_executed': False,
                   'cuda_initialized': False, 'production_execution_authority_verified': False,
                   'intermediate_equivalence_proven': False, 'jobs_submitted': 0, 'ready_for_gpu': False}
    after_sources = diag.collect_snapshot_records(context['source_manifest'], (),
                                                  snapshot_files=context['snapshot_files'])
    require([(r['relative_path'], r['size'], r['sha256']) for r in after_sources]
            == [(r['relative_path'], r['size'], r['sha256']) for r in capability.source_records],
            'snapshot source changed')
    diag._verify_v4_pinned_records(diag._get_trace(), context['manifest'], context['contract'])
    pinned(diag_path, DIAG_SHA)
    pinned(V18 / 'input_freeze.json', FREEZE_SHA)
    pinned(V4 / 'state/evaluation.lock', LOCK_SHA)
    print(json.dumps(summary, sort_keys=True), flush=True)


if __name__ == '__main__':
    import traceback
    try:
        main()
    except Exception as error:
        event('failed', error_type=type(error).__name__, message=str(error)[:1200])
        traceback.print_exc(limit=8)
        raise SystemExit(2)

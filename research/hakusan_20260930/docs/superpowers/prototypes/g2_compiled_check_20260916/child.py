"""One cold synthetic child; original inference guards, no real checkpoint."""
import base64
import faulthandler
import json
import os
from pathlib import Path
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import support as s
import protocol as p


def delegate(self, cue, scene, background):
    self.calls.append('model')
    return self.model(cue, scene, background)


def inner_forward(self, cue, scene, background):
    if background is not None:
        raise RuntimeError('background must be None')
    base = (scene + cue).reshape(scene.shape[0], -1).mean(dim=1)
    return base[:, None] + torch.arange(800, dtype=base.dtype)[None, :] / 1000.


def main(argv):
    global torch
    mode, profile, role, output_arg, release_sha, nonce = argv
    s.require(mode in ('local', 'native') and profile in ('RC' if mode == 'native' else 'DE')
              and role in ('reference', 'observed'), 'child scope differs')
    native = mode == 'native'
    output = Path(output_arg)
    release = json.loads(s.read(s.ROOT.parent / 'RELEASE.json'))
    s.require(s.sha(s.wire(release)) == release_sha, 'release digest differs')
    s.check(s.ROOT, release)
    s.require(sys.flags.isolated and sys.dont_write_bytecode and os.environ.get('CUDA_VISIBLE_DEVICES') == '',
              'isolated CPU child required')
    import torch
    s.require(not torch.cuda.is_initialized(), 'CUDA initialized')
    if native:
        s.require(str(torch.__version__) == '2.1.1+cu118' and sys.version.split()[0] == '3.11.5',
                  'native version differs; no model executed')
        # No scheduler submission is provided by this package. A separately
        # approved launcher must establish and verify the new CPU allocation.
        s.require(sys.platform == 'linux' and os.environ.get('SLURM_JOB_ID', '').isdigit()
                  and len(os.sched_getaffinity(0)) == 1, 'approved single-CPU allocation required')
    else:
        s.require(str(torch.__version__) == '2.12.1', 'local test version differs')
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    s.require(sys.getprofile() is None and threading.getprofile() is None, 'existing profiler rejected')
    cache = Path(os.environ['TORCHINDUCTOR_CACHE_DIR'])
    s.require(cache.is_dir() and not any(cache.iterdir()), 'fresh compiler cache required')
    faulthandler.enable()
    faulthandler.dump_traceback_later(60, repeat=True)
    started = time.monotonic()
    def phase(name):
        print('G2_CHECK_PHASE=' + json.dumps(dict(phase=name, elapsed=time.monotonic()-started)), flush=True)
    bridge = s.load(s.ROOT / (s.PREFIX + 'g2_worker_20260916/cell_bridge.py'), 'g2_check_bridge')
    if native:
        bridge.preload_compiled_backend()
    sys.path.insert(0, str(s.ROOT / s.PARENT))
    fixture = s.load(s.ROOT / (s.PARENT + 'test_numeric_diag.py'), 'g2_check_fixture')
    diag = bridge.load_candidate(s.ROOT / (s.FIXED + profile + '/diagnose_batch_invariance.py'), profile)
    fixture.diagnose = diag  # Existing, explicit hermetic fixture seam only.
    outer_type = type('SyntheticOuter', (fixture._Task4Model,), {'forward': delegate})
    inner_type = type('SyntheticInner', (torch.nn.Module,), {'forward': inner_forward})
    model = outer_type()
    model.model = torch.compile(inner_type(), **({'mode': 'default'} if native else {'backend': 'eager'}))
    model.eval().requires_grad_(False)
    lifecycle = None
    if native:
        # Synthetic preinjection is deliberately disclosed: this is NOT proof
        # of production checkpoint loading or its compiler-issuance chronology.
        lifecycle = diag._issue_compiler_lifecycle(model, diag._direct_model_module_inventory(model))
        lifecycle.verify()
        target, context, enter, compiler, _ = lifecycle.contexts[0]
        s.require(len(lifecycle.contexts) == 1 and target is model.model
                  and context is model.model.dynamo_ctx and enter is context.on_enter
                  and dict(zip(enter.__code__.co_freevars, enter.__closure__))['compiler_fn'].cell_contents is compiler,
                  'compiler target binding differs')
    evaluator, scene = fixture._Task4Evaluator(model_to_load=model), fixture._Task4SceneAPI()
    bank = fixture._task4_bank(32)
    for name, value in dict(control_subset=0, distractor_count=1, snr_bin=0, snr_db=-3.,
                            target_gender='synthetic', target_speaker='synthetic').items():
        bank[name] = value
    trials = tuple(diag.TrialSpec(i, int(row.trial_id), int(index), {
        key: diag._json_value(int(row.distractor_1_label) if key == 'probe_distractor_label' else row[key])
        for key in diag.TRIAL_IDENTITY_COLUMNS}) for i, (index, row) in enumerate(bank.iterrows()))
    expected = diag._trial_documents(trials)
    def state():
        return {name: p.encode(tensor.detach().cpu().reshape(-1).numpy().copy())
                for name, tensor in model.state_dict().items()}
    with fixture._task4_hermetic_worker_context(evaluator, scene) as context:
        phase('PREPARE_BEGIN')
        prepared = diag.prepare_formal40_worker(context, allow_cpu=True)
        s.require(prepared['model'] is model, 'strict loader returned another model')
        run = {**context, **prepared, 'bank': bank, 'clips_dir': Path('/clips'), 'cell_id': profile,
               'historical_scene_hashes': fixture._task4_scene_hashes(bank),
               'scratch_root': str(output.parent), 'cache_roots': {}}
        before, rng_before = state(), diag._get_trace().snapshot_rng_state()
        phase('TWO_PASSES_BEGIN')
        if role == 'observed':
            result = bridge.CellBridge(diag, run, trials, expected, hermetic_test=True).run(cache_root=cache)
            passes, backend = result['passes'], result['backend'] if native else None
        else:
            # No CellBridge instance or backend profiler on this reference path.
            passes = tuple(diag.run_trace_pass(run, trials, 'pass' + str(i+1), size, False, output.parent)
                           for i, size in enumerate((16, 1)))
            backend = None
            for i, part in enumerate(passes):
                diag._validate_cell_pass(part, diag.CellSpec(profile, False, (16, 1)), i)
        timepoints = diag._cell_timepoints(*passes)
        s.require(timepoints['model_state']['state_unchanged'] and not timepoints['rng']['rng_changed'],
                  'original guard detected state/RNG change')
        after, rng_after = state(), diag._get_trace().snapshot_rng_state()
        s.require(before == after and rng_before == rng_after, 'cross-pass state/RNG changed')
        if native:
            lifecycle.verify()
            s.require(id(model.model.dynamo_ctx) in lifecycle.entered,
                      'original compiler lifecycle did not enter target')
        records = []
        for i, part in enumerate(passes):
            records.append(dict(pass_id='pass' + str(i+1), batch_size=(16, 1)[i], trial_ids=list(part.trial_ids),
                original_commitment=bridge._commitment(diag, part),
                boundaries={name: p.encode(part.boundary_records[name]['tensor'].detach().cpu().numpy().copy())
                            for name in p.BOUNDARIES},
                outputs={name: p.encode(part.outputs[name]) for name in p.OFFICIAL}))
    if backend:
        for artifact in backend['artifacts']:
            artifact['source'] = base64.b64encode(s.read(Path(artifact['path']), 4*1024**2)).decode()
    s.require(sys.getprofile() is None and threading.getprofile() is None and not torch.cuda.is_initialized(),
              'profiler/CUDA cleanup differs')
    s.check(s.ROOT, release)
    value = dict(scope=p.NATIVE_SCOPE if native else p.LOCAL_SCOPE, profile=profile, role=role,
        release_sha256=release_sha, nonce=nonce, pid=os.getpid(), python=sys.version.split()[0], torch=str(torch.__version__),
        allocation_job_id=os.environ.get('SLURM_JOB_ID') if native else None,
        complete_passes=2, forward_calls=model.calls.count('model'), strict_loads=len(evaluator.load_calls),
        raw_batch_sizes=[len(x[0]) for x in scene.raw_calls], amp_enabled=False,
        state_unchanged=before == after, rng_unchanged=rng_before == rng_after, model_state=before, model_state_after=after,
        rng_before=rng_before, rng_after=rng_after, runtime=prepared['runtime'], fixture_seed=0,
        test_model_preinjection_used=True, production_load_chronology_validated=False,
        profiler_removed=True, source_postcheck=True, trials=expected, passes=records,
        compiler_lifecycle_verified=native, compiler_target_verified=native, backend=backend,
        cache_root=str(cache), production_model_loaded=False, cuda_initialized=False,
        ready_for_gpu=False, production_interference_validated=False, jobs_submitted=0)
    p.child(value, profile=profile, role=role, native=native, release_sha=release_sha, nonce=nonce)
    s.write(output, s.wire(value))
    faulthandler.cancel_dump_traceback_later()
    phase('CHILD_PASS')


if __name__ == '__main__':
    main(sys.argv[1:])

"""Cold LOCAL synthetic bridge + actual file spill/mmap integration.

Linux-mount evidence is explicitly stubbed on macOS. No ProductionCell.run,
real input loader, real checkpoint, native compiler, GPU or scheduler.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import production_cell as cell

JOB, FREEZE = '7770017', 'a' * 64
BRIDGE = HERE.parent / 'g2_worker_20260916/cell_bridge.py'
FIXED = ROOT / 'docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu'
PARENT = ROOT / 'same_bank_eval_2026_09_03_v4_numeric_diag_v19'
FIXTURE_SHA = '453973e8948c12dcc924391ec9d1584497be79d3c5d60d3e1cff721c6d5c98bf'


def load(path, digest, name):
    raw = cell.input_api.read_stable(path, 2 * 1024**2)
    cell.require(hashlib.sha256(raw).hexdigest() == digest, 'test source differs')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec', dont_inherit=True), vars(module))
    return module


def delegate(self, cue, scene, background):
    if self.fail_single and cue.shape[0] == 1:
        raise RuntimeError('SYNTHETIC_SECOND_PASS_FAILURE')
    return self.model(cue, scene, background)


def main(profile, mode):
    cell.require(profile in ('D', 'E') and mode in ('pass', 'fail'), 'fixed local test required')
    cell.require(sys.flags.isolated and sys.dont_write_bytecode, 'isolated cold test required')
    cell.scratch_api.cold()
    home = os.environ.get('HOME')
    bridge = load(BRIDGE, cell.input_api.BRIDGE_SHA, 'g2_lifetime_test_bridge')
    diag = bridge.load_candidate(FIXED / profile / 'diagnose_batch_invariance.py', profile)
    binding = cell.scratch_api.Binding(bridge, diag)
    with tempfile.TemporaryDirectory(prefix='g2-lifetime-mmap-test-') as temp:
        base = Path(temp).resolve() / ('audattn_g2_' + JOB)
        base.mkdir(mode=0o700)
        environment = binding.environment(dict(os.environ, SLURM_JOB_ID=JOB), base, JOB, 'observed')
        environment.pop('HOME')  # never change/restore the real HOME variable
        # Explicit local-only mount seam. All file, fd, owner, mode, source,
        # content, tensor, state and RNG checks continue to execute normally.
        namespace = binding._factory.__wrapped__.__globals__
        def mount_stub(path):
            return {'scope':'LOCAL_MOUNT_STUB', 'path':str(path)}
        with mock.patch.dict(namespace, {'_require_local_scratch_mount':mount_stub}), \
                mock.patch.dict(os.environ, environment), binding.scope(JOB, FREEZE, 'observed') as scratch:
            import torch
            cell.require(str(torch.__version__) == '2.12.1' and not torch.cuda.is_initialized(),
                         'documented local CPU runtime required')
            torch.set_num_threads(1)
            sys.path.insert(0, str(PARENT))
            fixture = load(PARENT / 'test_numeric_diag.py', FIXTURE_SHA, 'g2_lifetime_hermetic_fixture')
            fixture.diagnose = diag  # original explicit hermetic fixture seam
            outer = type('SyntheticOuter', (fixture._Task4Model,), {'forward':delegate})
            model = outer()
            model.fail_single = mode == 'fail'
            model.model = torch.compile(fixture._Task4Model(model.calls), backend='eager')
            model.eval().requires_grad_(False)
            evaluator, scene = fixture._Task4Evaluator(model_to_load=model), fixture._Task4SceneAPI()
            bank = fixture._task4_bank(32)
            for key, value in dict(control_subset=0, distractor_count=1, snr_bin=0, snr_db=-3.,
                                    target_gender='synthetic', target_speaker='synthetic').items():
                bank[key] = value
            trials = tuple(diag.TrialSpec(i, int(row.trial_id), int(index), {
                key: diag._json_value(int(row.distractor_1_label) if key == 'probe_distractor_label' else row[key])
                for key in diag.TRIAL_IDENTITY_COLUMNS}) for i, (index, row) in enumerate(bank.iterrows()))
            expected = diag._trial_documents(trials)
            with fixture._task4_hermetic_worker_context(evaluator, scene) as context:
                prepared = diag.prepare_formal40_worker(context, allow_cpu=True)
                run = {**context, **prepared, 'bank':bank, 'clips_dir':Path('/clips'), 'cell_id':profile,
                       'historical_scene_hashes':fixture._task4_scene_hashes(bank),
                       'scratch_root':str(scratch.root), 'cache_roots':scratch.cache_roots}
                gate = binding.bridge_type(diag, run, trials, expected, hermetic_test=True)
                if mode == 'fail':
                    try:
                        gate.run(scratch=scratch, cache_root=scratch.cache_roots['torchinductor'])
                    except RuntimeError as error:
                        cell.require('SYNTHETIC_SECOND_PASS_FAILURE' in str(error), 'unexpected failure')
                    else:
                        raise AssertionError('second pass must fail')
                    cell.require(len(scratch.spills) == 2 and len(scratch._maps) == 2,
                                 'only complete first-pass spill should survive')
                    cell.require(id(gate.attestation) in diag._REVOKED_FORMAL40_ATTESTATIONS,
                                 'failed attestation still live')
                    status = 'HERMETIC_MMAP_SECOND_PASS_FAILURE_HANDLED'
                    commitments = []
                else:
                    result = gate.run(scratch=scratch, cache_root=scratch.cache_roots['torchinductor'])
                    cell.require(result['status'] == 'HERMETIC_G2_CELL_COMPLETE'
                                 and result['numeric']['status'] == 'NUMERIC_ACCEPT', 'synthetic cell differs')
                    cell.require(len(scratch.spills) == 4 and len(scratch._maps) == 4,
                                 'two feature spills per pass required')
                    commitments = [bridge._commitment(diag, p) for p in result['passes']]
                    cell.require(commitments == result['pass_commitments'], 'mmap changed pass evidence')
                    summary = cell.input_api.canonical({k: v for k, v in result.items() if k != 'passes'})
                    cell.require(len(summary) <= 1024**2, 'real bridge summary is not bounded JSON')
                    cell.require(result['state']['model_state']['state_unchanged']
                                 and not result['state']['rng']['rng_changed'], 'state/RNG changed')
                    status = 'HERMETIC_MMAP_TWO_PASS_PASS'
                cleanup = object.__new__(cell.ProductionCell)
                cleanup.diag, cleanup.cleanup_errors = diag, []
                cleanup.revoke()
                cell.require(not cleanup.cleanup_errors
                             and id(gate.attestation) in diag._REVOKED_FORMAL40_ATTESTATIONS,
                             'actual original authority cleanup failed')
                scratch.verify_spills()
                try:
                    gate.run(scratch=scratch)
                except RuntimeError as error:
                    cell.require('single use' in str(error), 'wrong retry rejection')
                else:
                    raise AssertionError('repeat must fail')
                cell.require(len(evaluator.load_calls) == 1, 'strict load count differs')
                expected_calls = 2 if mode == 'fail' else 34
                cell.require(model.calls.count('model') == expected_calls, 'extra or missing forward')
                cell.require([len(x[0]) for x in scene.raw_calls]
                             == ([16,16,1] if mode == 'fail' else [16,16] + [1] * 32), 'raw pass schedule differs')
                cell.require(not torch.cuda.is_initialized() and os.environ.get('HOME') == home,
                             'CUDA/HOME changed')
                value = dict(status=status, profile=profile, mode=mode, forward_calls=expected_calls,
                             spills=len(scratch.spills), mappings=len(scratch._maps),
                             pass_commitments=commitments, strict_loads=1, retry_rejected=True,
                             home_unchanged=True, cuda_initialized=False, production_model_loaded=False,
                             actual_production_loader_executed=False, production_lifetime_executed=False,
                             linux_mount_test_stub=True, jobs_submitted=0)
        cell.require(not binding.active and all(not a.chain for a in scratch.anchors), 'descriptor scope leaked')
    value.update(temporary_directory_removed=True, descriptor_scopes_closed=True)
    print('G2_LIFETIME_MMAP_REPORT=' + json.dumps(value, sort_keys=True), flush=True)


if __name__ == '__main__':
    os.umask(0o077)
    cell.require(len(sys.argv) == 3, 'expected fixed profile and pass/fail')
    main(*sys.argv[1:])

"""Local-only integration/negative tests. Never real checkpoint/GPU evidence."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import cell_bridge as bridge
import numpy as np

FIXED = ROOT / 'docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu'
PARENT = ROOT / 'same_bank_eval_2026_09_03_v4_numeric_diag_v19'
FIXTURE_SHA = '453973e8948c12dcc924391ec9d1584497be79d3c5d60d3e1cff721c6d5c98bf'


def arrays():
    return dict(pred_label=np.arange(32, dtype=np.int64), nll=np.zeros(32, dtype=np.float32),
                p_target=np.full(32, .25, dtype=np.float32), p_probe_distractor=np.full(32, .1, dtype=np.float32))


class SummaryTests(unittest.TestCase):
    def test_exact(self):
        summary = bridge.official_summary(arrays(), arrays())
        self.assertEqual(summary['status'], 'NUMERIC_ACCEPT')
        self.assertFalse(summary['scientific_acceptance'])

    def test_numeric_difference_is_not_execution_exception(self):
        left, right = arrays(), arrays()
        right['nll'][3] = .002
        result = bridge.official_summary(left, right)
        self.assertEqual(result['status'], 'NUMERIC_DIFF')
        self.assertEqual(result['comparisons']['nll']['above_atol'], 1)

    def test_each_official_probability_is_checked(self):
        for key in ('nll', 'p_target', 'p_probe_distractor'):
            left, right = arrays(), arrays()
            right[key][0] += .001
            self.assertEqual(bridge.official_summary(left, right)['status'], 'NUMERIC_DIFF')

    def test_below_threshold(self):
        left, right = arrays(), arrays()
        right['nll'][0] = 0.5e-6
        self.assertEqual(bridge.official_summary(left, right)['status'], 'NUMERIC_ACCEPT')

    def test_class_flip(self):
        left, right = arrays(), arrays()
        right['pred_label'][3] = 7
        result = bridge.official_summary(left, right)
        self.assertEqual(result['status'], 'NUMERIC_DIFF')
        self.assertEqual(result['comparisons']['pred_label']['flips'], 1)

    def test_nonfinite_rejected(self):
        for value in (np.nan, np.inf, -np.inf):
            right = arrays()
            right['nll'][0] = value
            with self.assertRaises(bridge.BridgeError):
                bridge.official_summary(arrays(), right)

    def test_missing_extra_shape_dtype_and_range_rejected(self):
        variants = []
        value = arrays(); value.pop('nll'); variants.append(value)
        value = arrays(); value['extra'] = value['nll']; variants.append(value)
        value = arrays(); value['nll'] = value['nll'][:-1]; variants.append(value)
        value = arrays(); value['nll'] = value['nll'].astype(np.float64); variants.append(value)
        value = arrays(); value['pred_label'][0] = 800; variants.append(value)
        for value in variants:
            with self.assertRaises(bridge.BridgeError):
                bridge.official_summary(arrays(), value)


class BindingTests(unittest.TestCase):
    def test_unissued_module_rejected(self):
        with self.assertRaises(bridge.BridgeError):
            bridge._check_module(object())

    def test_all_four_sources_bound_cli_stays_closed(self):
        for name in ('R', 'C', 'D', 'E'):
            diag = bridge.load_candidate(FIXED / name / 'diagnose_batch_invariance.py', name)
            bridge._check_module(diag)
            with self.assertRaisesRegex(diag.DiagnosticError, 'preparation candidate only'):
                diag.main(['run-cell'])

    def test_wrong_profile_source_rejected(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.load_candidate(FIXED / 'D/diagnose_batch_invariance.py', 'R')

    def test_replaced_function_rejected(self):
        diag = bridge.load_candidate(FIXED / 'D/diagnose_batch_invariance.py', 'D')
        diag.run_trace_pass = lambda *a: None
        with self.assertRaisesRegex(bridge.BridgeError, 'source callable changed'):
            bridge._check_module(diag)

    def test_local_compiled_runtime_not_certified(self):
        import torch
        # This checks the closed version gate, not native backend execution.
        if str(torch.__version__) == '2.1.1+cu118':
            raise AssertionError('local test expects the documented non-production runtime')
        with self.assertRaisesRegex(bridge.BridgeError, 'reviewed cold Torch'):
            bridge.preload_compiled_backend()
        for name in ('R', 'C'):
            diag = bridge.load_candidate(FIXED / name / 'diagnose_batch_invariance.py', name)
            candidate = object.__new__(bridge.CellBridge)
            candidate.diag, candidate.model = diag, torch.nn.Linear(4, 4)
            candidate.profile = bridge.profiles.profile(name)
            with self.assertRaisesRegex(bridge.BridgeError, 'reviewed Torch 2.1.1'):
                candidate._backend_scope(None)


def delegate(self, cue, scene, background):
    return self.model(cue, scene, background)


def fail_on_singleton(self, cue, scene, background):
    if cue.shape[0] == 1:
        raise RuntimeError('synthetic second-pass failure')
    return self.model(cue, scene, background)


def guarded(name, fail=False):
    import torch
    torch.set_num_threads(1)
    path = PARENT / 'test_numeric_diag.py'
    bridge.read(path, FIXTURE_SHA)
    sys.path.insert(0, str(PARENT))
    spec = importlib.util.spec_from_file_location('g2_bridge_hermetic_fixture', path)
    fixture = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = fixture
    spec.loader.exec_module(fixture)
    diag = bridge.load_candidate(FIXED / name / 'diagnose_batch_invariance.py', name)
    fixture.diagnose = diag  # Original fixture's explicit hermetic test seam only.
    cls = type('GuardedRoot', (fixture._Task4Model,), {'forward': fail_on_singleton if fail else delegate})
    model = cls()
    model.model = torch.compile(fixture._Task4Model(model.calls), backend='eager')
    model.eval().requires_grad_(False)
    evaluator = fixture._Task4Evaluator(model_to_load=model)
    scene = fixture._Task4SceneAPI()
    bank = fixture._task4_bank(32)
    for column, value in dict(control_subset=0, distractor_count=1, snr_bin=0, snr_db=-3.,
                              target_gender='synthetic', target_speaker='synthetic').items():
        bank[column] = value
    trials = tuple(diag.TrialSpec(i, int(row.trial_id), int(index), {
        key: diag._json_value(int(row.distractor_1_label) if key == 'probe_distractor_label' else row[key])
        for key in diag.TRIAL_IDENTITY_COLUMNS}) for i, (index, row) in enumerate(bank.iterrows()))
    expected = diag._trial_documents(trials)
    case = unittest.TestCase()
    checks = []
    with tempfile.TemporaryDirectory() as directory, fixture._task4_hermetic_worker_context(evaluator, scene) as context:
        prepared = diag.prepare_formal40_worker(context, allow_cpu=True)
        run = {**context, **prepared, 'bank': bank, 'clips_dir': Path('/clips'), 'cell_id': name,
               'historical_scene_hashes': fixture._task4_scene_hashes(bank), 'scratch_root': directory, 'cache_roots': {}}
        if fail:
            candidate = bridge.CellBridge(diag, run, trials, expected, hermetic_test=True)
            with case.assertRaisesRegex(RuntimeError, 'synthetic second-pass failure'):
                candidate.run()
            with case.assertRaisesRegex(bridge.BridgeError, 'single use'):
                candidate.run()
            with candidate._scope(), case.assertRaises(diag.DiagnosticError):
                candidate._live('failed_attestation_must_be_revoked')
            case.assertEqual(model.calls.count('model'), 2)
            case.assertEqual([len(x[0]) for x in scene.raw_calls], [16, 16, 1])
            print('G2_FAILURE_REPORT=' + json.dumps(dict(profile=name, model_calls=2,
                  attempts=[16, 16, 1], partial_results_returned=False, attestation_revoked=True,
                  repeat_rejected=True, production_ready=False)), flush=True)
            return
        for defect in ('identity', 'order', 'partial'):
            wrong = copy.deepcopy(expected)
            if defect == 'identity':
                wrong[0]['identity']['target_label'] = 799
            elif defect == 'order':
                wrong.reverse()
            else:
                wrong.pop()
            with case.assertRaises((bridge.BridgeError, diag.DiagnosticError)):
                bridge.CellBridge(diag, run, trials, wrong, hermetic_test=True)
            checks.append(defect + '_rejected')
        with case.assertRaisesRegex(bridge.BridgeError, 'pinned parent trial freeze'):
            bridge.CellBridge(diag, run, trials, expected)
        checks.append('hermetic_not_production')
        wrong = dict(run, cell_id='R')
        with case.assertRaisesRegex(bridge.BridgeError, 'context profile'):
            bridge.CellBridge(diag, wrong, trials, expected, hermetic_test=True)
        checks.append('profile_rejected')
        candidate = bridge.CellBridge(diag, run, trials, expected, hermetic_test=True)
        # Bank content, not only the caller's TrialSpec ID list, is bound.
        bank.loc[20, 'target_label'] = 799
        with candidate._scope(), case.assertRaisesRegex(bridge.BridgeError, 'bank full identity'):
            candidate._live('test_bad_bank')
        bank.loc[20, 'target_label'] = 0
        checks.append('bank_identity_rejected')
        result = candidate.run()
        case.assertEqual(result['status'], 'HERMETIC_G2_CELL_COMPLETE')
        case.assertEqual(result['numeric']['status'], 'NUMERIC_ACCEPT')
        case.assertFalse(result['ready_for_gpu'])
        case.assertFalse(result['independent_results_verified'])
        case.assertFalse(result['production_interference_validated'])
        case.assertEqual(result['backend'], dict(compiled=False, observer_installed=False,
                                                native_cold_state_verified=False))
        case.assertEqual(len(evaluator.load_calls), 1)
        case.assertEqual(sum(type(x) is tuple and x[0] == 'configure_runtime' for x in evaluator.calls), 1)
        case.assertEqual(model.calls.count('model'), 34)
        case.assertEqual([len(x[0]) for x in scene.raw_calls], [16, 16] + [1] * 32)
        for key in result['passes'][0].outputs:
            np.testing.assert_array_equal(result['passes'][0].outputs[key], result['passes'][1].outputs[key])
        checks.append('32_trials_34_calls_amp_off')
        with case.assertRaisesRegex(bridge.BridgeError, 'single use'):
            candidate.run()
        checks.append('repeat_rejected')
        original = result['passes'][0]
        for defect in ('output', 'amp', 'nonce', 'order'):
            saved = original
            original = copy.copy(saved)
            original.outputs = {key: value.copy() for key, value in saved.outputs.items()}
            original.boundary_records = dict(saved.boundary_records)
            original.boundary_records['metadata'] = dict(saved.boundary_records['metadata'])
            if defect == 'output':
                original.outputs['nll'][0] += 1
            elif defect == 'amp':
                original.boundary_records['metadata']['autocast_enabled'] = True
            elif defect == 'nonce':
                original.boundary_records['metadata']['worker_nonce'] = 'forged'
                # A new untrusted content hash cannot issue a worker identity.
                diag._bind_pass_commitment(original)
            else:
                original.trial_ids = original.trial_ids[::-1]
            with candidate._scope(), case.assertRaises((bridge.BridgeError, diag.DiagnosticError)):
                candidate._consume(original, 0)
            original = saved
            checks.append(defect + '_evidence_rejected')
        model.model.anchor.add_(1)
        with candidate._scope(), case.assertRaises(diag.DiagnosticError):
            candidate._live('test_mutated_model')
        checks.append('original_model_guard_rejected')
        case.assertFalse(torch.cuda.is_initialized())
        print('G2_GUARDED_REPORT=' + json.dumps(dict(profile=name, checks=checks,
              numeric=result['numeric'], pass_commitments=result['pass_commitments'],
              model_calls=34, strict_loads=1, cuda_initialized=False, production_model_loaded=False,
              scope='synthetic_CPU_eager_only', production_ready=False), sort_keys=True), flush=True)


class GuardedTests(unittest.TestCase):
    def test_D_full_guarded_bridge(self):
        self._child('D')

    def test_E_full_guarded_bridge(self):
        self._child('E')

    def test_D_partial_failure_no_retry(self):
        self._child('D', fail=True)

    def test_E_partial_failure_no_retry(self):
        self._child('E', fail=True)

    def _child(self, name, fail=False):
        result = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve()),
                                 '--fail' if fail else '--guarded', name],
            env={**os.environ, 'CUDA_VISIBLE_DEVICES': '', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'},
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('G2_FAILURE_REPORT=' if fail else 'G2_GUARDED_REPORT=', result.stdout)
        print(result.stdout, end='', flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] in ('--guarded', '--fail') and sys.argv[2] in ('D', 'E'):
        guarded(sys.argv[2], fail=sys.argv[1] == '--fail')
    else:
        import torch
        test = unittest.main(verbosity=2, exit=False).result
        report = dict(tests=test.testsRun, failures=len(test.failures), errors=len(test.errors), skipped=len(test.skipped),
                      python=sys.version.split()[0], torch=str(torch.__version__), cuda_initialized=torch.cuda.is_initialized(),
                      production_model_loaded=False, production_ready=False, native_compiled_integration_verified=False,
                      jobs_submitted=0, remote_operations=0)
        print('G2_BRIDGE_TEST_REPORT=' + json.dumps(report, sort_keys=True), flush=True)
        sys.exit(0 if test.wasSuccessful() and not test.skipped else 1)

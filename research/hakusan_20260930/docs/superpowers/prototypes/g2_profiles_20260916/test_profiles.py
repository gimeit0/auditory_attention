"""CPU preparation/derivation tests; no A100, production checkpoint, or jobs."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import adapter as a
import profiles
import build_candidate as build
import torch


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Root(torch.nn.Module):
    def __init__(self, inner):
        super().__init__()
        self.model = inner
        self.register_buffer('counter', torch.zeros((), dtype=torch.int64))

    def forward(self, x):
        return self.model(x)


def root():
    model = Root(torch.compile(torch.nn.Linear(4, 800), backend='eager'))
    model.eval()
    model.requires_grad_(False)
    return model


def high():
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.set_float32_matmul_precision('high')
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True


class PreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        high()

    def tearDown(self):
        high()
        self.assertFalse(torch.cuda.is_initialized())

    def test_profile_matrix(self):
        self.assertEqual([(p, profiles.profile(p).tf32, profiles.profile(p).compiled) for p in profiles.ORDER],
                         [('R', True, True), ('C', False, True), ('D', True, False), ('E', False, False)])
        for p in profiles.ORDER:
            d = profiles.profile(p).document()
            self.assertEqual(d['runtime'], a._g2_expected(p))
            self.assertEqual(d['pass_batch_sizes'], [16, 1])
            self.assertEqual(len(set(d['trial_ids'])), 32)
            self.assertEqual(d['forward_calls'], 34)
            self.assertEqual(d['official_atol'], 1e-6)
            self.assertFalse(d['production_ready'])

    def test_unknown_profile_rejected(self):
        for value in ('B2', 'r', '', True, None):
            with self.subTest(value=value), self.assertRaises((ValueError, RuntimeError)):
                a._g2_expected(value)

    def test_all_four_runtime_readbacks(self):
        for p in profiles.ORDER:
            high()
            a._g2_apply_runtime(torch, p)
            self.assertEqual(a._g2_read_runtime(torch), profiles.profile(p).runtime())

    def test_runtime_typed_and_exact(self):
        expected = a._g2_expected('R')
        for name in expected:
            actual = dict(expected)
            actual[name] = 1 if type(expected[name]) is bool else 'medium'
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                a._g2_check_runtime(actual, 'R')

    def test_missing_extra_readback_rejected(self):
        for actual in ({}, {**a._g2_expected('R'), 'extra': True}):
            with self.assertRaises(RuntimeError):
                a._g2_check_runtime(actual, 'R')

    def test_incorrect_parent_runtime_not_repaired(self):
        torch.backends.cudnn.benchmark = True
        with self.assertRaises(RuntimeError):
            a._g2_apply_runtime(torch, 'E')
        self.assertTrue(torch.backends.cudnn.benchmark)

    def test_four_dispatch_bindings_preserve_objects(self):
        for p in profiles.ORDER:
            high(); a._g2_apply_runtime(torch, p)
            model = root()
            wrapped, original = model.model, model.model._orig_mod
            before = [id(x) for x in model.parameters()]
            record = a._g2_adapt_loaded_model(model, {}, p, 'hermetic-test')
            self.assertIs(model.model, wrapped if p in ('R', 'C') else original)
            self.assertEqual(before, [id(x) for x in model.parameters()])
            self.assertFalse(record['compiled_execution_verified'])
            self.assertFalse(record['production_ready'])

    def test_eager_endpoint_equal_to_compiled_eager_test_backend(self):
        # This is Dynamo backend='eager' on CPU, NOT production Inductor proof.
        for p in ('D', 'E'):
            high(); a._g2_apply_runtime(torch, p)
            model = root()
            x = torch.arange(128, dtype=torch.float32).reshape(32, 4) / 100
            with torch.no_grad():
                before = model(x)
                a._g2_adapt_loaded_model(model, {}, p, 'hermetic-test')
                after = model(x)
            self.assertTrue(torch.equal(before, after))

    def test_without_native_wrapper_rejected(self):
        model = Root(torch.nn.Linear(4, 800)).eval().requires_grad_(False)
        with self.assertRaises(RuntimeError):
            a._g2_adapt_loaded_model(model, {}, 'D', 'hermetic-test')

    def test_nested_wrapper_rejected(self):
        model = root()
        model.extra = torch.compile(torch.nn.Linear(4, 4), backend='eager')
        with self.assertRaises(RuntimeError):
            a._g2_adapt_loaded_model(model, {}, 'D', 'hermetic-test')

    def test_mode_and_hooks_rejected(self):
        model = root()
        model.model._orig_mod.train()
        with self.assertRaises(RuntimeError):
            a._g2_adapt_loaded_model(model, {}, 'D', 'hermetic-test')
        model.eval()
        handle = model.register_forward_hook(lambda *args: None)
        try:
            with self.assertRaises(RuntimeError):
                a._g2_adapt_loaded_model(model, {}, 'D', 'hermetic-test')
        finally:
            handle.remove()

    def test_unfrozen_and_nonfinite_state_rejected(self):
        for kind in ('gradient', 'nan'):
            model = root()
            weight = next(model.parameters())
            if kind == 'gradient':
                weight.requires_grad_(True)
            else:
                weight.fill_(float('nan'))
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                a._g2_adapt_loaded_model(model, {}, 'D', 'hermetic-test')

    def test_wrapper_owned_state_rejected(self):
        model = root()
        model.model.register_buffer('unexpected', torch.ones(1))
        with self.assertRaises(RuntimeError):
            a._g2_adapt_loaded_model(model, {}, 'D', 'hermetic-test')

    def test_model_mutation_rejected_during_adaptation(self):
        model = root()
        original = a._g2_state
        calls = []
        def changing(*args):
            if calls:
                next(model.parameters()).add_(1)
            calls.append(True)
            return original(*args)
        with patch.object(a, '_g2_state', side_effect=changing), self.assertRaises(RuntimeError):
            a._g2_adapt_loaded_model(model, {}, 'D', 'hermetic-test')

    def test_rng_mutation_rejected_during_adaptation(self):
        model = root()
        with patch.object(a, '_g2_rng', side_effect=['before', 'after']), self.assertRaises(RuntimeError):
            a._g2_adapt_loaded_model(model, {}, 'D', 'hermetic-test')

    def test_wrong_domain_and_production_version_rejected(self):
        model = root()
        with self.assertRaises(RuntimeError):
            a._g2_adapt_loaded_model(model, {}, 'D', 'unknown')
        if str(torch.__version__) != '2.1.1+cu118':
            with self.assertRaisesRegex(RuntimeError, 'unreviewed production'):
                a._g2_before_configuration(torch, 'production')

    def test_context_entered_not_compiler_proof(self):
        with self.assertRaisesRegex(RuntimeError, 'not verified'):
            a._g2_backend_gate(compiled=True, context_entered=True, target_backend='inductor',
                               generated_graphs=0, compiled_execution_verified=False)

    def test_eager_backend_not_inductor_proof(self):
        with self.assertRaises(RuntimeError):
            a._g2_backend_gate(compiled=True, context_entered=True, target_backend='eager',
                               generated_graphs=1, compiled_execution_verified=True)

    def test_unexpected_compiler_in_eager_profile_rejected(self):
        with self.assertRaises(RuntimeError):
            a._g2_backend_gate(compiled=False, context_entered=True, target_backend='inductor',
                               generated_graphs=1, compiled_execution_verified=True)

    def test_reversible_derivation_and_profile_readers(self):
        with tempfile.TemporaryDirectory() as directory:
            for p in profiles.ORDER:
                location = Path(directory) / p
                recipe = build.materialize(location, p)
                self.assertTrue(recipe['exact_parent_restoration'])
                self.assertEqual(recipe['unchanged_definition_count'], 275)
                self.assertFalse(recipe['cli_released'])
                diag = load(location / 'diagnose_batch_invariance.py', 'g2_local_reader_' + p)
                high(); a._g2_apply_runtime(torch, p)
                self.assertEqual(diag._read_frozen_numeric_runtime(torch), profiles.profile(p).runtime())
                with self.assertRaisesRegex(diag.DiagnosticError, 'preparation candidate only'):
                    diag.main(['freeze-inputs'])

    def test_parent_tamper_rejected(self):
        read = build.read
        # The real digest reader rejects changed file contents, before derivation.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'changed.py'
            target.write_bytes(read(build.PARENT / 'diagnose_batch_invariance.py', build.PARENT_SHA) + b'\n')
            with self.assertRaises(RuntimeError):
                build.read(target, build.PARENT_SHA)


def _delegating_forward(self, cue, scene, background):
    return self.model(cue, scene, background)


class GuardedPreparationTests(unittest.TestCase):
    def test_eager_profiles_original_guarded_32_trial_lifecycle(self):
        for p in ('D', 'E'):
            completed = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--guarded-profile', p],
                env={**os.environ, 'CUDA_VISIBLE_DEVICES': '', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'},
                capture_output=True, text=True, timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn('G2_HERMETIC_GUARDED_PASS=' + p, completed.stdout)
            print(completed.stdout.strip(), flush=True)

    def run_guarded_profile(self, name):
        torch.set_num_threads(1)
        fixture_path = build.PARENT / 'test_numeric_diag.py'
        build.read(fixture_path, '453973e8948c12dcc924391ec9d1584497be79d3c5d60d3e1cff721c6d5c98bf')
        sys.path.insert(0, str(build.PARENT))
        fixture = load(fixture_path, 'g2_original_hermetic_fixture')
        for p in (name,):
            with tempfile.TemporaryDirectory() as directory:
                generated = Path(directory) / 'candidate'
                build.materialize(generated, p)
                diag = load(generated / 'diagnose_batch_invariance.py', 'g2_guarded_' + p)
                fixture.diagnose = diag  # Explicitly hermetic-only test seam.
                cls = type('GuardedRoot', (fixture._Task4Model,), {'forward': _delegating_forward})
                model = cls()
                model.model = torch.compile(fixture._Task4Model(model.calls), backend='eager')
                model.eval(); model.requires_grad_(False)
                evaluator = fixture._Task4Evaluator(model_to_load=model)
                scene = fixture._Task4SceneAPI()
                bank = fixture._task4_bank(32)
                trials = fixture._task4_trials(bank)
                with fixture._task4_hermetic_worker_context(evaluator, scene) as context:
                    prepared = diag.prepare_formal40_worker(context, allow_cpu=True)
                    self.assertEqual(len(evaluator.load_calls), 1)
                    self.assertEqual(sum(type(x) is tuple and x[0] == 'configure_runtime' for x in evaluator.calls), 1)
                    self.assertEqual(prepared['runtime'], profiles.profile(p).runtime())
                    self.assertIs(prepared['model'], model)
                    self.assertFalse(prepared['load_report']['g2_adaptation']['compiled_wrapper_retained'])
                    self.assertEqual(prepared['attestation']['trust_domain'], 'hermetic-test')
                    run = {**context, **prepared, 'bank': bank, 'clips_dir': Path('/clips'), 'cell_id': p,
                           'historical_scene_hashes': fixture._task4_scene_hashes(bank),
                           'scratch_root': directory, 'cache_roots': {}}
                    passes = []
                    for pass_id, size in (('pass1', 16), ('pass2', 1)):
                        result = diag.run_trace_pass(run, trials, pass_id, size, False, Path(directory))
                        self.assertEqual(len(result.outputs['pred_label']), 32)
                        passes.append(result.outputs)
                    import numpy as np
                    for key in ('pred_label', 'nll', 'p_target', 'p_probe_distractor'):
                        np.testing.assert_array_equal(passes[0][key], passes[1][key])
                    self.assertEqual(model.calls.count('model'), 34)
                    self.assertEqual([len(x[0]) for x in scene.raw_calls], [16, 16] + [1] * 32)
                    model.model.anchor.add_(1)
                    with self.assertRaises(diag.DiagnosticError):
                        diag.run_trace_pass(run, trials, 'pass1', 16, False, Path(directory))
                    print('G2_HERMETIC_GUARDED_PASS=' + p, flush=True)
                self.assertFalse(torch.cuda.is_initialized())
        high()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--guarded-profile':
        if sys.argv[2] not in ('D', 'E'):
            raise RuntimeError('eager hermetic profile required')
        GuardedPreparationTests().run_guarded_profile(sys.argv[2])
    else:
        program = unittest.main(verbosity=2, exit=False)
        result = program.result
        success = result.wasSuccessful() and result.testsRun == 22 and not result.skipped
        print('G2_LOCAL_TEST_REPORT=' + json.dumps(dict(
            status='LOCAL_PREPARATION_TESTS_PASS' if success else 'LOCAL_PREPARATION_TESTS_FAIL',
            tests=result.testsRun, errors=len(result.errors), failures=len(result.failures),
            skipped=len(result.skipped), python=sys.version.split()[0], torch=str(torch.__version__),
            cuda_initialized=torch.cuda.is_initialized(), production_model_loaded=False,
            guarded_cold_profiles=['D', 'E'] if success else [],
            guarded_scope='synthetic 32 trials, 16 then 1, 34 calls per profile; original state guards',
            compiler_test_backend='eager', production_ready=False, jobs_submitted=0,
        ), sort_keys=True), flush=True)
        sys.exit(0 if success else 1)

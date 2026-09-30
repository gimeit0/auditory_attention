"""CPU regression only: these manufactured predictions are NOT new science."""
import copy
from contextlib import nullcontext
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
import torch
from e1_inputs import build_contract
from fine_alpha_contract import CODES, BLOCKS, BUDGET, name, decode, passes, inventory, contract
from fine_alpha_execution import verify_arrays, execute
from fine_alpha_gain import context, check_formula
from architecture_adapter import NAMES, InterventionGain
from test_gain_observer_and_stages import fixture

def tiny_layout():
    return dict(main_batches=[[1, 9000]], control_batches=[[1]], clean_batches=[[9000]],
                labels={'1': 0, '9000': 0})

def arrays(layout, block=None):
    return {k: dict(trial_ids=ids, logits=np.zeros((len(ids), 800), np.float32),
                    nll=np.full(len(ids), np.log(800), np.float32)) for k, ids in inventory(layout, block).items()}

def reference(layout):
    return {('completed_epochs_40', k[1], 'alpha_1', k[3]): v for k, v in arrays(layout, 'A').items() if k[2] == 'reference'}

class GridTests(unittest.TestCase):
    def test_exact_grid_and_block_counts(self):
        self.assertEqual(CODES, (500,) + tuple(range(510, 741, 10)) + (750, 800, 850, 900, 950))
        self.assertEqual(len(CODES), 30); self.assertEqual(BLOCKS, ('A', 'B'))
        names = [n for b in BLOCKS for n in passes(b) if n.startswith('alpha_')]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(names, [name(c) for c in CODES])
        self.assertEqual([passes(b)[:2] for b in BLOCKS], [('original', 'reference')]*2)
        self.assertNotIn('explicit_bypass', [n for b in BLOCKS for n in passes(b)])
        for c in CODES: self.assertEqual(decode(name(c)), c/1000)
        c = build_contract(); spec = contract(c)
        self.assertEqual(spec['science_predictions'], 108000)
        self.assertEqual(spec['predictions'], 122400)
        self.assertEqual(spec['block_predictions'], {'A': 61200, 'B': 61200})
        self.assertEqual(spec['anchor_alpha_integer_milli'], [500, 750])
        self.assertEqual(len(inventory(c)), 204)
        self.assertEqual(c['predictions'], 38400)  # Old audited input object not rewritten.
        from fine_alpha_contract import check_production_counts
        check_production_counts(spec)
        with self.assertRaisesRegex(ValueError, 'PREDICTION_COUNTS'): check_production_counts(contract(tiny_layout()))
    def test_invalid_codes(self):
        for code in (True, .5, 1, 0, 1000, 490, 505, 745, 960, -10):
            with self.assertRaises(ValueError): name(code)
        for value in ('alpha_0000', 'alpha_1000', 'alpha_0505', 'alpha_0.51', 'alpha_nan', 'alpha_0010'):
            with self.assertRaises(ValueError): decode(value)
    def test_array_acceptance(self):
        c = tiny_layout(); self.assertEqual(verify_arrays(c, arrays(c), reference=reference(c))['predictions'], 238)
    def test_missing_condition(self):
        c = tiny_layout(); r = arrays(c); r.pop(next(iter(r)))
        with self.assertRaisesRegex(ValueError, 'INVENTORY'): verify_arrays(c, r)
    def test_swapped_ids(self):
        c = tiny_layout(); r = arrays(c); k = ('A', 'main', 'alpha_0510', 'correct')
        r[k]['trial_ids'].reverse()
        with self.assertRaisesRegex(ValueError, 'TRIAL_ORDER'): verify_arrays(c, r)
    def test_nonfinite_and_bad_nll(self):
        for field, value, pattern in [('logits', np.nan, 'NONFINITE'), ('nll', 0., 'NLL_RECOMPUTE')]:
            c = tiny_layout(); r = arrays(c); r[('A', 'main', 'alpha_0510', 'correct')][field].flat[0] = value
            with self.assertRaisesRegex(ValueError, pattern): verify_arrays(c, r)
    def test_low_accuracy_not_failure(self):
        c = tiny_layout(); r = arrays(c); p = r[('A', 'main', 'alpha_0510', 'correct')]
        p['logits'][:, 1] = 100.
        p['nll'][:] = 100.
        self.assertEqual(verify_arrays(c, r)['predictions'], 238)
    def test_cold_and_native_reference_bits_required(self):
        for key in [('B', 'main', 'reference', 'correct'), ('A', 'main', 'original', 'correct'), ('B', 'clean', 'original', 'zero_cue')]:
            c = tiny_layout(); r = arrays(c); r[key]['logits'] += 1  # Equal probabilities, unequal bits.
            with self.assertRaisesRegex(ValueError, 'BITS'): verify_arrays(c, r)
    def test_v4_has_no_alpha0_identities(self):
        # V1-V3 required alpha=0 bypass and clean alpha=0 two-cue identities; V4 has no alpha=0 pass.
        c = tiny_layout(); r = arrays(c); r[('A', 'clean', 'alpha_0500', 'correct_cue')]['logits'] += 1
        self.assertEqual(verify_arrays(c, r)['predictions'], 238)

class FineGainTests(unittest.TestCase):
    def setUp(self): self.f = fixture()
    def test_all_30_formula_checks_and_restore(self):
        f = self.f; original = [f.outer.model.model_dict[n] for n in NAMES]
        before = f.core.state_digest(f.outer), f.core.rng_digest(), f.core.runtime_values()
        for code in CODES:
            with self.subTest(code=code), context(f.core, f.outer, f.arch, f.gain, name(code)):
                result = check_formula(f.outer.model, name(code))
                self.assertEqual(len(result['checks']), 32)
        self.assertEqual(original, [f.outer.model.model_dict[n] for n in NAMES])
        self.assertEqual(before, (f.core.state_digest(f.outer), f.core.rng_digest(), f.core.runtime_values()))
    def test_wrong_formula_rejected_restore_on_exception(self):
        f = self.f; original = f.outer.model.model_dict['attn0']; forward = InterventionGain.forward
        with self.assertRaisesRegex(ValueError, 'G5_FORMULA_MISMATCH'):
            with context(f.core, f.outer, f.arch, f.gain, name(510)):
                with patch.object(InterventionGain, 'forward', lambda m, *a: forward(m, *a)+.01):
                    check_formula(f.outer.model, name(510))
        self.assertIs(f.outer.model.model_dict['attn0'], original)
    def test_rng_mutation_rejected(self):
        f = self.f
        with self.assertRaisesRegex(ValueError, 'STATE_RNG_RUNTIME'):
            with context(f.core, f.outer, f.arch, f.gain, name(510)): torch.rand(1)
    def test_state_mutation_rejected(self):
        f = self.f
        with self.assertRaisesRegex(ValueError, 'STATE_RNG_RUNTIME'):
            with context(f.core, f.outer, f.arch, f.gain, name(510)):
                f.outer.model.model_dict['attn0'].bias.add_(.01)
    def test_model_endpoint_bits(self):
        f = self.f; results = {}
        for n in ('original', 'reference', name(500), name(950)):
            with context(f.core, f.outer, f.arch, f.gain, n):
                results[n] = f.core.predict(f.base, f.outer, f.scene, f.cue, f.labels, f.labels, f.device)[1]
        self.assertEqual(results['original'].tobytes(), results['reference'].tobytes())
        self.assertNotEqual(results['original'].tobytes(), results[name(500)].tobytes())
        for outside in ('alpha_0000', 'alpha_1000'):
            with self.assertRaises(ValueError):
                with context(f.core, f.outer, f.arch, f.gain, outside): pass

class BodyTests(unittest.TestCase):
    def test_real_synthetic_model_all_blocks(self):
        # Real pinned predict + all eight gain modules on tiny manufactured features.
        # No production checkpoint, audio, CUDA, or scheduler is used.
        c = tiny_layout(); f = fixture(); captured = {}; ref = {}
        def provider(domain, bi, cond, ids):
            grid = torch.arange(30, dtype=torch.float32).reshape(1, 2, 3, 5)
            scene = ((grid+torch.tensor(ids)[:, None, None, None]) % 19)/10
            cue = scene.flip(-1)+.1
            if cond in ('silent', 'zero_cue'): cue = torch.zeros_like(cue)
            elif cond == 'shuffled': cue = cue+.2
            elif cond == 'distractor': cue = cue+.3
            labels = torch.tensor([c['labels'][str(i)] for i in ids])
            return scene, cue, labels, labels
        ctx = dict(core=f.core, base=f.base, outer=f.outer, batch_provider=provider,
                   architecture_type=f.arch, gain_type=f.gain, device=f.device)
        for key, ids in inventory(c, 'A').items():
            if key[2] != 'reference': continue
            s, cue, labels, probes = provider(key[1], 0, key[3], ids)
            values, logits = f.core.predict(f.base, f.outer, s, cue, labels, probes, f.device)
            ref[('completed_epochs_40', key[1], 'alpha_1', key[3])] = dict(trial_ids=ids, logits=logits, nll=values['nll'])
        for block in BLOCKS:
            execute(c, block, ctx, lambda k, v: captured.update({k: v}), reference=ref)
        self.assertEqual(verify_arrays(c, captured, reference=ref)['predictions'], 238)

    def run_body(self, *, changed_input=False, wrong_label=False, bad_reference=False, sink_error=False, clock=None):
        c = tiny_layout(); calls = []; records = {}; seen = {}; ref = reference(c)
        if bad_reference: ref[next(iter(ref))]['logits'] += 1
        def provider(domain, bi, cond, ids):
            calls.append((domain, cond)); key = domain, bi, cond; seen[key] = seen.get(key, 0)+1
            scene = torch.tensor(ids) + int(changed_input and seen[key] > 1)
            labels = torch.tensor([c['labels'][str(i)] for i in ids])+int(wrong_label)
            return scene, torch.tensor(ids), labels, labels
        core = SimpleNamespace(runtime_values=lambda: {}, predict=lambda base, outer, s, cue, labels, probes, device: (
            dict(nll=np.full(len(labels), np.log(800), np.float32)), np.zeros((len(labels), 800), np.float32)))
        base = SimpleNamespace(_tensor_hashes=lambda x: [str(v) for v in x.tolist()])
        ctx = dict(core=core, base=base, outer=SimpleNamespace(model=None), batch_provider=provider,
                   architecture_type=None, gain_type=None, device='cpu')
        def sink(k, p):
            if sink_error: raise RuntimeError('SINK_TEST')
            records[k] = p
        kwargs = {} if clock is None else dict(clock=clock, seconds=1)
        with patch('fine_alpha_execution.context', side_effect=lambda *args: nullcontext()), \
             patch('fine_alpha_execution.check_formula', return_value={'synthetic': True}):
            result = execute(c, 'A', ctx, sink, reference=ref, **kwargs)
        return result, records, calls
    def test_schedule(self):
        r, arrays_, calls = self.run_body()
        self.assertEqual(r['predictions'], 119)
        self.assertEqual(len(arrays_), 102)
        self.assertEqual(calls[:6], [('main', c) for c in ('correct', 'shuffled', 'silent', 'distractor')]+[('clean', c) for c in ('correct_cue', 'zero_cue')])
        self.assertTrue(r['historical_bridge_completed'])
    def test_input_change(self):
        with self.assertRaisesRegex(ValueError, 'INPUT_CHANGED'): self.run_body(changed_input=True)
    def test_wrong_labels(self):
        with self.assertRaisesRegex(ValueError, 'LABELS'): self.run_body(wrong_label=True)
    def test_bridge_before_science(self):
        with self.assertRaisesRegex(ValueError, 'HISTORY_BITS'): self.run_body(bad_reference=True)
    def test_sink_fail(self):
        with self.assertRaisesRegex(RuntimeError, 'SINK_TEST'): self.run_body(sink_error=True)
    def test_timeout(self):
        times = iter([0, 2])
        with self.assertRaisesRegex(TimeoutError, 'DEADLINE'): self.run_body(clock=lambda: next(times))

class PackageTests(unittest.TestCase):
    def test_portable_check_and_mutation(self):
        from build_fine_alpha_package import build
        from fine_alpha_entry import verify_package
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)/'package'; report = build(root); sha = report['release_sha256']
            p = subprocess.run([sys.executable, '-I', '-B', str(root/'fine_alpha_entry.py'), 'check', sha],
                               capture_output=True, text=True, cwd=d, timeout=40)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout)['predictions'], 122400)
            self.assertEqual(json.loads(p.stdout)['science_predictions'], 108000)
            runner = (root/'run_fine_alpha.sbatch').read_text()
            self.assertNotIn('@REMOTE_ROOT@', runner)
            self.assertIn('fine_alpha_20260929_v4', runner)
            for old in ('fine_alpha_20260928_v1', 'fine_alpha_20260928_v2', 'fine_alpha_20260928_v3'): self.assertNotIn(old, runner)
            self.assertEqual(json.loads((root/'RELEASE.json').read_text())['scope'], 'FINE_ALPHA_002_20260929_V4')
            self.assertEqual(json.loads((root/'RELEASE.json').read_text())['budget']['wall_minutes'], 240)
            with self.assertRaises(FileExistsError): build(root)
            (root/'fine_alpha_gain.py').write_bytes(b'# mutation\n')
            with self.assertRaisesRegex(ValueError, 'PACKAGE_BYTES'): verify_package(root, sha)
    def test_explicit_release_permission(self):
        from fine_alpha_entry import approval_gate
        approval = dict(release_sha256='sha', budget=BUDGET, authorized=True,
                        single_held_submission_authorized=True, release_authorized=False)
        receipt = dict(status='SUBMITTED_HELD_NOT_RELEASED', job_id='123', release_sha256='sha', approval='aid')
        auth = dict(job_id='123', release_sha256='sha', release_authorized=True, submission='rid', runner='runner')
        approval_gate(approval, receipt, auth, 'sha', BUDGET, '123', 'aid', 'rid', 'runner')
        for key in ('release_authorized', 'submission', 'runner'):
            wrong = dict(auth); wrong[key] = None
            with self.assertRaises(ValueError): approval_gate(approval, receipt, wrong, 'sha', BUDGET, '123', 'aid', 'rid', 'runner')

if __name__ == '__main__': unittest.main()

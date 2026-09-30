"""Explicit control-flow doubles + real OS lock checks, not production load.

The fake capabilities/devices/receipts below must never be execution evidence.
The public production path has no hermetic or allow_cpu bypass switch.
"""
import ast
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import production_cell as subject


def fake_cell(fail=None, domain='production', numeric='NUMERIC_ACCEPT'):
    """Use object.__new__ only inside tests; do NOT forge an issued live loader."""
    cell = object.__new__(subject.ProductionCell)
    events = []

    def event(name):
        events.append(name)
        if fail == name:
            raise RuntimeError('synthetic failure at ' + name)

    @contextlib.contextmanager
    def lock():
        event('lock_enter')
        try:
            yield lambda: event('lock_check')
        finally:
            event('lock_exit')

    scratch = types.SimpleNamespace(root=Path('/SYNTHETIC/scratch'), cache_roots={'torchinductor':'/SYNTHETIC/cache'},
                                    record={'scope':'control-flow-double'}, verify_spills=lambda: event('spills'))

    @contextlib.contextmanager
    def scope(job, digest, side):
        assert (job, digest, side) == ('7770017', 'a' * 64, 'observed')
        event('scratch_enter')
        try:
            yield scratch
        finally:
            event('scratch_exit')

    @contextlib.contextmanager
    def scene(path, sources):
        assert path == Path('/SYNTHETIC/snapshot') and sources == {'synthetic.py':{'relative_path':'synthetic.py'}}
        event('scene_enter')
        try:
            yield object()
        finally:
            event('scene_exit')

    diag = types.SimpleNamespace(_G2_PROFILE='E', _ISSUED_FORMAL40_ATTESTATIONS={},
                                _ISSUED_COMPILER_LIFECYCLES={}, frozen_scene_context=scene,
                                _worker_software_record=lambda _: {'synthetic':True})
    diag._get_trace = lambda: types.SimpleNamespace(snapshot_rng_state=lambda: {'synthetic_rng':0})
    att, compiler = object(), types.SimpleNamespace(revoked=False)

    def prepare(context, *, allow_cpu):
        assert allow_cpu is False and context['cell_id'] == 'E' and 'scene_api' in context
        diag._ISSUED_FORMAL40_ATTESTATIONS[1] = att
        diag._ISSUED_COMPILER_LIFECYCLES[1] = compiler
        event('prepare')
        return dict(device=types.SimpleNamespace(type='cuda'), attestation={'synthetic':True}, model=object())

    diag.prepare_formal40_worker = prepare
    diag._revoke_attestation = lambda a: event('revoke')
    bundle = dict(context={'snapshot_files':Path('/SYNTHETIC/snapshot'),
                           '_frozen_context_capability':types.SimpleNamespace(trust_domain=domain)},
                  trials=('SYNTHETIC',), freeze={'trials':['SYNTHETIC']},
                  audit={'snapshot_files':[{'relative_path':'synthetic.py'}]})

    def load():
        event('input_load')
        return bundle

    result = dict(status='G2_CELL_CANDIDATE_COMPLETE', trust_domain='production',
                  passes=[{'commitment':'b' * 64},{'commitment':'c' * 64}],
                  pass_commitments=['b' * 64, 'c' * 64], numeric={'status':numeric})

    class Gate:
        def __init__(self, candidate, run, trials, expected, *, old_freeze):
            assert candidate is diag and trials == ('SYNTHETIC',) and expected == ['SYNTHETIC']
            assert run['scratch_root'] == str(scratch.root) and old_freeze == cell.parent_path
            event('gate')

        def run(self, **kwargs):
            assert kwargs == {'scratch':scratch, 'cache_root':scratch.cache_roots['torchinductor']}
            event('passes')
            return result

        def _scope(self):
            return contextlib.nullcontext()

        def _live(self, _):
            event('live_after_archive')

    cell.diag, cell.job, cell.freeze_sha = diag, '7770017', 'a' * 64
    cell.pid, cell.used, cell.cleanup_errors = os.getpid(), False, []
    cell.parent_path = Path('/SYNTHETIC/parent.json')
    cell.binding = types.SimpleNamespace(scope=scope, bridge_type=Gate)
    cell.inputs = types.SimpleNamespace(load=load, revalidate=lambda: event('inputs_revalidate'), proof={'synthetic':True})
    cell.bridge = types.SimpleNamespace(_commitment=lambda d, p: p['commitment'])
    cell.source_check = lambda: event('source')
    cell.runtime_check = lambda: event('runtime')
    cell.device_check = lambda _: event('device')
    cell.exclusive_lock = lock

    def consume(value, metadata):
        event('archive')
        assert value is result
        return dict(status='G2_PASS_ARTIFACTS_WRITTEN',
                    **{k: metadata[k] for k in ('job_id','pid','profile','input_freeze_sha256')},
                    pass_commitments=['b' * 64, 'c' * 64], archive_manifest_sha256='d' * 64)

    return cell, consume, events, result, compiler


class LifetimeTests(unittest.TestCase):
    def test_cold_module_import_and_source_pins(self):
        subject.scratch_api.cold()
        for relative, digest in subject.PINS.items():
            self.assertEqual(hashlib.sha256((HERE.parent / relative).read_bytes()).hexdigest(), digest)

    def test_fixed_flow_archive_inside_live_scopes(self):
        cell, consume, events, _, compiler = fake_cell()
        value = cell.run(consume)
        self.assertEqual(value['status'], 'G2_PRODUCTION_CELL_STORED_CANDIDATE')
        self.assertFalse(value['independent_results_verified'])
        self.assertFalse(value['production_interference_validated'])
        self.assertTrue(compiler.revoked)
        for first, second in [('lock_enter','scratch_enter'), ('scratch_enter','input_load'),
                              ('input_load','runtime'), ('runtime','scene_enter'), ('scene_enter','prepare'),
                              ('prepare','device'), ('device','gate'), ('gate','passes'),
                              ('passes','archive'), ('archive','live_after_archive'),
                              ('live_after_archive','revoke'), ('revoke','scene_exit'),
                              ('scene_exit','scratch_exit'), ('scratch_exit','lock_exit')]:
            self.assertLess(events.index(first), events.index(second))
        self.assertEqual(events.count('input_load'), 1)
        self.assertEqual(events.count('prepare'), 1)
        self.assertEqual(events.count('passes'), 1)
        self.assertEqual(events.count('inputs_revalidate'), 2)

    def test_numeric_difference_preserved_not_execution_failure(self):
        cell, consume, _, _, _ = fake_cell(numeric='NUMERIC_DIFF')
        self.assertEqual(cell.run(consume)['numeric']['status'], 'NUMERIC_DIFF')

    def test_failures_stop_and_scopes_close_without_retry(self):
        for name in ('input_load','runtime','scene_enter','prepare','device','gate','passes',
                     'inputs_revalidate','archive','live_after_archive','spills'):
            with self.subTest(phase=name):
                cell, consume, events, _, compiler = fake_cell(fail=name)
                with self.assertRaises(subject.CellFailure) as caught:
                    cell.run(consume)
                self.assertIn(name, str(caught.exception.primary))
                self.assertIn('scratch_exit', events)
                self.assertIn('lock_exit', events)
                if name not in ('input_load','runtime','scene_enter'):
                    self.assertTrue(compiler.revoked)
                with self.assertRaisesRegex(RuntimeError, 'single-use'):
                    cell.run(consume)

    def test_cleanup_failure_cannot_return_success(self):
        for name in ('scene_exit','scratch_exit','lock_exit','revoke'):
            cell, consume, _, _, _ = fake_cell(fail=name)
            with self.subTest(phase=name), self.assertRaises(subject.CellFailure):
                cell.run(consume)

    def test_primary_and_cleanup_errors_preserved(self):
        cell, consume, _, _, _ = fake_cell(fail='passes')
        cell.diag._revoke_attestation = mock.Mock(side_effect=RuntimeError('cleanup failed'))
        with self.assertRaises(subject.CellFailure) as caught:
            cell.run(consume)
        self.assertIn('passes', str(caught.exception.primary))
        self.assertTrue(any('cleanup failed' in str(e) for e in caught.exception.cleanup))

    def test_hermetic_provenance_rejected_before_preparation(self):
        cell, consume, events, _, _ = fake_cell(domain='hermetic-test')
        with self.assertRaises(subject.CellFailure) as caught:
            cell.run(consume)
        self.assertIn('hermetic', str(caught.exception.primary))
        self.assertNotIn('prepare', events)

    def test_archive_content_and_summary_mutation_rejected(self):
        for field in ('pass', 'numeric', 'coverage'):
            cell, consume, _, _, _ = fake_cell()
            def mutate(value, meta):
                receipt = consume(value, meta)
                if field == 'pass':
                    value['passes'][0]['commitment'] = 'e' * 64
                elif field == 'numeric':
                    value['numeric']['status'] = 'forged'
                else:
                    value['pass_commitments'].pop()
                return receipt
            with self.subTest(field=field), self.assertRaises(subject.CellFailure):
                cell.run(mutate)

    def test_missing_or_other_archive_receipt_rejected(self):
        for change in ('empty','huge','nan','job','pid','profile','sha','coverage'):
            cell, consume, _, _, _ = fake_cell()
            def invalid(value, meta):
                receipt = consume(value, meta)
                if change == 'empty': return {}
                if change == 'huge': receipt['extra'] = 'x' * 1024**2
                if change == 'nan': receipt['extra'] = float('nan')
                if change == 'job': receipt['job_id'] = '7770018'
                if change == 'pid': receipt['pid'] += 1
                if change == 'profile': receipt['profile'] = 'R'
                if change == 'sha': receipt['archive_manifest_sha256'] = 'not-a-sha'
                if change == 'coverage': receipt['pass_commitments'].pop()
                return receipt
            with self.subTest(change=change), self.assertRaises(subject.CellFailure):
                cell.run(invalid)

    def test_wrong_process_and_reuse_rejected(self):
        cell, consume, _, _, _ = fake_cell()
        cell.pid += 1
        with self.assertRaisesRegex(RuntimeError, 'owner process'):
            cell.run(consume)
        cell.pid = os.getpid()
        cell.run(consume)
        with self.assertRaisesRegex(RuntimeError, 'single-use'):
            cell.run(consume)

    def test_preparation_failure_partial_authorities_revoked(self):
        cell, consume, events, _, compiler = fake_cell(fail='prepare')
        with self.assertRaises(subject.CellFailure): cell.run(consume)
        self.assertIn('revoke', events)
        self.assertTrue(compiler.revoked)
        self.assertNotIn('gate', events)

    def test_final_source_check_rejects_drift(self):
        cell, consume, _, _, _ = fake_cell()
        cell.source_check = mock.Mock(side_effect=[None, None, RuntimeError('late source drift')])
        with self.assertRaises(subject.CellFailure) as caught:
            cell.run(consume)
        self.assertIn('late source drift', str(caught.exception.cleanup))

    def test_archive_rng_mutation_rejected(self):
        cell, consume, _, _, _ = fake_cell()
        cell.diag._get_trace = lambda: types.SimpleNamespace(
            snapshot_rng_state=mock.Mock(side_effect=[{'synthetic_rng':0}, {'synthetic_rng':1}]))
        trace = cell.diag._get_trace()
        cell.diag._get_trace = lambda: trace
        with self.assertRaises(subject.CellFailure) as caught:
            cell.run(consume)
        self.assertIn('archive callback changed RNG', str(caught.exception.primary))

    def test_invalid_callback_consumes_single_use(self):
        cell, consume, _, _, _ = fake_cell()
        with self.assertRaises(subject.CellFailure): cell.run(None)
        with self.assertRaisesRegex(RuntimeError, 'single-use'): cell.run(consume)

    def test_original_calls_and_no_cli_bypass(self):
        tree = ast.parse((HERE / 'production_cell.py').read_bytes())
        calls = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call)]
        self.assertIn('diag.prepare_formal40_worker(context, allow_cpu=False)', calls)
        self.assertIn('self.inputs.load()', calls)
        self.assertEqual(calls.count('self.inputs.revalidate()'), 2)
        self.assertNotIn('allow_cpu=True', ast.unparse(tree))
        self.assertFalse(any('sbatch' in c or 'subprocess' in c for c in calls))


class LockTests(unittest.TestCase):
    @contextlib.contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory(prefix='g2-lifetime-lock-test-') as temp:
            root = Path(temp).resolve()
            (root / 'state').mkdir()
            path = root / 'state/evaluation.lock'
            path.write_bytes(b'synthetic OS lock fixture\n')
            cell = object.__new__(subject.ProductionCell)
            cell.diag = types.SimpleNamespace(V4_ROOT=root)
            with mock.patch.object(subject, 'LOCK_SHA', hashlib.sha256(path.read_bytes()).hexdigest()):
                yield cell, path

    def test_exclusive_os_lock_released_without_content_change(self):
        with self.fixture() as (cell, path):
            original = path.read_bytes()
            other = os.open(path, os.O_RDONLY)
            try:
                with cell.exclusive_lock() as check:
                    check()
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertEqual(path.read_bytes(), original)
            finally:
                os.close(other)

    def test_exception_releases_os_lock(self):
        with self.fixture() as (cell, path):
            with self.assertRaisesRegex(ValueError, 'body failure'):
                with cell.exclusive_lock(): raise ValueError('body failure')
            fd = os.open(path, os.O_RDONLY)
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally: os.close(fd)

    def test_changed_lock_bytes_rejected(self):
        with self.fixture() as (cell, path):
            with self.assertRaisesRegex(RuntimeError, 'held v4 lock changed'):
                with cell.exclusive_lock(): path.write_bytes(b'changed fixture\n')

    def test_symlink_lock_rejected(self):
        with self.fixture() as (cell, path):
            saved = path.with_name('saved.lock')
            path.rename(saved)
            path.symlink_to(saved)
            with self.assertRaisesRegex(ValueError, 'nonsymlink'):
                with cell.exclusive_lock(): pass


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print('G2_LIFETIME_TEST_REPORT=' + json.dumps(dict(tests=result.testsRun,
        errors=len(result.errors), failures=len(result.failures), skipped=len(result.skipped),
        scope='LOCAL_CONTROL_FLOW_DOUBLES_AND_OS_LOCK_ONLY',
        production_model_loaded=False, actual_production_loader_executed=False,
        gpu_validated=False, jobs_submitted=0)), flush=True)
    raise SystemExit(0 if result.wasSuccessful() else 2)

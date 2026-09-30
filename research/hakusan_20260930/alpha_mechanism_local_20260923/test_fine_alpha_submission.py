"""All scheduler calls are explicit fakes; never contacts HAKUSAN."""
import json
from pathlib import Path
import tempfile
import unittest
from build_fine_alpha_package import build
from fine_alpha_contract import BUDGET
from fine_alpha_submit_once import submit
from fine_alpha_submission_queue import POLICY
from fine_alpha_pipeline import coordinate
from test_e2_submission import response, scheduler

class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.package = self.root/'package'
        self.sha = build(self.package)['release_sha256']; self.calls = []
    def approve(self):
        (self.root/'APPROVAL.json').write_text(json.dumps(dict(release_sha256=self.sha, budget=BUDGET, authorized=True,
             single_held_submission_authorized=True, release_authorized=False,
             concurrency_review=dict(policy=POLICY, jobs={}))))
    def execute(self, argv):
        self.calls.append(argv)
        if argv[0].endswith('squeue') or '--test-only' in argv: return response()
        if '--hold' in argv: return response('123\n')
        if argv[1:3] == ['write', 'batch_script']: return response((self.package/'run_fine_alpha.sbatch').read_text())
        r = scheduler(); r['stdout'] = r['stdout'].replace('01:00:00', '04:00:00'); return r
    def test_held_once_no_release(self):
        self.approve(); result = submit(self.package, self.sha, execute=self.execute)
        self.assertEqual(result['job_id'], '123')
        self.assertEqual(sum('--hold' in a for a in self.calls), 1)
        self.assertTrue(all('--time=04:00:00' in a for a in self.calls if '--hold' in a))
        self.assertFalse(any('release' in a or 'update' in a for a in self.calls))
        with self.assertRaises(FileExistsError): submit(self.package, self.sha, execute=self.execute)
        self.assertEqual(sum('--hold' in a for a in self.calls), 1)
    def test_budget_derived_limits(self):
        from fine_alpha_submit_once import time_limit, confirm_action
        self.assertEqual(time_limit(BUDGET), '04:00:00')
        self.assertEqual(confirm_action(BUDGET), 'SUBMIT_FINE_ALPHA_HELD_ONCE_4_GPU_HOURS')
        with self.assertRaises(ValueError): confirm_action(dict(BUDGET, wall_minutes=250))
        from fine_alpha_submit_once import argv
        self.assertIn('--time=04:00:00', argv(self.package, self.root/'state', self.sha))
        self.assertIn('--time=06:00:00', argv(Path('/nonexistent'), self.root/'state', self.sha, budget=dict(BUDGET, wall_minutes=360)))
    def test_no_approval_no_calls(self):
        with self.assertRaises(ValueError): submit(self.package, self.sha, execute=self.execute)
        self.assertEqual(self.calls, [])
    def test_uncertain_submit_no_retry(self):
        self.approve()
        def uncertain(argv):
            r = self.execute(argv)
            if '--hold' in argv: r = response('unknown')
            return r
        with self.assertRaisesRegex(ValueError, 'UNKNOWN'): submit(self.package, self.sha, execute=uncertain)
        self.assertEqual(sum('--hold' in a for a in self.calls), 1)
        with self.assertRaises(FileExistsError): submit(self.package, self.sha, execute=self.execute)
    def test_typed_gres_change_is_not_repaired(self):
        self.approve()
        def changed(argv):
            r = self.execute(argv)
            if argv[1:3] == ['show', 'job']: r['stdout'] = r['stdout'].replace('gpu:nvidia_a100', 'gpu:h100-20c')
            return r
        with self.assertRaisesRegex(ValueError, 'TYPED_GRES'): submit(self.package, self.sha, execute=changed)
        self.assertEqual(json.loads((self.root/'state/SUBMISSION.json').read_text())['job_id'], '123')
        self.assertFalse(any('update' in a or 'release' in a for a in self.calls))
    def test_failed_test_only_no_submit(self):
        self.approve()
        def failure(argv):
            r = self.execute(argv)
            return response(rc=1) if '--test-only' in argv else r
        with self.assertRaisesRegex(ValueError, 'TEST_ONLY_FAILED'): submit(self.package, self.sha, execute=failure)
        self.assertFalse(any('--hold' in a for a in self.calls))
    def test_queue_conflict(self):
        self.approve()
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_FINE_ALPHA_JOB'):
            submit(self.package, self.sha, execute=lambda argv: response('100|audattn_fine_alpha|RUNNING'))
        self.assertFalse((self.root/'state/INTENT.json').exists())
        self.assertFalse((self.root/'state').exists())

class PipelineTests(unittest.TestCase):
    def test_child_failure_stops_without_retry(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)/'attempt'; calls = []
            def runner(argv, directory, seconds):
                calls.append(argv); raise RuntimeError('FAIL_CHILD')
            with self.assertRaisesRegex(RuntimeError, 'FAIL_CHILD'):
                coordinate(root, lambda b: [b], 'sha', '123', lambda: None, ['verify'], runner=runner)
            self.assertEqual(calls, [['A']]); self.assertTrue((root/'FAILED.json').exists())
            with self.assertRaises(FileExistsError):
                coordinate(root, lambda b: [b], 'sha', '123', lambda: None, ['verify'], runner=runner)
    def test_coordinator_deadline_before_child(self):
        with tempfile.TemporaryDirectory() as d:
            times = iter([0, 13801]); calls = []
            with self.assertRaisesRegex(TimeoutError, 'DEADLINE'):
                coordinate(Path(d)/'a', lambda b: [b], 'sha', '123', lambda: None, ['verify'],
                           runner=lambda *a: calls.append(a), clock=lambda: next(times))
            self.assertEqual(calls, [])
    def test_no_success_without_verifier(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)/'a'; calls = []
            def runner(argv, directory, seconds):
                directory.mkdir(); calls.append(argv)
                if argv == ['verify']: raise RuntimeError('VERIFY_FAIL')
                return dict(synthetic=True)
            with self.assertRaisesRegex(RuntimeError, 'VERIFY_FAIL'):
                coordinate(root, lambda b: [b], 'sha', '123', lambda: None, ['verify'], runner=runner)
            self.assertEqual(calls, [['A'], ['B'], ['verify']])
            self.assertFalse((root/'COMPLETE.json').exists())

if __name__ == '__main__': unittest.main()

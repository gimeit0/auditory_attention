"""Synthetic scheduler tests plus real local exclusive-journal/process checks.

No SSH, scheduler executable, production input, model or GPU is used.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).absolute().parent
sys.path.insert(0, str(HERE))
import control as c
sys.path.insert(0, str(HERE.parent/'g2_runtime_20260917'))
import entry as e
import bootstrap
from test_entry import scheduler, row


class FakeContext:
    """Explicit fake filesystem/plan, never reachable from the native CLI."""
    def __init__(self, root):
        self.root, self.state, self.e = root, root/'state', e
        for name in ('state', 'attempts'):
            (root/name).mkdir(mode=0o700)
        self.plan = dict(schema_version=1, protocol=e.REMOTE.name, nonce='a'*32,
            release_sha256=c.RELEASE_SHA, freezes={p:'b'*64 for p in e.ORDER},
            limits=dict(e.LIMITS), partition=c.PARTITION)
        self.plan_raw = c.wire(self.plan)
        self.plan_sha, self.control_sha = c.sha(self.plan_raw), 'c'*64
        self.checks, self.broken = 0, False

    def request(self, job):
        return bootstrap.derive_request(self.plan_raw, self.plan_sha, c.RELEASE_SHA, self.plan['nonce'], job)

    def check(self):
        self.checks += 1
        c.require(not self.broken, 'simulated source drift')


def result(argv, out='', rc=0, error=None):
    return dict(argv=argv, stdout=out, stderr='', returncode=rc, error=error, elapsed_seconds=0.001)


class SchedulerDouble:
    def __init__(self, context):
        self.context = context
        self.calls, self.submits, self.releases = [], 0, 0
        self.fail = None
        self.bad_field = None

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[0] == '/usr/bin/squeue':
            return result(argv, '123|RUNNING|unrelated\n' if self.fail == 'queue' else '')
        if argv[:5] == ['/usr/bin/scontrol', '-o', 'show', 'partition', c.PARTITION]:
            out = 'PartitionName=GPU-1A State=UP AllowGroups=ALL AllowAccounts=ALL MaxMemPerCPU=9845 MaxTime=UNLIMITED TRES=cpu=520,mem=5153060M,node=10,billing=520,gres/gpu:nvidia_a100=20'
            if self.fail == 'partition':
                out = out.replace('State=UP', 'State=DOWN')
            return result(argv, out)
        if argv[0] == str(c.PYTHON):
            profile = argv[-1]
            value = dict(status='G2_PROFILE_INPUTS_CHECKED', profile=profile,
                plan_sha256=self.context.plan_sha, input_freeze_sha256=self.context.plan['freezes'][profile])
            if self.fail == 'profile':
                return result(argv, rc=2)
            if self.fail == 'profile_identity':
                value['plan_sha256'] = '0'*64
            return result(argv, 'G2_CONTROL_RESULT='+json.dumps(value)+'\n')
        if argv[0] == '/usr/bin/sbatch' and '--test-only' in argv:
            return result(argv, rc=1 if self.fail == 'test' else 0)
        if argv[0] == '/usr/bin/sbatch':
            self.submits += 1
            assert (self.context.state/'INTENT.json').is_file(), 'external mutation must follow durable journal'
            assert not (self.context.root/'RUN_REQUEST.json').exists(), 'job ID must not be preassigned'
            if self.fail == 'submit_timeout':
                return result(argv, error=dict(type='TimeoutError', message='synthetic ambiguous response'), rc=-9)
            if self.fail == 'submit_raise':
                raise OSError('synthetic transport loss after mutation could have happened')
            if self.fail == 'submit_id':
                return result(argv, '123456\n123457\n')
            return result(argv, '123456\n')
        if argv[:4] == ['/usr/bin/scontrol', '-o', 'show', 'job']:
            if self.fail == 'held':
                return result(argv, rc=1)
            fields = scheduler(self.context.request(argv[-1]))
            fields.update(JobState='PENDING', Reason='JobHeldUser', Priority='0', RunTime='00:00:00', NodeList='', AllocTRES='(null)')
            if self.bad_field:
                fields[self.bad_field[0]] = self.bad_field[1]
            if self.fail == 'drift_after_hold':
                self.context.broken = True
            return result(argv, row(fields))
        if argv[:2] == ['/usr/bin/scontrol', 'release']:
            self.releases += 1
            assert (self.context.state/'RELEASE_INTENT.json').is_file()
            assert json.loads(c.read(self.context.root/'RUN_REQUEST.json'))['job_id'] == argv[-1]
            return result(argv, rc=1 if self.fail == 'release' else 0)
        if argv[0] == '/usr/bin/sacct':
            return result(argv, '123456|PENDING|0:0|00:00:00|synthetic|||\n')
        raise AssertionError('unreviewed command: '+repr(argv))


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.context = FakeContext(Path(self.directory.name).resolve())
        self.execute = SchedulerDouble(self.context)

    def prepare_test(self):
        return c.scheduler_test(self.context, self.execute)['test_sha256']

    def test_exact_single_job_command(self):
        argv = c.batch_argv(self.context)
        for flag in ('--hold', '--no-requeue', '--export=NONE', '--gres=gpu:nvidia_a100:1',
                     '--mem=65536M', '--time=03:00:00', '--cpus-per-task=8', '--partition=GPU-1A'):
            self.assertIn(flag, argv)
        self.assertNotIn('--test-only', argv)
        self.assertEqual(argv[-3:], [c.RELEASE_SHA, self.context.plan_sha, self.context.plan['nonce']])
        self.assertNotIn('123456', argv)

    def test_four_cold_input_checks_then_test_only(self):
        digest = self.prepare_test()
        self.assertEqual(self.execute.submits, 0)
        checks = [a for a in self.execute.calls if a[0] == str(c.PYTHON)]
        self.assertEqual([a[-1] for a in checks], list(e.ORDER))
        value = c.decode(c.read(self.context.state/'TEST_ONLY.json'), digest)
        self.assertEqual(set(value['profiles']), set(e.ORDER))
        self.assertIn('--test-only', self.execute.calls[-1])

    def test_success_held_binding_release_and_no_second_submit(self):
        digest = self.prepare_test()
        answer = c.submit(self.context, digest, c.CONFIRM, self.execute)
        self.assertEqual(answer['status'], 'G2_JOB_RELEASED')
        self.assertEqual((self.execute.submits, self.execute.releases), (1, 1))
        self.assertEqual(c.read(self.context.root/'RUN_REQUEST.json'), c.wire(self.context.request('123456')))
        with self.assertRaises(RuntimeError):
            c.submit(self.context, digest, c.CONFIRM, self.execute)
        self.assertEqual((self.execute.submits, self.execute.releases), (1, 1))

    def test_approval_required_before_any_external_command(self):
        for confirmation in (None, '', 'goon', 'ONE_JOB'):
            with self.subTest(confirmation=confirmation), self.assertRaises(RuntimeError):
                c.submit(self.context, '0'*64, confirmation, self.execute)
        self.assertFalse(self.execute.calls)
        self.assertFalse((self.context.state/'INTENT.json').exists())

    def test_test_receipt_out_of_band_digest_required(self):
        self.prepare_test()
        with self.assertRaises(RuntimeError):
            c.submit(self.context, '0'*64, c.CONFIRM, self.execute)
        self.assertEqual(self.execute.submits, 0)

    def test_profile_receipt_tamper_stops_before_submission(self):
        digest = self.prepare_test()
        (self.context.state/'CHECK_R.json').write_bytes(b'{}\n')
        with self.assertRaises(RuntimeError):
            c.submit(self.context, digest, c.CONFIRM, self.execute)
        self.assertEqual(self.execute.submits, 0)

    def test_nonempty_queue_stops_before_test_or_intent(self):
        self.execute.fail = 'queue'
        with self.assertRaises(RuntimeError): self.prepare_test()
        self.assertEqual(self.execute.submits, 0)
        self.assertFalse((self.context.state/'TEST_INTENT.json').exists())

    def test_changed_partition_stops_before_test(self):
        self.execute.fail = 'partition'
        with self.assertRaises(RuntimeError): self.prepare_test()
        self.assertEqual(self.execute.submits, 0)

    def test_failed_input_check_stops_without_scheduler_mutation(self):
        self.execute.fail = 'profile'
        with self.assertRaises(RuntimeError): self.prepare_test()
        self.assertFalse(any(a[0] == '/usr/bin/sbatch' for a in self.execute.calls))
        self.assertTrue((self.context.state/'CHECK_R.json').exists())

    def test_wrong_input_check_identity_stops(self):
        self.execute.fail = 'profile_identity'
        with self.assertRaises(RuntimeError): self.prepare_test()
        self.assertFalse(any(a[0] == '/usr/bin/sbatch' for a in self.execute.calls))

    def test_failed_test_only_is_preserved_and_cannot_submit(self):
        self.execute.fail = 'test'
        with self.assertRaises(RuntimeError): self.prepare_test()
        digest = c.sha(c.read(self.context.state/'TEST_ONLY.json'))
        with self.assertRaises(RuntimeError): c.submit(self.context, digest, c.CONFIRM, self.execute)
        self.assertEqual(self.execute.submits, 0)

    def test_test_only_cannot_be_repeated(self):
        self.prepare_test()
        previous = len([a for a in self.execute.calls if a[0] == '/usr/bin/sbatch'])
        with self.assertRaises(FileExistsError): self.prepare_test()
        self.assertEqual(len([a for a in self.execute.calls if a[0] == '/usr/bin/sbatch']), previous)

    def test_ambiguous_submission_timeout_consumes_intent(self):
        digest = self.prepare_test()
        self.execute.fail = 'submit_timeout'
        with self.assertRaises(RuntimeError): c.submit(self.context, digest, c.CONFIRM, self.execute)
        self.assertTrue((self.context.state/'INTENT.json').exists())
        self.assertTrue((self.context.state/'SBATCH_RESPONSE.json').exists())
        with self.assertRaises(RuntimeError): c.submit(self.context, digest, c.CONFIRM, self.execute)
        self.assertEqual((self.execute.submits, self.execute.releases), (1, 0))

    def test_exception_after_intent_never_retries(self):
        digest = self.prepare_test()
        self.execute.fail = 'submit_raise'
        with self.assertRaises(OSError): c.submit(self.context, digest, c.CONFIRM, self.execute)
        with self.assertRaises(RuntimeError): c.submit(self.context, digest, c.CONFIRM, self.execute)
        self.assertEqual((self.execute.submits, self.execute.releases), (1, 0))

    def test_ambiguous_job_id_does_not_release(self):
        digest = self.prepare_test()
        self.execute.fail = 'submit_id'
        with self.assertRaises(RuntimeError): c.submit(self.context, digest, c.CONFIRM, self.execute)
        self.assertFalse((self.context.root/'RUN_REQUEST.json').exists())
        self.assertEqual((self.execute.submits, self.execute.releases), (1, 0))

    def test_wrong_held_gpu_leaves_job_held(self):
        digest = self.prepare_test()
        self.execute.bad_field = ('TresPerNode', 'gres/gpu:1')
        with self.assertRaises(RuntimeError): c.submit(self.context, digest, c.CONFIRM, self.execute)
        self.assertTrue((self.context.state/'SUBMISSION_RECEIPT.json').exists())
        self.assertFalse((self.context.state/'RELEASE_INTENT.json').exists())
        self.assertEqual(self.execute.releases, 0)

    def test_held_query_failure_preserves_receipt_without_release(self):
        digest = self.prepare_test()
        self.execute.fail = 'held'
        with self.assertRaises(RuntimeError): c.submit(self.context, digest, c.CONFIRM, self.execute)
        self.assertEqual(self.execute.releases, 0)

    def test_source_drift_after_held_check_blocks_release(self):
        digest = self.prepare_test()
        self.execute.fail = 'drift_after_hold'
        with self.assertRaises(RuntimeError): c.submit(self.context, digest, c.CONFIRM, self.execute)
        self.assertEqual(self.execute.releases, 0)

    def test_release_failure_preserved_no_automatic_retry(self):
        digest = self.prepare_test()
        self.execute.fail = 'release'
        with self.assertRaises(RuntimeError): c.submit(self.context, digest, c.CONFIRM, self.execute)
        self.assertTrue((self.context.state/'RELEASE_RESPONSE.json').exists())
        with self.assertRaises(RuntimeError): c.submit(self.context, digest, c.CONFIRM, self.execute)
        self.assertEqual((self.execute.submits, self.execute.releases), (1, 1))

    def test_readonly_status_without_receipt_does_not_infer_job(self):
        answer = c.status(self.context, self.execute)
        self.assertIsNone(answer['receipt'])
        self.assertIsNone(answer['accounting'])
        self.assertEqual((self.execute.submits, self.execute.releases), (0, 0))
        self.assertFalse(list(self.context.state.iterdir()))

    def test_readonly_status_after_submission(self):
        c.submit(self.context, self.prepare_test(), c.CONFIRM, self.execute)
        before = {p.name:c.read(p) for p in self.context.state.iterdir()}
        answer = c.status(self.context, self.execute)
        self.assertEqual(answer['receipt']['job_id'], '123456')
        self.assertEqual(answer['jobs_submitted'], 0)
        self.assertEqual(before, {p.name:c.read(p) for p in self.context.state.iterdir()})

    def test_real_exclusive_journal_refuses_overwrite(self):
        path = self.context.state/'intent'
        first = c.write_once(path, dict(a=1))
        with self.assertRaises(FileExistsError): c.write_once(path, dict(a=2))
        self.assertEqual(c.sha(c.read(path)), first)

    def test_incomplete_old_held_record_blocks_submission(self):
        digest = self.prepare_test()
        c.write_once(self.context.state/'HELD.json', dict(partial=True))
        with self.assertRaises(RuntimeError): c.submit(self.context, digest, c.CONFIRM, self.execute)
        self.assertEqual(self.execute.submits, 0)

    def test_any_existing_attempt_blocks_submission(self):
        digest = self.prepare_test()
        (self.context.root/'attempts/slurm-previous').mkdir(mode=0o700)
        with self.assertRaises(RuntimeError): c.submit(self.context, digest, c.CONFIRM, self.execute)
        self.assertEqual(self.execute.submits, 0)

    def test_changed_request_between_held_and_release_blocks(self):
        digest = self.prepare_test()
        original = self.execute
        def execute(argv, **kwargs):
            answer = original(argv, **kwargs)
            if argv[:4] == ['/usr/bin/scontrol', '-o', 'show', 'job']:
                (self.context.root/'RUN_REQUEST.json').write_bytes(b'{}\n')
            return answer
        with self.assertRaises(RuntimeError): c.submit(self.context, digest, c.CONFIRM, execute)
        self.assertEqual(self.execute.releases, 0)

    def test_symlink_and_hardlink_journal_inputs_rejected(self):
        path = self.context.state/'source'
        c.write_once(path, dict(value=1))
        link = self.context.state/'link'
        link.symlink_to(path)
        with self.assertRaises(RuntimeError): c.read(link)
        os.link(path, self.context.state/'hard')
        with self.assertRaises(RuntimeError): c.read(path)

    def test_real_supervisor_separates_streams(self):
        answer = c.command([sys.executable, '-I', '-B', '-c', 'import sys; print("out"); print("err",file=sys.stderr)'])
        self.assertTrue(c.succeeded(answer), answer)
        self.assertEqual((answer['stdout'], answer['stderr']), ('out\n', 'err\n'))

    def test_real_supervisor_timeout_and_output_bound(self):
        answer = c.command([sys.executable, '-I', '-B', '-c', 'import time; time.sleep(10)'], seconds=0.1)
        self.assertFalse(c.succeeded(answer))
        self.assertEqual(answer['error']['type'], 'TimeoutError')
        answer = c.command([sys.executable, '-I', '-B', '-c', 'print("x"*65536)'], max_bytes=100)
        self.assertFalse(c.succeeded(answer))
        self.assertLessEqual(len(answer['stdout'])+len(answer['stderr']), 100)

    def test_no_user_scheduler_environment_is_forwarded(self):
        previous = os.environ.get('SBATCH_GRES')
        os.environ['SBATCH_GRES'] = 'gpu:2'
        try:
            answer = c.command([sys.executable, '-I', '-B', '-c', 'import os; print(os.environ.get("SBATCH_GRES"))'])
            self.assertEqual(answer['stdout'], 'None\n')
        finally:
            if previous is None:
                del os.environ['SBATCH_GRES']
            else:
                os.environ['SBATCH_GRES'] = previous

    def test_native_controller_refuses_local_execution(self):
        with self.assertRaises(RuntimeError): c.Context('0'*64, '1'*64)
        self.assertNotIn('torch', sys.modules)
        self.assertNotIn('numpy', sys.modules)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ControlTests)
    answer = unittest.TextTestRunner(verbosity=2).run(suite)
    print('G2_CONTROL_TEST_REPORT='+json.dumps(dict(tests=answer.testsRun, failures=len(answer.failures),
        errors=len(answer.errors), skipped=len(answer.skipped), scheduler='SYNTHETIC_ONLY',
        jobs_submitted=0, production_model_loaded=False)), flush=True)
    raise SystemExit(0 if answer.wasSuccessful() else 2)

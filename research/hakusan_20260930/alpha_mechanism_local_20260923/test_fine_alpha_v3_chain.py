"""V3 queue-review, held-submit, GRES-correction and release driver guards; no SSH or scheduler calls."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

import review_fine_alpha_v3_queue as qr
import submit_fine_alpha_v3 as sub
import correct_fine_alpha_v3_once as cor
import release_fine_alpha_v3_once as rel
BUDGET = sub.BUDGET   # v3's own frozen budget (the source tree now holds v4)
from fine_alpha_entry import approval_gate, identity

HERE = Path(__file__).absolute().parent
V1 = HERE/'release_fine_alpha_20260928_candidate_v1'
JOB = '800001'
# Pinned to the capture the GPU approval cites; later release-time captures must not change fixtures.
LIVE = [sub.RELEASE_ROOT/'queue-review-w7nz2c2r/remote.json']


def v1_scontrol(stage_file, stage):
    rows = [json.loads(line) for line in stage_file.read_text().splitlines()]
    return next(row['stdout'] for row in rows if row['stage'] == stage)


def as_v3(raw):
    return (raw.replace('753729', JOB).replace('fine_alpha_20260928_v1', 'fine_alpha_20260928_v3'))


def rewritten_held():
    return as_v3(v1_scontrol(V1/'held-submission-20260928/remote.jsonl', 'scontrol'))


def corrected_held():
    return as_v3(v1_scontrol(V1/'gres-correction-753729/remote.jsonl', 'after'))


def journal(name, record):
    raw = json.dumps(record, sort_keys=True, indent=2)
    return dict(stage='journal', file=name, raw=raw, size=len(raw.encode()), sha256=hashlib.sha256(raw.encode()).hexdigest())


def ident(row): return {k: row[k] for k in ('size', 'sha256')}


class QueueReviewTests(unittest.TestCase):
    def capture(self):
        self.assertTrue(LIVE, 'live read-only capture required')
        return json.loads(LIVE[0].read_text())

    def test_live_capture_builds_valid_review(self):
        review, notes = qr.build_review(self.capture())
        self.assertEqual(set(review['jobs']), {'754073'})
        self.assertEqual(review['policy'], 'EXPLICIT_INDEPENDENT_JOB_REVIEW_V1')
        self.assertIn('basis', notes['754073'])

    def test_empty_queue_is_empty_review(self):
        review, _ = qr.build_review(dict(queue=dict(returncode=0, stdout='', stderr=''), jobs={}))
        self.assertEqual(review['jobs'], {})

    def test_unknown_duplicate_or_changed_job_stops(self):
        cap = self.capture()
        extra = copy.deepcopy(cap); extra['queue']['stdout'] += '999|other|PENDING\n'
        with self.assertRaisesRegex(ValueError, 'UNASSESSED'): qr.build_review(extra)
        dup = copy.deepcopy(cap); dup['queue']['stdout'] += '999|audattn_fine_alpha|PENDING\n'
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_FINE_ALPHA'): qr.build_review(dup)
        spool = copy.deepcopy(cap); spool['jobs']['754073']['spool']['stdout'] += '#'
        with self.assertRaisesRegex(ValueError, 'SCRIPT_CHANGED'): qr.build_review(spool)
        cmd = copy.deepcopy(cap); cmd['jobs']['754073']['command']['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'SCRIPT_CHANGED'): qr.build_review(cmd)
        fail = copy.deepcopy(cap); fail['queue']['returncode'] = 1
        with self.assertRaises(ValueError): qr.build_review(fail)

    def test_output_overlap_with_fine_alpha_roots_stops(self):
        cap = self.capture(); raw = cap['jobs']['754073']['scontrol']['stdout']
        for old, new in (('StdOut=/home/s2510040/selective_listening_repro/code/auditory_attention_seed20260928/',
                          'StdOut=/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v3/'),
                         ('WorkDir=/home/s2510040/selective_listening_repro/code/auditory_attention_seed20260928',
                          'WorkDir=/home/s2510040/selective_listening_repro/code/auditory_attention')):
            changed = copy.deepcopy(cap); changed['jobs']['754073']['scontrol']['stdout'] = raw.replace(old, new, 1)
            with self.subTest(new=new), self.assertRaises(ValueError): qr.build_review(changed)

    def test_seed_root_is_not_prefix_confused_with_original_tree(self):
        self.assertTrue(qr.disjoint(qr.SEED_ROOT, '/home/s2510040/selective_listening_repro/code/auditory_attention'))
        self.assertFalse(qr.disjoint(qr.SEED_ROOT+'/x', qr.SEED_ROOT))


class SubmitTests(unittest.TestCase):
    def approval(self):
        review, _ = qr.build_review(json.loads(LIVE[0].read_text()))
        return dict(schema_version=1, release_sha256=sub.SHA, budget=BUDGET, authorized=True,
                    single_held_submission_authorized=True, release_authorized=False, gres_correction_authorized=False,
                    automatic_retry=False, automatic_reconnect=False, scheduler_quota_verified=False,
                    concurrency_review=review)

    def queue_record(self, review):
        verified = dict(status='CONCURRENT_JOBS_REVIEWED_DISJOINT', policy=review['policy'],
                        jobs=[dict(job_id=j) for j in review['jobs']], scheduler_quota_verified=False, jobs_submitted=0)
        return [dict(stage='queue', record={}), dict(stage='verified', record=verified)]

    def fixture(self, rewrite=True):
        approval = self.approval(); review = approval['concurrency_review']
        initial = journal('QUEUE_INITIAL.json', self.queue_record(review))
        final = journal('QUEUE_FINAL.json', self.queue_record(review))
        intent = dict(argv=sub.package_argv()(Path(sub.REMOTE_ROOT)/'package', Path(sub.REMOTE_ROOT)/'state', sub.SHA),
                      release_sha256=sub.SHA, automatic_retry=False, queue_review=ident(final))
        rows = [journal('APPROVAL.json', approval), initial, journal('TEST_ONLY.json', dict(returncode=0, stdout='', stderr='')),
                final, journal('INTENT.json', intent), journal('RESPONSE.json', dict(returncode=0, stdout=JOB+'\n', stderr=''))]
        receipt = dict(status='SUBMITTED_HELD_NOT_RELEASED', job_id=JOB, release_sha256=sub.SHA,
                       automatic_retry=False, automatic_release=False,
                       approval=ident(rows[0]), intent=ident(rows[4]), response=ident(rows[5]))
        observed = dict(returncode=0, stderr='', stdout=rewritten_held() if rewrite else corrected_held())
        if rewrite:
            rows.append(journal('STOPPED.json', dict(error='SCHEDULER_TYPED_GRES', error_type='ValueError',
                                                     submission_may_have_happened=True, automatic_retry=False)))
        raw = (sub.PACKAGE/'run_fine_alpha.sbatch').read_text()
        rows += [journal('SUBMISSION.json', receipt), dict(stage='receipt', receipt=receipt),
                 dict(stage='submit', returncode=1 if rewrite else 0), dict(stage='scontrol', **observed),
                 dict(stage='spool', returncode=0, stdout=raw, sha256=hashlib.sha256(raw.encode()).hexdigest()),
                 dict(stage='post-check', status='FINE_ALPHA_PACKAGE_BYTES_PASS', release_sha256=sub.SHA)]
        return rows, approval

    def test_approval_scope(self):
        approval = self.approval(); sub.validate_approval(approval)
        for key, value in (('release_authorized', True), ('gres_correction_authorized', True), ('automatic_retry', True),
                           ('scheduler_quota_verified', True), ('concurrency_review', None), ('release_sha256', '0'*64)):
            changed = copy.deepcopy(approval); changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): sub.validate_approval(changed)
        changed = copy.deepcopy(approval); changed['budget'] = dict(BUDGET, wall_minutes=420)
        with self.assertRaises(ValueError): sub.validate_approval(changed)

    def test_site_rewrite_keeps_held_mismatch(self):
        rows, approval = self.fixture(rewrite=True); result = sub.review(rows, approval)
        self.assertEqual(result['status'], 'FINE_ALPHA_SUBMITTED_HELD_RESOURCE_MISMATCH')
        self.assertEqual(result['resource_error'], 'SCHEDULER_TYPED_GRES')
        self.assertEqual(result['job_id'], JOB)
        self.assertEqual(result['submission_identity'], ident(next(r for r in rows if r.get('file') == 'SUBMISSION.json')))

    def test_exact_a100_passes(self):
        rows, approval = self.fixture(rewrite=False)
        self.assertEqual(sub.review(rows, approval)['status'], 'FINE_ALPHA_HELD_RESOURCES_VERIFIED_NOT_RELEASED')

    def test_queue_final_must_bind_intent(self):
        rows, approval = self.fixture()
        for row in rows:
            if row.get('file') == 'QUEUE_FINAL.json':
                raw = json.dumps([dict(stage='queue', record={})], sort_keys=True, indent=2)
                row.update(raw=raw, size=len(raw.encode()), sha256=hashlib.sha256(raw.encode()).hexdigest())
        with self.assertRaises(ValueError): sub.review(rows, approval)

    def test_incomplete_queue_record_rejected(self):
        with self.assertRaises(ValueError): sub.queue_verified([dict(stage='queue', record={})], {'jobs': {}})
        bad = self.queue_record({'policy': 'x', 'jobs': {}}); bad[-1]['record']['jobs'] = [dict(job_id='5')]
        with self.assertRaises(ValueError): sub.queue_verified(bad, {'jobs': {}})

    def test_unjournaled_resource_stop_rejected(self):
        rows, approval = self.fixture(rewrite=True)
        rows = [r for r in rows if r.get('file') != 'STOPPED.json']
        with self.assertRaisesRegex(ValueError, 'RESOURCE_STOP_NOT_JOURNALED'): sub.review(rows, approval)

    def test_remote_compiles_and_formats(self):
        compile(sub.REMOTE, '<submit-v3>', 'exec')
        self.assertIn("'%i|%T|%r|%P|%b'", sub.REMOTE)
        self.assertIn('QUEUE_FINAL.json', sub.REMOTE)
        self.assertIn("fine_alpha_20260928_v3')", sub.REMOTE)


class CorrectionTests(unittest.TestCase):
    def test_rewritten_and_corrected_fixtures(self):
        self.assertEqual(cor.held_fields(rewritten_held(), 'h100-20c', JOB, cor.REMOTE_ROOT)['JobId'], JOB)
        self.assertEqual(cor.held_fields(corrected_held(), 'nvidia_a100', JOB, cor.REMOTE_ROOT)['TimeLimit'], '06:00:00')

    def test_v1_paths_or_other_job_rejected(self):
        raw = v1_scontrol(V1/'held-submission-20260928/remote.jsonl', 'scontrol')
        with self.assertRaises(ValueError): cor.held_fields(raw, 'h100-20c', '753729', cor.REMOTE_ROOT)
        with self.assertRaises(ValueError): cor.held_fields(rewritten_held(), 'h100-20c', '1', cor.REMOTE_ROOT)

    def test_budget_or_hold_drift_rejected(self):
        for old, new in (('NumCPUs=8', 'NumCPUs=16'), ('TimeLimit=06:00:00', 'TimeLimit=07:00:00'),
                         ('mem=64G', 'mem=128G'), ('JobState=PENDING', 'JobState=RUNNING'), ('Priority=0', 'Priority=1'),
                         ('UserId=s2510040(', 'UserId=s2510040x(')):
            with self.subTest(old=old), self.assertRaises(ValueError):
                cor.held_fields(rewritten_held().replace(old, new), 'h100-20c', JOB, cor.REMOTE_ROOT)

    def test_authorization_no_expansion(self):
        receipt = dict(size=1, sha256='a'*64); auth = cor.authorization_for(JOB, receipt)
        cor.validate_authorization(auth, JOB, receipt)
        for key, value in (('job_id', '1'), ('maximum_update_invocations', 2), ('maximum_update_invocations', True),
                           ('release_authorized', True), ('must_remain_held', False), ('resubmission_authorized', True),
                           ('submission', dict(size=1, sha256='b'*64))):
            changed = copy.deepcopy(auth); changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): cor.validate_authorization(changed, JOB, receipt)

    def test_remote_guard_matches_local(self):
        import ast
        tree = ast.parse(cor.REMOTE)
        selected = ast.Module(body=[n for n in tree.body if isinstance(n, (ast.Import, ast.FunctionDef))
                                    or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
                                        ('REMOTE_ROOT', 'SHA') for t in n.targets))], type_ignores=[])
        ns = {}; exec(compile(selected, '<guard>', 'exec'), ns)
        self.assertEqual(ns['REMOTE_ROOT'], cor.REMOTE_ROOT); self.assertEqual(ns['SHA'], cor.SHA)
        self.assertEqual(ns['held_fields'](corrected_held(), 'nvidia_a100', JOB, ns['REMOTE_ROOT']),
                         cor.held_fields(corrected_held(), 'nvidia_a100', JOB, cor.REMOTE_ROOT))


class ReleaseTests(unittest.TestCase):
    def released(self):
        return corrected_held().replace('Reason=JobHeldUser', 'Reason=Priority').replace('Priority=0', 'Priority=100')

    def test_pending_and_running_readback(self):
        self.assertEqual(rel.released_fields(self.released(), JOB, rel.REMOTE_ROOT)['JobState'], 'PENDING')
        running = self.released().replace('JobState=PENDING', 'JobState=RUNNING')
        self.assertEqual(rel.released_fields(running, JOB, rel.REMOTE_ROOT)['JobState'], 'RUNNING')

    def test_hold_or_resource_change_rejected(self):
        for old, new in (('Priority=100', 'Priority=0'), ('Reason=Priority', 'Reason=JobHeldUser'),
                         ('TimeLimit=06:00:00', 'TimeLimit=07:00:00'), ('gpu:nvidia_a100', 'gpu:h100-20c'),
                         ('JobId='+JOB, 'JobId=1')):
            with self.subTest(old=old), self.assertRaises(ValueError):
                rel.released_fields(self.released().replace(old, new), JOB, rel.REMOTE_ROOT)

    def test_authorization_scope_and_gate(self):
        manifest = json.loads((rel.PACKAGE/'RELEASE.json').read_text())
        runner = manifest['files']['run_fine_alpha.sbatch']; receipt = dict(size=10, sha256='c'*64)
        correction = dict(size=5, sha256='d'*64)
        review, _ = qr.build_review(json.loads(LIVE[0].read_text()))
        auth = rel.authorization_for(JOB, receipt, runner, correction, review, dict(path='x', size=1, sha256='f'*64))
        rel.validate_authorization(auth, JOB, receipt, runner, correction)
        self.assertEqual(runner, identity(rel.PACKAGE/'run_fine_alpha.sbatch'))
        for key, value in (('maximum_release_invocations', 2), ('release_authorized', False), ('automatic_retry', True),
                           ('resubmission_authorized', True), ('job_id', '1'), ('correction', None),
                           ('budget', dict(BUDGET, wall_minutes=420)), ('concurrency_review', None),
                           ('scheduler_quota_verified', True)):
            changed = copy.deepcopy(auth); changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                rel.validate_authorization(changed, JOB, receipt, runner, correction)
        approval = dict(release_sha256=rel.SHA, budget=BUDGET, authorized=True,
                        single_held_submission_authorized=True, release_authorized=False)
        approval_id = dict(size=3, sha256='e'*64)
        held = dict(status='SUBMITTED_HELD_NOT_RELEASED', job_id=JOB, release_sha256=rel.SHA, approval=approval_id)
        approval_gate(approval, held, auth, rel.SHA, BUDGET, JOB, approval_id, receipt, runner)

    def test_own_row_filter_removes_only_this_held_job(self):
        calls = []
        def scheduler(argv):
            calls.append(argv)
            return dict(returncode=0, stderr='', stdout=f'754073|audattn_numcheck_seed20260928|RUNNING\n{JOB}|audattn_fine_alpha|PENDING\n')
        own = []; execute = rel.own_row_filter(scheduler, JOB, own)
        row = execute(['/usr/bin/squeue', '-h', '-u', 's2510040', '-o', '%i|%j|%T'])
        self.assertEqual(row['stdout'], '754073|audattn_numcheck_seed20260928|RUNNING\n')
        self.assertEqual(own, [f'{JOB}|audattn_fine_alpha|PENDING'])
        # A running or differently named row is not ours and stays visible (the frozen reviewer then refuses it).
        own = []; execute = rel.own_row_filter(lambda a: dict(returncode=0, stderr='', stdout=f'{JOB}|audattn_fine_alpha|RUNNING\n'), JOB, own)
        self.assertEqual(execute(['/usr/bin/squeue', '-h'])['stdout'], f'{JOB}|audattn_fine_alpha|RUNNING\n'); self.assertEqual(own, [])
        other = rel.own_row_filter(lambda a: dict(returncode=0, stderr='', stdout='x'), JOB, [])
        self.assertEqual(other(['/usr/bin/scontrol', 'show', 'job', '-o', '1'])['stdout'], 'x')

    def test_frozen_reviewer_accepts_filtered_queue(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('q_v3', rel.PACKAGE/'fine_alpha_submission_queue.py')
        q = importlib.util.module_from_spec(spec); spec.loader.exec_module(q)
        cap = json.loads(LIVE[0].read_text()); review, _ = qr.build_review(cap)
        responses = {'squeue': dict(returncode=0, stderr='', stdout=cap['queue']['stdout']+f'{JOB}|audattn_fine_alpha|PENDING\n'),
                     'show': cap['jobs']['754073']['scontrol'], 'write': cap['jobs']['754073']['spool']}
        def scheduler(argv):
            key = 'squeue' if argv[0].endswith('squeue') else argv[1]
            return {k: responses[key][k] for k in ('returncode', 'stdout', 'stderr')}
        own = []
        from unittest.mock import patch
        # macOS /home is itself a symlink; the cluster paths were checked symlink-free by the live upload receiver.
        guard = patch.object(Path, 'is_symlink', return_value=False); guard.start(); self.addCleanup(guard.stop)
        result = q.inspect_queue(rel.own_row_filter(scheduler, JOB, own), Path(rel.REMOTE_ROOT), review,
                                 command_sha=lambda path: review['jobs']['754073']['command_sha256'])
        self.assertEqual(result['status'], 'CONCURRENT_JOBS_REVIEWED_DISJOINT'); self.assertEqual(len(own), 1)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_FINE_ALPHA_JOB'):
            q.inspect_queue(scheduler, Path(rel.REMOTE_ROOT), review,
                            command_sha=lambda path: review['jobs']['754073']['command_sha256'])

    def test_remote_compiles(self):
        compile(rel.REMOTE, '<release-v3>', 'exec')
        self.assertIn('def own_row_filter', rel.REMOTE); self.assertIn('fine_alpha_20260928_v3', rel.REMOTE)


class ReviewFixTests(unittest.TestCase):
    """Regressions for the adversarial-review findings (2026-09-28)."""
    def test_release_time_capture_skips_only_own_held_row(self):
        cap = json.loads(LIVE[0].read_text())
        withown = copy.deepcopy(cap); withown['queue']['stdout'] += f'{JOB}|audattn_fine_alpha|PENDING\n'
        review, _ = qr.build_review(withown, JOB)
        self.assertEqual(set(review['jobs']), {'754073'})
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_FINE_ALPHA'): qr.build_review(withown)
        with self.assertRaisesRegex(ValueError, 'OWN_HELD_ROW'): qr.build_review(cap, JOB)
        running = copy.deepcopy(cap); running['queue']['stdout'] += f'{JOB}|audattn_fine_alpha|RUNNING\n'
        with self.assertRaises(ValueError): qr.build_review(running, JOB)
        empty = dict(queue=dict(returncode=0, stdout=f'{JOB}|audattn_fine_alpha|PENDING\n', stderr=''), jobs={})
        self.assertEqual(qr.build_review(empty, JOB)[0]['jobs'], {})

    def test_basis_names_shared_cv_train(self):
        basis = qr.ASSESSED['754073']['basis']
        self.assertIn('symlinks to the original', basis); self.assertNotIn('reads its own', basis)

    def test_completed_result_rejects_error_or_transport_mismatch(self):
        good = dict(status='x', transport_returncode=1, submitter_returncode=1)
        sub.completed_result(good)
        for extra in (dict(error='E'), dict(error_type='E'), dict(unverified_review={}), dict(transport_returncode=255)):
            with self.subTest(extra=extra), self.assertRaises(ValueError): sub.completed_result(dict(good, **extra))

    def submission_dir(self, root, status='FINE_ALPHA_SUBMITTED_HELD_RESOURCE_MISMATCH', error='SCHEDULER_TYPED_GRES',
                       held=None, **extra):
        root.mkdir()
        (root/'RESULT.json').write_text(json.dumps(dict(status=status, release_sha256=sub.SHA, resource_error=error,
            jobs_submitted=1, held=True, job_id=JOB, submission_identity=dict(size=1, sha256='a'*64),
            transport_returncode=1, submitter_returncode=1, finished_utc='2026-09-28T13:00:00+00:00', **extra)))
        (root/'remote.jsonl').write_text(json.dumps(dict(stage='scontrol', returncode=0, stdout=held or rewritten_held()))+'\n')

    def test_correction_binding_accepts_only_h100_rewrite_shape(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            ok = Path(d)/'ok'; self.submission_dir(ok)
            with patch.object(cor, 'submission_evidence', lambda: ok): self.assertEqual(cor.submission_binding()[0], JOB)
            node = Path(d)/'node'; self.submission_dir(node, error='SCHEDULER_NODE_GRES')
            with patch.object(cor, 'submission_evidence', lambda: node), self.assertRaises(ValueError): cor.submission_binding()
            other = Path(d)/'other'; self.submission_dir(other, held=rewritten_held().replace('h100-20c', 'h100-40c'))
            with patch.object(cor, 'submission_evidence', lambda: other), self.assertRaises(ValueError): cor.submission_binding()
            failed = Path(d)/'failed'; self.submission_dir(failed, error_type='ValueError', error='TRANSPORT_RETURN_CODE')
            with patch.object(cor, 'submission_evidence', lambda: failed), self.assertRaisesRegex(ValueError, 'ENDED_WITH_ERROR'):
                cor.submission_binding()

    def test_release_attempts_only_after_clean_refusals(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with patch.object(rel, 'RELEASE_ROOT', root):
                self.assertEqual(rel.attempt_paths(), (root/'RELEASE_AUTHORIZATION_1.json', root/'release-v3-1'))
                (root/'release-v3-1').mkdir()
                (root/'release-v3-1/RESULT.json').write_text(json.dumps(dict(status=rel.REFUSED, release_command_reached=False)))
                self.assertEqual(rel.attempt_paths()[1], root/'release-v3-2')
                (root/'release-v3-2').mkdir()   # master check failed: nothing was sent
                (root/'release-v3-2/RESULT.json').write_text(json.dumps(dict(status='RELEASE_NOT_ATTEMPTED',
                                                                          release_command_reached=None)))
                self.assertEqual(rel.attempt_paths()[1], root/'release-v3-3')
                (root/'release-v3-3').mkdir(); (root/'release-v3-3/remote.jsonl').write_text('')
                (root/'release-v3-3/RESULT.json').write_text(json.dumps(dict(status='RELEASE_NOT_ATTEMPTED')))
                with self.assertRaisesRegex(ValueError, 'PRIOR_RELEASE_ATTEMPT'): rel.attempt_paths()
                (root/'release-v3-3/remote.jsonl').unlink()
                (root/'release-v3-3/RESULT.json').write_text(json.dumps(dict(status='RELEASE_UNKNOWN_INSPECT_NO_RETRY',
                                                                          release_command_reached=None)))
                with self.assertRaisesRegex(ValueError, 'PRIOR_RELEASE_ATTEMPT'): rel.attempt_paths()

    def test_release_remote_refusal_writes_no_state_and_records_before_emit(self):
        remote = rel.REMOTE
        refused = remote.index("emit('refused-before-write'"); written = remote.index("write(state/'QUEUE_RELEASE.json'")
        self.assertLess(refused, written)
        self.assertEqual(remote.count("write(state/"), remote[refused:].count("write(state/"))
        self.assertLess(remote.index("write(state/'RELEASE_RESULT.json', result)"), remote.index("emit('release_once'"))
        self.assertIn("auth['concurrency_review']", remote); self.assertNotIn("approval['concurrency_review']", remote)

    def test_helper_read_failure_classified_by_own_readback(self):
        t = SubmitTests()
        for rewrite, status in ((True, 'FINE_ALPHA_SUBMITTED_HELD_RESOURCE_MISMATCH'), (False, 'FINE_ALPHA_HELD_RESOURCES_VERIFIED_NOT_RELEASED')):
            rows, approval = t.fixture(rewrite=rewrite)
            rows = [r for r in rows if r.get('file') != 'STOPPED.json']
            rows.insert(0, journal('STOPPED.json', dict(error='SCHEDULER_QUERY_FAILED', error_type='ValueError',
                                                        submission_may_have_happened=True, automatic_retry=False)))
            for r in rows:
                if r.get('stage') == 'submit': r['returncode'] = 1
            result = sub.review(rows, approval)
            self.assertEqual(result['status'], status); self.assertTrue(result['helper_read_failed'])
        rows, approval = t.fixture(rewrite=False)
        rows.insert(0, journal('STOPPED.json', dict(error='FINE_BUDGET', submission_may_have_happened=True)))
        with self.assertRaisesRegex(ValueError, 'HELPER_STOPPED'): sub.review(rows, approval)

    def test_submit_remote_retries_only_read_only_queries(self):
        self.assertIn("read_only(command, name in ('scontrol', 'spool'))", sub.REMOTE)
        self.assertNotIn('/usr/bin/sbatch', sub.REMOTE)  # the only sbatch call is inside the frozen helper

    def test_fresh_review_uses_newest_capture_after_attempts(self):
        import tempfile
        from unittest.mock import patch
        cap = json.loads(LIVE[0].read_text())
        withown = copy.deepcopy(cap); withown['queue']['stdout'] += f'{JOB}|audattn_fine_alpha|PENDING\n'
        review, _ = qr.build_review(withown, JOB)
        def capture(root, name, started, ok=True):
            d = root/name; d.mkdir()
            row = dict(status='FINE_ALPHA_V3_CONCURRENCY_REVIEW_CAPTURED' if ok else 'STOPPED_INSPECT_NO_RETRY',
                       release_sha256=rel.SHA, own_held_job=JOB, started_utc=started)
            if ok:
                row.update(capture=withown, review=review)
                (d/'CONCURRENCY_REVIEW.json').write_text(json.dumps(review))
            (d/'RESULT.json').write_text(json.dumps(row))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(rel, 'RELEASE_ROOT', root):
                capture(root, 'queue-review-a', '2026-09-28T14:00:00+00:00')
                self.assertEqual(rel.fresh_review(JOB, '2026-09-28T13:00:00+00:00')[0], review)
                with self.assertRaisesRegex(ValueError, 'REQUIRED'): rel.fresh_review(JOB, '2026-09-28T15:00:00+00:00')
                (root/'release-v3-1').mkdir()
                (root/'release-v3-1/RESULT.json').write_text(json.dumps(dict(finished_utc='2026-09-28T14:30:00+00:00')))
                with self.assertRaisesRegex(ValueError, 'REQUIRED'): rel.fresh_review(JOB, '2026-09-28T13:00:00+00:00')
                capture(root, 'queue-review-b', '2026-09-28T15:00:00+00:00', ok=False)
                with self.assertRaisesRegex(ValueError, 'STATUS'): rel.fresh_review(JOB, '2026-09-28T13:00:00+00:00')
                capture(root, 'queue-review-c', '2026-09-28T16:00:00+00:00')
                self.assertEqual(rel.fresh_review(JOB, '2026-09-28T13:00:00+00:00')[1]['path'], 'queue-review-c')

    def test_submit_attempts_only_after_provable_no_job(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with patch.object(sub, 'RELEASE_ROOT', root):
                self.assertEqual(sub.attempt_paths(), (root/'GPU_HELD_AUTHORIZATION_1.json', root/'held-submission-v3-1'))
                a = root/'held-submission-v3-1'; a.mkdir()   # master check never happened inside: nothing sent
                (a/'RESULT.json').write_text(json.dumps(dict(status='SUBMISSION_NOT_ATTEMPTED')))
                self.assertEqual(sub.attempt_paths()[1], root/'held-submission-v3-2')
                b = root/'held-submission-v3-2'; b.mkdir()   # helper stopped before state, approval retired
                sent = dict(size=10, sha256='a'*64)
                (b/'LOCAL_INTENT.json').write_text(json.dumps(dict(authorization=sent)))
                rows = [dict(stage='approval', **sent), dict(stage='submit', returncode=1),
                        dict(stage='approval-retired', name='APPROVAL.no-state-x-1.json', **sent), dict(stage='no-state')]
                (b/'remote.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
                (b/'RESULT.json').write_text(json.dumps(dict(status='STOPPED_BEFORE_STATE_NO_JOB', jobs_submitted=0)))
                self.assertEqual(sub.attempt_paths()[1], root/'held-submission-v3-3')
                c = root/'held-submission-v3-3'; c.mkdir()   # receipt reached
                (c/'RESULT.json').write_text(json.dumps(dict(status='FINE_ALPHA_SUBMITTED_HELD_RESOURCE_MISMATCH')))
                self.assertEqual(sub.submission_evidence(), c)
                with self.assertRaisesRegex(ValueError, 'PRIOR_SUBMISSION_ATTEMPT'): sub.attempt_paths()
                rows[2]['sha256'] = 'b'*64   # retired bytes differ from what was sent
                (b/'remote.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
                with self.assertRaisesRegex(ValueError, 'PRIOR_SUBMISSION_ATTEMPT'): sub.submission_evidence()

    def test_submit_remote_retires_approval_without_overwrite(self):
        remote = sub.REMOTE
        self.assertLess(remote.index('os.link(root/'), remote.index("os.unlink(root/'APPROVAL.json')"))
        self.assertLess(remote.index("emit('approval-retired'"), remote.index("emit('no-state'"))

    def test_no_job_stop_after_state_is_evidence_only(self):
        t = SubmitTests(); approval = t.approval(); raw = json.dumps(approval).encode()
        rows = [dict(stage='approval', size=len(raw), sha256=hashlib.sha256(raw).hexdigest()), journal('APPROVAL.json', approval),
                journal('STOPPED.json', dict(error='UNREVIEWED_CONCURRENT_JOB: 9', submission_may_have_happened=False)),
                dict(stage='submit', returncode=1)]
        self.assertEqual(sub.no_job_stop(rows, approval, raw)['error'], 'UNREVIEWED_CONCURRENT_JOB: 9')
        self.assertIsNone(sub.no_job_stop(rows+[journal('INTENT.json', {})], approval, raw))
        maybe = [r if r.get('file') != 'STOPPED.json' else journal('STOPPED.json', dict(submission_may_have_happened=True)) for r in rows]
        self.assertIsNone(sub.no_job_stop(maybe, approval, raw))

    def test_correction_attempts_and_markers(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with patch.object(cor, 'RELEASE_ROOT', root):
                self.assertEqual(cor.attempt_paths()[1], root/'gres-correction-v3-1')
                a = root/'gres-correction-v3-1'; a.mkdir()
                (a/'RESULT.json').write_text(json.dumps(dict(status=cor.REFUSED, update_reached=False)))
                self.assertEqual(cor.attempt_paths()[1], root/'gres-correction-v3-2')
                b = root/'gres-correction-v3-2'; b.mkdir()
                (b/'RESULT.json').write_text(json.dumps(dict(status='FINE_ALPHA_A100_CORRECTED_VERIFIED_STILL_HELD')))
                self.assertEqual(cor.correction_evidence(), b)
                with self.assertRaisesRegex(ValueError, 'PRIOR_CORRECTION_ATTEMPT'): cor.attempt_paths()
        remote = cor.REMOTE
        self.assertLess(remote.index("emit('refused-before-intent'"), remote.index("write(intent_path"))
        self.assertIn("command('update_once', update)", remote)
        self.assertIn('evidence_only=True', remote)

    def test_submit_pre_write_refusal_allows_retry(self):
        import tempfile
        from unittest.mock import patch
        remote = sub.REMOTE
        self.assertLess(remote.index("emit('refused-before-write'"), remote.index("with (root/'APPROVAL.json').open('xb')"))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with patch.object(sub, 'RELEASE_ROOT', root):
                a = root/'held-submission-v3-1'; a.mkdir()
                (a/'remote.jsonl').write_text(json.dumps(dict(stage='refused-before-write', kind='refused', error='ROOT_PERMISSIONS'))+'\n')
                (a/'RESULT.json').write_text(json.dumps(dict(status='SUBMISSION_NOT_ATTEMPTED_REMOTE_REFUSED', jobs_submitted=0)))
                self.assertEqual(sub.attempt_paths()[1], root/'held-submission-v3-2')
                (a/'remote.jsonl').write_text(json.dumps(dict(stage='refused-before-write', kind='existing'))+'\n')
                with self.assertRaisesRegex(ValueError, 'PRIOR_SUBMISSION_ATTEMPT'): sub.attempt_paths()

    def test_refusal_marker_with_dropped_transport_is_clean(self):
        import inspect as ins
        for module in (cor, rel):
            self.assertIn('p.returncode != 0', ins.getsource(module.main)); self.assertNotIn('(0, 255)', ins.getsource(module.main))

    def test_timeouts_cover_worst_case(self):
        import inspect as ins
        self.assertIn('timeout=900', sub.REMOTE); self.assertIn('timeout=1140', ins.getsource(sub.main))
        self.assertIn('timeout=600', ins.getsource(rel.main)); self.assertIn('timeout=720', ins.getsource(cor.main))


if __name__ == '__main__': unittest.main()

"""Synthetic receipt review tests; no SSH, writes or scheduler calls."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from submit_fine_alpha_authorized import AUTHORIZATION, BUDGET, PACKAGE, REMOTE, REMOTE_ROOT, SHA, review, validate_approval, package_argv
argv = package_argv()   # the frozen v1 package's own argv (06:00:00), not the current source tree
from test_e2_submission import scheduler


def journal(name, record):
    raw = json.dumps(record, sort_keys=True, indent=2)
    return dict(stage='journal', file=name, raw=raw, size=len(raw.encode()), sha256=hashlib.sha256(raw.encode()).hexdigest())


class AuthorizedSubmissionTests(unittest.TestCase):
    def fixture(self, rewrite=False):
        approval = json.loads(AUTHORIZATION.read_text())
        intent = dict(argv=argv(Path(REMOTE_ROOT)/'package', Path(REMOTE_ROOT)/'state', SHA),
                      release_sha256=SHA, automatic_retry=False)
        rows = [journal('APPROVAL.json', approval), journal('INTENT.json', intent),
                journal('RESPONSE.json', dict(returncode=0, stdout='123\n', stderr=''))]
        receipt = dict(status='SUBMITTED_HELD_NOT_RELEASED', job_id='123', release_sha256=SHA,
                       automatic_retry=False, automatic_release=False)
        for key, row in zip(('approval', 'intent', 'response'), rows):
            receipt[key] = {field: row[field] for field in ('size', 'sha256')}
        observed = scheduler()
        observed['stdout'] = observed['stdout'].replace('01:00:00', '06:00:00')+' RunTime=00:00:00'
        if rewrite:
            observed['stdout'] = observed['stdout'].replace('gpu:nvidia_a100', 'gpu:h100-20c')
            rows.append(journal('STOPPED.json', dict(error='SCHEDULER_TYPED_GRES')))
        raw = (PACKAGE/'run_fine_alpha.sbatch').read_text()
        rows += [journal('SUBMISSION.json', receipt), dict(stage='receipt', receipt=receipt),
                 dict(stage='submit', returncode=1 if rewrite else 0), dict(stage='scontrol', **observed),
                 dict(stage='spool', returncode=0, stdout=raw, sha256=hashlib.sha256(raw.encode()).hexdigest()),
                 dict(stage='post-check', status='FINE_ALPHA_PACKAGE_BYTES_PASS', release_sha256=SHA)]
        return rows, approval

    def test_fixture_intent_matches_six_hour_v1_budget(self):
        rows, approval = self.fixture()
        intent = json.loads(next(r['raw'] for r in rows if r.get('file') == 'INTENT.json'))
        self.assertIn('--time=06:00:00', intent['argv']); self.assertEqual(approval['budget']['wall_minutes'], 360)

    def test_replay_real_753729_evidence(self):
        root = Path(__file__).parent/'release_fine_alpha_20260928_candidate_v1'
        rows = [json.loads(l) for l in (root/'held-submission-20260928/remote.jsonl').read_text().splitlines() if l.strip()]
        result = review(rows, json.loads(AUTHORIZATION.read_text()))
        recorded = json.loads((root/'held-submission-20260928/RESULT.json').read_text())
        self.assertEqual(result['status'], recorded['status'])
        self.assertEqual(result['status'], 'FINE_ALPHA_SUBMITTED_HELD_RESOURCE_MISMATCH')
        self.assertEqual(result['resource_error'], 'SCHEDULER_TYPED_GRES')

    def test_replay_real_756262_evidence(self):
        import submit_fine_alpha_v3 as v3
        root = v3.RELEASE_ROOT
        rows = [json.loads(l) for l in (root/'held-submission-v3-1/remote.jsonl').read_text().splitlines() if l.strip()]
        result = v3.review(rows, json.loads((root/'GPU_HELD_AUTHORIZATION_1.json').read_text()))
        recorded = json.loads((root/'held-submission-v3-1/RESULT.json').read_text())
        self.assertEqual((result['status'], result['job_id']), (recorded['status'], recorded['job_id']))

    def test_authorization_is_held_only_six_hours(self):
        rows, approval = self.fixture(); validate_approval(approval)
        self.assertEqual(approval['budget']['wall_minutes'], 360)
        for key, value in (('release_authorized', True), ('gres_correction_authorized', True),
                           ('single_held_submission_authorized', False), ('automatic_retry', True)):
            changed = copy.deepcopy(approval); changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_approval(changed)
        changed = copy.deepcopy(approval); changed['budget']['wall_minutes'] = 420
        with self.assertRaises(ValueError): validate_approval(changed)

    def test_valid_held_review(self):
        rows, approval = self.fixture(); result = review(rows, approval)
        self.assertEqual(result['status'], 'FINE_ALPHA_HELD_RESOURCES_VERIFIED_NOT_RELEASED')
        self.assertTrue(result['held']); self.assertEqual(result['job_id'], '123')

    def test_site_rewrite_preserves_held_receipt(self):
        rows, approval = self.fixture(rewrite=True); result = review(rows, approval)
        self.assertEqual(result['status'], 'FINE_ALPHA_SUBMITTED_HELD_RESOURCE_MISMATCH')
        self.assertEqual(result['resource_error'], 'SCHEDULER_TYPED_GRES')
        self.assertEqual(result['job_id'], '123'); self.assertTrue(result['held'])

    def test_journal_tampering_rejected(self):
        rows, approval = self.fixture(); rows[0]['raw'] += ' '
        with self.assertRaisesRegex(ValueError, 'JOURNAL_IDENTITY'): review(rows, approval)

    def test_running_job_not_called_held(self):
        rows, approval = self.fixture()
        row = next(r for r in rows if r['stage'] == 'scontrol')
        row['stdout'] = row['stdout'].replace('JobState=PENDING', 'JobState=RUNNING')
        with self.assertRaisesRegex(ValueError, 'NOT_CONFIRMED_HELD'): review(rows, approval)

    def test_spool_mismatch_rejected(self):
        rows, approval = self.fixture()
        next(r for r in rows if r['stage'] == 'spool')['stdout'] += '# changed\n'
        with self.assertRaisesRegex(ValueError, 'SPOOL_MISMATCH'): review(rows, approval)

    def test_missing_receipt_and_duplicate_stage(self):
        rows, approval = self.fixture()
        with self.assertRaisesRegex(ValueError, 'MISSING_RECEIPT'):
            review([r for r in rows if r['stage'] != 'receipt'], approval)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_STAGE'):
            review(rows+[rows[-1]], approval)

    def test_postcheck_required(self):
        rows, approval = self.fixture(); rows[-1]['release_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'POST_CHECK'): review(rows, approval)

    def test_remote_syntax(self):
        compile(REMOTE, '<held-once-remote>', 'exec')


if __name__ == '__main__':
    unittest.main()

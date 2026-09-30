"""Local release guards only; no scheduler calls."""
import copy
import json
import unittest
from release_fine_alpha_753729_once import AUTHORIZATION, RELEASE_ROOT, REMOTE, validate_authorization, released_fields
from fine_alpha_entry import approval_gate


class ReleaseTests(unittest.TestCase):
    def fixture(self):
        rows = [json.loads(line) for line in (RELEASE_ROOT/'gres-correction-753729/remote.jsonl').read_text().splitlines()]
        raw = next(row['stdout'] for row in rows if row['stage'] == 'after')
        return raw.replace('Reason=JobHeldUser', 'Reason=Priority').replace('Priority=0', 'Priority=100')

    def test_pending_and_running_readback(self):
        self.assertEqual(released_fields(self.fixture())['JobState'], 'PENDING')
        self.assertEqual(released_fields(self.fixture().replace('JobState=PENDING', 'JobState=RUNNING'))['JobState'], 'RUNNING')

    def test_hold_or_resource_change_rejected(self):
        for old, new in (('Priority=100', 'Priority=0'), ('Reason=Priority', 'Reason=JobHeldUser'),
                         ('TimeLimit=06:00:00', 'TimeLimit=07:00:00'), ('NumCPUs=8', 'NumCPUs=16'),
                         ('gpu:nvidia_a100', 'gpu:h100-20c'), ('JobId=753729', 'JobId=123')):
            with self.subTest(old=old), self.assertRaises(ValueError): released_fields(self.fixture().replace(old, new))

    def test_expanded_authorization_rejected(self):
        auth = json.loads(AUTHORIZATION.read_text()); validate_authorization(auth)
        for key, value in (('maximum_release_invocations', 2), ('release_authorized', False),
                           ('automatic_retry', True), ('resubmission_authorized', True), ('job_id', '123')):
            row = copy.deepcopy(auth); row[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_authorization(row)

    def test_production_authorization_gate_compatible(self):
        rows = [json.loads(line) for line in (RELEASE_ROOT/'held-submission-20260928/remote.jsonl').read_text().splitlines()]
        journals = {r['file']: r for r in rows if r['stage'] == 'journal'}
        auth = json.loads(AUTHORIZATION.read_text())
        approval_gate(json.loads(journals['APPROVAL.json']['raw']), json.loads(journals['SUBMISSION.json']['raw']),
                      auth, auth['release_sha256'], auth['budget'], auth['job_id'],
                      {k: journals['APPROVAL.json'][k] for k in ('size', 'sha256')}, auth['submission'], auth['runner'])

    def test_remote_syntax(self):
        compile(REMOTE, '<release-remote>', 'exec')


if __name__ == '__main__': unittest.main()

"""Read-only local guard tests using the saved submission observation."""
import copy
import json
import unittest
from correct_fine_alpha_753729_once import AUTHORIZATION, RELEASE_ROOT, REMOTE, held_fields, validate_authorization


class CorrectionTests(unittest.TestCase):
    def before(self):
        rows = [json.loads(line) for line in (RELEASE_ROOT/'held-submission-20260928/remote.jsonl').read_text().splitlines()]
        return next(row['stdout'] for row in rows if row['stage'] == 'scontrol')

    def after(self):
        return self.before().replace('gres/gpu:h100-20c=1', 'gres/gpu:nvidia_a100=1').replace(
            'TresPerNode=gres/gpu:1', 'TresPerNode=gres/gpu:nvidia_a100:1')

    def test_original_observation_and_corrected_fixture(self):
        self.assertEqual(held_fields(self.before(), 'h100-20c')['JobId'], '753729')
        self.assertEqual(held_fields(self.after(), 'nvidia_a100')['TimeLimit'], '06:00:00')

    def test_budget_or_hold_drift_rejected(self):
        for old, new in (('JobId=753729', 'JobId=123'), ('NumCPUs=8', 'NumCPUs=16'),
                         ('TimeLimit=06:00:00', 'TimeLimit=07:00:00'), ('mem=64G', 'mem=128G'),
                         ('JobState=PENDING', 'JobState=RUNNING'), ('Priority=0', 'Priority=1'),
                         ('RunTime=00:00:00', 'RunTime=00:00:01')):
            with self.subTest(old=old), self.assertRaises(ValueError):
                held_fields(self.before().replace(old, new), 'h100-20c')

    def test_wrong_or_extra_gpu_rejected(self):
        with self.assertRaises(ValueError): held_fields(self.before(), 'nvidia_a100')
        for old, new in (('gres/gpu:nvidia_a100=1', 'gres/gpu:nvidia_a100=2'),
                         ('gres/gpu:nvidia_a100=1', 'gres/gpu:nvidia_a100=1,gres/gpu:h100-20c=1'),
                         ('TresPerNode=gres/gpu:nvidia_a100:1', 'TresPerNode=gres/gpu:1')):
            with self.subTest(new=new), self.assertRaises(ValueError):
                held_fields(self.after().replace(old, new), 'nvidia_a100')

    def test_authorization_no_expansion(self):
        auth = json.loads(AUTHORIZATION.read_text()); validate_authorization(auth)
        for key, value in (('job_id', '123'), ('maximum_update_invocations', 2), ('maximum_update_invocations', True),
                           ('release_authorized', True), ('must_remain_held', False), ('resubmission_authorized', True)):
            altered = copy.deepcopy(auth); altered[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_authorization(altered)

    def test_remote_guard_matches_local(self):
        import ast
        tree = ast.parse(REMOTE)
        selected = ast.Module(body=[node for node in tree.body if isinstance(node, (ast.Import, ast.FunctionDef))
                                    or (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
                                        ('JOB', 'REMOTE_ROOT', 'SHA', 'RECEIPT_SHA') for t in node.targets))], type_ignores=[])
        ns = {}; exec(compile(selected, '<guard-only>', 'exec'), ns)
        self.assertEqual(ns['held_fields'](self.after(), 'nvidia_a100'), held_fields(self.after(), 'nvidia_a100'))
        compile(REMOTE, '<remote-correction>', 'exec')


if __name__ == '__main__':
    unittest.main()

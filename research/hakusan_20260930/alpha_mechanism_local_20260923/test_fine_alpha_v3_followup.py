"""v3 status/watch/collect guards on synthetic snapshots; no SSH or scheduler calls."""
import copy
import unittest

import status_fine_alpha_v3 as st
import watch_fine_alpha_v3 as wa
import collect_fine_alpha_v3 as co

JOB = '756262'


def snapshot(squeue='756262|RUNNING|None|10:00|gres/gpu:nvidia_a100:1|spcc-a100g04\n', sq_rc=0,
             sacct='JobIDRaw|State|ExitCode|Elapsed|Start|End|NodeList|ReqTRES|Timelimit\n'
                   '756262|RUNNING|0:0|00:10:00|x|Unknown|spcc-a100g04|cpu=8|06:00:00\n', sa_rc=0, markers=None, blocks=None):
    blocks = blocks or {b: dict(completed_records_observed=0, worker_record_present=False) for b in 'ABC'}
    return dict(job_id=JOB, release_sha256=st.SHA, commands=dict(squeue=dict(returncode=sq_rc, stdout=squeue, stderr=''),
                sacct=dict(returncode=sa_rc, stdout=sacct, stderr='')), markers=markers or {}, blocks=blocks, log_sizes={})


class StatusTests(unittest.TestCase):
    def test_running(self):
        r = st.classify(snapshot(), JOB)
        self.assertEqual((r['scheduler_state'], r['terminal'], r['node']), ('RUNNING', False, 'spcc-a100g04'))

    def test_squeue_failure_needs_terminal_accounting(self):
        with self.assertRaisesRegex(ValueError, 'INCONCLUSIVE'): st.classify(snapshot(sq_rc=1, squeue=''), JOB)
        done = snapshot(sq_rc=1, squeue='', sacct='h\n756262|COMPLETED|0:0|05:10:00|x|y|n|r|06:00:00\n')
        r = st.classify(done, JOB); self.assertTrue(r['terminal']); self.assertEqual(r['query_warnings'], ['squeue'])

    def test_left_queue_uses_accounting(self):
        r = st.classify(snapshot(squeue='', sacct='h\n756262|FAILED|1:0|01:00:00|x|y|n|r|06:00:00\n'), JOB)
        self.assertEqual((r['scheduler_state'], r['exit_code']), ('FAILED', '1:0'))

    def test_binding_and_duplicates(self):
        with self.assertRaises(ValueError): st.classify(snapshot(), '1')
        with self.assertRaises(ValueError): st.classify(snapshot(squeue='756262|RUNNING|a\n756262|RUNNING|b\n'), JOB)
        bad = snapshot(markers={'COMPLETE.json': dict(job_id=JOB, release_sha256='0'*64, status='FINE_ALPHA_ARTIFACTS_VERIFIED')})
        with self.assertRaisesRegex(ValueError, 'COMPLETE_BINDING'): st.classify(bad, JOB)

    def test_block_failure_surfaces(self):
        blocks = {b: dict(completed_records_observed=0, worker_record_present=False) for b in 'ABC'}
        blocks['A']['output/FAILED.json'] = dict(error='X')
        self.assertEqual(st.classify(snapshot(blocks=blocks), JOB)['block_failures'], {'A': dict(error='X')})

    def test_elapsed(self):
        self.assertEqual(st.elapsed_seconds('1-00:00:01'), 86401); self.assertEqual(st.elapsed_seconds('05:40:01'), 20401)
        self.assertEqual(st.elapsed_seconds('12:30'), 750); self.assertIsNone(st.elapsed_seconds(None))
        self.assertGreater(wa.WALL_ALERT_SECONDS, 5*3600); self.assertLess(wa.WALL_ALERT_SECONDS, 6*3600)

    def test_fingerprint_tracks_progress(self):
        a = st.classify(snapshot(), JOB); b = copy.deepcopy(a); b['observed_records']['A'] = 1
        self.assertNotEqual(wa.fingerprint(a), wa.fingerprint(b)); self.assertEqual(wa.fingerprint(a), wa.fingerprint(copy.deepcopy(a)))

    def test_remotes_read_only(self):
        for remote in (st.REMOTE, co.REMOTE):
            compile(remote, '<r>', 'exec')
            for verb in ("'release'", "'update'", 'scancel', "'--hold'", '/usr/bin/sbatch', 'unlink', 'rmtree'):
                self.assertNotIn(verb, remote)
        self.assertIn('fine_alpha_20260928_v3', st.REMOTE); self.assertIn('fine_alpha_20260928_v3', co.REMOTE)
        self.assertEqual(st.EXPECTED_RECORDS, {'A': 126, 'B': 120, 'C': 120})


if __name__ == '__main__': unittest.main()

"""Synthetic scheduler regressions only; no SSH, sbatch or real checkpoints."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from build_fine_alpha_package import build
from fine_alpha_contract import BUDGET
from fine_alpha_entry import identity
from fine_alpha_submit_once import submit
from fine_alpha_submission_queue import (POLICY, validate_review, inspect_queue, metadata_fields,
                                         validate_paths, reviewed_command_sha, digest)
from test_e2_submission import response, scheduler


def reviewed(root='/independent', script=b'#!/bin/sh\npython train.py\n'):
    fields = dict(JobName='audattn_numcheck_seed20260928', UserId='s2510040(27831)',
                  Command=root+'/run_numerics_preflight.sbatch', WorkDir=root,
                  StdOut=root+'/logs/job.log', StdErr=root+'/logs/job.log')
    return dict(policy=POLICY, jobs={'754073': dict(fields=fields, command_sha256=digest(script),
                spool_sha256=digest(script), independent_outputs=True, shared_inputs_read_only=True)})


class QueuePolicyTests(unittest.TestCase):
    def setUp(self):
        self.review = reviewed(); self.calls = []
        self.fields = dict(JobId='754073', **self.review['jobs']['754073']['fields'])

    def execute(self, argv):
        self.calls.append(argv)
        if argv[0].endswith('squeue'): return response('754073|audattn_numcheck_seed20260928|RUNNING\n')
        if argv[1:3] == ['show', 'job']:
            return response(' '.join(k+'='+v for k, v in self.fields.items()))
        if argv[1:3] == ['write', 'batch_script']: return response('#!/bin/sh\npython train.py\n')
        raise AssertionError('unexpected scheduler command')

    def inspect(self, execute=None, review=None, **kwargs):
        return inspect_queue(execute or self.execute, '/scan/v3', self.review if review is None else review,
                             command_sha=lambda path: self.review['jobs']['754073']['command_sha256'], **kwargs)

    def test_reviewed_independent_audattn_job_allowed(self):
        report = self.inspect()
        self.assertEqual(report['jobs'][0]['job_id'], '754073')
        self.assertFalse(report['scheduler_quota_verified'])
        self.assertEqual(report['jobs_submitted'], 0)
        self.assertEqual(len(self.calls), 3)

    def test_empty_queue_allows_finished_reviewed_jobs(self):
        report = self.inspect(execute=lambda argv: response())
        self.assertEqual(report['jobs'], [])

    def test_missing_or_relaxed_review_rejected(self):
        bad = [None, {}, {'policy': 'skip', 'jobs': {}}, {'policy': POLICY, 'jobs': []}]
        for key in ('independent_outputs', 'shared_inputs_read_only'):
            r = copy.deepcopy(self.review); r['jobs']['754073'][key] = False; bad.append(r)
        for r in bad:
            with self.subTest(review=r), self.assertRaises(ValueError): validate_review(r)

    def test_review_owner_sha_and_noncanonical_paths_rejected(self):
        for key, value in (('UserId', 'other(27831)'), ('WorkDir', '/x/../independent'),
                           ('Command', 'relative/script'), ('StdOut', '/independent//job.log')):
            r = copy.deepcopy(self.review); r['jobs']['754073']['fields'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_review(r)
        for value in (None, 'x'*64, 'f'*63, 123):
            r = copy.deepcopy(self.review); r['jobs']['754073']['spool_sha256'] = value
            with self.assertRaises(ValueError): validate_review(r)

    def test_unknown_job_rejected_even_without_audattn_name(self):
        with self.assertRaisesRegex(ValueError, 'UNREVIEWED'):
            self.inspect(execute=lambda argv: response('99|different|RUNNING\n'))

    def test_duplicate_scan_cannot_be_approved(self):
        r = copy.deepcopy(self.review); r['jobs']['754073']['fields']['JobName'] = 'audattn_fine_alpha'
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_FINE_ALPHA'):
            self.inspect(execute=lambda argv: response('754073|audattn_fine_alpha|PENDING\n'), review=r)

    def test_disguised_scan_runner_rejected(self):
        r = copy.deepcopy(self.review)
        r['jobs']['754073']['fields']['Command'] = '/independent/run_fine_alpha.sbatch'
        self.fields['Command'] = r['jobs']['754073']['fields']['Command']
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_FINE_ALPHA'): self.inspect(review=r)

    def test_overlapping_work_log_or_command_rejected(self):
        for key in ('Command', 'WorkDir', 'StdOut', 'StdErr'):
            for path in ('/scan', '/scan/v3', '/scan/v3/state/file'):
                fields = dict(self.fields); fields[key] = path
                with self.subTest(key=key, path=path), self.assertRaisesRegex(ValueError, 'PATH_CONFLICT'):
                    validate_paths(fields, '/scan/v3')
        fields = dict(self.fields, WorkDir='/scan/v30')
        validate_paths(fields, '/scan/v3')  # Not a string-prefix false positive.

    def test_changed_metadata_rejected(self):
        original = dict(self.fields)
        for key in self.fields:
            self.fields = dict(original); self.fields[key] += '_changed'
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'IDENTITY_CHANGED'): self.inspect()

    def test_missing_duplicate_metadata_rejected(self):
        text = ' '.join(k+'='+v for k, v in self.fields.items())
        for value in (text+' JobId=754073', text.replace('JobId=754073 ', '')):
            with self.assertRaisesRegex(ValueError, 'METADATA'): metadata_fields(value)

    def test_query_error_malformed_and_duplicate_queue_rejected(self):
        for result in (response(rc=1), response('unstructured'), response('1_2|job|RUNNING\n'),
                       response('754073|audattn_numcheck_seed20260928|RUNNING\n'*2),
                       dict(returncode=False, stdout='', stderr='')):
            with self.subTest(result=result), self.assertRaises(ValueError):
                self.inspect(execute=lambda argv: result)

    def test_failed_metadata_or_spool_queries_rejected(self):
        for verb in ('show', 'write'):
            def failed(argv):
                return response(rc=1) if argv[1] == verb else self.execute(argv)
            with self.subTest(verb=verb), self.assertRaisesRegex(ValueError, 'QUERY_FAILED'):
                self.inspect(execute=failed)

    def test_command_and_spool_changes_rejected(self):
        r = copy.deepcopy(self.review); r['jobs']['754073']['command_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'COMMAND_CHANGED'): self.inspect(review=r)
        r = copy.deepcopy(self.review); r['jobs']['754073']['spool_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'SPOOL_CHANGED'): self.inspect(review=r)

    def test_script_path_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d).resolve()/'script'; p.write_bytes(b'reviewed')
            self.assertEqual(reviewed_command_sha(p), digest(b'reviewed'))
            link = p.with_name('link'); link.symlink_to(p)
            with self.assertRaisesRegex(ValueError, 'COMMAND_FILE'): reviewed_command_sha(link)

    def test_log_directory_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d).resolve(); real = base/'real'; real.mkdir()
            link = base/'linked'; link.symlink_to(real, target_is_directory=True)
            fields = dict(self.fields, StdOut=str(link/'job.log'))
            with self.assertRaisesRegex(ValueError, 'PATH_SYMLINK'):
                validate_paths(fields, str(base/'scan'))

    def test_event_stream_does_not_include_raw_script(self):
        events = []; self.inspect(record=lambda name, row: events.append((name, row)))
        spool = next(row for name, row in events if name.startswith('spool-'))
        self.assertEqual(spool['sha256'], self.review['jobs']['754073']['spool_sha256'])
        self.assertNotIn('stdout', spool)


class ConcurrentSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve(); self.root = base/'scan'; self.root.mkdir()
        self.package = self.root/'package'; self.sha = build(self.package)['release_sha256']
        other = base/'independent'; other.mkdir(); self.script = b'#!/bin/sh\npython train.py\n'
        self.review = reviewed(str(other), self.script)
        self.job = self.review['jobs']['754073']; Path(self.job['fields']['Command']).write_bytes(self.script)
        self.calls = []; self.queries = 0
        self.approval = dict(release_sha256=self.sha, budget=BUDGET, authorized=True,
                             single_held_submission_authorized=True, release_authorized=False,
                             concurrency_review=self.review)
        (self.root/'APPROVAL.json').write_text(json.dumps(self.approval))

    def execute(self, argv):
        self.calls.append(argv)
        if argv[0].endswith('squeue'):
            self.queries += 1
            return response('754073|audattn_numcheck_seed20260928|RUNNING\n')
        if '--test-only' in argv: return response()
        if '--hold' in argv: return response('123\n')
        if argv[1:3] == ['show', 'job'] and argv[-1] == '754073':
            fields = dict(JobId='754073', **self.job['fields'])
            return response(' '.join(k+'='+v for k, v in fields.items()))
        if argv[1:3] == ['write', 'batch_script']:
            return response(self.script.decode() if argv[3] == '754073' else (self.package/'run_fine_alpha.sbatch').read_text())
        r = scheduler(); r['stdout'] = r['stdout'].replace('01:00:00', '04:00:00'); return r

    def invoke(self, execute=None):
        with redirect_stdout(io.StringIO()):
            return submit(self.package, self.sha, execute=execute or self.execute)

    def test_two_live_reviews_then_exactly_one_held_submit(self):
        receipt = self.invoke()
        self.assertEqual(receipt['job_id'], '123'); self.assertEqual(self.queries, 2)
        self.assertEqual(sum('--hold' in a for a in self.calls), 1)
        self.assertFalse(any('release' in a or 'update' in a or 'scancel' in a[0] for a in self.calls))
        intent = json.loads((self.root/'state/INTENT.json').read_text())
        self.assertEqual(intent['queue_review'], identity(self.root/'state/QUEUE_FINAL.json'))
        with self.assertRaises(FileExistsError): self.invoke()
        self.assertEqual(sum('--hold' in a for a in self.calls), 1)

    def test_unreviewed_before_state_creates_no_attempt(self):
        with self.assertRaisesRegex(ValueError, 'UNREVIEWED'):
            self.invoke(execute=lambda argv: response('99|independent_new_job|PENDING\n'))
        self.assertFalse((self.root/'state').exists())

    def test_missing_concurrency_review_no_calls(self):
        self.approval.pop('concurrency_review')
        (self.root/'APPROVAL.json').write_text(json.dumps(self.approval))
        with self.assertRaisesRegex(ValueError, 'CONCURRENCY_REVIEW'): self.invoke()
        self.assertEqual(self.calls, []); self.assertFalse((self.root/'state').exists())

    def test_new_conflict_between_reviews_no_hold(self):
        def changed(argv):
            result = self.execute(argv)
            if argv[0].endswith('squeue') and self.queries == 2:
                return response('100|audattn_fine_alpha|PENDING\n')
            return result
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'): self.invoke(changed)
        self.assertFalse(any('--hold' in a for a in self.calls))
        state = self.root/'state'
        self.assertTrue((state/'QUEUE_FINAL.json').exists())
        self.assertFalse((state/'INTENT.json').exists())
        self.assertFalse(json.loads((state/'STOPPED.json').read_text())['submission_may_have_happened'])
        with self.assertRaises(FileExistsError): self.invoke()

    def test_approval_changes_after_test_only_no_hold(self):
        def changed(argv):
            result = self.execute(argv)
            if '--test-only' in argv:
                (self.root/'APPROVAL.json').write_text(json.dumps(dict(self.approval, changed=True)))
            return result
        with self.assertRaisesRegex(ValueError, 'APPROVAL_CHANGED'): self.invoke(changed)
        self.assertFalse(any('--hold' in a for a in self.calls))

    def test_script_changed_before_first_review_no_state(self):
        Path(self.job['fields']['Command']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'COMMAND_CHANGED'): self.invoke()
        self.assertFalse((self.root/'state').exists())

    def test_frozen_v3_contract_matched_v2_except_scope(self):
        # Historical check, now between the two frozen packages (the source tree holds V4).
        v2 = Path(__file__).parent/'release_fine_alpha_20260928_candidate_v2/package'
        v3 = Path(__file__).parent/'release_fine_alpha_20260928_candidate_v3/package'
        left = dict(json.loads((v2/'RELEASE.json').read_text())['contract'])
        right = dict(json.loads((v3/'RELEASE.json').read_text())['contract'])
        self.assertEqual(left.pop('scope'), 'FINE_ALPHA_001_20260928_V2')
        self.assertEqual(right.pop('scope'), 'FINE_ALPHA_001_20260928_V3')
        self.assertEqual(left, right)

    def test_v4_changes_only_grid_blocks_counts_budget_and_anchor(self):
        v3 = Path(__file__).parent/'release_fine_alpha_20260928_candidate_v3/package'
        old = dict(json.loads((v3/'RELEASE.json').read_text())['contract'])
        new = dict(json.loads((self.package/'RELEASE.json').read_text())['contract'])
        changed = {'scope', 'alpha_integer_milli', 'process_order', 'block_passes', 'predictions', 'block_predictions',
                   'science_predictions', 'budget'}
        self.assertEqual(set(new) - set(old), {'anchor_job', 'anchor_alpha_integer_milli'})
        self.assertEqual(new['anchor_job'], '756262'); self.assertEqual(new['anchor_alpha_integer_milli'], [500, 750])
        for key in set(old) - changed: self.assertEqual(old[key], new[key], key)   # model, bank, freeze, layout, formula, roles
        self.assertEqual(new['budget'], dict(old['budget'], wall_minutes=240, coordinator_deadline_seconds=13800))
        # Whole manifest: only the files V4 had to change may differ from the frozen V3 package; every other file
        # (gain adapter, providers, loaders, inputs, bank, reference arrays...) must be byte-identical, because the
        # 0.50/0.75 anchors to 756262 depend on them.
        old_files = json.loads((v3/'RELEASE.json').read_text())['files']
        new_files = json.loads((self.package/'RELEASE.json').read_text())['files']
        self.assertEqual(set(new_files), set(old_files))
        changed = {k for k in new_files if new_files[k] != old_files[k]}
        self.assertEqual(changed, {'fine_alpha_archive.py', 'fine_alpha_contract.py', 'fine_alpha_entry.py',
                                   'fine_alpha_execution.py', 'fine_alpha_pipeline.py', 'fine_alpha_submit_once.py',
                                   'run_fine_alpha.sbatch'})

if __name__ == '__main__': unittest.main()

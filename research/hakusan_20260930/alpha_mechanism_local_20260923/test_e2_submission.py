import json
from pathlib import Path
import tempfile
import unittest
from build_e2_package import build
from e2_entry import profile_spec
from e2_submit_once import submit,check_job_resources

def response(text='',rc=0): return dict(returncode=rc,stdout=text,stderr='')
def scheduler():
    return response('JobId=123 UserId=s2510040(27831) Requeue=0 Restarts=0 Partition=GPU-1A Account=student NumNodes=1-1 NumCPUs=8 NumTasks=1 '
        'TimeLimit=01:00:00 JobState=PENDING Reason=JobHeldUser Priority=0 '
        'ReqTRES=cpu=8,mem=64G,node=1,billing=8,gres/gpu:nvidia_a100=1 TresPerNode=gres/gpu:nvidia_a100:1')

class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.package=self.root/'package'
        self.sha=build(self.package,'pilot')['release_sha256']; self.calls=[]
    def approval(self):
        (self.root/'APPROVAL.json').write_text(json.dumps(dict(release_sha256=self.sha,budget=profile_spec('pilot')['budget'],
            authorized=True,single_held_submission_authorized=True,release_authorized=False)))
    def execute(self,argv):
        self.calls.append(argv)
        if argv[0].endswith('squeue'): return response()
        if '--test-only' in argv: return response()
        if '--hold' in argv: return response('123\n')
        if argv[1:3]==['write','batch_script']: return response((self.package/'run_e2.sbatch').read_text())
        return scheduler()
    def test_held_once_no_release(self):
        self.approval(); r=submit(self.package,self.sha,execute=self.execute)
        self.assertEqual(r['job_id'],'123')
        self.assertEqual(sum('--hold' in a for a in self.calls),1)
        self.assertFalse(any('release' in a or 'update' in a for a in self.calls))
        with self.assertRaises(FileExistsError): submit(self.package,self.sha,execute=self.execute)
        self.assertEqual(sum('--hold' in a for a in self.calls),1)
    def test_missing_approval_no_scheduler_calls(self):
        with self.assertRaises(ValueError): submit(self.package,self.sha,execute=self.execute)
        self.assertEqual(self.calls,[])
    def test_uncertain_response_no_retry(self):
        self.approval()
        def unknown(argv):
            if '--hold' in argv:
                self.calls.append(argv); return response('unparseable')
            return self.execute(argv)
        with self.assertRaisesRegex(ValueError,'UNKNOWN'): submit(self.package,self.sha,execute=unknown)
        self.assertEqual(sum('--hold' in a for a in self.calls),1)
        self.assertTrue((self.root/'state/STOPPED.json').exists())
    def test_site_rewrite_preserves_receipt_without_repair(self):
        self.approval()
        def changed(argv):
            if argv[1:3]==['show','job']:
                r=scheduler();r['stdout']=r['stdout'].replace('gres/gpu:nvidia_a100','gres/gpu');return r
            return self.execute(argv)
        with self.assertRaisesRegex(ValueError,'TYPED_GRES'): submit(self.package,self.sha,execute=changed)
        self.assertEqual(json.loads((self.root/'state/SUBMISSION.json').read_text())['job_id'],'123')
        self.assertFalse(any('update' in a for a in self.calls))
    def test_historical_site_resource_format(self):
        p=Path(__file__).parent/'release_e1_20260927_v3/release-750474/remote.jsonl'
        row=next(json.loads(s) for s in p.read_text().splitlines() if json.loads(s)['stage']=='before')
        budget=dict(profile_spec('pilot')['budget'],wall_minutes=180)
        self.assertEqual(check_job_resources(row,'750474',budget,held=True)['job_id'],'750474')
    def test_resource_mutations(self):
        for old,new in [('NumCPUs=8','NumCPUs=16'),('mem=64G','mem=128G'),
                        ('TimeLimit=01:00:00','TimeLimit=02:00:00'),('Priority=0','Priority=1')]:
            r=scheduler();r['stdout']=r['stdout'].replace(old,new)
            with self.subTest(new=new),self.assertRaises(ValueError):
                check_job_resources(r,'123',profile_spec('pilot')['budget'],held=True)
    def test_running_allocation_gate(self):
        r=scheduler(); r['stdout']=r['stdout'].replace('JobState=PENDING','JobState=RUNNING')
        self.assertFalse(check_job_resources(r,'123',profile_spec('pilot')['budget'],held=False)['held'])
        with self.assertRaises(ValueError): check_job_resources(r,'123',profile_spec('pilot')['budget'],held=True)

if __name__=='__main__': unittest.main()

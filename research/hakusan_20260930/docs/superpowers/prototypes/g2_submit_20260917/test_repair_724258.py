"""Replay downloaded real held evidence; all mutation RPCs are test doubles."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).absolute().parent
sys.path.insert(0, str(HERE))
import control as c
import repair_724258 as r
from test_control import FakeContext, result

FIXTURE = Path(sys.argv.pop(1)).absolute()
receipt = json.loads(c.read(FIXTURE/'RECEIPT.json'))
assert receipt['returncode'] == 0 and receipt['result']['ok'] is True
assert c.sha(c.read(FIXTURE/'output.log', 8*1024**2)) == receipt['output_sha256']
assert c.sha(c.read(FIXTURE/'request.py', 16*1024**2)) == receipt['payload_sha256']
OBSERVED = receipt['result']['result']


class RPC:
    def __init__(self, context):
        self.context = context
        self.data = copy.deepcopy(OBSERVED['snapshot'])
        self.calls, self.updates, self.releases = [], 0, 0
        self.fail, self.bad_readback = None, False

    def __call__(self, argv):
        self.calls.append(argv)
        if argv == r.UPDATE:
            self.updates += 1
            assert (self.context.state/'GPU_TYPE_UPDATE_INTENT.json').exists()
            if self.fail == 'update': return result(argv, rc=1)
            if self.fail == 'raise': raise OSError('simulated transport uncertainty')
            if not self.bad_readback:
                self.data['job']['stdout'] = self.data['job']['stdout'].replace(
                    'gres/gpu:h100-20c=1', 'gres/gpu:nvidia_a100=1').replace(
                    'TresPerNode=gres/gpu:1', 'TresPerNode='+r.GPU+' TresPerJob='+r.GPU)
                self.data['accounting']['stdout'] = self.data['accounting']['stdout'].replace(
                    'gres/gpu:h100-20c=1', 'gres/gpu:nvidia_a100=1')
            return result(argv)
        if argv == r.RELEASE:
            self.releases += 1
            assert (self.context.state/'RELEASE_INTENT.json').exists()
            if self.fail == 'release': return result(argv, rc=1)
            self.data['job']['stdout'] = self.data['job']['stdout'].replace(
                'Reason=JobHeldUser', 'Reason=Resources').replace('Priority=0', 'Priority=100')
            return result(argv)
        for value in self.data.values():
            if value['argv'] == argv: return copy.deepcopy(value)
        raise AssertionError('unexpected RPC '+repr(argv))


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name).resolve()
        self.context = FakeContext(root)
        for p in self.context.e.ORDER:
            (root/p/'attempts').mkdir(parents=True, mode=0o700)
        plan = c.decode(c.read(HERE.parents[3]/'docs/superpowers/evidence/g2-production-20260917/EXECUTION_PLAN.json'), r.PLAN)
        self.context.plan, self.context.plan_raw = plan, c.wire(plan)
        self.context.plan_sha, self.context.control_sha = r.PLAN, r.CONTROL
        c.write_once(root/'RUN_REQUEST.json', self.context.request(r.JOB))
        for name, value in OBSERVED['journals'].items():
            c.write_once(self.context.state/name, value)
        self.rpc = RPC(self.context)
        self.spec = dict(action='update', repair_sha256=c.sha(c.read(HERE/'repair_724258.py')))

    def update(self):
        return r.mutate(c, self.context, self.spec, self.rpc)

    def release(self):
        return r.mutate(c, self.context, dict(self.spec, action='release'), self.rpc)

    def test_actual_original_binding_and_held_snapshot(self):
        r.checked(c, self.context)
        r.validate(c, self.context, self.rpc.data, corrected=False)
        with self.assertRaises(RuntimeError):
            r.validate(c, self.context, self.rpc.data, corrected=True)

    def test_one_same_job_update_then_release(self):
        self.assertEqual(self.update()['status'], 'A100_CORRECTED_STILL_HELD')
        self.assertEqual(self.rpc.releases, 0)
        self.assertEqual(self.release()['status'], 'SAME_JOB_RELEASED')
        self.assertEqual((self.rpc.updates, self.rpc.releases), (1, 1))
        self.assertFalse(any('sbatch' in a[0] for a in self.rpc.calls))

    def test_reject_already_corrected_update(self):
        self.update()
        with self.assertRaises(RuntimeError): self.update()
        self.assertEqual(self.rpc.updates, 1)

    def test_no_second_release(self):
        self.update(); self.release()
        with self.assertRaises(RuntimeError): self.release()
        self.assertEqual(self.rpc.releases, 1)

    def test_release_without_verified_update_rejected(self):
        with self.assertRaises(RuntimeError): self.release()
        self.assertEqual(self.rpc.releases, 0)

    def test_failed_update_consumes_intent(self):
        self.rpc.fail = 'update'
        with self.assertRaises(RuntimeError): self.update()
        with self.assertRaises(FileExistsError): self.update()
        self.assertEqual(self.rpc.updates, 1)

    def test_uncertain_update_consumes_intent(self):
        self.rpc.fail = 'raise'
        with self.assertRaises(OSError): self.update()
        with self.assertRaises(FileExistsError): self.update()
        self.assertEqual(self.rpc.updates, 1)

    def test_bad_update_readback_no_release(self):
        self.rpc.bad_readback = True
        with self.assertRaises(RuntimeError): self.update()
        with self.assertRaises(RuntimeError): self.release()
        self.assertEqual(self.rpc.releases, 0)

    def test_failed_release_not_repeated(self):
        self.update(); self.rpc.fail = 'release'
        with self.assertRaises(RuntimeError): self.release()
        with self.assertRaises(RuntimeError): self.release()
        self.assertEqual(self.rpc.releases, 1)

    def test_source_drift_stops_before_rpc(self):
        self.context.broken = True
        with self.assertRaises(RuntimeError): self.update()
        self.assertFalse(self.rpc.calls)

    def test_started_attempt_stops_before_rpc(self):
        (self.context.root/'R/attempts/slurm-724258').mkdir()
        with self.assertRaises(RuntimeError): self.update()
        self.assertFalse(self.rpc.calls)

    def test_changed_identity_or_budget_rejected(self):
        for old, new in (('JobId=724258','JobId=724259'), ('NumCPUs=8','NumCPUs=16'),
                         ('TimeLimit=03:00:00','TimeLimit=04:00:00'), ('Reason=JobHeldUser','Reason=Resources'),
                         ('AllocTRES=(null)','AllocTRES=cpu=8'), ('RunTime=00:00:00','RunTime=00:00:01'),
                         ('gres/gpu:h100-20c=1','gres/gpu:h100-20c=2'), ('Requeue=0','Requeue=1')):
            data = copy.deepcopy(self.rpc.data)
            data['job']['stdout'] = data['job']['stdout'].replace(old, new)
            with self.subTest(old=old), self.assertRaises(RuntimeError):
                r.validate(c, self.context, data, corrected=False)

    def test_extra_resources_rejected(self):
        data = copy.deepcopy(self.rpc.data)
        data['job']['stdout'] += ' TresPerSocket=gres/gpu:1'
        with self.assertRaises(RuntimeError): r.validate(c, self.context, data, corrected=False)

    def test_accounting_disagreement_rejected(self):
        data = copy.deepcopy(self.rpc.data)
        data['accounting']['stdout'] = data['accounting']['stdout'].replace('h100-20c','nvidia_a100')
        with self.assertRaises(RuntimeError): r.validate(c, self.context, data, corrected=False)

    def test_other_active_job_rejected(self):
        data = copy.deepcopy(self.rpc.data)
        data['queue']['stdout'] += '724259|PENDING|other|other\n'
        with self.assertRaises(RuntimeError): r.validate(c, self.context, data, corrected=False)

    def test_changed_repair_before_release_rejected(self):
        self.update()
        with self.assertRaises(RuntimeError):
            r.mutate(c, self.context, dict(action='release', repair_sha256='0'*64), self.rpc)
        self.assertEqual(self.rpc.releases, 0)

    def test_original_intent_drift_rejected(self):
        p = self.context.state/'INTENT.json'
        value = json.loads(c.read(p)); value['confirmation'] = 'not-approved'
        p.write_bytes(c.wire(value))
        with self.assertRaises(RuntimeError): self.update()
        self.assertFalse(self.rpc.calls)


if __name__ == '__main__':
    unittest.main(verbosity=2)

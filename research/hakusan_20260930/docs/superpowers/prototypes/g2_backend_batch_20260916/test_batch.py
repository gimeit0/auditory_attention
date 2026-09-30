"""Fail-closed CPU scheduler contract and preserved source/fixture tests."""
import base64
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import struct
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c
import remote
import driver
import verify

NONCE = 'a' * 32
DIGEST = 'b' * 64


def job_text(root, held=True):
    f = dict(JobId='12345', JobName=c.JOB_NAME, Partition='TINY', Account='student', UserId='s2510040(1000)',
        NumCPUs='1', NumTasks='1', NumNodes='1', TimeLimit='00:10:00', Requeue='0', Restarts='0',
        MinMemoryNode='6000M', Comment='g2-backend-cpu-' + NONCE, WorkDir=str(root), StdIn='/dev/null',
        StdOut=str(root / 'logs/cpu_12345.log'), StdErr=str(root / 'logs/cpu_12345.log'),
        Command=str(root / 'package' / c.PREFIX / 'run_cpu.sbatch'), ReqTRES='cpu=1,mem=6000M,node=1,billing=1',
        JobState='PENDING' if held else 'RUNNING', Reason='JobHeldUser' if held else 'None',
        Priority='0', RunTime='00:00:00', NodeList='' if held else 'lcpcc-001',
        AllocTRES='(null)' if held else 'cpu=1,mem=6000M,node=1,billing=1')
    f['CPUs/Task'] = '1'
    return ' '.join(k + '=' + v for k, v in f.items())


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def spec(self):
        raw = c.wire(dict(release_sha256=DIGEST, result=dict(returncode=0)))
        c.write(self.root / 'TEST_ONLY.json', raw)
        return dict(confirm=c.CONFIRM, nonce=NONCE, release_sha256=DIGEST, test_sha256=c.sha(raw))

    def execute(self, argv):
        self.calls.append(argv)
        output = ''
        if argv[0] == '/usr/bin/sbatch':
            self.assertTrue((self.root / 'INTENT.json').is_file())
            output = '12345\n'
        elif 'show' in argv:
            output = job_text(self.root)
        return dict(returncode=0, stdout=output, stderr='')

    def test_exact_held_and_running(self):
        for held in (True, False):
            c.job_check(job_text(self.root, held), '12345', NONCE, self.root, held=held)

    def test_resource_mutations_rejected(self):
        original = job_text(self.root)
        for old, new in [('NumCPUs=1', 'NumCPUs=2'), ('mem=6000M', 'mem=8192M'),
                         ('billing=1', 'billing=1,gres/gpu=1'), ('00:10:00', '00:20:00'),
                         ('Requeue=0', 'Requeue=1'), ('Restarts=0', 'Restarts=1'),
                         ('Partition=TINY', 'Partition=GPU-1A'), ('CPUs/Task=1', 'CPUs/Task=2')]:
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                c.job_check(original.replace(old, new), '12345', NONCE, self.root, held=True)

    def test_identity_hold_mutations_rejected(self):
        for old, new in [('s2510040', 'other'), (NONCE, 'c' * 32), ('JobHeldUser', 'Resources'),
                         ('Priority=0', 'Priority=100'), ('AllocTRES=(null)', 'AllocTRES=cpu=1,mem=6000M,node=1,billing=1'),
                         ('NodeList=', 'NodeList=lcpcc-001'), ('run_cpu.sbatch', 'other.sbatch')]:
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                c.job_check(job_text(self.root).replace(old, new), '12345', NONCE, self.root, held=True)

    def test_array_and_duplicate_fields_rejected(self):
        for extra in (' ArrayJobId=12345', ' HetJobId=12345', ' NumCPUs=1', ' TresPerNode=gres/gpu:1'):
            with self.subTest(extra=extra), self.assertRaises(RuntimeError):
                c.job_check(job_text(self.root) + extra, '12345', NONCE, self.root, held=True)

    def test_source_inventory_and_hash(self):
        raw, files, _ = driver.sources()
        self.assertEqual(len(files), 10)
        driver.unpack(self.root, raw, files)
        c.source_check(self.root / 'package', c.release(raw, c.sha(raw)))
        target = self.root / 'package' / c.PREFIX / 'runtime.py'
        target.write_bytes(target.read_bytes() + b'\n')
        with self.assertRaises(RuntimeError):
            c.source_check(self.root / 'package', c.release(raw, c.sha(raw)))

    def test_extra_member_rejected(self):
        raw, files, _ = driver.sources()
        driver.unpack(self.root, raw, files)
        c.write(self.root / 'package/extra.py', b'')
        with self.assertRaises(RuntimeError):
            c.source_check(self.root / 'package', c.release(raw, c.sha(raw)))

    def test_release_limits_immutable(self):
        raw, _, _ = driver.sources()
        for key, value in [('cpus', 2), ('gpus', 1), ('wall_seconds', 601), ('memory_mib', 8192)]:
            altered = json.loads(raw)
            altered['limits'][key] = value
            b = c.wire(altered)
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                c.release(b, c.sha(b))

    def test_path_escape_rejected(self):
        for name in ('../x', '/tmp/x', 'a/../x', 'a//b', 'a\\b', ''):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                c.member(name)

    def test_symlink_rejected(self):
        p = self.root / 'link'
        p.symlink_to('/etc/passwd')
        with self.assertRaises(RuntimeError):
            c.read(p)

    def test_write_once(self):
        c.write(self.root / 'intent', b'x')
        with self.assertRaises(FileExistsError):
            c.write(self.root / 'intent', b'y')
        self.assertEqual(c.read(self.root / 'intent'), b'x')

    def test_exact_sbatch_arguments(self):
        for test in (False, True):
            argv = remote.batch_argv(self.root, DIGEST, NONCE, test)
            self.assertIn('--test-only' if test else '--hold', argv)
            self.assertIn('--mem=6000M', argv)
            self.assertIn('--cpus-per-task=1', argv)
            self.assertIn('--time=00:10:00', argv)
            self.assertFalse(any('gres' in s or '--gpus' in s for s in argv))
            self.assertEqual(argv[-2:], [DIGEST, NONCE])

    def test_shell_syntax(self):
        p = subprocess.run(['/bin/bash', '-n', str(driver.HERE / 'run_cpu.sbatch')], capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_single_submit_then_release(self):
        spec = self.spec()
        result = remote.submit(spec, self.execute, self.root)
        self.assertEqual(result['status'], 'CPU_JOB_RELEASED')
        self.assertEqual(sum(a[0] == '/usr/bin/sbatch' for a in self.calls), 1)
        self.assertEqual(sum('release' in a for a in self.calls), 1)
        with self.assertRaises(FileExistsError):
            remote.submit(spec, self.execute, self.root)
        self.assertEqual(sum(a[0] == '/usr/bin/sbatch' for a in self.calls), 1)

    def test_uncertain_submit_keeps_intent_never_retries(self):
        spec = self.spec()
        def fail(argv):
            self.calls.append(argv)
            if argv[0] == '/usr/bin/sbatch':
                raise TimeoutError('uncertain')
            return dict(returncode=0, stdout='', stderr='')
        with self.assertRaises(TimeoutError):
            remote.submit(spec, fail, self.root)
        with self.assertRaises(FileExistsError):
            remote.submit(spec, fail, self.root)
        self.assertEqual(sum(a[0] == '/usr/bin/sbatch' for a in self.calls), 1)

    def test_wrong_held_resources_never_release(self):
        spec = self.spec()
        def wrong(argv):
            result = self.execute(argv)
            if 'show' in argv:
                result['stdout'] = result['stdout'].replace('NumCPUs=1', 'NumCPUs=2')
            return result
        with self.assertRaises(RuntimeError):
            remote.submit(spec, wrong, self.root)
        self.assertFalse(any('release' in a for a in self.calls))
        self.assertTrue((self.root / 'SUBMISSION_RECEIPT.json').exists())

    def test_failed_test_blocks_submission(self):
        spec = self.spec()
        spec['test_sha256'] = '0' * 64
        with self.assertRaises(RuntimeError):
            remote.submit(spec, self.execute, self.root)
        self.assertFalse(self.calls)
        self.assertFalse((self.root / 'INTENT.json').exists())

    def test_queue_blocks_submission(self):
        spec = self.spec()
        def busy(argv):
            return dict(returncode=0, stdout='456|RUNNING|other\n', stderr='')
        with self.assertRaises(RuntimeError):
            remote.submit(spec, busy, self.root)
        self.assertFalse((self.root / 'INTENT.json').exists())

    def test_release_failure_persists_response(self):
        spec = self.spec()
        def fail(argv):
            result = self.execute(argv)
            if 'release' in argv:
                result['returncode'] = 1
            return result
        with self.assertRaises(RuntimeError):
            remote.submit(spec, fail, self.root)
        self.assertTrue((self.root / 'RELEASE_INTENT.json').exists())
        self.assertTrue((self.root / 'RELEASE_RESPONSE.json').exists())

    def tensor(self, value=0.25, shape=None):
        shape = shape or [1,8]
        raw = struct.pack('<' + str(shape[0]*shape[1]) + 'f', *([value]*(shape[0]*shape[1])))
        return dict(dtype='float32',shape=shape,sha256=c.sha(raw),bytes_b64=base64.b64encode(raw).decode())

    def values(self):
        state = dict(weights={'linear.weight':self.tensor()},inputs=[self.tensor()],rng_sha256='0'*64,
            runtime=[True,True,False,'highest',False,False],training=[False,False],requires_grad=[False,False])
        a = dict(status='NATIVE_CPU_CHILD_PASS',role='reference',job_id='12345',release_sha256=DIGEST,nonce=NONCE,
            python='3.11.5',torch='2.1.1+cu118',affinity=[0],threads=1,interop_threads=1,source_postcheck=True,
            profiler_removed=True,cuda_initialized=False,production_model_loaded=False,ready_for_gpu=False,
            before=state,after=copy.deepcopy(state),outputs=[self.tensor(shape=[16,8]),self.tensor()],
            eager=[self.tensor(shape=[16,8]),self.tensor()],backend=None,pid=10,cache_root='/tmp/reference')
        b = copy.deepcopy(a)
        b.update(role='observed',pid=11,cache_root='/tmp/observed',backend=dict(compiler_calls=2,compiler_returns=2,
            target_generated_artifacts_executed=True,production_ready=False,interference_validated=False,
            artifacts=[dict(source=base64.b64encode(b'x').decode(),sha256=c.sha(b'x'),path='/tmp/observed/x',calls=1,returns=1)]))
        return a,b

    def test_numeric_pair_pass_is_scoped(self):
        a,b = self.values()
        result = verify.pair(a,b,DIGEST,NONCE,'12345')
        self.assertTrue(result['bit_exact'])
        self.assertFalse(result['ready_for_gpu'])
        self.assertFalse(result['production_interference_validated'])

    def test_numeric_difference_rejected(self):
        a,b = self.values()
        b['outputs'][0] = self.tensor(0.26,[16,8])
        with self.assertRaises(RuntimeError):
            verify.pair(a,b,DIGEST,NONCE,'12345')

    def test_bad_tensor_hash_and_nonfinite_rejected(self):
        for row in [self.tensor(float('nan')), {**self.tensor(),'sha256':'0'*64}]:
            with self.assertRaises(RuntimeError):
                verify.decode(row)

    def test_missing_backend_or_execution_rejected(self):
        for key,value in [('compiler_returns',0),('target_generated_artifacts_executed',False),('artifacts',[])]:
            a,b = self.values()
            b['backend'][key] = value
            with self.assertRaises(RuntimeError):
                verify.pair(a,b,DIGEST,NONCE,'12345')

    def test_same_pid_or_cache_rejected(self):
        for key in ('pid','cache_root'):
            a,b = self.values()
            b[key] = a[key]
            with self.assertRaises(RuntimeError):
                verify.pair(a,b,DIGEST,NONCE,'12345')

    def test_state_mutation_or_mismatched_input_rejected(self):
        a,b = self.values()
        b['after']['runtime'][0] = False
        with self.assertRaises(RuntimeError):
            verify.pair(a,b,DIGEST,NONCE,'12345')
        a,b = self.values()
        b['before']['inputs'] = b['after']['inputs'] = [self.tensor(0.4)]
        with self.assertRaises(RuntimeError):
            verify.pair(a,b,DIGEST,NONCE,'12345')

    def test_supervisor_timeout_preserves_stage_log(self):
        import importlib.util
        p = driver.HERE.parent/'targeted_gpu_job_20260915_v5/process_runner.py'
        spec = importlib.util.spec_from_file_location('test_supervisor',p)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.run_process([sys.executable,'-I','-B','-c',
            'import time; print("stage",flush=True); time.sleep(20)'],{},self.root/'child.log',seconds=0.4,max_log_bytes=1024)
        self.assertEqual(result['error']['type'],'TimeoutError')
        self.assertEqual(result['returncode'],-9)
        self.assertIn(b'stage',c.read(self.root/'child.log'))


if __name__ == '__main__':
    unittest.main(verbosity=2)

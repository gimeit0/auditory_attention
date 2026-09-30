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
import time
import types
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c
import remote
import driver
import verify
import runtime

NONCE = 'a' * 32
DIGEST = 'b' * 64


def job_text(root, held=True):
    f = dict(JobId='12345', JobName=c.JOB_NAME, Partition='TINY', Account='student', UserId='s2510040(1000)',
        NumCPUs='1', NumTasks='1', NumNodes='1', TimeLimit='00:22:00', Requeue='0', Restarts='0',
        MinMemoryNode='6000M', Comment='g2-bridge-cpu-' + NONCE, WorkDir=str(root), StdIn='/dev/null',
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
                         ('billing=1', 'billing=1,gres/gpu=1'), ('00:22:00', '00:20:00'),
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
        self.assertEqual(len(files), 30)
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
            self.assertIn('--time=00:22:00', argv)
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

    def synthetic_records(self):
        # Contract-test doubles derived from the fixed LOCAL eager outputs.
        # These fabricated native labels are NOT native execution evidence.
        snapshot = driver.ROOT / 'docs/superpowers/evidence/g2-paired-local-20260916T044126Z-o3f8g1xe'
        values = {}
        for i, stage in enumerate(runtime.ORDER):
            profile, role = stage.split('-')
            old = 'D' if profile == 'R' else 'E'
            value = json.loads(c.read(snapshot / (old + '-' + role + '.json')))
            value.update(scope=verify.protocol().NATIVE_SCOPE, profile=profile, pid=100+i,
                python='3.11.5', torch='2.1.1+cu118', allocation_job_id='12345', nonce=NONCE,
                compiler_lifecycle_verified=True, compiler_target_verified=True,
                release_sha256=c.CORE_SHA, cache_root='/tmp/unit-contract-only/' + stage)
            if role == 'observed':
                value['backend'] = dict(compiler_calls=1, compiler_returns=1,
                    compiler_sources=verify.protocol().COMPILER_PINS,
                    target_generated_artifacts_executed=True, production_ready=False, interference_validated=False,
                    artifacts=[dict(source=base64.b64encode(b'unit fixture only').decode(),
                        sha256=c.sha(b'unit fixture only'), calls=1, returns=1,
                        path=value['cache_root'] + '/generated.py', key='unit-fixture')])
            values[stage] = value
        return values

    def test_four_stage_contract_scope(self):
        result = verify.matrix(self.synthetic_records(), NONCE, '12345')
        self.assertEqual([r['profile'] for r in result['pairs']], ['R', 'C'])
        self.assertTrue(all(r['bit_exact'] for r in result['pairs']))
        self.assertFalse(result['ready_for_gpu'])

    def test_cross_profile_pid_and_cache_reuse_rejected(self):
        for key in ('pid', 'cache_root'):
            values = self.synthetic_records()
            values['C-reference'][key] = values['R-reference'][key]
            with self.assertRaises(RuntimeError): verify.matrix(values, NONCE, '12345')

    def test_stage_profile_order_partial_rejected(self):
        original = self.synthetic_records()
        variants = [dict(reversed(list(original.items()))), {k:v for k,v in original.items() if k != 'C-observed'}]
        wrong = copy.deepcopy(original)
        wrong['R-reference'] = copy.deepcopy(original['C-reference'])
        wrong['R-observed'] = copy.deepcopy(original['C-observed'])
        wrong['R-reference']['pid'] = 999; wrong['R-reference']['cache_root'] += '/wrong'
        wrong['R-observed']['pid'] = 998; wrong['R-observed']['cache_root'] += '/wrong'
        variants.append(wrong)
        for values in variants:
            with self.assertRaises(RuntimeError): verify.matrix(values, NONCE, '12345')

    def test_compiler_missing_return_source_and_scope_rejected(self):
        for key, value in [('compiler_returns', 0), ('compiler_sources', {}), ('artifacts', []),
                           ('target_generated_artifacts_executed', False), ('production_ready', True)]:
            values = self.synthetic_records()
            values['R-observed']['backend'][key] = value
            with self.assertRaises(RuntimeError): verify.matrix(values, NONCE, '12345')

    def test_native_job_binding_rejected(self):
        values = self.synthetic_records()
        values['C-observed']['allocation_job_id'] = '54321'
        with self.assertRaises(RuntimeError): verify.matrix(values, NONCE, '12345')

    def test_core_release_independent_of_batch_release(self):
        raw, files, _ = driver.sources()
        driver.unpack(self.root, raw, files)
        runtime.core_check(self.root)
        self.assertNotEqual(c.sha(raw), c.CORE_SHA)
        self.assertEqual(c.sha(c.read(self.root / 'RELEASE.json')), c.CORE_SHA)

    def test_four_stage_launcher_argv_budget_and_no_retry(self):
        values, commands = self.synthetic_records(), []
        folder, scratch = self.root / 'attempt', self.root / 'scratch'
        folder.mkdir(mode=0o700); scratch.mkdir(mode=0o700)
        def execute(argv, env, log, *, seconds, max_log_bytes):
            commands.append(argv)
            self.assertEqual(argv[4], 'native')
            self.assertEqual(argv[-2:], [c.CORE_SHA, NONCE])
            self.assertTrue(0 < seconds <= 300)
            self.assertEqual(max_log_bytes, 4*1024**2)
            self.assertEqual(env['CUDA_VISIBLE_DEVICES'], '')
            stage = argv[5] + '-' + argv[6]
            value = copy.deepcopy(values[stage])
            value['cache_root'] = env['TORCHINDUCTOR_CACHE_DIR']
            if value['backend']:
                value['backend']['artifacts'][0]['path'] = value['cache_root'] + '/generated.py'
            c.write(Path(argv[7]), c.wire(value)); c.write(log, b'synthetic launcher fixture\n')
            return dict(returncode=0, error=None, pid=value['pid'])
        runtime.stages(self.root, folder, scratch, types.SimpleNamespace(run_process=execute), NONCE, '12345', time.monotonic())
        self.assertEqual([a[5]+'-'+a[6] for a in commands], list(runtime.ORDER))
        self.assertTrue((folder / 'PAIR.json').exists())
        with self.assertRaises(FileExistsError):
            runtime.stages(self.root, folder, scratch, types.SimpleNamespace(run_process=execute), NONCE, '12345', time.monotonic())
        self.assertEqual(len(commands), 4)

    def test_failed_first_child_stops_and_retains_log(self):
        folder, scratch = self.root / 'attempt', self.root / 'scratch'
        folder.mkdir(mode=0o700); scratch.mkdir(mode=0o700)
        calls = []
        def execute(argv, env, log, **kwargs):
            calls.append(argv); c.write(log, b'original failure\n')
            return dict(returncode=2, error=None, pid=100)
        with self.assertRaisesRegex(RuntimeError, 'child failed: R-reference'):
            runtime.stages(self.root, folder, scratch, types.SimpleNamespace(run_process=execute), NONCE, '12345', time.monotonic())
        self.assertEqual(len(calls), 1)
        self.assertEqual(c.read(folder / 'R-reference/child.log'), b'original failure\n')
        self.assertTrue((folder / 'R-reference/process.json').exists())
        self.assertFalse((folder / 'R-observed').exists())
        self.assertFalse((folder / 'PAIR.json').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)

"""No production fixtures or GPU. Scheduler rows below are explicit test data."""
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest

HERE = Path(__file__).absolute().parent
sys.path.insert(0, str(HERE))
import entry as e
import runtime as r
import build_release as b
import bootstrap


def request():
    return dict(schema_version=1, protocol=e.REMOTE.name, job_id='123456', nonce='a'*32,
                release_sha256='b'*64, freezes={p:'c'*64 for p in e.ORDER}, limits=dict(e.LIMITS), partition='TEST_GPU')


def scheduler(req):
    job = req['job_id']
    fields = dict(JobId=job, JobName='audattn_g2_matrix', UserId='s2510040(1234)',
        Partition=req['partition'], Account='student', NumCPUs='8', NumTasks='1',
        TimeLimit='03:00:00', Requeue='0', Restarts='0', Comment='g2-matrix-'+req['nonce'],
        WorkDir=str(e.REMOTE), StdIn='/dev/null', StdOut=str(e.REMOTE/'logs'/('matrix_'+job+'.log')),
        StdErr=str(e.REMOTE/'logs'/('matrix_'+job+'.log')),
        Command=str(e.REMOTE/'package'/e.PREFIX/'run_matrix.sbatch'),
        NumNodes='1', JobState='RUNNING', MinMemoryNode='64G',
        ReqTRES='cpu=8,mem=64G,node=1,billing=8,gres/gpu=1,gres/gpu:nvidia_a100=1',
        AllocTRES='cpu=8,mem=64G,node=1,billing=8,gres/gpu=1,gres/gpu:nvidia_a100=1',
        TresPerNode='gres/gpu:nvidia_a100:1', TresPerTask='cpu=8')
    fields['CPUs/Task'] = '8'
    return fields


def row(values):
    return ' '.join(k+'='+v for k, v in values.items())


class EntryTests(unittest.TestCase):
    def test_exact_request(self):
        e.validate_request(request())

    def test_request_rejects_extra_or_missing_field(self):
        for mutate in (lambda q:q.update(approved=True), lambda q:q.pop('nonce')):
            q = request(); mutate(q)
            with self.assertRaises(RuntimeError): e.validate_request(q)

    def test_resource_increases_and_numeric_coercion_rejected(self):
        for name, value in (('gpus',2), ('wall_seconds',14400), ('jobs',2), ('jobs',True), ('cpus',8.0)):
            q=request(); q['limits'][name]=value
            with self.subTest(name=name, value=value), self.assertRaises(RuntimeError): e.validate_request(q)

    def test_wrong_ids_freezes_and_partition_rejected(self):
        for key,value in (('job_id','001'), ('job_id',123), ('nonce','x'*32), ('release_sha256','z'*64),
                          ('freezes',{'E':'c'*64}), ('partition','GPU,OTHER')):
            q=request(); q[key]=value
            with self.subTest(key=key), self.assertRaises(RuntimeError): e.validate_request(q)

    def test_canonical_and_external_hash_required(self):
        raw=e.wire(request())
        self.assertEqual(e.decode(raw,e.digest(raw)),request())
        with self.assertRaises(RuntimeError): e.decode(raw,'0'*64)
        pretty=json.dumps(request(),indent=2).encode()
        with self.assertRaises(RuntimeError): e.decode(pretty,e.digest(pretty))
        duplicate=b'{"x":1,"x":1}\n'
        with self.assertRaises(RuntimeError): e.decode(duplicate,e.digest(duplicate))

    def test_source_inventory_includes_backend_and_all_profiles(self):
        names=e.required_files()
        self.assertEqual(len(names),32)
        self.assertIn('package/docs/superpowers/prototypes/g2_native_20260916/backend_evidence.py',names)
        for p in e.ORDER:
            for n in e.TOOLS: self.assertIn(p+'/tools/'+n,names)
        self.assertFalse(any('test_' in n or 'hermetic' in n for n in names))

    def test_read_file_budget_and_link_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve(); target=root/'source'
            target.write_bytes(b'abc')
            self.assertEqual(e.read(target,3),b'abc')
            with self.assertRaises(RuntimeError): e.read(target,2)
            link=root/'link'; link.symlink_to(target)
            with self.assertRaises(RuntimeError): e.read(link)
            hard=root/'hard'; os.link(target,hard)
            with self.assertRaises(RuntimeError): e.read(target)

    def test_private_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            e.private_directory(root)
            root.chmod(0o755)
            with self.assertRaises(RuntimeError): e.private_directory(root)

    def test_scheduler_exact_fixture(self):
        self.assertEqual(e.check_scheduler(row(scheduler(request())),request())['NumCPUs'],'8')

    def test_scheduler_wrong_identity_rejected(self):
        for key,value in (('JobId','123457'), ('Command','/tmp/other.sh'), ('UserId','other(1234)'),
                          ('Comment','other'), ('Requeue','1'), ('Restarts','1'), ('JobState','PENDING')):
            f=scheduler(request()); f[key]=value
            with self.subTest(key=key), self.assertRaises(RuntimeError): e.check_scheduler(row(f),request())

    def test_scheduler_resource_drift_rejected(self):
        for key,value in (('NumCPUs','16'), ('NumNodes','2'), ('MinMemoryNode','128G'),
                          ('TimeLimit','04:00:00'), ('CPUs/Task','1'), ('ArrayJobId','123456')):
            f=scheduler(request()); f[key]=value
            with self.subTest(key=key), self.assertRaises(RuntimeError): e.check_scheduler(row(f),request())

    def test_scheduler_gpu_and_tres_rejected(self):
        for field in ('ReqTRES','AllocTRES'):
            for value in ('cpu=8,mem=64G,node=1', 'cpu=8,mem=64G,node=1,gres/gpu=2',
                          'cpu=8,mem=64G,node=1,gres/gpu=1,license=x',
                          'cpu=8,cpu=8,mem=64G,node=1,gres/gpu=1'):
                f=scheduler(request()); f[field]=value
                with self.subTest(field=field,value=value), self.assertRaises(RuntimeError):
                    e.check_scheduler(row(f),request())

    def test_duplicate_scheduler_field(self):
        with self.assertRaises(RuntimeError): e.check_scheduler(row(scheduler(request()))+' JobId=123456',request())

    def test_commands_are_fixed_no_caller_argv(self):
        c=types.SimpleNamespace(request_sha='a'*64)
        command=e.child_argv(c,'worker','E')
        self.assertEqual(command[:3],[str(e.PYTHON),'-I','-B'])
        self.assertEqual(command[4:],['worker','a'*64,'E'])
        self.assertEqual(e.child_argv(c,'verify','E','b'*64)[-1],'b'*64)
        for args in (('shell','E',None),('worker','X',None),('verify','E',None),('worker','E','b'*64)):
            with self.assertRaises(RuntimeError): e.child_argv(c,*args)

    def test_local_production_context_rejected_before_remote_reads(self):
        with self.assertRaises(RuntimeError): e.Context('a'*64)

    def test_entry_help_and_no_numeric_import(self):
        process=subprocess.run([sys.executable,'-I','-B',str(HERE/'entry.py'),'--help'],
                               capture_output=True,timeout=5)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertIn(b'matrix,worker,verify',process.stdout)
        self.assertNotIn('torch',sys.modules)
        self.assertNotIn('numpy',sys.modules)

    def test_worker_missing_profile_rejected(self):
        process=subprocess.run([sys.executable,'-I','-B',str(HERE/'entry.py'),'worker','a'*64],
                               capture_output=True,timeout=5)
        self.assertEqual(process.returncode,2)
        self.assertIn(b'mode arguments differ',process.stderr)

    def test_real_supervisor_success_and_no_log_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'child.log'
            process=r.process_api.run_process([sys.executable,'-I','-B','-c','print("CHILD_ONLY")'],
                dict(os.environ),path,seconds=5,max_log_bytes=1024)
            self.assertEqual(process['returncode'],0)
            self.assertIsNone(process['error'])
            self.assertNotEqual(process['pid'],os.getpid())
            self.assertEqual(path.read_bytes(),b'CHILD_ONLY\n')
            with self.assertRaises(FileExistsError):
                r.process_api.run_process([sys.executable,'-c','print(2)'],dict(os.environ),path,seconds=1)

    def test_real_timeout_stops_child(self):
        with tempfile.TemporaryDirectory() as directory:
            process=r.process_api.run_process([sys.executable,'-I','-B','-c','import time; time.sleep(10)'],
                dict(os.environ),Path(directory)/'timeout.log',seconds=0.2,max_log_bytes=1024)
            self.assertEqual(process['error']['type'],'TimeoutError')
            self.assertEqual(process['returncode'],-signal.SIGKILL)
            with self.assertRaises(ProcessLookupError): os.kill(process['pid'],0)

    def test_real_log_limit_stops_child(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'limit.log'
            process=r.process_api.run_process([sys.executable,'-I','-B','-c','print("x"*4096)'],
                dict(os.environ),path,seconds=5,max_log_bytes=128)
            self.assertEqual(process['error']['type'],'RuntimeError')
            self.assertEqual(path.stat().st_size,128)

    def test_candidate_build_and_immutable_recheck(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory).resolve()/'candidate'
            sha=b.build(folder)
            release=b.verify(folder,sha)
            self.assertEqual(set(release['files']),e.required_files())
            self.assertFalse((folder/'RUN_REQUEST.json').exists())
            self.assertFalse(any((folder/p/'input_freeze.json').exists() for p in e.ORDER))
            with self.assertRaises(RuntimeError): b.build(folder)
            (folder/'E/tools/run_numeric_diag.sbatch').write_bytes(b'exit 0\n')
            with self.assertRaises(RuntimeError): b.verify(folder,sha)

    def test_candidate_rejects_extra_file(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory).resolve()/'candidate'
            sha=b.build(folder)
            (folder/'package/unreviewed.py').write_bytes(b'pass\n')
            with self.assertRaises(RuntimeError): b.verify(folder,sha)

    def test_plan_digest_known_before_job_assignment(self):
        wanted=request(); plan=dict(wanted); plan.pop('job_id')
        raw=e.wire(plan); digest=e.digest(raw)
        for job in ('123456','123457'):
            bound=bootstrap.derive_request(raw,digest,plan['release_sha256'],plan['nonce'],job)
            e.validate_request(bound)
            self.assertEqual(bound,dict(plan,job_id=job))
        self.assertEqual(e.digest(raw),digest)

    def test_plan_cannot_preassign_job_or_change_nonce(self):
        plan=request(); raw=e.wire(plan)
        with self.assertRaises(RuntimeError):
            bootstrap.derive_request(raw,e.digest(raw),plan['release_sha256'],plan['nonce'],'123456')
        plan.pop('job_id'); raw=e.wire(plan)
        for digest,release,nonce,job in ((e.digest(raw),'0'*64,plan['nonce'],'123456'),
                (e.digest(raw),plan['release_sha256'],'0'*32,'123456'),
                ('0'*64,plan['release_sha256'],plan['nonce'],'123456'),
                (e.digest(raw),plan['release_sha256'],plan['nonce'],'001')):
            with self.assertRaises(RuntimeError): bootstrap.derive_request(raw,digest,release,nonce,job)

    def test_held_request_has_no_allocation(self):
        f=scheduler(request())
        f.update(JobState='PENDING',Reason='JobHeldUser',Priority='0',RunTime='00:00:00',NodeList='',AllocTRES='(null)')
        e.check_scheduler(row(f),request(),held=True)
        with self.assertRaises(RuntimeError): e.check_scheduler(row(f),request())
        for key,value in (('Priority','1'),('NodeList','gpu-node'),('Reason','Resources'),('AllocTRES',f['ReqTRES'])):
            changed=dict(f,**{key:value})
            with self.subTest(key=key), self.assertRaises(RuntimeError): e.check_scheduler(row(changed),request(),held=True)

    def test_h100_or_generic_gpu_never_counts_as_a100(self):
        f=scheduler(request())
        for wrong in ('gres/gpu:h100-20c=1','gres/gpu=1'):
            changed=dict(f,ReqTRES='cpu=8,mem=64G,node=1,billing=8,'+wrong)
            with self.assertRaises(RuntimeError): e.check_scheduler(row(changed),request())
        changed=dict(f,TresPerNode='gres/gpu:1')
        with self.assertRaises(RuntimeError): e.check_scheduler(row(changed),request())

    def test_native_tres_may_omit_only_aggregate_gpu(self):
        f=scheduler(request())
        for key in ('ReqTRES','AllocTRES'):
            f[key]=f[key].replace('gres/gpu=1,','')
        e.check_scheduler(row(f),request())


if __name__ == '__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(EntryTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    print('G2_ENTRY_TEST_REPORT='+json.dumps(dict(tests=result.testsRun,failures=len(result.failures),
        errors=len(result.errors),skipped=len(result.skipped),production_model_loaded=False,jobs_submitted=0,
        scope='LOCAL_ENTRY_CHECKS_SYNTHETIC_SCHEDULER_AND_REAL_TINY_PROCESS_SUPERVISION')),flush=True)
    raise SystemExit(0 if result.wasSuccessful() else 2)

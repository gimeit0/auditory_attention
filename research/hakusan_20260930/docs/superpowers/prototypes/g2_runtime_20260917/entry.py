"""G2 cold worker/verifier/coordinator entry. No SSH, sbatch or retry.

Only a separately reviewed deployment may supply the out-of-band REQUEST SHA.
This file does not create a request, approve resources, freeze inputs, or submit.
It refuses local/test roots and verifies the actual running allocation before
production. The source release must include this entire transitive package.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import time

HERE = Path(__file__).absolute().parent
PACKAGE = HERE.parents[3]
REMOTE = Path('/home/s2510040/audattn_external_eval_diag/formal40_numeric_profiles_20260916_v1')
PYTHON = Path('/home/s2510040/miniconda3/envs/attn/bin/python')
PREFIX = 'docs/superpowers/prototypes/g2_runtime_20260917/'
RUNTIME_SHA = 'cfbd9280e53294a6b1ac3a9534a31f0dc5f9b839a2c6b0348ee59f9d59467507'
EVIDENCE_SHA = 'bd69ecec9426649d26c3df4a75765ff394ef5fa0369b0d3c49afe42ea104d4d8'
BRIDGE_SHA = '9b7e033ac8796e142782ea4dcc59ec527bd97538f51ccf8d4bea0caa1cd7d59d'
LIMITS = dict(cpus=8, memory_mib=65536, gpus=1, wall_seconds=10800,
              child_seconds=1800, matrix_seconds=10000, jobs=1)
SHA = re.compile('[0-9a-f]{64}')
ORDER = ('R', 'C', 'D', 'E')
DEPENDENCIES = (
    'g2_runtime_20260917/runtime.py', 'g2_runtime_20260917/evidence.py',
    'g2_runtime_20260917/entry.py', 'g2_runtime_20260917/run_matrix.sbatch',
    'g2_runtime_20260917/bootstrap.py',
    'g2_lifetime_20260917/production_cell.py', 'g2_archive_20260917/pass_store.py',
    'g2_inputs_20260917/input_binding.py', 'g2_scratch_20260917/scratch_binding.py',
    'g2_worker_20260916/cell_bridge.py', 'g2_profiles_20260916/profiles.py',
    'g2_native_20260916/backend_evidence.py',
    'targeted_gpu_job_20260915_v5/process_runner.py',
    'targeted_gpu_pair_20260915_scan/pass_archive.py',
)
DATA = (
    'docs/superpowers/evidence/v18-deployment-artifacts/input_freeze.json',
    'docs/superpowers/evidence/parent-replay-local-20260911T155226Z-rcw6ytm5/PARENT_REPLAY_CONTRACT.json',
)
TOOLS = ('diagnose_batch_invariance.py', 'numeric_trace.py',
         'submit_numeric_diag.py', 'run_numeric_diag.sbatch')


def require(ok, message):
    if not ok:
        raise RuntimeError('G2 entry: ' + message)


def wire(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                       allow_nan=False) + '\n').encode('ascii')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, limit=2*1024**2):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts
            and not any(p.is_symlink() for p in (path, *path.parents)), 'aliased path')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                and before.st_nlink == 1 and before.st_size <= limit, 'bounded owned single-link file required')
        with os.fdopen(os.dup(fd), 'rb') as handle:
            raw = handle.read(limit+1)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mode, s.st_uid,
                              s.st_nlink, s.st_mtime_ns, s.st_ctime_ns)
        require(len(raw) == before.st_size and identity(before) == identity(os.fstat(fd))
                == identity(path.lstat()), 'file changed while reading')
        return raw
    finally:
        os.close(fd)


def decode(raw, expected):
    require(type(expected) is str and SHA.fullmatch(expected) and digest(raw) == expected,
            'external digest differs')
    value = json.loads(raw)
    require(type(value) is dict and wire(value) == raw, 'canonical unique-key JSON required')
    return value


def load(name, path, expected):
    raw = read(path)
    require(digest(raw) == expected, 'source differs: ' + str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    require(name not in sys.modules, 'module name already occupied')
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec', dont_inherit=True), vars(module))
    return module


def validate_request(value):
    require(set(value) == {'schema_version', 'protocol', 'job_id', 'nonce', 'release_sha256',
                          'freezes', 'limits', 'partition'}, 'request fields differ')
    require(type(value['schema_version']) is int and value['schema_version'] == 1
            and value['protocol'] == REMOTE.name and value['limits'] == LIMITS
            and all(type(v) is int for v in value['limits'].values()), 'request contract differs')
    require(type(value['job_id']) is str and re.fullmatch('[1-9][0-9]{0,19}', value['job_id'])
            and type(value['nonce']) is str and re.fullmatch('[0-9a-f]{32}', value['nonce']), 'job/nonce differs')
    require(type(value['release_sha256']) is str and SHA.fullmatch(value['release_sha256'])
            and type(value['freezes']) is dict and set(value['freezes']) == set(ORDER)
            and all(type(v) is str and SHA.fullmatch(v) for v in value['freezes'].values()), 'four frozen inputs required')
    require(type(value['partition']) is str and re.fullmatch('[A-Za-z0-9_-]{1,32}', value['partition']),
            'one reviewed partition required')


def required_files():
    return {'package/docs/superpowers/prototypes/' + n for n in DEPENDENCIES} | {
        'package/' + n for n in DATA} | {p + '/tools/' + n for p in ORDER for n in TOOLS}


class Context:
    def __init__(self, request_sha):
        require(sys.platform == 'linux' and sys.version.split()[0] == '3.11.5'
                and sys.flags.isolated and sys.dont_write_bytecode and PYTHON.resolve() == Path(sys.executable).resolve(),
                'isolated native interpreter required')
        require(PACKAGE == REMOTE/'package' and HERE == PACKAGE/PREFIX
                and os.environ.get('HOME') == '/home/s2510040', 'new deployment/real HOME required')
        self.request_sha = request_sha
        self.raw = read(REMOTE/'RUN_REQUEST.json')
        self.request = decode(self.raw, request_sha)
        validate_request(self.request)
        self.job = self.request['job_id']
        require(os.environ.get('SLURM_JOB_ID') == self.job, 'request is not this allocation')
        self.release_raw = read(REMOTE/'RELEASE.json')
        self.release = decode(self.release_raw, self.request['release_sha256'])
        require(set(self.release) == {'schema_version', 'protocol', 'files'}
                and self.release['schema_version'] == 1 and self.release['protocol'] == REMOTE.name
                and set(self.release['files']) == required_files(), 'execution release inventory differs')
        require(all(type(h) is str and SHA.fullmatch(h) for h in self.release['files'].values()), 'release digest malformed')
        self.check()
        self.r = load('runtime', HERE/'runtime.py', RUNTIME_SHA)
        self.bridge = load('g2_entry_bridge', HERE.parent/'g2_worker_20260916/cell_bridge.py', BRIDGE_SHA)
        self.scratch = Path('/tmp')/('audattn_g2_' + self.job)
        self.folder = REMOTE/'attempts'/('slurm-' + self.job)
        self.diags = {}

    def check(self):
        require(read(REMOTE/'RUN_REQUEST.json') == self.raw and read(REMOTE/'RELEASE.json') == self.release_raw,
                'request/release changed')
        observed = {'package/' + str(p.relative_to(PACKAGE)) for p in PACKAGE.rglob('*')
                    if p.is_symlink() or not p.is_dir()}
        require(observed == {n for n in self.release['files'] if n.startswith('package/')},
                'unexpected package member')
        for name, expected in self.release['files'].items():
            require(digest(read(REMOTE/name)) == expected, 'release member changed: ' + name)
        for profile in ORDER:
            require({p.name for p in (REMOTE/profile/'tools').iterdir()} == set(TOOLS), 'profile tools inventory differs')
            decode(read(REMOTE/profile/'input_freeze.json'), self.request['freezes'][profile])

    def diag(self, profile):
        require(profile in ORDER, 'unknown profile')
        if profile not in self.diags:
            self.diags[profile] = self.bridge.load_candidate(REMOTE/profile/'tools/diagnose_batch_invariance.py', profile)
        return self.diags[profile]

    def production(self, profile):
        return {n: read(REMOTE/profile/'tools'/n) for n in TOOLS}


def scheduler_fields(raw):
    pairs = re.findall(r'(?:^|\s)([A-Za-z0-9_/]+)=([^\s]*)', raw)
    require(len(dict(pairs)) == len(pairs), 'duplicate scheduler field')
    return dict(pairs)


def check_scheduler(raw, request, *, held=False):
    f = scheduler_fields(raw)
    job, nonce = request['job_id'], request['nonce']
    expected = dict(JobId=job, JobName='audattn_g2_matrix', Partition=request['partition'], Account='student',
        NumCPUs='8', NumTasks='1', TimeLimit='03:00:00', Requeue='0', Restarts='0',
        Comment='g2-matrix-'+nonce, WorkDir=str(REMOTE), StdIn='/dev/null',
        StdOut=str(REMOTE/'logs'/('matrix_'+job+'.log')), StdErr=str(REMOTE/'logs'/('matrix_'+job+'.log')),
        Command=str(REMOTE/'package'/PREFIX/'run_matrix.sbatch'))
    require(all(f.get(k) == v for k, v in expected.items()) and f.get('CPUs/Task') == '8'
            and f.get('NumNodes') in ('1', '1-1')
            and f.get('MinMemoryNode') in ('64G', '65536M')
            and re.fullmatch(r's2510040\([0-9]+\)', f.get('UserId', ''))
            and not any(k in f for k in ('ArrayJobId', 'HetJobId')), 'actual scheduler identity/resources differ')
    require(f.get('TresPerNode') == 'gres/gpu:nvidia_a100:1'
            and f.get('TresPerTask') == 'cpu=8'
            and f.get('TresPerJob') in (None, 'gres/gpu:nvidia_a100:1')
            and not any(k in f for k in ('TresPerSocket', 'MemPerTres', 'CpusPerTres')), 'explicit single A100 request required')
    if held:
        require(all(f.get(k) == v for k, v in dict(JobState='PENDING', Reason='JobHeldUser', Priority='0',
                    RunTime='00:00:00', NodeList='', AllocTRES='(null)').items()), 'job is not unallocated user-held')
    else:
        require(f.get('JobState') in ('RUNNING', 'COMPLETING'), 'compute allocation must be running')
    for name in (('ReqTRES',) if held else ('ReqTRES', 'AllocTRES')):
        pairs = [x.split('=', 1) for x in f.get(name, '').split(',')]
        require(all(len(p) == 2 for p in pairs) and len(dict(pairs)) == len(pairs), 'bad TRES')
        values = dict(pairs)
        require(values.get('cpu') == '8' and values.get('mem') in ('64G', '65536M')
                and values.get('node') == '1' and values.get('billing') == '8'
                and values.get('gres/gpu:nvidia_a100') == '1'
                and values.get('gres/gpu') in (None, '1'), 'allocated/requested typed A100 TRES differs')
        require(set(values) in ({'cpu', 'mem', 'node', 'billing', 'gres/gpu:nvidia_a100'},
                               {'cpu', 'mem', 'node', 'billing', 'gres/gpu:nvidia_a100', 'gres/gpu'}),
                'additional/untyped resource request differs')
    return f


def allocation(context, label):
    process = context.r.process_api.run_process(['/usr/bin/scontrol', '-o', 'show', 'job', context.job],
        {'PATH':'/usr/bin:/bin', 'HOME':'/home/s2510040'}, context.folder/(label+'.log'),
        seconds=15, max_log_bytes=65536)
    context.r.process_api.write_once(context.folder/(label+'.json'), process)
    require(process['returncode'] == 0 and process['error'] is None, 'allocation query failed')
    check_scheduler(read(context.folder/(label+'.log'), 65536).decode(), context.request)


def private_directory(path):
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'directory aliases')
    info = path.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700, 'owned private directory required')


def child_argv(context, mode, profile, launch_sha=None):
    require(mode in ('worker', 'verify') and profile in ORDER, 'fixed child mode/profile required')
    command = [str(PYTHON), '-I', '-B', str(HERE/'entry.py'), mode, context.request_sha, profile]
    if mode == 'verify':
        require(type(launch_sha) is str and SHA.fullmatch(launch_sha), 'parent launch pin required')
        command.append(launch_sha)
    else:
        require(launch_sha is None, 'worker cannot carry verifier receipt')
    return command


def worker(context, profile):
    private_directory(context.scratch)
    diag = context.diag(profile)
    expected = context.r.worker_environment(context.r.cell_api.scratch_api.Binding(context.bridge, diag),
                                            os.environ, context.scratch, context.job)
    require(dict(os.environ) == expected, 'worker environment was not parent-constructed')
    result = context.r.run_worker(context.bridge, diag, job=context.job,
        freeze_sha=context.request['freezes'][profile], production_bytes=context.production(profile),
        parent_path=context.r.store.PARENT, release_sha=context.request['release_sha256'], source_check=context.check)
    return 0 if result['status'] == 'G2_WORKER_STORED' else 2


def verify(context, profile, launch_sha):
    part = context.folder/profile
    launch = decode(read(part/'LAUNCH.json'), launch_sha)
    require(launch['request_sha256'] == context.request_sha and launch['argv'] == child_argv(context, 'worker', profile),
            'parent launch request/command differs')
    require(os.environ.get('CUDA_VISIBLE_DEVICES') == '', 'offline verifier must have no visible GPU')
    diag = context.diag(profile)
    root = REMOTE/profile/'attempts'/('slurm-'+context.job)
    pins = launch['artifact_pins']
    require(set(pins) == {'TERMINAL.json', 'ARCHIVE_RECEIPT.json'}, 'worker receipt pins differ')
    terminal = decode(read(root/'TERMINAL.json'), pins['TERMINAL.json'])
    receipt = decode(read(root/'ARCHIVE_RECEIPT.json'), pins['ARCHIVE_RECEIPT.json'])
    freeze = decode(read(REMOTE/profile/'input_freeze.json'), context.request['freezes'][profile])
    # Import pinned verifier only AFTER runtime has been bound.
    evidence = load('g2_entry_evidence', HERE/'evidence.py', EVIDENCE_SHA)
    result = evidence.verify_worker(root, terminal=terminal, terminal_sha=pins['TERMINAL.json'], receipt=receipt,
        receipt_sha=pins['ARCHIVE_RECEIPT.json'], launch=launch, bridge=context.bridge, diag=diag, freeze=freeze,
        production_bytes=context.production(profile), release_sha=context.request['release_sha256'], source_check=context.check)
    context.r.process_api.write_once(part/'OBSERVATION.json', result)
    return 0


def matrix(context):
    r = context.r
    private_directory(REMOTE/'attempts')
    context.folder.mkdir(mode=0o700)  # partial old attempts are not reused
    runner = r.process_api
    runner.write_once(context.folder/'STARTED.json', dict(request_sha256=context.request_sha, pid=os.getpid(),
        job_id=context.job, release_sha256=context.request['release_sha256'], automatic_retry=False))
    began = time.monotonic()
    result, error = None, None
    try:
        allocation(context, 'ALLOCATION_BEFORE')
        require(not socket.gethostname().startswith('hakusan') and len(os.sched_getaffinity(0)) == 8
                and os.environ.get('SLURM_CPUS_PER_TASK') == '8', 'compute affinity differs')
        context.scratch.mkdir(mode=0o700)
        private_directory(context.scratch)
        # No source/model is copied to /tmp. Original mount checks remain active.
        context.diag('R')._require_local_scratch_mount(context.scratch)
        for path, minimum in ((context.scratch, 32*1024**3), (REMOTE, 16*1024**3)):
            fs = os.statvfs(path)
            require(fs.f_bavail * fs.f_frsize >= minimum, 'insufficient scratch/archive free space')

        def launch(profile, seconds):
            context.check()
            part = context.folder/profile
            part.mkdir(mode=0o700)
            diag = context.diag(profile)
            binding = r.cell_api.scratch_api.Binding(context.bridge, diag)
            env = r.worker_environment(binding, os.environ, context.scratch, context.job)
            command = child_argv(context, 'worker', profile)
            runner.write_once(part/'LAUNCH_INTENT.json', dict(argv=command, environment=env,
                              request_sha256=context.request_sha, seconds=seconds))
            process = runner.run_process(command, env, part/'worker.log', seconds=seconds, max_log_bytes=8*1024**2)
            runner.write_once(part/'PROCESS.json', process)
            pins = {}
            if process['returncode'] == 0 and process['error'] is None:
                root = REMOTE/profile/'attempts'/('slurm-'+context.job)
                pins = {n:digest(read(root/n)) for n in ('TERMINAL.json', 'ARCHIVE_RECEIPT.json')}
            process.update(argv=command, environment=env, request_sha256=context.request_sha, artifact_pins=pins)
            runner.write_once(part/'LAUNCH.json', process)
            return process

        def independently_verify(profile, process, remaining):
            part = context.folder/profile
            launch_sha = digest(read(part/'LAUNCH.json'))
            command = child_argv(context, 'verify', profile, launch_sha)
            env = dict(process['environment'], CUDA_VISIBLE_DEVICES='')
            # Verifier runs after worker death, in another cold interpreter. No inference.
            seconds = min(600, remaining, LIMITS['matrix_seconds']-(time.monotonic()-began))
            verified = runner.run_process(command, env, part/'verify.log', seconds=seconds, max_log_bytes=4*1024**2)
            runner.write_once(part/'VERIFY_PROCESS.json', dict(verified, argv=command, environment=env,
                launch_sha256=launch_sha, request_sha256=context.request_sha))
            require(verified['returncode'] == 0 and verified['error'] is None and verified['pid'] != process['pid'],
                    'independent cold verifier failed')
            observation = json.loads(read(part/'OBSERVATION.json'))
            context.check()
            return observation

        def persist(name, value):
            runner.write_once(context.folder/(name+'-VERIFIED.json'), value)

        result = r.run_matrix(job=context.job, release_sha=context.request['release_sha256'],
            freezes=context.request['freezes'], launch=launch, verify=independently_verify, persist=persist)
        require(result['execution_valid'], 'matrix has an invalid execution')
        allocation(context, 'ALLOCATION_AFTER')
    except BaseException as exc:
        error = r.error_record(exc)
    try:
        context.check()
    except BaseException as exc:
        error = dict(r.error_record(exc), prior=error)
    if time.monotonic()-began >= LIMITS['matrix_seconds']:
        error = dict(type='TimeoutError', message='matrix elapsed deadline exceeded', prior=error)
    terminal = dict(status='G2_MATRIX_RECORDED' if error is None else 'EXECUTION_INVALID',
        job_id=context.job, request_sha256=context.request_sha, release_sha256=context.request['release_sha256'],
        result=result, error=error, elapsed_seconds=time.monotonic()-began, scratch_retained=str(context.scratch),
        independent_download_verified=False, ready_for_full_evaluation=False, automatic_retry=False, jobs_submitted=0)
    runner.write_once(context.folder/'TERMINAL.json', terminal)
    print(json.dumps(dict(status=terminal['status'], error=error)), flush=True)
    return 0 if error is None else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('matrix', 'worker', 'verify'))
    parser.add_argument('request_sha256')
    parser.add_argument('profile', nargs='?', choices=ORDER)
    parser.add_argument('launch_sha256', nargs='?')
    args = parser.parse_args()
    require((args.mode == 'matrix' and args.profile is None and args.launch_sha256 is None)
            or (args.mode == 'worker' and args.profile and args.launch_sha256 is None)
            or (args.mode == 'verify' and args.profile and args.launch_sha256), 'mode arguments differ')
    os.umask(0o077)
    context = Context(args.request_sha256)
    if args.mode == 'matrix': return matrix(context)
    if args.mode == 'worker': return worker(context, args.profile)
    return verify(context, args.profile, args.launch_sha256)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps(dict(status='G2_ENTRY_REJECTED', error_type=type(exc).__name__, message=str(exc))), file=sys.stderr)
        raise SystemExit(2)

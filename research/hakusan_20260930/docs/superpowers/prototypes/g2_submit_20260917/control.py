"""Single held G2 submission controller; no deployment, freeze, reconnect or retry.

An operator must supply reviewed plan/control digests and explicit resource
confirmation. A durable intent consumes the one-shot submission even if sbatch
times out. Failed/uncertain holds are preserved for read-only reconciliation.
This controller is outside the immutable 32-file execution package.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import selectors
import signal
import stat
import subprocess
import sys
import time

REMOTE = Path('/home/s2510040/audattn_external_eval_diag/formal40_numeric_profiles_20260916_v1')
PYTHON = Path('/home/s2510040/miniconda3/envs/attn/bin/python')
PREFIX = 'package/docs/superpowers/prototypes/g2_runtime_20260917/'
RELEASE_SHA = '6becba7b27f8ba37657e66f0173bf991aec0136e8285afbd211eeeb65318d300'
ENTRY_SHA = '31e3594d66bf6da52d7a35873322df4b20eac16640cf75b6050e563005a99125'
BOOTSTRAP_SHA = '036b086e336a7a5be1aa00fbcf8d58b65f3711209ce67342fa5281f6f072a4d1'
CONFIRM = 'ONE_G2_MATRIX_1A100_8CPU_64G_3H_NO_RETRY'
PARTITION = 'GPU-1A'


def require(ok, message):
    if not ok:
        raise RuntimeError('G2 submission: ' + message)


def wire(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe(path):
    require(path.is_absolute() and '..' not in path.parts
            and not any(p.is_symlink() for p in (path, *path.parents)), 'aliased path')
    return path


def read(path, limit=2*1024**2):
    fd = os.open(safe(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                and before.st_nlink == 1 and before.st_size <= limit, 'bounded owned file required')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            raw = stream.read(limit+1)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_uid, s.st_mode,
                              s.st_nlink, s.st_mtime_ns, s.st_ctime_ns)
        require(len(raw) == before.st_size and identity(before) == identity(os.fstat(fd))
                == identity(path.lstat()), 'file changed while reading')
        return raw
    finally:
        os.close(fd)


def private(path):
    info = safe(path).stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700, 'owned private directory required')


def write_once(path, value):
    private(path.parent)
    raw = wire(value)
    fd = os.open(safe(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return sha(raw)


def decode(raw, expected):
    require(type(expected) is str and re.fullmatch('[a-f0-9]{64}', expected)
            and sha(raw) == expected, 'external digest differs')
    value = json.loads(raw)
    require(type(value) is dict and wire(value) == raw, 'canonical unique-key object required')
    return value


def module(name, path, expected):
    raw = read(path)
    require(sha(raw) == expected, 'pinned source differs: ' + path.name)
    require(name not in sys.modules, 'occupied module name')
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    exec(compile(raw, str(path), 'exec', dont_inherit=True), vars(result))
    return result


def command(argv, *, seconds=30, max_bytes=1024**2):
    """Bound both output pipes while running; timeout may mean submit succeeded."""
    require(type(argv) is list and argv and all(type(a) is str for a in argv), 'explicit argv required')
    require(0 < seconds <= 180 and 0 < max_bytes <= 2*1024**2, 'command budget differs')
    started = time.monotonic()
    process, error, count = None, None, 0
    chunks = {'stdout': [], 'stderr': []}
    env = dict(HOME='/home/s2510040', USER='s2510040', LOGNAME='s2510040',
               PATH='/usr/bin:/bin', LANG='C', LC_ALL='C')
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=env, start_new_session=True)
        with selectors.DefaultSelector() as selector:
            for name in chunks:
                pipe = getattr(process, name)
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            deadline = started + seconds
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('command timed out; do not retry a mutation')
                for key, _ in selector.select(min(0.2, remaining)):
                    raw = os.read(key.fd, 65536)
                    if not raw:
                        selector.unregister(key.fileobj)
                        continue
                    allowed = min(len(raw), max_bytes-count)
                    chunks[key.data].append(raw[:allowed])
                    count += allowed
                    require(allowed == len(raw), 'command output exceeded budget')
            process.wait(timeout=max(0.001, deadline-time.monotonic()))
    except BaseException as exc:
        error = dict(type=type(exc).__name__, message=str(exc))
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            process.stdout.close()
            process.stderr.close()
    return dict(argv=argv, returncode=process.returncode if process else None, error=error,
                stdout=b''.join(chunks['stdout']).decode('utf-8', errors='replace'),
                stderr=b''.join(chunks['stderr']).decode('utf-8', errors='replace'),
                elapsed_seconds=round(time.monotonic()-started, 3))


def succeeded(result):
    return result['returncode'] == 0 and result['error'] is None


class Context:
    def __init__(self, plan_sha, control_sha):
        require(sys.platform == 'linux' and sys.version.split()[0] == '3.11.5'
                and sys.flags.isolated and sys.dont_write_bytecode
                and Path(sys.executable).resolve() == PYTHON.resolve()
                and Path(__file__).absolute() == REMOTE/'control/control.py'
                and pwd.getpwuid(os.getuid()).pw_name == 's2510040'
                and os.environ.get('HOME') == '/home/s2510040'
                and not os.environ.get('SLURM_JOB_ID'), 'native login-node controller required')
        self.root, self.state = REMOTE, REMOTE/'state'
        self.control_sha, self.plan_sha = control_sha, plan_sha
        require(sha(read(Path(__file__).absolute())) == control_sha, 'controller source differs')
        self.plan_raw = read(self.root/'EXECUTION_PLAN.json')
        self.plan = decode(self.plan_raw, plan_sha)
        self.e = module('g2_submit_entry', self.root/PREFIX/'entry.py', ENTRY_SHA)
        self.bootstrap = module('g2_submit_bootstrap', self.root/PREFIX/'bootstrap.py', BOOTSTRAP_SHA)
        self.e.validate_request(self.request('1'))
        require(self.plan['partition'] == PARTITION, 'unreviewed partition')
        self.check()

    def request(self, job):
        return self.bootstrap.derive_request(self.plan_raw, self.plan_sha, RELEASE_SHA,
                                             self.plan['nonce'], job)

    def check(self):
        require(sha(read(Path(__file__).absolute())) == self.control_sha, 'controller source drift')
        require(read(self.root/'EXECUTION_PLAN.json') == self.plan_raw, 'plan drift')
        release = decode(read(self.root/'RELEASE.json'), RELEASE_SHA)
        require(set(release) == {'schema_version', 'protocol', 'files'}
                and release['schema_version'] == 1 and release['protocol'] == REMOTE.name
                and set(release['files']) == self.e.required_files(), 'release inventory differs')
        for path in (self.root, self.state, self.root/'control', self.root/'logs', self.root/'attempts'):
            private(path)
        observed = {'package/'+str(p.relative_to(self.root/'package'))
                    for p in (self.root/'package').rglob('*') if p.is_symlink() or not p.is_dir()}
        require(observed == {n for n in release['files'] if n.startswith('package/')}, 'extra/missing package member')
        for name, expected in release['files'].items():
            path = self.root/name
            require(sha(read(path)) == expected and stat.S_IMODE(path.stat().st_mode) == 0o600,
                    'execution source/hash/mode differs: '+name)
        for profile in self.e.ORDER:
            require({p.name for p in (self.root/profile/'tools').iterdir()} == set(self.e.TOOLS), 'profile tools differ')
            freeze = decode(read(self.root/profile/'input_freeze.json'), self.plan['freezes'][profile])
            require(freeze['diagnostic_protocol'] == REMOTE.name+'_'+profile
                    and freeze['status'] == 'INPUTS_FROZEN', 'profile freeze identity differs')

    def check_profile(self, profile):
        require(profile in self.e.ORDER, 'unknown profile')
        bridge = module('g2_submit_bridge', self.root/'package/docs/superpowers/prototypes/g2_worker_20260916/cell_bridge.py', self.e.BRIDGE_SHA)
        binding = module('g2_submit_inputs', self.root/'package/docs/superpowers/prototypes/g2_inputs_20260917/input_binding.py',
                         '6a99559df859bb88cdf730d7dcd1bf72caf2f2f04800ae69781da23e64103896')
        diag = bridge.load_candidate(self.root/profile/'tools/diagnose_batch_invariance.py', profile)
        result = diag.check_only(expected_input_freeze_sha256=self.plan['freezes'][profile])
        _, proof = binding.verify_relation(bridge, diag, read(self.root/profile/'input_freeze.json'),
            self.plan['freezes'][profile], {n:read(self.root/profile/'tools'/n) for n in self.e.TOOLS},
            read(self.root/'package'/self.e.DATA[0]))
        self.check()
        require(result['status'] == 'CHECK_PASS' and proof['status'] == 'G2_SCIENTIFIC_INPUT_RELATION_PASS', 'input check failed')
        return dict(status='G2_PROFILE_INPUTS_CHECKED', profile=profile, plan_sha256=self.plan_sha,
                    input_freeze_sha256=self.plan['freezes'][profile], relation=proof, check=result)


def preflight(context, execute):
    context.check()
    queue = execute(['/usr/bin/squeue', '-h', '-u', 's2510040', '-o', '%i|%T|%j'])
    require(succeeded(queue) and not queue['stdout'].strip(), 'account queue nonempty/unavailable')
    partition = execute(['/usr/bin/scontrol', '-o', 'show', 'partition', PARTITION])
    require(succeeded(partition), 'partition query failed')
    fields = context.e.scheduler_fields(partition['stdout'])
    require(all(fields.get(k) == v for k, v in dict(PartitionName=PARTITION, State='UP',
        AllowGroups='ALL', AllowAccounts='ALL', MaxMemPerCPU='9845').items())
        and fields.get('MaxTime') in ('UNLIMITED', 'infinite'), 'partition contract changed')
    require('gres/gpu:nvidia_a100=' in fields.get('TRES', ''), 'partition lacks typed A100')
    return dict(queue=queue, partition=partition)


def batch_argv(context, *, test=False):
    return ['/usr/bin/sbatch', '--test-only' if test else '--hold', '--parsable', '--export=NONE', '--no-requeue',
        '--partition='+PARTITION, '--account=student', '--nodes=1', '--ntasks=1', '--cpus-per-task=8',
        '--threads-per-core=1', '--mem=65536M', '--time=03:00:00', '--gres=gpu:nvidia_a100:1',
        '--job-name=audattn_g2_matrix', '--comment=g2-matrix-'+context.plan['nonce'],
        '--chdir='+str(REMOTE), '--input=/dev/null', '--output='+str(REMOTE/'logs/matrix_%j.log'),
        '--error='+str(REMOTE/'logs/matrix_%j.log'), str(REMOTE/PREFIX/'run_matrix.sbatch'),
        RELEASE_SHA, context.plan_sha, context.plan['nonce']]


def unused(context):
    for name in ('INTENT.json', 'SBATCH_RESPONSE.json', 'SUBMISSION_RECEIPT.json', 'HELD.json', 'RELEASE_INTENT.json', 'RELEASE_RESPONSE.json'):
        require(not os.path.lexists(context.state/name), 'submission already attempted; query only')
    require(not os.path.lexists(context.root/'RUN_REQUEST.json'), 'request already exists; query only')
    require(not any((context.root/'attempts').iterdir()), 'attempt evidence exists; query only')


def scheduler_test(context, execute=command):
    unused(context)
    before = preflight(context, execute)
    write_once(context.state/'TEST_INTENT.json', dict(plan_sha256=context.plan_sha, control_sha256=context.control_sha))
    profiles = {}
    for profile in context.e.ORDER:
        argv = [str(PYTHON), '-I', '-B', str(REMOTE/'control/control.py'), 'check-profile',
                '--plan-sha256', context.plan_sha, '--control-sha256', context.control_sha, '--profile', profile]
        result = execute(argv, seconds=120)
        write_once(context.state/('CHECK_'+profile+'.json'), result)
        require(succeeded(result), 'profile check failed; no job submitted: '+profile)
        lines = [line for line in result['stdout'].splitlines() if line.startswith('G2_CONTROL_RESULT=')]
        require(len(lines) == 1, 'profile receipt missing/ambiguous')
        value = json.loads(lines[0].split('=', 1)[1])
        require(value['status'] == 'G2_PROFILE_INPUTS_CHECKED' and value['profile'] == profile
                and value['plan_sha256'] == context.plan_sha
                and value['input_freeze_sha256'] == context.plan['freezes'][profile], 'profile receipt identity differs')
        profiles[profile] = sha(wire(result))
    context.check()
    result = execute(batch_argv(context, test=True))
    receipt = dict(plan_sha256=context.plan_sha, control_sha256=context.control_sha,
                   release_sha256=RELEASE_SHA, profiles=profiles, preflight=before, result=result)
    digest = write_once(context.state/'TEST_ONLY.json', receipt)
    require(succeeded(result), 'scheduler rejected test; no job submitted')
    return dict(status='G2_SCHEDULER_TEST_PASS', test_sha256=digest, jobs_submitted=0)


def submit(context, test_sha, confirmation, execute=command):
    require(confirmation == CONFIRM, 'explicit single-job resource approval required')
    unused(context)
    test = decode(read(context.state/'TEST_ONLY.json'), test_sha)
    require(test['plan_sha256'] == context.plan_sha and test['control_sha256'] == context.control_sha
            and test['release_sha256'] == RELEASE_SHA and succeeded(test['result'])
            and set(test['profiles']) == set(context.e.ORDER), 'matching successful preflight required')
    for profile, expected in test['profiles'].items():
        require(sha(read(context.state/('CHECK_'+profile+'.json'))) == expected, 'input-check evidence drift')
    before = preflight(context, execute)
    intent = dict(plan_sha256=context.plan_sha, control_sha256=context.control_sha, release_sha256=RELEASE_SHA,
                  nonce=context.plan['nonce'], limits=context.plan['limits'], confirmation=confirmation,
                  test_sha256=test_sha, automatic_retry=False, argv=batch_argv(context), preflight=before)
    # Durable exclusive journal is the concurrency and no-retry boundary.
    write_once(context.state/'INTENT.json', intent)
    response = execute(batch_argv(context))
    write_once(context.state/'SBATCH_RESPONSE.json', response)
    require(succeeded(response) and re.fullmatch(r'[1-9][0-9]{0,19}\n?', response['stdout']),
            'submission uncertain/failed; retain intent, query only, never resubmit')
    job = response['stdout'].strip()
    request = context.request(job)
    context.e.validate_request(request)
    request_sha = write_once(context.root/'RUN_REQUEST.json', request)
    receipt = dict(status='SUBMITTED_HELD', job_id=job, plan_sha256=context.plan_sha,
                   request_sha256=request_sha, release_sha256=RELEASE_SHA, control_sha256=context.control_sha,
                   nonce=context.plan['nonce'], automatic_retry=False)
    write_once(context.state/'SUBMISSION_RECEIPT.json', receipt)
    held = execute(['/usr/bin/scontrol', '-o', 'show', 'job', job])
    write_once(context.state/'HELD.json', held)
    require(succeeded(held), 'held query failed; leave held, query only')
    context.e.check_scheduler(held['stdout'], request, held=True)
    context.check()
    require(read(context.root/'RUN_REQUEST.json') == wire(request), 'request drift before release')
    write_once(context.state/'RELEASE_INTENT.json', receipt)
    released = execute(['/usr/bin/scontrol', 'release', job])
    write_once(context.state/'RELEASE_RESPONSE.json', released)
    require(succeeded(released), 'release uncertain/failed; query only, never retry automatically')
    return dict(receipt, status='G2_JOB_RELEASED', jobs_submitted=1)


def status(context, execute=command):
    context.check()
    queue = execute(['/usr/bin/squeue', '-h', '-u', 's2510040', '-o', '%i|%T|%j|%k'])
    require(succeeded(queue), 'queue query failed')
    path = context.state/'SUBMISSION_RECEIPT.json'
    receipt = None
    if path.exists():
        receipt = json.loads(read(path))
        require(receipt['plan_sha256'] == context.plan_sha
                and receipt['nonce'] == context.plan['nonce']
                and receipt['control_sha256'] == context.control_sha
                and re.fullmatch('[1-9][0-9]{0,19}', receipt['job_id']), 'submission receipt differs')
        accounting = execute(['/usr/bin/sacct', '-j', receipt['job_id'], '-X', '-n', '-P',
            '--format=JobIDRaw,State,ExitCode,Elapsed,ReqTRES,AllocTRES,NodeList'])
    else:
        # No inferred job ID or repeated mutation after an uncertain sbatch reply.
        accounting = None
    return dict(status='QUERY_ONLY', queue=queue, receipt=receipt, accounting=accounting,
                intent_exists=os.path.lexists(context.state/'INTENT.json'), jobs_submitted=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('test-only', 'submit', 'status', 'check-profile'))
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--control-sha256', required=True)
    parser.add_argument('--test-sha256')
    parser.add_argument('--confirm')
    parser.add_argument('--profile', choices=('R', 'C', 'D', 'E'))
    args = parser.parse_args()
    require((args.action == 'submit') == (args.confirm is not None)
            and (args.action == 'submit') == (args.test_sha256 is not None)
            and (args.action == 'check-profile') == (args.profile is not None), 'action arguments differ')
    os.umask(0o077)
    context = Context(args.plan_sha256, args.control_sha256)
    if args.action == 'submit':
        return submit(context, args.test_sha256, args.confirm)
    if args.action == 'test-only':
        return scheduler_test(context)
    if args.action == 'check-profile':
        return context.check_profile(args.profile)
    return status(context)


if __name__ == '__main__':
    try:
        print('G2_CONTROL_RESULT='+json.dumps(main(), sort_keys=True), flush=True)
    except Exception as exc:
        print('G2_CONTROL_ERROR='+json.dumps(dict(error_type=type(exc).__name__, message=str(exc),
                                                automatic_retry=False)), file=sys.stderr, flush=True)
        raise SystemExit(2)

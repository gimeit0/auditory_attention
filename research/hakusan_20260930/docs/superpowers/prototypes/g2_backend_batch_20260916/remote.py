"""Write-once deployment and single held CPU submission, no reconnect/retry."""
import base64
import json
import os
from pathlib import Path
import re
import common as c


def queue(execute):
    result = execute(['/usr/bin/squeue', '-h', '-u', 's2510040', '-o', '%i|%T|%j'])
    c.require(result['returncode'] == 0 and not result['stdout'].strip(), 'account queue not empty/unavailable')
    return result


def preflight(execute, root=c.REMOTE):
    c.require(not root.exists() and not root.is_symlink(), 'new CPU root already exists')
    c.safe(root.parent)
    c.require(root.parent.is_dir() and root.parent.stat().st_uid == os.getuid(), 'owned diagnostic base required')
    q = queue(execute)
    p = execute(['/usr/bin/scontrol', '-o', 'show', 'partition', 'TINY'])
    f = c.fields(p['stdout'])
    c.require(p['returncode'] == 0 and f.get('PartitionName') == 'TINY' and f.get('State') == 'UP'
              and f.get('AllowAccounts') == 'ALL' and f.get('MaxMemPerCPU') == '6000', 'TINY partition contract differs')
    return dict(status='CPU_PREFLIGHT_PASS', partition=p, queue=q, jobs_submitted=0)


def deployment(spec, execute, root=c.REMOTE):
    before = preflight(execute, root)
    raw = base64.b64decode(spec['release'], validate=True)
    manifest = c.release(raw, spec['release_sha256'])
    c.require(set(spec['files']) == set(manifest['files']), 'upload inventory differs')
    files = {n: base64.b64decode(v, validate=True) for n, v in spec['files'].items()}
    c.require(sum(map(len, files.values())) <= 16 * 1024**2
              and all(c.sha(b) == manifest['files'][n] for n, b in files.items()), 'upload hash/budget differs')
    root.mkdir(mode=0o700)
    for name in ('package', 'logs', 'attempts'):
        (root / name).mkdir(mode=0o700)
    for name, data in files.items():
        path = root / 'package' / c.member(name)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        c.write(path, data)
    c.source_check(root / 'package', manifest)
    c.write(root / 'RELEASE.json', raw)
    c.write(root / 'DEPLOYMENT.json', c.wire(before))
    return dict(status='CPU_PACKAGE_DEPLOYED', files=len(files), release_sha256=spec['release_sha256'], jobs_submitted=0)


def batch_argv(root, digest, nonce, test=False):
    return ['/usr/bin/sbatch', '--test-only' if test else '--hold', '--parsable', '--export=NONE', '--no-requeue',
        '--partition=TINY', '--account=student', '--nodes=1', '--ntasks=1', '--cpus-per-task=1', '--threads-per-core=1',
        '--mem=6000M', '--time=00:10:00', '--job-name=' + c.JOB_NAME, '--comment=g2-backend-cpu-' + nonce,
        '--chdir=' + str(root), '--input=/dev/null', '--output=' + str(root / 'logs/cpu_%j.log'),
        '--error=' + str(root / 'logs/cpu_%j.log'), str(root / 'package' / c.PREFIX / 'run_cpu.sbatch'), digest, nonce]


def submitted(root, digest):
    value = json.loads(c.read(root / 'SUBMISSION_RECEIPT.json'))
    c.require(value['release_sha256'] == digest and value['limits'] == c.LIMITS
              and re.fullmatch('[1-9][0-9]*', value['job_id']) and re.fullmatch('[a-f0-9]{32}', value['nonce']), 'submission receipt differs')
    return value


def submit(spec, execute, root=c.REMOTE):
    c.require(spec['confirm'] == c.CONFIRM, 'explicit CPU budget confirmation required')
    nonce, digest = spec['nonce'], spec['release_sha256']
    c.require(re.fullmatch('[a-f0-9]{32}', nonce), 'invalid nonce')
    test_raw = c.read(root / 'TEST_ONLY.json')
    test = json.loads(test_raw)
    c.require(c.sha(test_raw) == spec['test_sha256'] and test['release_sha256'] == digest
              and test['result']['returncode'] == 0, 'matching scheduler test required')
    queue(execute)
    # Durable intent precedes sbatch. An ambiguous reply never permits another call.
    c.write(root / 'INTENT.json', c.wire(dict(release_sha256=digest, nonce=nonce, limits=c.LIMITS,
        approved_scope='synthetic_native_inductor_cpu_pair', confirmation=spec['confirm'], automatic_retry=False)))
    response = execute(batch_argv(root, digest, nonce))
    c.write(root / 'SBATCH_RESPONSE.json', c.wire(response))
    c.require(response['returncode'] == 0 and re.fullmatch(r'[1-9][0-9]*\n?', response['stdout']), 'submission ambiguous/failed; reconcile, never retry')
    job = response['stdout'].strip()
    receipt = dict(status='SUBMITTED_HELD', job_id=job, nonce=nonce, release_sha256=digest, limits=c.LIMITS)
    c.write(root / 'SUBMISSION_RECEIPT.json', c.wire(receipt))
    held = execute(['/usr/bin/scontrol', '-o', 'show', 'job', job])
    c.write(root / 'HELD.json', c.wire(held))
    c.require(held['returncode'] == 0, 'held inspection failed; do not release')
    c.job_check(held['stdout'], job, nonce, root, held=True)
    c.write(root / 'RELEASE_INTENT.json', c.wire(receipt))
    released = execute(['/usr/bin/scontrol', 'release', job])
    c.write(root / 'RELEASE_RESPONSE.json', c.wire(released))
    c.require(released['returncode'] == 0, 'release uncertain/failed; query only')
    return {**receipt, 'status': 'CPU_JOB_RELEASED', 'jobs_submitted': 1}


def operate(spec, execute=c.command, root=c.REMOTE):
    action, digest = spec['action'], spec['release_sha256']
    if action == 'preflight':
        return preflight(execute, root)
    if action == 'deploy':
        return deployment(spec, execute, root)
    manifest = c.release(c.read(root / 'RELEASE.json'), digest)
    c.source_check(root / 'package', manifest)
    if action == 'test-only':
        queue(execute)
        result = execute(batch_argv(root, digest, spec['nonce'], test=True))
        raw = c.wire(dict(release_sha256=digest, result=result))
        h = c.write(root / 'TEST_ONLY.json', raw)
        c.require(result['returncode'] == 0, 'scheduler test rejected; no submission')
        return dict(status='CPU_SCHEDULER_TEST_PASS', test_sha256=h, result=result, jobs_submitted=0)
    if action == 'submit':
        return submit(spec, execute, root)
    c.require(action in ('status', 'collect'), 'unknown action')
    receipt = submitted(root, digest)
    job = receipt['job_id']
    accounting = execute(['/usr/bin/sacct', '-j', job, '-X', '-n', '-P', '--format=JobIDRaw,State,ExitCode,Elapsed,ReqTRES,AllocTRES,NodeList'])
    q = execute(['/usr/bin/squeue', '-h', '-j', job, '-o', '%i|%T|%j|%M|%R'])
    terminal = root / 'attempts' / ('slurm-' + job) / 'TERMINAL.json'
    result = dict(receipt=receipt, accounting=accounting, queue=q,
        terminal=json.loads(c.read(terminal)) if terminal.exists() else None)
    if action == 'collect':
        names = ['RELEASE.json', 'INTENT.json', 'SBATCH_RESPONSE.json', 'SUBMISSION_RECEIPT.json', 'HELD.json',
                 'RELEASE_INTENT.json', 'RELEASE_RESPONSE.json', 'logs/cpu_' + job + '.log']
        names += ['attempts/slurm-' + job + '/' + n for n in ['TERMINAL.json', 'ENVIRONMENT.json', 'PAIR.json'] +
                  [s + '/' + n for s in ('reference', 'observed') for n in ('result.json', 'process.json', 'child.log')]]
        files = {n: c.read(root / n) for n in names if (root / n).exists()}
        c.require(sum(map(len, files.values())) < 16 * 1024**2, 'collection budget exceeded')
        result['files'] = {n: dict(sha256=c.sha(raw), data=base64.b64encode(raw).decode()) for n, raw in files.items()}
    return result


if __name__ == '__main__':
    os.umask(0o077)
    try:
        c.require(os.uname().sysname == 'Linux', 'Linux required')
        import pwd
        c.require(pwd.getpwuid(os.getuid()).pw_name == 's2510040', 'account differs')
        result = dict(ok=True, action=SPEC['action'], result=operate(SPEC))
    except BaseException as error:
        result = dict(ok=False, action=SPEC['action'], error=dict(type=type(error).__name__, message=str(error)))
    print('CPU_BATCH_RESPONSE=' + json.dumps(result, sort_keys=True), flush=True)
    raise SystemExit(0 if result['ok'] else 2)


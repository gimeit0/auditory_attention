"""Native write-once deployment/freeze/plan operations. No scheduler submission.

Loaded by the local driver with pinned c (control), SPEC and SOURCE_BYTES.
Every invocation uses a cold isolated native interpreter. Partial writes are
retained; an existing target is never repaired, overwritten or retried here.
"""
import base64
import json
import os
from pathlib import Path
import pwd
import sys


def write_raw(path, raw):
    c.private(path.parent)
    fd = os.open(c.safe(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def native():
    c.require(sys.platform == 'linux' and sys.version.split()[0] == '3.11.5'
        and Path(sys.executable).resolve() == c.PYTHON.resolve()
        and sys.flags.isolated and sys.dont_write_bytecode
        and pwd.getpwuid(os.getuid()).pw_name == 's2510040'
        and os.environ.get('HOME') == '/home/s2510040'
        and not os.environ.get('SLURM_JOB_ID'), 'native login-node preparation required')
    c.require(c.sha(SOURCE_BYTES) == SPEC['stage_sha256'], 'stage source differs')
    c.require(c.sha(CONTROL_BYTES) == SPEC['control_sha256'], 'controller source differs')


def idle():
    result = c.command(['/usr/bin/squeue', '-h', '-u', 's2510040', '-o', '%A|%T|%j'])
    c.require(c.succeeded(result) and not result['stdout'].strip(), 'queue unavailable/nonempty')
    return result


def installed():
    root = c.REMOTE
    c.private(root)
    release_raw = c.read(root/'RELEASE.json')
    release = c.decode(release_raw, c.RELEASE_SHA)
    e = c.module('g2_stage_entry', root/c.PREFIX/'entry.py', c.ENTRY_SHA)
    c.require(set(release) == {'schema_version', 'protocol', 'files'}
        and release['schema_version'] == 1 and release['protocol'] == root.name
        and set(release['files']) == e.required_files(), 'deployment inventory differs')
    actual = {'package/'+str(p.relative_to(root/'package')) for p in (root/'package').rglob('*')
              if p.is_symlink() or not p.is_dir()}
    c.require(actual == {n for n in release['files'] if n.startswith('package/')}, 'extra package member')
    for name, digest in release['files'].items():
        c.require(c.sha(c.read(root/name)) == digest and (root/name).stat().st_mode & 0o777 == 0o600,
                  'deployed source differs: '+name)
    c.require(c.read(root/'control/control.py') == CONTROL_BYTES
              and c.read(root/'control/stage.py') == SOURCE_BYTES, 'deployed operations differ')
    for profile in e.ORDER:
        c.require({p.name for p in (root/profile/'tools').iterdir()} == set(e.TOOLS), 'profile inventory differs')
    return e, release_raw


def deploy():
    root = c.REMOTE
    c.require(not os.path.lexists(root), 'new root already exists; inspect, do not redeploy')
    c.private(root.parent)
    queue = idle()
    raw = base64.b64decode(SPEC['release'], validate=True)
    release = c.decode(raw, c.RELEASE_SHA)
    data = {name:base64.b64decode(value, validate=True) for name,value in SPEC['files'].items()}
    c.require(set(data) == set(release['files']) and len(data) == 32
              and sum(map(len, data.values())) < 16*1024**2, 'upload inventory/budget differs')
    for name, value in data.items():
        path = Path(name)
        c.require(not path.is_absolute() and '..' not in path.parts and str(path) == name
            and c.sha(value) == release['files'][name], 'unsafe or changed upload member')
    c.require(c.sha(data[c.PREFIX+'entry.py']) == c.ENTRY_SHA
              and c.sha(data[c.PREFIX+'bootstrap.py']) == c.BOOTSTRAP_SHA, 'pinned entry differs')
    root.mkdir(mode=0o700)
    for name in ('package', 'logs', 'state', 'attempts', 'control'):
        (root/name).mkdir(mode=0o700)
    for profile in ('R','C','D','E'):
        (root/profile).mkdir(mode=0o700)
        for name in ('tools','logs','state','attempts','submitted_runners'):
            (root/profile/name).mkdir(mode=0o700)
    for name, value in sorted(data.items()):
        path = root/name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_raw(path, value)
    write_raw(root/'control/control.py', CONTROL_BYTES)
    write_raw(root/'control/stage.py', SOURCE_BYTES)
    write_raw(root/'RELEASE.json', raw)
    installed()
    receipt = dict(status='G2_DEPLOYED', release_sha256=c.RELEASE_SHA, control_sha256=SPEC['control_sha256'],
                   stage_sha256=SPEC['stage_sha256'], files=32, queue=queue, jobs_submitted=0)
    c.write_once(root/'state/DEPLOYMENT.json', receipt)
    return receipt


def freeze():
    root = c.REMOTE
    e, _ = installed()
    profile = SPEC['profile']
    c.require(profile in e.ORDER, 'unknown profile')
    idle()
    c.require(not os.path.lexists(root/profile/'input_freeze.json'), 'freeze already exists; inspect only')
    c.require(not os.path.lexists(root/'state/INTENT.json'), 'submission already attempted')
    c.write_once(root/'state'/('FREEZE_'+profile+'_INTENT.json'),
                 dict(profile=profile, release_sha256=c.RELEASE_SHA, automatic_retry=False))
    bridge = c.module('g2_stage_bridge', root/'package/docs/superpowers/prototypes/g2_worker_20260916/cell_bridge.py', e.BRIDGE_SHA)
    binding = c.module('g2_stage_inputs', root/'package/docs/superpowers/prototypes/g2_inputs_20260917/input_binding.py',
                       '6a99559df859bb88cdf730d7dcd1bf72caf2f2f04800ae69781da23e64103896')
    diag = bridge.load_candidate(root/profile/'tools/diagnose_batch_invariance.py', profile)
    frozen = diag.freeze_inputs(confirm_protocol=diag.DIAGNOSTIC_PROTOCOL)
    raw = c.read(root/profile/'input_freeze.json')
    digest = c.sha(raw)
    c.require(c.decode(raw, digest) == frozen, 'saved freeze differs')
    _, proof = binding.verify_relation(bridge, diag, raw, digest,
        {n:c.read(root/profile/'tools'/n) for n in e.TOOLS}, c.read(root/'package'/e.DATA[0]))
    receipt = dict(status='G2_PROFILE_FROZEN', profile=profile, freeze_sha256=digest,
        release_sha256=c.RELEASE_SHA, relation=proof, trials=len(frozen['trials']),
        pinned_files=frozen['v4']['pinned_file_count'], jobs_submitted=0)
    c.write_once(root/'state'/('FREEZE_'+profile+'.json'), receipt)
    return dict(receipt, frozen_base64=base64.b64encode(raw).decode('ascii'))


def plan():
    root = c.REMOTE
    e, _ = installed()
    idle()
    value = SPEC['plan']
    e.validate_request(dict(value, job_id='1'))
    c.require(value['release_sha256'] == c.RELEASE_SHA and value['partition'] == c.PARTITION,
              'plan release/partition differs')
    for profile in e.ORDER:
        c.decode(c.read(root/profile/'input_freeze.json'), value['freezes'][profile])
        receipt = json.loads(c.read(root/'state'/('FREEZE_'+profile+'.json')))
        c.require(receipt['freeze_sha256'] == value['freezes'][profile]
            and receipt['release_sha256'] == c.RELEASE_SHA and receipt['trials'] == 32
            and receipt['pinned_files'] == 24 and receipt['relation']['status'] == 'G2_SCIENTIFIC_INPUT_RELATION_PASS',
            'freeze receipt differs')
    c.require(not os.path.lexists(root/'state/INTENT.json'), 'submission already attempted')
    digest = c.write_once(root/'EXECUTION_PLAN.json', value)
    return dict(status='G2_PLAN_CREATED', plan_sha256=digest, plan=value, jobs_submitted=0)


def operate():
    os.umask(0o077)
    native()
    if SPEC['action'] == 'deploy': return deploy()
    if SPEC['action'] == 'freeze': return freeze()
    if SPEC['action'] == 'plan': return plan()
    raise RuntimeError('unknown staging action')


if __name__ == '__main__':
    try:
        answer = dict(ok=True, action=SPEC['action'], result=operate())
    except BaseException as exc:
        answer = dict(ok=False, action=SPEC['action'], error=dict(type=type(exc).__name__, message=str(exc)), automatic_retry=False)
    print('G2_STAGE_RESULT='+json.dumps(answer, sort_keys=True), flush=True)
    raise SystemExit(0 if answer['ok'] else 2)

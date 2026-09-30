"""Reconcile one existing, never-started held job; no submission or retry.

Kept outside the immutable execution release. Update and release are separate
write-once actions. Only the observed H100/generic request may be corrected to
the already approved single A100; all other request fields must match.
"""
import argparse
import base64
import datetime
import json
import os
from pathlib import Path
import sys
import tempfile

JOB = '724258'
NONCE = '69ca46b61e7a414d8d29c3bcf1ca200d'
PLAN = 'f8d8e491fe64c3430845b25d850e8e992ea71ecd79c52d744089a318b6e4e59e'
REQUEST = '7225bb609611114f84026e4eca7fc107ac5ccfb8db4946f2bceb81db9565e309'
TEST = '4a5d468e6bacbe39a7d7e041864033b78785cfd958408982a8bdb93a456f9579'
CONTROL = '581fcaafc6e4d9ef59a1d534acce7d04532ba0a3e0a6bd35769d234910e60956'
GPU = 'gres/gpu:nvidia_a100:1'
UPDATE = ['/usr/bin/scontrol', 'update', 'JobId='+JOB,
          'TresPerJob='+GPU, 'TresPerNode='+GPU]
RELEASE = ['/usr/bin/scontrol', 'release', JOB]
JOURNALS = ('INTENT.json', 'SBATCH_RESPONSE.json', 'SUBMISSION_RECEIPT.json',
            'HELD.json', 'TEST_ONLY.json', 'GPU_TYPE_UPDATE_INTENT.json',
            'GPU_TYPE_UPDATE_RESPONSE.json', 'GPU_TYPE_UPDATE_READBACK.json',
            'GPU_TYPE_UPDATED.json', 'RELEASE_INTENT.json',
            'RELEASE_RESPONSE.json', 'RELEASE_READBACK.json', 'RELEASED.json',
            'CHECK_R.json', 'CHECK_C.json', 'CHECK_D.json', 'CHECK_E.json')


def tres(c, raw):
    pairs = [s.split('=', 1) for s in raw.split(',')]
    c.require(all(len(p) == 2 for p in pairs) and len(dict(pairs)) == len(pairs), 'bad TRES')
    value = dict(pairs)
    if value.get('mem') == '65536M':
        value['mem'] = '64G'
    return value


def checked(c, context):
    context.check()
    c.require(context.plan_sha == PLAN and context.control_sha == CONTROL
              and context.plan['nonce'] == NONCE, 'fixed original plan required')
    request = c.decode(c.read(context.root/'RUN_REQUEST.json'), REQUEST)
    c.require(request == context.request(JOB), 'original job/request binding differs')
    test = c.decode(c.read(context.state/'TEST_ONLY.json'), TEST)
    c.require(test['plan_sha256'] == PLAN and test['control_sha256'] == CONTROL
              and test['release_sha256'] == c.RELEASE_SHA and c.succeeded(test['result'])
              and set(test['profiles']) == set(context.e.ORDER), 'original test differs')
    for profile, digest in test['profiles'].items():
        c.require(c.sha(c.read(context.state/('CHECK_'+profile+'.json'))) == digest, 'profile check drift')
    intent = json.loads(c.read(context.state/'INTENT.json'))
    c.require(intent['plan_sha256'] == PLAN and intent['control_sha256'] == CONTROL
              and intent['release_sha256'] == c.RELEASE_SHA and intent['nonce'] == NONCE
              and intent['limits'] == context.plan['limits'] and intent['test_sha256'] == TEST
              and intent['confirmation'] == c.CONFIRM and intent['automatic_retry'] is False
              and intent['argv'] == c.batch_argv(context), 'original single-submit authority differs')
    response = json.loads(c.read(context.state/'SBATCH_RESPONSE.json'))
    c.require(c.succeeded(response) and response['stdout'].strip() == JOB
              and response['argv'] == intent['argv'], 'original submission differs')
    receipt = json.loads(c.read(context.state/'SUBMISSION_RECEIPT.json'))
    c.require(receipt == dict(status='SUBMITTED_HELD', job_id=JOB, plan_sha256=PLAN,
        request_sha256=REQUEST, release_sha256=c.RELEASE_SHA, control_sha256=CONTROL,
        nonce=NONCE, automatic_retry=False), 'original receipt differs')
    return request


def snapshot(execute):
    return dict(
        version=execute(['/usr/bin/scontrol', '--version']),
        job=execute(['/usr/bin/scontrol', '-o', 'show', 'job', JOB]),
        accounting=execute(['/usr/bin/sacct', '-j', JOB, '-X', '-n', '-P',
            '--format=JobIDRaw,State,ReqTRES%256,AllocTRES%256,Elapsed']),
        nodes=execute(['/usr/bin/sinfo', '-p', 'GPU-1A', '-N', '-h', '-o', '%N|%G|%t']),
        queue=execute(['/usr/bin/squeue', '-h', '-u', 's2510040', '-o', '%i|%T|%j|%k']))


def validate(c, context, value, *, corrected):
    for name, result in value.items():
        c.require(c.succeeded(result), 'query failed: '+name)
    c.require(value['version']['stdout'].strip() == 'slurm 25.05.5', 'unreviewed Slurm version')
    c.require(value['queue']['stdout'].strip() == JOB+'|PENDING|audattn_g2_matrix|g2-matrix-'+NONCE,
              'account queue changed')
    nodes = [s.split('|') for s in value['nodes']['stdout'].splitlines() if s.strip()]
    c.require(len(nodes) == 10 and {s[0] for s in nodes} == {'spcc-a100g%02d'%i for i in range(1, 11)}
              and all(len(s) == 3 and s[1] == 'gpu:nvidia_a100:2(S:0-1)' for s in nodes), 'A100 node inventory differs')
    raw = value['job']['stdout']
    fields = context.e.scheduler_fields(raw)
    requested = tres(c, fields.get('ReqTRES', ''))
    if not corrected:
        c.require(fields.get('TresPerNode') == 'gres/gpu:1' and 'TresPerJob' not in fields
                  and requested == {'cpu':'8', 'mem':'64G', 'node':'1', 'billing':'8', 'gres/gpu:h100-20c':'1'},
                  'not the exact observed unallocated GPU mismatch')
        # Validate all other fields using the unchanged production validator.
        # This normalized view is solely a pre-update guard, never evidence of A100.
        normalized = dict(fields, TresPerNode=GPU)
        normalized['ReqTRES'] = fields['ReqTRES'].replace('gres/gpu:h100-20c=1', 'gres/gpu:nvidia_a100=1')
        context.e.check_scheduler(' '.join(k+'='+v for k,v in normalized.items()), context.request(JOB), held=True)
    else:
        context.e.check_scheduler(raw, context.request(JOB), held=True)
        c.require(fields.get('TresPerJob') == GPU, 'corrected total GPU request absent')
    lines = [s.split('|') for s in value['accounting']['stdout'].splitlines() if s.strip()]
    c.require(len(lines) == 1 and len(lines[0]) == 5, 'one accounting record required')
    job, state, req, alloc, elapsed = lines[0]
    c.require(job == JOB and state == 'PENDING' and alloc == '' and elapsed == '00:00:00'
              and tres(c, req) == requested, 'independent accounting differs; keep held')


def mutate(c, context, spec, execute):
    action = spec['action']
    c.require(action in ('update', 'release'), 'unknown recovery action')
    checked(c, context)
    for name in ('RELEASE_INTENT.json', 'RELEASE_RESPONSE.json', 'RELEASED.json'):
        c.require(not os.path.lexists(context.state/name), 'release already attempted; inspect only')
    c.require(not any((context.root/'attempts').iterdir())
              and all(not any((context.root/p/'attempts').iterdir()) for p in context.e.ORDER),
              'execution evidence exists; inspect only')
    before = snapshot(execute)
    validate(c, context, before, corrected=(action == 'release'))
    if action == 'release':
        prior = json.loads(c.read(context.state/'GPU_TYPE_UPDATED.json'))
        c.require(prior['status'] == 'A100_CORRECTED_STILL_HELD' and prior['job_id'] == JOB
                  and prior['repair_sha256'] == spec['repair_sha256'], 'verified same-source update required')
        update_intent = json.loads(c.read(context.state/'GPU_TYPE_UPDATE_INTENT.json'))
        update_response = json.loads(c.read(context.state/'GPU_TYPE_UPDATE_RESPONSE.json'))
        c.require(update_intent['argv'] == UPDATE and update_intent['plan_sha256'] == PLAN
                  and update_intent['repair_sha256'] == spec['repair_sha256']
                  and c.succeeded(update_response) and update_response['argv'] == UPDATE, 'update RPC evidence differs')
        validate(c, context, prior['after'], corrected=True)
    prefix = 'GPU_TYPE_UPDATE' if action == 'update' else 'RELEASE'
    argv = UPDATE if action == 'update' else RELEASE
    record = dict(job_id=JOB, nonce=NONCE, plan_sha256=PLAN, request_sha256=REQUEST,
        repair_sha256=spec['repair_sha256'], argv=argv, before=before,
        authority='Restore existing never-started job to its approved A100 budget; no additional job.',
        jobs_submitted=0, automatic_retry=False)
    c.write_once(context.state/(prefix+'_INTENT.json'), record)
    response = execute(argv)
    c.write_once(context.state/(prefix+'_RESPONSE.json'), response)
    after = snapshot(execute)
    c.write_once(context.state/(prefix+'_READBACK.json'), after)
    c.require(c.succeeded(response), 'RPC failed/uncertain; do not retry')
    checked(c, context)
    if action == 'update':
        validate(c, context, after, corrected=True)
    else:
        c.require(c.succeeded(after['job']), 'release successful but readback failed; inspect only')
        old = context.e.scheduler_fields(before['job']['stdout'])
        live = context.e.scheduler_fields(after['job']['stdout'])
        stable = ('JobId', 'JobName', 'UserId', 'Comment', 'Partition', 'Account', 'NumCPUs',
            'NumTasks', 'CPUs/Task', 'TimeLimit', 'Requeue', 'Restarts', 'Command', 'WorkDir',
            'StdIn', 'StdOut', 'StdErr', 'TresPerJob', 'TresPerNode', 'TresPerTask', 'MinMemoryNode')
        c.require(all(old.get(k) == live.get(k) for k in stable)
                  and tres(c, old['ReqTRES']) == tres(c, live.get('ReqTRES', ''))
                  and live.get('Priority') not in (None, '0')
                  and live.get('Reason') not in ('JobHeldUser', 'JobHeldAdmin'), 'release readback differs')
    result = dict(status='A100_CORRECTED_STILL_HELD' if action == 'update' else 'SAME_JOB_RELEASED',
        job_id=JOB, repair_sha256=spec['repair_sha256'], jobs_submitted=0, automatic_retry=False, after=after)
    c.write_once(context.state/('GPU_TYPE_UPDATED.json' if action == 'update' else 'RELEASED.json'), result)
    return result


def remote(spec, c):
    context = c.Context(PLAN, CONTROL)
    checked(c, context)
    if spec['action'] == 'inspect':
        return dict(status='READ_ONLY', job_id=JOB, snapshot=snapshot(c.command), journals={
            name:json.loads(c.read(context.state/name)) for name in JOURNALS if os.path.lexists(context.state/name)})
    return mutate(c, context, spec, c.command)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect', 'update', 'release'))
    parser.add_argument('--expected-source-sha256', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    here = Path(__file__).absolute().parent
    sys.path.insert(0, str(here))
    import ship
    c = ship.c
    controller, _, _, _ = ship.sources()
    source = c.read(Path(__file__).absolute())
    c.require(c.sha(source) == args.expected_source_sha256, 'recovery source changed')
    spec = dict(action=args.action, job_id=JOB, plan_sha256=PLAN, repair_sha256=c.sha(source))
    transport = ship.transport_module()
    transport.master_check(transport.SOCKET)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    folder = Path(tempfile.mkdtemp(prefix='repair-'+args.action+'-'+stamp, dir=ship.EVIDENCE))
    print('G2_REPAIR_EVIDENCE='+str(folder), flush=True)
    if args.action != 'inspect':
        c.write_once(ship.EVIDENCE/('LOCAL_724258_'+args.action.upper()+'_INTENT.json'), dict(spec, evidence=str(folder)))
    code = 'import base64,hashlib,types,sys\nSPEC='+repr(spec)+'\n'
    for name, raw, path in (('c', controller, str(c.REMOTE/'control/control.py')), ('repair', source, '<pinned-held-recovery>')):
        code += 'raw=base64.b64decode('+repr(base64.b64encode(raw).decode())+',validate=True)\n'
        code += 'assert hashlib.sha256(raw).hexdigest()=='+repr(c.sha(raw))+'\n'
        code += name+'=types.ModuleType('+repr('g2_recovery_'+name)+'); '+name+'.__file__='+repr(path)+'\n'
        code += 'sys.modules['+name+'.__name__]='+name+'\nexec(compile(raw,'+repr(path)+',"exec"),vars('+name+'))\n'
    code += 'import json\ntry:\n result={"ok":True,"result":repair.remote(SPEC,c)}\n'
    code += 'except Exception as e:\n result={"ok":False,"error":{"type":type(e).__name__,"message":str(e)}}\n'
    code += 'print("G2_REPAIR_RESULT="+json.dumps(result),flush=True)\nraise SystemExit(0 if result["ok"] else 2)\n'
    payload = code.encode('ascii')
    run = transport.transport(transport.ssh_command(transport.SOCKET), payload, folder, timeout=180, log_cap=8*1024**2)
    output = c.read(folder/'output.log', 8*1024**2)
    prefix = 'G2_REPAIR_RESULT='
    lines = [s[len(prefix):] for s in output.decode(errors='replace').splitlines() if s.startswith(prefix)]
    result = json.loads(lines[0]) if len(lines) == 1 else None
    ok = c.succeeded(run) and result is not None and result['ok']
    c.write_once(folder/'RECEIPT.json', dict(spec=spec, result=result, transport=run,
        payload_sha256=c.sha(payload), output_sha256=c.sha(output), returncode=0 if ok else 2))
    ship.sources()
    c.require(c.sha(c.read(Path(__file__).absolute())) == spec['repair_sha256'], 'recovery source drift')
    print(json.dumps({k:v for k,v in result.get('result', result).items() if k not in ('after','snapshot','journals')}) if result else output.decode(errors='replace')[-4000:])
    return 0 if ok else 2


if __name__ == '__main__':
    raise SystemExit(main())

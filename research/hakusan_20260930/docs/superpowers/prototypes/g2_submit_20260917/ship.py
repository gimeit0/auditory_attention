"""Explicit stage/control actions via an existing SSH master; never retry.

Keeps write-once local action journals, complete payload/output logs and remote
receipts. Reads the existing immutable candidate, not a newly rebuilt package.
"""
import argparse
import base64
import datetime
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import uuid

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import control as c

CANDIDATE = ROOT/'docs/superpowers/evidence/g2-entry-local-20260917T063951Z-zcygp8in/candidate'
EVIDENCE = ROOT/'docs/superpowers/evidence/g2-production-20260917'
CONTROL_SHA = '581fcaafc6e4d9ef59a1d534acce7d04532ba0a3e0a6bd35769d234910e60956'
TRANSPORT_DIR = HERE.parent/'targeted_gpu_control_20260914_v4'
TRANSPORT_SHA = '6316b50dec15365c4562953fda04411fc95ba68d5f2cfc8383b1dc9db8e78754'
OPS_SHA = 'b4766450edae186912e586bd862e7d30697ef7b69e82c35f6ca6b8b63e18e06d'


def sources():
    control = c.read(HERE/'control.py')
    c.require(c.sha(control) == CONTROL_SHA, 'controller differs from reviewed source')
    raw = c.read(CANDIDATE/'RELEASE.json')
    release = c.decode(raw, c.RELEASE_SHA)
    files = {n:c.read(CANDIDATE/n) for n in release['files']}
    c.require(all(c.sha(data) == release['files'][n] for n,data in files.items()), 'candidate source changed')
    expected = set(files) | {'RELEASE.json'}
    c.require({str(p.relative_to(CANDIDATE)) for p in CANDIDATE.rglob('*') if p.is_symlink() or not p.is_dir()} == expected,
              'candidate inventory drift')
    return control, c.read(HERE/'stage.py'), raw, files


def transport_module():
    c.module('remote_ops', TRANSPORT_DIR/'remote_ops.py', OPS_SHA)
    return c.module('g2_shared_transport', TRANSPORT_DIR/'control.py', TRANSPORT_SHA)


def payload(spec, control, stage):
    header = 'import base64,types,sys,hashlib\nSPEC='+repr(spec)+'\n'
    header += 'CONTROL_BYTES=base64.b64decode('+repr(base64.b64encode(control).decode())+',validate=True)\n'
    header += 'assert hashlib.sha256(CONTROL_BYTES).hexdigest()=='+repr(CONTROL_SHA)+'\n'
    header += 'c=types.ModuleType("g2_ship_control"); c.__file__='+repr(str(c.REMOTE/'control/control.py'))+'; sys.modules[c.__name__]=c\n'
    header += 'exec(compile(CONTROL_BYTES,c.__file__,"exec"),vars(c))\n'
    if spec['action'] in ('deploy','freeze','plan'):
        header += 'SOURCE_BYTES=base64.b64decode('+repr(base64.b64encode(stage).decode())+',validate=True)\n'
        header += 'assert hashlib.sha256(SOURCE_BYTES).hexdigest()==SPEC["stage_sha256"]\n'
        header += 'exec(compile(SOURCE_BYTES,"<g2-write-once-stage>","exec"))\n'
    else:
        argv = [str(c.PYTHON), '-I', '-B', str(c.REMOTE/'control/control.py'), spec['action'],
                '--plan-sha256', spec['plan_sha256'], '--control-sha256', CONTROL_SHA]
        if spec['action'] == 'submit':
            argv += ['--test-sha256', spec['test_sha256'], '--confirm', c.CONFIRM]
        header += 'import os\nassert c.read(c.REMOTE/"control/control.py")==CONTROL_BYTES\n'
        header += 'os.execv('+repr(str(c.PYTHON))+','+repr(argv)+')\n'
    return header.encode('ascii')


def recorded(folder):
    value = json.loads(c.read(folder/'RECEIPT.json'))
    c.require(value['returncode'] == 0 and value['transport']['returncode'] == 0
              and value['transport']['error'] is None, 'successful receipt required')
    c.require(c.sha(c.read(folder/'output.log', 8*1024**2)) == value['output_sha256']
              and c.sha(c.read(folder/'request.py', 16*1024**2)) == value['payload_sha256'], 'saved transport drift')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('deploy','freeze','plan','test-only','submit','status','local-check'))
    parser.add_argument('--profile', choices=('R','C','D','E'))
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--plan-sha256')
    parser.add_argument('--test-receipt', type=Path)
    parser.add_argument('--confirm')
    args = parser.parse_args()
    os.umask(0o077)
    control, stage, raw, files = sources()
    if args.action == 'local-check':
        for name in ('ship.py','stage.py','control.py'):
            compile(c.read(HERE/name), str(HERE/name), 'exec')
        print(json.dumps(dict(status='G2_SHIP_LOCAL_SOURCES_CHECKED', release_sha256=c.RELEASE_SHA,
            control_sha256=CONTROL_SHA, stage_sha256=c.sha(stage), files=len(files), jobs_submitted=0)))
        return 0
    spec = dict(action=args.action, release_sha256=c.RELEASE_SHA, control_sha256=CONTROL_SHA, stage_sha256=c.sha(stage))
    if args.action == 'deploy':
        spec.update(release=base64.b64encode(raw).decode(), files={n:base64.b64encode(data).decode() for n,data in files.items()})
    elif args.action == 'freeze':
        c.require(args.profile is not None, 'one profile required')
        spec['profile'] = args.profile
    elif args.action == 'plan':
        c.require(args.plan is not None and args.plan_sha256 is not None, 'external reviewed plan required')
        spec['plan'] = c.decode(c.read(args.plan.absolute()), args.plan_sha256)
    else:
        c.require(args.plan_sha256 is not None, 'external reviewed plan SHA required')
        spec['plan_sha256'] = args.plan_sha256
    if args.action == 'submit':
        c.require(args.confirm == c.CONFIRM and args.test_receipt is not None, 'explicit approved budget and test receipt required')
        previous = recorded(args.test_receipt.absolute())
        c.require(previous['spec']['action'] == 'test-only' and previous['spec']['plan_sha256'] == args.plan_sha256
                  and previous['result']['status'] == 'G2_SCHEDULER_TEST_PASS', 'matching successful test required')
        spec['test_sha256'] = previous['result']['test_sha256']
        spec['confirmation'] = args.confirm
    else:
        c.require(args.confirm is None and args.test_receipt is None, 'approval arguments only for submit')
    t = transport_module()
    t.master_check(t.SOCKET)
    EVIDENCE.mkdir(mode=0o700, exist_ok=True)
    c.private(EVIDENCE)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    folder = Path(tempfile.mkdtemp(prefix=args.action+'-'+stamp, dir=EVIDENCE))
    print('G2_ACTION_EVIDENCE='+str(folder), flush=True)
    summary = {k:v for k,v in spec.items() if k not in ('files','release')}
    if args.action != 'status':
        key = args.action + ('-'+args.profile if args.action == 'freeze' else '')
        c.write_once(EVIDENCE/('LOCAL_'+key+'_INTENT.json'), dict(summary, evidence=str(folder), automatic_retry=False))
    request = payload(spec, control, stage)
    run = t.transport(t.ssh_command(t.SOCKET), request, folder,
                      timeout=660 if args.action == 'test-only' else 180, log_cap=8*1024**2)
    output = c.read(folder/'output.log', 8*1024**2)
    prefix = 'G2_STAGE_RESULT=' if args.action in ('deploy','freeze','plan') else 'G2_CONTROL_RESULT='
    lines = [line[len(prefix):] for line in output.decode(errors='replace').splitlines() if line.startswith(prefix)]
    parsed = json.loads(lines[0]) if len(lines) == 1 else None
    ok = run['returncode'] == 0 and run['error'] is None and parsed is not None
    if prefix == 'G2_STAGE_RESULT=':
        ok = ok and parsed['ok'] and parsed['action'] == args.action
    result = parsed['result'] if parsed and prefix == 'G2_STAGE_RESULT=' and parsed['ok'] else parsed
    receipt = dict(spec=summary, result=result, transport=run, payload_sha256=c.sha(request),
        output_sha256=c.sha(output), returncode=0 if ok else 2, automatic_retry=False)
    c.write_once(folder/'RECEIPT.json', receipt)
    if args.action == 'freeze' and ok:
        frozen = base64.b64decode(result['frozen_base64'], validate=True)
        c.decode(frozen, result['freeze_sha256'])
        # Independent local preservation of the actual remotely frozen bytes.
        write = t.ops.write_new
        write(folder/'input_freeze.json', frozen)
    if result:
        printable = {k:v for k,v in result.items() if k != 'frozen_base64'}
        print(json.dumps(printable, sort_keys=True), flush=True)
    if not ok:
        print(output.decode(errors='replace')[-12000:], flush=True)
        print('STOP: action failed/uncertain; preserve evidence and query; no retry.', flush=True)
    sources()
    return 0 if ok else 2


if __name__ == '__main__':
    raise SystemExit(main())

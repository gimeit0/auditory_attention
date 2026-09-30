"""Read-only terminal evidence download for the one fixed G2 job.

Uses the existing authenticated master only. No submit, update, release or
reconnect. Bounded download includes exact release, freezes, state and attempts.
"""
import base64
import datetime
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile

REPAIR_SHA = '931cd810c24a2ba1db94ed1351630b2e5a621948ea35fe607c2bfb2a450ff8dd'


def remote(c, repair):
    context = c.Context(repair.PLAN, repair.CONTROL)
    repair.checked(c, context)
    accounting = c.command(['/usr/bin/sacct', '-j', repair.JOB, '-X', '-n', '-P',
        '--format=JobIDRaw,State,ExitCode,Elapsed,Start,End,ReqTRES%256,AllocTRES%256,NodeList'])
    c.require(c.succeeded(accounting), 'accounting query failed')
    rows = [s.split('|') for s in accounting['stdout'].splitlines() if s.strip()]
    c.require(len(rows) == 1 and len(rows[0]) == 9 and rows[0][0] == repair.JOB
              and rows[0][1] in ('COMPLETED', 'FAILED', 'TIMEOUT', 'CANCELLED', 'OUT_OF_MEMORY'), 'terminal job required')
    root = context.root
    release = c.decode(c.read(root/'RELEASE.json'), c.RELEASE_SHA)
    names = set(release['files']) | {'RELEASE.json', 'EXECUTION_PLAN.json', 'RUN_REQUEST.json',
        'control/control.py', 'control/stage.py', 'logs/matrix_'+repair.JOB+'.log'}
    names.update(p+'/input_freeze.json' for p in context.e.ORDER)
    directories = [root/'state', root/'attempts'/('slurm-'+repair.JOB)]
    directories += [root/p/'attempts'/('slurm-'+repair.JOB) for p in context.e.ORDER]
    for directory in directories:
        c.safe(directory)
        if not directory.exists(): continue
        for path in directory.rglob('*'):
            c.safe(path)
            if not path.is_dir(): names.add(str(path.relative_to(root)))
    c.require(len(names) <= 512, 'collection file count exceeds budget')
    files, total = {}, 0
    for name in sorted(names):
        path = PurePosixPath(name)
        c.require(not path.is_absolute() and '..' not in path.parts and str(path) == name, 'unsafe collection name')
        raw = c.read(root/name, 16*1024**2)
        total += len(raw)
        c.require(total <= 16*1024**2, 'collection byte budget exceeded')
        files[name] = dict(sha256=c.sha(raw), size=len(raw), data=base64.b64encode(raw).decode())
    # Preserve exact bytes and prove the finished files stayed stable throughout.
    for name, record in files.items():
        c.require(c.sha(c.read(root/name, 16*1024**2)) == record['sha256'], 'evidence changed while collecting')
    repair.checked(c, context)
    return dict(status='G2_TERMINAL_EVIDENCE_DOWNLOADED', job_id=repair.JOB,
        plan_sha256=repair.PLAN, release_sha256=c.RELEASE_SHA, accounting=accounting,
        file_count=len(files), total_bytes=total, files=files, jobs_submitted=0,
        numeric_results_verified=False)


def main():
    os.umask(0o077)
    here = Path(__file__).absolute().parent
    sys.path.insert(0, str(here))
    import ship
    c = ship.c
    controller, _, _, _ = ship.sources()
    repair = c.read(here/'repair_724258.py')
    c.require(c.sha(repair) == REPAIR_SHA, 'reviewed recovery source differs')
    source = c.read(Path(__file__).absolute())
    transport = ship.transport_module()
    transport.master_check(transport.SOCKET)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    folder = Path(tempfile.mkdtemp(prefix='terminal-'+stamp, dir=ship.EVIDENCE))
    print('G2_TERMINAL_EVIDENCE='+str(folder), flush=True)
    code = 'import base64,hashlib,types,sys,json\n'
    for name, raw, path in (('c', controller, str(c.REMOTE/'control/control.py')),
                           ('repair', repair, '<pinned-recovery>'), ('collect', source, '<read-only-collect>')):
        code += 'raw=base64.b64decode('+repr(base64.b64encode(raw).decode())+',validate=True)\n'
        code += 'assert hashlib.sha256(raw).hexdigest()=='+repr(c.sha(raw))+'\n'
        code += name+'=types.ModuleType('+repr('g2_collect_'+name)+'); '+name+'.__file__='+repr(path)+'\n'
        code += 'sys.modules['+name+'.__name__]='+name+'\nexec(compile(raw,'+repr(path)+',"exec"),vars('+name+'))\n'
    code += 'try:\n result={"ok":True,"result":collect.remote(c,repair)}\n'
    code += 'except Exception as e:\n result={"ok":False,"error":{"type":type(e).__name__,"message":str(e)}}\n'
    code += 'print("G2_COLLECT="+json.dumps(result),flush=True)\nraise SystemExit(0 if result["ok"] else 2)\n'
    payload = code.encode('ascii')
    run = transport.transport(transport.ssh_command(transport.SOCKET), payload, folder, timeout=180, log_cap=24*1024**2)
    output = c.read(folder/'output.log', 24*1024**2)
    prefix = 'G2_COLLECT='
    lines = [s[len(prefix):] for s in output.decode(errors='replace').splitlines() if s.startswith(prefix)]
    result = json.loads(lines[0]) if len(lines) == 1 else None
    ok = c.succeeded(run) and result is not None and result['ok']
    manifest = {}
    if ok:
        download = folder/'download'
        download.mkdir(mode=0o700)
        for name, record in result['result']['files'].items():
            member = PurePosixPath(name)
            c.require(not member.is_absolute() and '..' not in member.parts and str(member) == name
                      and member.parts and member.parts[0] in (
                          'RELEASE.json', 'EXECUTION_PLAN.json', 'RUN_REQUEST.json',
                          'package', 'control', 'state', 'logs', 'attempts', 'R', 'C', 'D', 'E'),
                      'unsafe downloaded member')
            raw = base64.b64decode(record['data'], validate=True)
            c.require(len(raw) == record['size'] and c.sha(raw) == record['sha256'], 'download content mismatch')
            path = download/member
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            transport.ops.write_new(path, raw)
            c.require(c.sha(c.read(path, 16*1024**2)) == record['sha256'], 'local saved content differs')
            manifest[name] = {k:v for k,v in record.items() if k != 'data'}
        result['result']['files'] = manifest
    c.write_once(folder/'RECEIPT.json', dict(result=result, transport=run,
        payload_sha256=c.sha(payload), output_sha256=c.sha(output), returncode=0 if ok else 2))
    ship.sources()
    c.require(c.read(Path(__file__).absolute()) == source, 'collector source changed')
    print(json.dumps({k:v for k,v in result.get('result', result).items() if k != 'files'}) if result else output.decode(errors='replace')[-4000:])
    return 0 if ok else 2


if __name__ == '__main__':
    raise SystemExit(main())

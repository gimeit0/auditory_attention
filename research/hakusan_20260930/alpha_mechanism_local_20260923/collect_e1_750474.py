"""Read-only collection of the completed authorized job; never reconnects or submits."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile

BASE = Path(__file__).resolve().parent / 'release_e1_20260927_v3'
DIGEST = '558fa3fb953704b3fbf52952c9e474ef9824dead2e4c0eb2adaaa21a561dffd3'
SSH = ['/usr/bin/ssh', '-S', '/Users/gigi/发表/超算/.hakusan-control/master.sock',
       '-o', 'ControlMaster=no', '-o', 'BatchMode=yes', '-o', 'ProxyCommand=false',
       '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2', 's2510040@hakusan1']
REMOTE = r'''
import hashlib, io, json, pathlib, subprocess, sys, tarfile
r = pathlib.Path('/home/s2510040/audattn_e1/e1_20260927_v3/state')
assert r.is_dir() and not r.is_symlink()
paths = sorted(r.rglob('*'))
assert all(not p.is_symlink() and (p.is_dir() or p.is_file()) for p in paths)
files = [p for p in paths if p.is_file()]
assert len(files) < 200 and sum(p.stat().st_size for p in files) < 256*1024**2
done = json.loads((r/'attempt/E1_COMPLETE.json').read_bytes())
assert done['job_id'] == '750474' and done['status'] == 'E1_EXECUTION_VERIFIED_ANALYSIS_PENDING'
inventory = {str(p.relative_to(r)): {'size': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in files}
a = subprocess.run(['sacct','-j','750474','-X','-P','--format=JobIDRaw,State,ExitCode,Elapsed,Start,End,NodeList'],capture_output=True,text=True,timeout=30,check=True).stdout
assert '750474|COMPLETED|0:0|' in a
meta = json.dumps({'files':inventory,'sacct':a},sort_keys=True,indent=2).encode()
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as t:
    info = tarfile.TarInfo('COLLECTION_MANIFEST.json'); info.size = len(meta)
    t.addfile(info,io.BytesIO(meta))
    for p in files:
        data = p.read_bytes(); name = str(p.relative_to(r))
        assert {'size':len(data),'sha256':hashlib.sha256(data).hexdigest()} == inventory[name]
        info = tarfile.TarInfo('state/'+name); info.size = len(data)
        t.addfile(info,io.BytesIO(data))
assert sorted(r.rglob('*')) == paths
assert all(hashlib.sha256(p.read_bytes()).hexdigest() == inventory[str(p.relative_to(r))]['sha256'] for p in files)
'''

def main():
    out = Path(tempfile.mkdtemp(prefix='collected-750474-', dir=BASE))
    print('COLLECTION_DIRECTORY='+str(out), flush=True)
    try:
        with (out/'transport.tar').open('xb') as stream, (out/'transport.stderr').open('xb') as err:
            p = subprocess.run(SSH+['/home/s2510040/miniconda3/envs/attn/bin/python -I -B -'],
                               input=REMOTE.encode(), stdout=stream, stderr=err, timeout=240)
        if p.returncode: raise RuntimeError('SSH_COLLECTION_RC='+str(p.returncode))
        if (out/'transport.tar').stat().st_size > 257*1024**2: raise ValueError('ARCHIVE_LIMIT')
        with tarfile.open(out/'transport.tar', 'r:') as tar:
            members = tar.getmembers()
            names = [m.name for m in members]
            if len(names) != len(set(names)) or len(names)>201: raise ValueError('INVENTORY')
            manifest = json.load(tar.extractfile('COLLECTION_MANIFEST.json'))
            expected = {'COLLECTION_MANIFEST.json'} | {'state/'+n for n in manifest['files']}
            if set(names)!=expected: raise ValueError('ARCHIVE_INVENTORY')
            for m in members:
                path = PurePosixPath(m.name)
                if not m.isfile() or path.is_absolute() or '..' in path.parts: raise ValueError('UNSAFE_MEMBER')
                raw = tar.extractfile(m).read()
                if m.name != 'COLLECTION_MANIFEST.json':
                    if dict(size=len(raw),sha256=hashlib.sha256(raw).hexdigest()) != manifest['files'][m.name[6:]]:
                        raise ValueError('TRANSFER_SHA')
                dest = out/m.name
                dest.parent.mkdir(parents=True,exist_ok=True)
                with dest.open('xb') as f: f.write(raw)
        with (out/'offline-check.json').open('xb') as stdout, (out/'offline-check.stderr').open('xb') as stderr:
            p = subprocess.run([sys.executable,'-I','-B',str(BASE/'package_ready/e1_entry.py'),
                'offline-check',DIGEST,str(out/'state/attempt'),'750474'],stdout=stdout,stderr=stderr,timeout=180)
        if p.returncode: raise RuntimeError('OFFLINE_CHECK_RC='+str(p.returncode))
        result=json.loads((out/'offline-check.json').read_bytes())
        if result.get('verified') is not True: raise ValueError('NOT_VERIFIED')
        summary=dict(status='E1_COLLECTED_OFFLINE_VERIFIED_ANALYSIS_PENDING',job_id='750474',
                     release_sha256=DIGEST,files=len(manifest['files']),sacct=manifest['sacct'],
                     scientific_conclusion=False,jobs_submitted=0)
        (out/'RESULT.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps(summary),flush=True)
    except Exception as e:
        (out/'COLLECTION_FAILED.json').write_text(json.dumps({'error':str(e),'automatic_retry':False})+'\n')
        raise

if __name__ == '__main__': main()

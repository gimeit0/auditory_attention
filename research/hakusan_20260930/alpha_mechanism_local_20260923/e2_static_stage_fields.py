"""Extract only literal epoch/global_step using pickle disassembly, never load."""
import hashlib
import io
import json
from pathlib import Path
import pickletools
import signal
import stat
import zipfile
import os

def literal_stage_fields(data):
    # No pickle.loads, REDUCE execution, class imports or persistent-load calls.
    wanted = {'epoch', 'global_step'}
    found = {}
    pending = None
    for op, arg, pos in pickletools.genops(data):
        if pending is not None:
            if op.name in ('BINPUT', 'LONG_BINPUT', 'MEMOIZE'):
                continue
            if op.name not in ('BININT', 'BININT1', 'BININT2', 'LONG1', 'LONG4', 'INT', 'LONG') or type(arg) is not int:
                raise ValueError('NONLITERAL_STAGE_FIELD')
            found[pending] = arg
            pending = None
        elif op.name in ('BINUNICODE','SHORT_BINUNICODE','UNICODE','BINUNICODE8') and arg in wanted:
            if arg in found: raise ValueError('AMBIGUOUS_REPEATED_STAGE_FIELD')
            pending = arg
    if pending is not None or set(found) != wanted:
        raise ValueError('MISSING_STAGE_FIELDS')
    return found

def inspect(row):
    path=Path(row['path'])
    for p in reversed((path,*path.parents)):
        if stat.S_ISLNK(p.lstat().st_mode): raise ValueError('SYMLINK')
    s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_size != row['size'] or s.st_size>1024**3:
        raise ValueError('SIZE_OR_TYPE')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f: raw=f.read(row['size']+1)
    if len(raw)!=row['size'] or hashlib.sha256(raw).hexdigest()!=row['sha256']:
        raise ValueError('CHECKPOINT_SHA')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        members=[m for m in z.infolist() if m.filename.endswith('/data.pkl')]
        if len(members)!=1 or members[0].file_size>16*1024**2: raise ValueError('PICKLE_MEMBER')
        data=z.read(members[0])
    fields=literal_stage_fields(data)
    globals_used=sorted({arg for op,arg,_ in pickletools.genops(data) if op.name=='GLOBAL'})
    indirect_globals=any(op.name in ('STACK_GLOBAL','EXT1','EXT2','EXT4') for op,_,_ in pickletools.genops(data))
    rounds=row['completed_epochs_candidate']
    expected=dict(epoch=max(0,rounds-1),global_step=1736*rounds)
    return dict(path=str(path),sha256=row['sha256'],completed_epochs_candidate=rounds,
                observed=fields,expected=expected,globals_used=globals_used,indirect_globals=indirect_globals,
                status='STATIC_STAGE_LITERALS_MATCH' if fields==expected else 'STAGE_LITERAL_MISMATCH',
                limitation='Literal occurrences only; not proof of top-level mapping, loop state or tensor compatibility')

def remote_main(rows):
    def timeout(*args): raise SystemExit('STATIC_READ_TIMEOUT')
    signal.signal(signal.SIGALRM,timeout); signal.alarm(90)
    results=[]
    for row in rows:
        try: results.append(inspect(row))
        except Exception as exc:
            results.append(dict(path=row['path'],status='STATIC_READ_REFUSED',error=str(exc)))
    print(json.dumps(dict(status='E2_STATIC_STAGE_EVIDENCE_COLLECTED',records=results,
                          pickle_executed=False,model_loaded=False,jobs_submitted=0)))

"""E2 child lifecycle recorder: covers loading through archive completion."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import time

def utc(): return datetime.now(timezone.utc).isoformat()

def write(path, value):
    with path.open('x') as f:
        json.dump(value,f,sort_keys=True,indent=2,allow_nan=False)
        f.flush(); os.fsync(f.fileno())

def run_child(argv, directory, seconds):
    if not isinstance(argv,list) or not argv or any(type(x) is not str for x in argv):
        raise ValueError('ARGV')
    if type(seconds) not in (int,float) or not 0 < seconds <= 14400:
        raise ValueError('BUDGET')
    directory=Path(directory)
    directory.mkdir(mode=0o700,exist_ok=False)
    start=time.monotonic()
    record=dict(argv=argv,launch_requested_utc=utc(),pid=None,returncode=None,
                exit_observed_utc=None,status='LAUNCHING',automatic_retry=False,
                timestamp_semantics='parent-observed lifecycle bounds, not exact kernel creation/exit instants')
    child=None
    try:
        with (directory/'stdout.log').open('xb') as out,(directory/'stderr.log').open('xb') as err:
            child=subprocess.Popen(argv,stdout=out,stderr=err,start_new_session=True)
            record['pid']=child.pid
            write(directory/'LAUNCH.json',record)
            child.wait(timeout=max(.001,seconds-(time.monotonic()-start)))
            record['status']='CHILD_COMPLETE' if child.returncode==0 else 'CHILD_FAILED'
    except BaseException as exc:
        record.update(status='CHILD_TIMEOUT' if isinstance(exc,subprocess.TimeoutExpired) else 'LAUNCH_OR_SUPERVISION_FAILED',
                      error_type=type(exc).__name__,error=str(exc))
        raise
    finally:
        if child is not None:
            # Stop remaining descendants even if the leader has already exited.
            try: os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            child.wait()
            record.update(returncode=child.returncode,exit_observed_utc=utc())
        record['elapsed_seconds']=time.monotonic()-start
        write(directory/'PROCESS.json',record)
    if record['returncode']!=0: raise RuntimeError('CHILD_NONZERO')
    return record

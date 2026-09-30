"""Sequential A/B subprocess supervisor; no default commands or remote access.

Runs only caller-supplied commands. Requires independent verification callback;
zero exits alone never qualify science. Partial outputs are preserved on failure.
"""
import os
from pathlib import Path
import signal
import subprocess
import time
from e0_archive_harness import write_json
from e0_layout_reference import require

def stop_group(process):
    # New session's group id is its leader PID; kill also reaches worker children.
    try: os.killpg(process.pid,signal.SIGKILL)
    except ProcessLookupError: pass
    process.wait()

def run_pair(root,command_factory,verify,*,timeout_seconds=1500):
    require(os.name=='posix','POSIX_REQUIRED')
    require(type(timeout_seconds) in (int,float) and 0<timeout_seconds<=1500,'PAIR_DEADLINE')
    root=Path(root)
    root.mkdir(mode=0o700,exist_ok=False)
    started=time.monotonic()
    records=[]
    try:
        for label in ('A','B'):
            remaining=timeout_seconds-(time.monotonic()-started)
            if remaining<=0: raise TimeoutError('PAIR_DEADLINE')
            directory=root/label
            directory.mkdir(mode=0o700)
            argv=command_factory(label,directory)
            require(type(argv) is list and argv and all(type(x) is str for x in argv),'WORKER_ARGV')
            with (directory/'stdout.log').open('xb') as out,(directory/'stderr.log').open('xb') as err:
                process=subprocess.Popen(argv,stdout=out,stderr=err,start_new_session=True)
                record=dict(label=label,pid=process.pid,argv=argv)
                records.append(record)
                try:
                    write_json(directory/'LAUNCH.json',record)
                    remaining=timeout_seconds-(time.monotonic()-started)
                    if remaining<=0: raise TimeoutError('PAIR_DEADLINE')
                    rc=process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    raise TimeoutError('PAIR_DEADLINE') from None
                finally:
                    stop_group(process)
                record['returncode']=rc
                require(rc==0,'WORKER_NONZERO')
        require(records[0]['pid']!=records[1]['pid'],'DISTINCT_WORKER_PIDS')
        if time.monotonic()-started>=timeout_seconds: raise TimeoutError('PAIR_DEADLINE')
        # Local verifier is cooperative; unlike child execution it is not killed.
        verification=verify(root,records)
        require(type(verification) is dict and verification.get('verified') is True,'PAIR_NOT_VERIFIED')
        if time.monotonic()-started>=timeout_seconds: raise TimeoutError('PAIR_DEADLINE')
        result=dict(status='PAIR_EXECUTION_VERIFIED_NOT_SCIENCE_QUALIFIED',workers=records,
                    verification=verification,production_verified=False)
        write_json(root/'PAIR_EXECUTION.json',result)
        return result
    except BaseException as error:
        write_json(root/'FAILED.json',dict(status='PAIR_FAILED',error_type=type(error).__name__,
                   error=str(error),workers=records,retry_attempted=False,
                   elapsed_seconds=time.monotonic()-started))
        raise

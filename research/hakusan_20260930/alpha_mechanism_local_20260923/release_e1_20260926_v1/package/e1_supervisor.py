"""Sequential A/B and separate verifier, one shared hard deadline. No retries."""
import json
import os
from pathlib import Path
import subprocess
import time
from e0_archive_harness import write_json
from e0_layout_reference import require
from two_process_supervisor import stop_group

def run_e1(root,worker_command,verifier_command,*,seconds=9900):
    require(os.name=='posix' and 0<seconds<=9900,'E1_SUPERVISOR_BUDGET')
    root=Path(root); root.mkdir(mode=0o700,exist_ok=False)
    start=time.monotonic(); records=[]
    try:
        for label in ('A','B','VERIFY'):
            remaining=seconds-(time.monotonic()-start)
            if remaining<=0: raise TimeoutError('E1_TOTAL_DEADLINE')
            d=root/label; d.mkdir(mode=0o700)
            argv=worker_command(label,d) if label!='VERIFY' else verifier_command(root,d,records)
            require(type(argv) is list and argv and all(type(v) is str for v in argv),'E1_ARGV')
            with (d/'stdout.log').open('xb') as out,(d/'stderr.log').open('xb') as err:
                p=subprocess.Popen(argv,stdout=out,stderr=err,start_new_session=True)
                record=dict(label=label,pid=p.pid,argv=argv); records.append(record)
                try:
                    write_json(d/'LAUNCH.json',record)
                    remaining=seconds-(time.monotonic()-start)
                    if remaining<=0: raise TimeoutError('E1_TOTAL_DEADLINE')
                    rc=p.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    raise TimeoutError('E1_TOTAL_DEADLINE') from None
                finally: stop_group(p)
            record['returncode']=rc
            require(rc==0,'E1_CHILD_NONZERO')
        require(len({r['pid'] for r in records})==3,'E1_DISTINCT_PIDS')
        path=root/'VERIFY'/'VERIFIED.json'
        require(path.is_file() and not path.is_symlink() and path.stat().st_size<1048576,'E1_VERIFY_RECORD')
        report=json.loads(path.read_text())
        require(report.get('verified') is True,'E1_NOT_VERIFIED')
        if time.monotonic()-start>=seconds: raise TimeoutError('E1_TOTAL_DEADLINE')
        result=dict(status='E1_PROCESS_PIPELINE_FINISHED_NOT_SCIENCE_QUALIFIED',records=records,
                    verification=report,elapsed_seconds=time.monotonic()-start)
        write_json(root/'PROCESS_COMPLETE.json',result)
        return result
    except BaseException as e:
        write_json(root/'FAILED.json',dict(error_type=type(e).__name__,error=str(e),records=records,
                   elapsed_seconds=time.monotonic()-start,retry_attempted=False))
        raise

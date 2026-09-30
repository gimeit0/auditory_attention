"""Sequential stage/cold/independent-verifier supervision; no scheduler calls."""
from pathlib import Path
import json
import time
from e2_process import run_child,write

WORKERS=tuple((f'stage_{r}',r,'matrix') for r in (40,0,1,2,4,8,16,24))+(('cold_40',40,'cold_alpha1'),)
PILOT_WORKERS=tuple((label,r,'pilot_cold' if mode=='cold_alpha1' else 'pilot') for label,r,mode in WORKERS)

def coordinate(root,worker_command,verifier_command,*,seconds,pilot=False,final_check=None,worker_seconds=None):
    if type(seconds) not in (int,float) or not 0<seconds<=14400:
        raise ValueError('E2_TOTAL_BUDGET')
    if worker_seconds is not None and (type(worker_seconds) not in (int,float) or not 0<worker_seconds<=9000):
        raise ValueError('E2_CHILD_BUDGET')
    root=Path(root); root.mkdir(mode=0o700,exist_ok=False)
    start=time.monotonic(); records=[]
    def remaining():
        left=seconds-(time.monotonic()-start)
        if left<=0: raise TimeoutError('E2_TOTAL_DEADLINE')
        return left
    try:
        for label,rounds,mode in (PILOT_WORKERS if pilot else WORKERS):
            directory=root/label
            argv=worker_command(rounds,mode,directory/'output')
            left=remaining()
            lifecycle=run_child(argv,directory,min(left,worker_seconds) if worker_seconds is not None else left)
            records.append(dict(label=label,completed_epochs=rounds,mode=mode,lifecycle=lifecycle))
        write(root/'VERIFY_REQUEST.json',dict(workers=records))
        verifier=run_child(verifier_command(root),root/'VERIFY',remaining())
        remaining()
        report=json.loads((root/'VERIFY'/'VERIFIED.json').read_text())
        if report.get('status')!='E2_ARTIFACTS_VERIFIED': raise ValueError('E2_VERIFIER_NOT_PASS')
        if final_check is not None: final_check()  # No COMPLETE marker before package postcheck.
        result=dict(status='E2_PIPELINE_COMPLETE_NOT_SCIENTIFIC_REPORT',workers=records,
                    verifier=verifier,verification=report,elapsed_seconds=time.monotonic()-start)
        write(root/'COMPLETE.json',result)
        return result
    except BaseException as exc:
        write(root/'FAILED.json',dict(status='E2_PIPELINE_FAILED',workers_completed=records,
                    error_type=type(exc).__name__,error=str(exc),elapsed_seconds=time.monotonic()-start,
                    retry_attempted=False))
        raise

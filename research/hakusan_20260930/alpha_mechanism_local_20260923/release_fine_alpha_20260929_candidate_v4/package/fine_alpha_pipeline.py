"""One bounded sequential attempt; any failed child stops the whole scan."""
import json
from pathlib import Path
import time
from e2_process import run_child, write, utc
from fine_alpha_contract import BLOCKS, BUDGET, PREDICTIONS

def coordinate(root, command, digest, job, final_check, verifier_argv, *, runner=run_child, clock=time.monotonic):
    root = Path(root); root.mkdir(mode=0o700, exist_ok=False)
    start = clock(); workers = []
    write(root/'RUN.json', dict(status='FINE_ALPHA_RUNNING', release_sha256=digest, job_id=job,
                              started_utc=utc(), budget=BUDGET, blocks=list(BLOCKS), automatic_retry=False))
    try:
        for block in BLOCKS:
            remaining = BUDGET['coordinator_deadline_seconds'] - (clock()-start) - BUDGET['verify_reserve_seconds']
            if remaining <= 0: raise TimeoutError('FINE_COORDINATOR_DEADLINE')
            process = runner(command(block), root/block, min(BUDGET['worker_deadline_seconds'], remaining))
            workers.append(dict(block=block, lifecycle=process)); final_check()
        write(root/'VERIFY_REQUEST.json', dict(blocks=list(BLOCKS), release_sha256=digest, job_id=job, workers=workers))
        remaining = BUDGET['coordinator_deadline_seconds'] - (clock()-start)
        if remaining <= 0: raise TimeoutError('FINE_COORDINATOR_DEADLINE')
        runner(verifier_argv, root/'VERIFY', min(300, remaining))
        final_check()
        verified = json.loads((root/'VERIFY/VERIFIED.json').read_text())
        if (verified.get('status') != 'FINE_ALPHA_ARTIFACTS_VERIFIED' or verified.get('predictions') != PREDICTIONS or
            verified.get('release_sha256') != digest or verified.get('job_id') != job): raise ValueError('FINE_FINAL_VERIFIER')
        write(root/'COMPLETE.json', dict(verified, finished_utc=utc(), elapsed_seconds=clock()-start))
        return verified
    except BaseException as exc:
        write(root/'FAILED.json', dict(status='FINE_ALPHA_FAILED', error_type=type(exc).__name__, error=str(exc),
            finished_utc=utc(), completed_blocks=[w['block'] for w in workers], automatic_retry=False))
        raise

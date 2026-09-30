"""Execute one unchanged staged synthetic fixture; outer record names the real host mode."""
import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    if len(sys.argv) != 7:
        raise RuntimeError('fixed staged child arguments required')
    package, stage, mode, folder, request_sha, run_id = sys.argv[1:]
    if stage not in ('A2', 'B2', 'mmap') or mode not in ('NATIVE_CPU', 'LOCAL_HARNESS'):
        raise RuntimeError('invalid stage/mode')
    if not sys.flags.isolated or not sys.dont_write_bytecode or os.environ.get('CUDA_VISIBLE_DEVICES') != '':
        raise RuntimeError('isolated CPU execution required')
    sys.path.insert(0, str(Path(package) / 'docs/superpowers/prototypes/staged_scratch_20260915'))
    import lifecycle
    lifecycle.sources()
    import torch
    if mode == 'NATIVE_CPU' and (sys.version.split()[0] != '3.11.5' or str(torch.__version__) != '2.1.1+cu118'
                                 or len(os.sched_getaffinity(0)) != 1):
        raise RuntimeError('native environment differs')
    request = lifecycle.read_bound(Path(folder) / 'request.json', request_sha)
    if request['stage'] != stage or request['session_id'] != run_id:
        raise RuntimeError('fixture request binding differs')
    # The unchanged helper's LOCAL_STAGE_PASS denotes its synthetic test
    # identity, not the execution host. This wrapper records NATIVE_CPU
    # separately; no original monolithic or production PASS is issued.
    lifecycle.child(Path(folder), request_sha)
    raw = lifecycle.read(Path(folder) / 'result.json')
    value = lifecycle.decode(raw)
    if torch.cuda.is_initialized():
        raise RuntimeError('CUDA unexpectedly initialized')
    result = {'status': 'STAGED_COMPONENT_PASS', 'stage': stage, 'group': stage, 'mode': mode,
              'run_id': run_id, 'pid': os.getpid(), 'tests': value.get('tests', 0),
              'failures': value.get('failures', 0), 'errors': value.get('errors', 0), 'skips': value.get('skips', 0),
              'python': sys.version.split()[0], 'torch': str(torch.__version__),
              'cpu_affinity': sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
              'result_sha256': hashlib.sha256(raw).hexdigest(), 'request_sha256': request_sha,
              'cuda_initialized': False, 'production_model_loaded': False, 'jobs_submitted': 0,
              'ready_for_gpu': False, 'original_native_monolithic_passed': False}
    print('STAGED_CPU_CHILD=' + json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()

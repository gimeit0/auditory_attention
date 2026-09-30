"""Native CPU toy supervisor: temporary package, one <=50s child, no retry."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time

started = time.monotonic()
os.umask(0o077)
os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
home_before = os.environ.get('HOME')
assert set(SPEC['files']) == {'backend_evidence.py', 'compiled_child.py', 'process_runner.py'}
result = dict(status='NATIVE_TOY_INDUCTOR_FAILED', request_id=SPEC['request_id'], jobs_submitted=0, production_ready=False)
with tempfile.TemporaryDirectory(prefix='g2-native-toy-', dir='/tmp') as temporary:
    root = Path(temporary)
    package = root / 'package'
    package.mkdir(mode=0o700)
    for name, item in SPEC['files'].items():
        raw = base64.b64decode(item['source'], validate=True)
        assert len(raw) <= 65536 and hashlib.sha256(raw).hexdigest() == item['sha256']
        with (package / name).open('xb') as out:
            out.write(raw)
    loader = importlib.util.spec_from_file_location('g2_original_process_supervisor', package / 'process_runner.py')
    runner = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(runner)
    env = {**os.environ, 'CUDA_VISIBLE_DEVICES': '', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
           'PYTHONDONTWRITEBYTECODE': '1', 'TORCHINDUCTOR_COMPILE_THREADS': '1',
           'TORCHINDUCTOR_CACHE_DIR': str(root / 'inductor'), 'TRITON_CACHE_DIR': str(root / 'triton'),
           'XDG_CACHE_HOME': str(root / 'cache'), 'TMPDIR': str(root / 'tmp')}
    for name in ('inductor', 'triton', 'cache', 'tmp'):
        (root / name).mkdir(mode=0o700)
    # -I omits script directory; insert this exact fresh package, not PYTHONPATH.
    bootstrap = 'import sys,runpy;sys.path.insert(0,sys.argv[1]);runpy.run_path(sys.argv[2],run_name="__main__")'
    command = ['/home/s2510040/miniconda3/envs/attn/bin/python', '-I', '-B', '-c', bootstrap,
               str(package), str(package / 'compiled_child.py')]
    process = runner.run_process(command, env, root / 'child.log', seconds=50, max_log_bytes=2 * 1024**2)
    log = (root / 'child.log').read_bytes()
    result.update(process=process, log=base64.b64encode(log).decode(),
                  sources={name: item['sha256'] for name, item in SPEC['files'].items()})
    rows = [json.loads(line.split('=', 1)[1]) for line in log.decode().splitlines() if line.startswith('G2_COMPILED_CHILD=')]
    if process['returncode'] == 0 and process['error'] is None and len(rows) == 1:
        result.update(status='NATIVE_TOY_INDUCTOR_COLLECTED', child=rows[0])
result.update(temporary_directory_removed=not Path(temporary).exists(), home_unchanged=os.environ.get('HOME') == home_before,
              elapsed_seconds=time.monotonic() - started)
print('G2_COMPILED_RESULT=' + json.dumps(result, sort_keys=True), flush=True)

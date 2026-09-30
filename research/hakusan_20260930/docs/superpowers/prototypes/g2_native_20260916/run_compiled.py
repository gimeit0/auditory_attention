"""One bounded native CPU Inductor toy; no production run or scheduler."""
import base64
import datetime
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run as api


def validate(record, spec):
    api.require(record['request_id'] == spec['request_id'] and record['status'] == 'NATIVE_TOY_INDUCTOR_COLLECTED', 'child failed')
    process = record['process']
    raw = base64.b64decode(record['log'], validate=True)
    api.require(process['returncode'] == 0 and process['error'] is None and process['elapsed_seconds'] < 50.5
                and process['log']['sha256'] == api.sha(raw) and process['log']['size'] == len(raw), 'process/log invalid')
    rows = [json.loads(line.split('=', 1)[1]) for line in raw.decode().splitlines() if line.startswith('G2_COMPILED_CHILD=')]
    api.require(rows == [record['child']], 'child/log mismatch')
    r = record['child']
    api.require(r['status'] == 'NATIVE_TOY_INDUCTOR_EXECUTION_PASS' and r['torch'] == '2.1.1+cu118'
                and r['python'] == '3.11.5' and len(r['cpu_affinity']) == 1
                and r['compiler_calls'] == r['compiler_returns'] > 0 and r['artifacts']
                and r['target_generated_artifacts_executed'] is True, 'native compile evidence missing')
    api.require(r['batch_sizes'] == [16, 1] and len(r['eager_max_abs']) == 2
                and all(type(x) in (int, float) and 0 <= x <= 1e-6 for x in r['eager_max_abs']), 'toy endpoint differs')
    for item in r['artifacts']:
        data = base64.b64decode(item['source'], validate=True)
        api.require(api.sha(data) == item['sha256'] and item['calls'] == item['returns'] > 0, 'artifact execution/source differs')
    for field in ('cuda_initialized', 'production_model_loaded', 'production_ready', 'real_g2_profiles_validated', 'interference_validated'):
        api.require(r[field] is False, 'overclaimed result scope: ' + field)
    api.require(r['profiler_removed'] is True and r['jobs_submitted'] == record['jobs_submitted'] == 0
                and record['production_ready'] is False and record['temporary_directory_removed'] is True
                and record['home_unchanged'] is True and record['elapsed_seconds'] < 60
                and record['sources'] == {n: v['sha256'] for n, v in spec['files'].items()}, 'scope/cleanup differs')


def main():
    api.require(len(sys.argv) == 2 and sys.argv[1] in ('test', 'native'), 'usage: run_compiled.py test|native')
    os.umask(0o077)
    mode = sys.argv[1]
    api.require(mode != 'native',
                'login-node Inductor check already attempted and timed out; no repeat released. '
                'Review the fixed evidence and obtain a separate bounded CPU batch authorization.')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    folder = Path(tempfile.mkdtemp(prefix='g2-backend-' + mode + '-' + stamp, dir=api.ROOT / 'docs/superpowers/evidence'))
    print('EVIDENCE=' + str(folder), flush=True)
    sources = {name: api.read(HERE / name) for name in ('backend_evidence.py', 'compiled_child.py', 'compiled_payload.py', 'test_backend.py', 'run_compiled.py')}
    for name, raw in sources.items():
        api.write(folder / name, raw)
    with (folder / 'tests.log').open('xb') as out:
        test = subprocess.run([sys.executable, '-I', '-B', str(HERE / 'test_backend.py')], stdout=out, stderr=subprocess.STDOUT, timeout=15)
    api.require(test.returncode == 0 and b'Ran 10 tests' in api.read(folder / 'tests.log') and b'\nOK\n' in api.read(folder / 'tests.log'), 'local event matcher failed')
    receipt = dict(mode=mode, status='LOCAL_TEST_PASS', tests=10, jobs_submitted=0, production_ready=False,
                   sources={name: api.sha(raw) for name, raw in sources.items()})
    if mode == 'native':
        runner = api.read(HERE.parent / 'targeted_gpu_job_20260915_v5/process_runner.py')
        api.require(api.sha(runner) == '189495e7af4fe5537df560909de456b8ca95acdf0c9f9d6603435e6230b5411a', 'reviewed supervisor differs')
        files = {n: sources[n] for n in ('backend_evidence.py', 'compiled_child.py')}
        files['process_runner.py'] = runner
        spec = dict(request_id=uuid.uuid4().hex, files={n: dict(source=base64.b64encode(raw).decode(), sha256=api.sha(raw)) for n, raw in files.items()})
        payload = ('SPEC=' + repr(spec) + '\n').encode() + sources['compiled_payload.py']
        api.write(folder / 'request.py', payload)
        socket = api.ROOT / '.hakusan-control/master.sock'
        api.require(socket.is_socket(), 'existing authenticated shared master required')
        command = ['/usr/bin/ssh', '-S', str(socket), '-o', 'ControlMaster=no', '-o', 'BatchMode=yes',
                   '-o', 'ProxyCommand=/usr/bin/false', '-o', 'ConnectionAttempts=1', '-o', 'ConnectTimeout=12',
                   '-o', 'StrictHostKeyChecking=yes', '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
                   's2510040@hakusan1', '/home/s2510040/miniconda3/envs/attn/bin/python -I -B -']
        receipt['status'] = 'FAILED'
        with (folder / 'stdout.log').open('xb') as out, (folder / 'stderr.log').open('xb') as err:
            try:
                transport = subprocess.run(command, input=payload, stdout=out, stderr=err, timeout=75)
                api.require(transport.returncode == 0, 'transport failed; no retry')
                rows = [json.loads(line.split('=', 1)[1]) for line in api.read(folder / 'stdout.log').decode().splitlines() if line.startswith('G2_COMPILED_RESULT=')]
                api.require(len(rows) == 1, 'missing or duplicate supervisor record')
                api.write(folder / 'result.json', api.wire(rows[0]))
                api.write(folder / 'child.log', base64.b64decode(rows[0]['log'], validate=True))
                validate(rows[0], spec)
                receipt['status'] = 'NATIVE_CPU_TOY_VERIFIED'
            except Exception as exc:
                receipt['error'] = dict(type=type(exc).__name__, message=str(exc))
    api.require(all(api.read(HERE / n) == raw for n, raw in sources.items()), 'local sources changed')
    receipt['artifacts'] = {p.name: api.sha(api.read(p)) for p in sorted(folder.iterdir()) if p.is_file()}
    api.write(folder / 'receipt.json', api.wire(receipt))
    print(json.dumps(receipt, sort_keys=True), flush=True)
    api.require(receipt['status'] != 'FAILED', 'native check failed; preserve evidence, no retry')


if __name__ == '__main__':
    main()

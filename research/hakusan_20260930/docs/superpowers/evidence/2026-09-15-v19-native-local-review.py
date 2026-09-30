"""Read-only reconstruction of the fixed local CPU harness evidence, no SSH."""
import ast
import base64
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROBE = ROOT / 'docs/superpowers/prototypes/targeted_pair_native_20260915'
EVIDENCE = ROOT / 'docs/superpowers/evidence/v19-local_harness-20260915T042507Z-joll00yp'
RECEIPT_SHA = '97eda2c2b8c24580dac42de05e7352d84705949ed49967af52c546efc1639742'
RELEASE_SHA = '4d2f742eea588eaaea8015538f48c8122d1258ed795c276eb86272d4840128da'
DRIVER_SHA = 'e2f677c3067ce222e2ef4e72b0b77b300116f85110b2f6f8fda99fbbc070e6ec'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink evidence')
    require(path.is_file() and path.stat().st_size <= 16 * 1024**2, 'bounded regular file required')
    return path.read_bytes()


def main():
    raw = read(EVIDENCE / 'receipt.json')
    require(sha(raw) == RECEIPT_SHA, 'local receipt changed')
    receipt = json.loads(raw)
    release = read(PROBE / 'PROBE_RELEASE.json')
    require(sha(release) == RELEASE_SHA, 'probe release changed')
    for name, expected in json.loads(release)['files'].items():
        require(Path(name).name == name and sha(read(PROBE / name)) == expected, 'probe source changed')
    driver_path = PROBE / 'driver.py'
    require(sha(read(driver_path)) == DRIVER_SHA, 'driver changed')
    loader = importlib.util.spec_from_file_location('read_only_native_review_driver', driver_path)
    driver = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(driver)
    files, release_sha = driver.local_sources()
    require(release_sha == RELEASE_SHA, 'source release differs')
    driver.check_local_receipt(EVIDENCE / 'receipt.json', release_sha)

    request = read(EVIDENCE / 'request.py')
    log = read(EVIDENCE / 'output.log')
    require(sha(request) == receipt['payload_sha256'], 'payload changed')
    require(sha(log) == receipt['output_sha256'], 'output changed')
    first, payload = request.split(b'\n', 1)
    require(first.startswith(b'SPEC='), 'one literal request specification required')
    spec = ast.literal_eval(first[5:].decode('utf-8'))  # data only; no request execution
    require(payload == read(PROBE / 'payload.py'), 'payload is not reviewed source')
    require({k: spec[k] for k in receipt['request']} == receipt['request'], 'request identity differs')
    require(spec['mode'] == 'LOCAL_HARNESS', 'local execution must not claim native validation')
    require(set(spec['files']) == set(files), 'transferred inventory differs')
    for name, encoded in spec['files'].items():
        require(base64.b64decode(encoded, validate=True) == files[name], 'transferred source differs')
    require(base64.b64decode(spec['child_source'], validate=True) == read(PROBE / 'child_checks.py'),
            'child source differs')
    lines = [s.removeprefix('V19_NATIVE_RESULT=') for s in log.decode().splitlines()
             if s.startswith('V19_NATIVE_RESULT=')]
    require(len(lines) == 1 and json.loads(lines[0]) == receipt['remote'], 'result/log binding differs')
    require(driver.check_response(receipt['remote'], spec) == 80, 'full test coverage missing')
    print(json.dumps({'status': 'LOCAL_NATIVE_HARNESS_EVIDENCE_PASS', 'mode': spec['mode'],
        'tests': 80, 'source_files_in_payload': len(files), 'child_logs_verified': 5,
        'receipt_sha256': RECEIPT_SHA, 'native_remote_verified': False,
        'jobs_submitted': 0, 'read_only': True}, sort_keys=True))


if __name__ == '__main__':
    main()

"""Independent read-only review of one local v19 pair-runtime test receipt."""
import hashlib
import json
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / 'docs/superpowers/prototypes/targeted_gpu_job_20260915_v5'
MANIFEST_SHA = 'c0b421d01d394f1fd3354eb74eb730e2d348cf4a37d0fb96f76a019c71c5aa20'
RECEIPT_SHA = 'd85d45f80af2cac44a486d28416b9590f5ad7c70e1c78d9e74022f3fb0e9c437'
RECIPE_SHA = 'a1eb16b8a36313bfc3b8559339e55b2b824e32b831075db6f9e82328ac223750'
EXPECTED = {'control': 27, 'input_binding': 25, 'startup': 12, 'result_identity': 11,
            'captures': 13, 'array_budget': 3, 'runtime_timing': 16, 'scratch_lifetime': 2,
            'archive_regression': 38, 'freeze_regression': 15}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def read(path, sha=None):
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink evidence/source')
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_size <= 8 * 1024**2, 'bounded regular file required')
    raw = path.read_bytes()
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'file changed during review')
    require(sha is None or hashlib.sha256(raw).hexdigest() == sha, 'SHA differs: ' + str(path))
    return raw


def main():
    require(len(sys.argv) == 2, 'supply the exact local evidence directory')
    folder = Path(sys.argv[1]).resolve()
    require(folder.parent == ROOT / 'docs/superpowers/evidence', 'local evidence directory required')
    receipt = json.loads(read(folder / 'receipt.json', RECEIPT_SHA))
    manifest = json.loads(read(PACKAGE / 'SOURCE_MANIFEST.json', MANIFEST_SHA))
    require(receipt['manifest_sha256'] == MANIFEST_SHA and receipt['source_files'] == len(manifest['files']) == 162,
            'source closure differs')
    require(receipt['status'] == 'LOCAL_V19_PAIR_RUNTIME_PASS' and receipt['sources_unchanged'] is True,
            'local test result not passed')
    for key in ('ready_for_gpu', 'remote_executed', 'submission_authorized', 'automatic_retry'):
        require(receipt[key] is False, 'scope overstated')
    require(receipt['jobs_submitted'] == 0 and receipt['candidate_input_freeze_sha256'] is None,
            'local-only scope differs')
    for name, sha in manifest['files'].items():
        relative = Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts, 'source path escape')
        read(ROOT / relative, sha)
    artifacts = receipt['artifacts']
    require(set(p.name for p in folder.iterdir()) == {*artifacts, 'receipt.json'}, 'evidence inventory differs')
    require(set(artifacts) == {name + ext for name in EXPECTED for ext in ('.log', '.json')}, 'missing group artifact')
    for name, record in artifacts.items():
        raw = read(folder / name, record['sha256'])
        require(len(raw) == record['size'], 'artifact size differs')
    seen, pids, count = set(), set(), 0
    for group in receipt['groups']:
        name, record, process = group['group'], group['record'], group['process']
        require(name in EXPECTED and name not in seen, 'duplicate/unknown test group')
        seen.add(name)
        require(group['verified'] is True and process['returncode'] == 0 and process['error'] is None,
                'child did not exit normally')
        require(record == json.loads(read(folder / (name + '.json')))
                and process['log'] == {'name': name + '.log', **artifacts[name + '.log']},
                'child record/log is not bound')
        require(record['pid'] == process['pid'] and record['pid'] not in pids, 'not distinct test processes')
        pids.add(record['pid'])
        require(record['passed'] is True and record['tests'] == EXPECTED[name]
                and record['errors'] == record['failures'] == record['skips'] == 0, 'tests incomplete')
        require(record['cuda_initialized'] is False and record['production_model_loaded'] is False
                and record['jobs_submitted'] == 0, 'test scope differs')
        require(record['python'] == '3.11.15' and record['torch'] == '2.12.1', 'local environment differs')
        count += record['tests']
    require(seen == set(EXPECTED) and count == receipt['tests'] == 162, 'group coverage differs')
    recipe = json.loads(read(PACKAGE / 'TRANSFORM_RECIPE.json', RECIPE_SHA))
    for name, spec in recipe['files'].items():
        text = read(ROOT / spec['source'], spec['source_sha256']).decode()
        for op in spec['changes']:
            require(text.count(op['old']) == op['count'], 'derivation count differs')
            text = text.replace(op['old'], op['new'])
        require((text.rstrip() + '\n').encode() == read(PACKAGE / name), 'unreviewed source delta')
    print(json.dumps({'status': 'OFFLINE_V19_PAIR_RUNTIME_REVIEW_PASS', 'tests': count,
        'cold_processes': len(pids), 'source_files': len(manifest['files']), 'artifacts': len(artifacts),
        'exact_derivations': len(recipe['files']), 'receipt_sha256': RECEIPT_SHA,
        'manifest_sha256': MANIFEST_SHA, 'jobs_submitted': 0, 'ready_for_gpu': False}, sort_keys=True))


if __name__ == '__main__':
    main()

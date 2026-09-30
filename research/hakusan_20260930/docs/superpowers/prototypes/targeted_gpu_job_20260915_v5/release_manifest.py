"""Read-only release calculation/check; never publish, upload, freeze or submit."""
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
INTEGRATION = ROOT / 'docs/superpowers/prototypes/guard_scan_integration_20260915'
INTEGRATION_SHA = '93508d886b6608dcdb31a4d84e7a033716cfb53fa80e62cb019743f18aeb28bd'


def digest(path):
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise RuntimeError('ordinary source path required: ' + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected():
    if digest(INTEGRATION / 'SOURCE_MANIFEST.json') != INTEGRATION_SHA:
        raise RuntimeError('reviewed integration manifest changed')
    source = json.loads((INTEGRATION / 'SOURCE_MANIFEST.json').read_bytes())
    files = {**source['parent_files'], **source['files']}
    recipe = json.loads((HERE / 'TRANSFORM_RECIPE.json').read_bytes())
    for spec in recipe['files'].values():
        if spec['source'] in files and files[spec['source']] != spec['source_sha256']:
            raise RuntimeError('derivation source is not reviewed parent')
        files[spec['source']] = spec['source_sha256']
    for path in (INTEGRATION / 'SOURCE_MANIFEST.json', INTEGRATION / 'freeze_relation.py',
                 INTEGRATION / 'test_freeze_relation.py'):
        files[str(path.relative_to(ROOT))] = digest(path)
    for path in sorted(HERE.iterdir()):
        if path.name == 'SOURCE_MANIFEST.json' or path.name == '__pycache__':
            continue
        if path.suffix not in ('.py', '.json', '.md', '.sbatch'):
            raise RuntimeError('unexpected release file: ' + str(path))
        files[str(path.relative_to(ROOT))] = digest(path)
    for name, sha in files.items():
        if digest(ROOT / name) != sha:
            raise RuntimeError('reviewed source changed: ' + name)
    return {'schema_version': 1, 'files': dict(sorted(files.items())),
            'integration_source_manifest_sha256': INTEGRATION_SHA,
            'candidate_input_freeze_sha256': None, 'submission_authorized': False,
            'ready_for_gpu': False, 'scope': 'local v19 B2 pair runtime integration; no deployment or GPU execution'}


def wire(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def check():
    value = expected()
    raw = (HERE / 'SOURCE_MANIFEST.json').read_bytes()
    if raw != wire(value):
        raise RuntimeError('candidate source manifest differs')
    return hashlib.sha256(raw).hexdigest(), value


if __name__ == '__main__':
    if sys.argv[1:] == ['--print']:
        sys.stdout.buffer.write(wire(expected()))
    elif sys.argv[1:] == ['--check']:
        sha, value = check()
        print(json.dumps({'status': 'SOURCE_CHECK_PASS', 'manifest_sha256': sha,
                          'files': len(value['files']), 'jobs_submitted': 0}))
    else:
        raise SystemExit('use --check or --print; both read-only')

"""Read-only exact source derivation check, including every retained statement."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def verify():
    recipe = json.loads((HERE / 'TRANSFORM_RECIPE.json').read_bytes())
    for name, spec in recipe['files'].items():
        path = ROOT / spec['source']
        raw = path.read_bytes()
        if path.is_symlink() or hashlib.sha256(raw).hexdigest() != spec['source_sha256']:
            raise RuntimeError('preserved source differs: ' + spec['source'])
        text = raw.decode('utf8')
        for change in spec['changes']:
            if text.count(change['old']) != change['count']:
                raise RuntimeError('source transformation count differs: ' + name)
            text = text.replace(change['old'], change['new'])
        if (HERE / name).read_bytes() != (text.rstrip() + '\n').encode('utf8'):
            raise RuntimeError('candidate derivation differs: ' + name)
    return {'exact_transformations_verified': True, 'derived_files': sorted(recipe['files']),
            'jobs_submitted': 0}


if __name__ == '__main__':
    print(json.dumps(verify(), sort_keys=True))

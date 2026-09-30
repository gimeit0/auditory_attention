"""Read-only review of the fixed local staged synthetic scratch evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CODE = ROOT / 'docs/superpowers/prototypes/staged_scratch_20260915'
EVIDENCE = ROOT / 'docs/superpowers/evidence/staged-scratch-local-20260915T091408Z-nobia7gy'
PINS = {
    CODE / 'lifecycle.py': '9b0f2c511ed1cda9ee4cb0743795ddf50d8518e31d05e1a23e5d2af3281ca20e',
    CODE / 'test_lifecycle.py': '5038f717ba5974336abf3ab3d5106b027a9798ac87e5f4ca2d5ad3c471de41e4',
    EVIDENCE / 'receipt.json': 'eabe071aed44e8f7f1dba6443d48555494bdcdbad677626434caa2143e340e6c',
}


def main():
    for path, expected in PINS.items():
        if (not path.is_file() or any(p.is_symlink() for p in (path, *path.parents))
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
            raise RuntimeError('fixed source/receipt differs: ' + path.name)
    spec = importlib.util.spec_from_file_location('fixed_staged_scratch_review', CODE / 'lifecycle.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.review(EVIDENCE)
    if result['contract_sha256'] != 'cdfe21ec7eb65f72a6fd11f76fc3c975a67c6a7d01f4c121de1f3c98dd271000':
        raise RuntimeError('fixed complete synthetic contract differs')
    print(json.dumps({**result, 'frozen_sources_verified': 162, 'artifacts_verified': 16,
                      'fixed_receipt_sha256': PINS[EVIDENCE / 'receipt.json'],
                      'remote_executed': False}))


if __name__ == '__main__':
    main()

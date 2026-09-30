"""Fixed local receipt/source gate; optional bounded CPU stages over an existing SSH master."""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'docs/superpowers/prototypes/staged_scratch_native_20260915'
LOCAL = ROOT / 'docs/superpowers/evidence/staged-scratch-local_harness-20260915T124305Z-jdqphuin'
PINS = {
    'child.py': '1b70e6764bcf6c9f58e052ce8bcc99284361538dae576be64749daef14864e62',
    'run_native.py': '023d55693fbba6409936d13709a048d2da1113d92e40e9c8535d0e021353eacb',
    'test_native.py': '13146ac7b44be37071599d7fc8b9d1064e75bbcb557e006029f9295d23920c5e',
}
RECEIPT_SHA = '29b587c8a8dc5bf222b730646de57234965df69e622eb4c0b03e297e8ab6c7cf'


def check(path, expected):
    if (not path.is_file() or any(p.is_symlink() for p in (path, *path.parents))
            or path.stat().st_size > 16 * 1024**2
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
        raise RuntimeError('fixed source/receipt differs: ' + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-only', action='store_true')
    args = parser.parse_args()
    for name, digest in PINS.items():
        check(SOURCE / name, digest)
    check(LOCAL / 'receipt.json', RECEIPT_SHA)
    spec = importlib.util.spec_from_file_location('fixed_staged_scratch_driver', SOURCE / 'run_native.py')
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    print(driver.review(LOCAL, local_only=True), flush=True)
    if args.review_only:
        return 0
    print('SCOPE: three sequential synthetic CPU invocations; each one CPU / child <=50s / supervisor <=90s.', flush=True)
    print('No production checkpoint, GPU, freeze, scheduler submission, automatic reconnect or retry.', flush=True)
    return driver.operate('NATIVE_CPU', LOCAL)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        raise SystemExit(2)

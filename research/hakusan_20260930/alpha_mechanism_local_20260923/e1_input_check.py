"""Stdlib-only portable input gate; no model import, upload or submission."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--expected-reader-sha256',required=True)
    parser.add_argument('--expected-contract-sha256',required=True)
    args=parser.parse_args()
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        raise ValueError('ISOLATED_NO_BYTECODE_REQUIRED')
    root=args.directory
    if root.is_symlink() or not root.is_dir(): raise ValueError('INPUT_DIRECTORY')
    reader=root/'e1_inputs.py'
    if reader.is_symlink() or not reader.is_file(): raise ValueError('READER_FILE')
    raw=reader.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.expected_reader_sha256:
        raise ValueError('READER_SHA')
    # Execute exactly the source bytes just verified, not a cached module.
    spec=importlib.util.spec_from_file_location('e1_checked_inputs',reader)
    module=importlib.util.module_from_spec(spec)
    exec(compile(raw,str(reader),'exec'),module.__dict__)
    c=module.build_contract(root)
    payload=(json.dumps(c,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    digest=hashlib.sha256(payload).hexdigest()
    if digest!=args.expected_contract_sha256: raise ValueError('CONTRACT_SHA')
    print(json.dumps(dict(status='E1_PORTABLE_INPUT_CHECK_PASS',contract_sha256=digest,
                         predictions=c['predictions'],checkpoint_loaded=False,jobs_submitted=0,
                         production_ready=False)))

if __name__=='__main__': main()

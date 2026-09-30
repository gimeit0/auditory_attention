"""Pinned E1 input reader; explicit portable directory never falls back locally."""
import csv
import hashlib
import io
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FREEZE_SHA = '6c4df571e897a2c13aa6c693a86783c83ac8620b1f24b7f932ddbe6d93ab62fe'
CANDIDATE_SHA = 'be2011fdd6489777521a5f54af8d8f4fc39a73b14c6669b636e674f844bbb69b'
BANK_SHA = 'd03404f2bca5aeb8a5d096b84f6ef758b6b07d0ee5efbd44ded59135bced0091'
FORMAL_SHA = '2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff'

def checked(path, sha):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError('E1_INPUT_FILE: '+str(path))
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError('E1_INPUT_SHA: '+str(path))
    return raw

def frozen_inputs(directory=None):
    root = HERE if directory is None else Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('E1_INPUT_DIRECTORY')
    return json.loads(checked(root/'E1_DATA_FREEZE_20260926_v1.json', FREEZE_SHA))

def build_contract(directory=None):
    root = HERE if directory is None else Path(directory)
    frozen = frozen_inputs(directory)
    candidate = json.loads(checked(root/'E1_CANDIDATE_2000_20260926.json', CANDIDATE_SHA))
    bank = root/'frozen_bank.tsv'
    # Development workspace compatibility only. Explicit package roots must be self-contained.
    if directory is None and not bank.exists():
        bank = HERE.parent/'docs/superpowers/evidence/p05-confirmation-set-20260919/frozen_bank.tsv'
    rows = list(csv.DictReader(io.StringIO(checked(bank, BANK_SHA).decode()), delimiter='\t'))
    ids = set(candidate['trial_ids'])
    labels = {r['trial_id']: int(r['target_label']) for r in rows if int(r['trial_id']) in ids}
    if len(labels) != 2000 or len(ids) != 2000:
        raise ValueError('E1_LABEL_INVENTORY')
    return dict(version='E1_EXECUTION_V2_20260927', data_freeze_sha256=FREEZE_SHA,
                checkpoint_sha256=FORMAL_SHA, labels=labels,
                main_batches=frozen['batches'], control_batches=frozen['control_batches'],
                clean_batches=frozen['clean_batches'], predictions=38400, production_authorized=False)

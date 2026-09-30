"""Default dry-run. Existing SSH only; bounded restricted CPU inspection."""
import hashlib
import json
from run_e2_checkpoint_inventory import module, HERE

EVIDENCE = HERE.parent/'docs/superpowers/evidence/r1-development-inventory-20260922/remote-readonly-fb3qsucc'
if __name__ == '__main__':
    raw = (EVIDENCE/'stdout.json').read_bytes()
    receipt = json.loads((EVIDENCE/'RECEIPT.json').read_text())
    if hashlib.sha256(raw).hexdigest() != receipt['stdout_sha256']:
        raise ValueError('INVENTORY_RECEIPT_SHA')
    inventory = json.loads(raw)
    if inventory['status'] != 'E2_BYTES_HASHED_STAGE_UNVERIFIED': raise ValueError('INVENTORY_STATUS')
    rows = inventory['records']
    if len(rows) != 8: raise ValueError('STAGE_COUNT')
    loader = (HERE/'e2_archive_loader.py').read_text()
    payload = ('import sys, types\n'
               'm=types.ModuleType("e2_archive_loader")\n'
               'sys.modules[m.__name__]=m\n'
               'exec(compile('+repr(loader)+', "e2_archive_loader.py", "exec"),m.__dict__)\n').encode()
    payload += (HERE/'e2_stage_inspection.py').read_bytes()
    payload += ('\nremote_main('+repr(rows)+')\n').encode()
    raise SystemExit(module.main(payload=payload,
        accepted=('E2_STAGE_INSPECTION_PASS', 'E2_STAGE_INSPECTION_INCOMPLETE'),
        scope='8 SHA-bound checkpoints, explicit-global-registry CPU reads, 1 thread, 90s, no models/GPU/jobs; not weights_only'))

import hashlib
import json
from run_e2_checkpoint_inventory import module, HERE
from run_e2_stage_inspection import EVIDENCE

if __name__=='__main__':
    raw=(EVIDENCE/'stdout.json').read_bytes()
    receipt=json.loads((EVIDENCE/'RECEIPT.json').read_text())
    if hashlib.sha256(raw).hexdigest()!=receipt['stdout_sha256']: raise ValueError('SHA')
    records=json.loads(raw)['records']
    if len(records)!=8: raise ValueError('COUNT')
    payload=(HERE/'e2_static_stage_fields.py').read_bytes()
    payload+=('\nremote_main('+repr(records)+')\n').encode()
    raise SystemExit(module.main(payload=payload,accepted=('E2_STATIC_STAGE_EVIDENCE_COLLECTED',),
        scope='Static pickle opcode inspection of 8 SHA-bound checkpoints; no unpickling, model or GPU'))

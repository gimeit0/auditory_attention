"""Read-only fixed Job718727 evidence review and rejection checks; no network."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch

WORKSPACE = Path(__file__).resolve().parents[3]
SOURCE = WORKSPACE / 'docs/superpowers/prototypes/staged_scratch_batch_20260915'
FOLDER = WORKSPACE / 'docs/superpowers/evidence/staged-cpu-batch-20260915/collect-20260915T151610Z-8o907xvv'
PINS = {
    SOURCE / 'common.py': 'd50999d9a1067761153c79ad797418d3b53dceb73356a0df38595cbae87760fd',
    SOURCE / 'runtime.py': 'a442eb1ff53f8aee6d6a5ca682d67eaa6f7f9b33fb4c07e909aa9446ec1c3d7a',
    FOLDER / 'RECEIPT.json': 'caa58df840637d092de626243d7c55f2ac51ffbc1cea781a0bfae97d25db27a6',
    FOLDER / 'VERIFIED.json': '847bfdf736156f9d529ef987379a07bdd3adecb11e52316c30c0d420bd2ab0c6',
}
for path, digest in PINS.items():
    if any(p.is_symlink() for p in (path, *path.parents)) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise RuntimeError('fixed evidence/source differs: ' + str(path))
sys.path.insert(0, str(SOURCE))
import common as c
import runtime

root = FOLDER / 'recovered'
digest = '9fedb04058706453561c874eb9fba90ac37283c46e81e65f54a8148ff35b78db'
nonce = '88dd88309d704362b417ae8ac8359aad'
job = '718727'
receipt = json.loads(c.read(FOLDER / 'RECEIPT.json', 24 * 1024**2))
output = c.read(FOLDER / 'output.log', 24 * 1024**2)
c.require(c.sha(output) == receipt['output_sha256'] and c.sha(c.read(FOLDER / 'request.py')) == receipt['request_sha256'], 'transport hashes differ')
rows = [json.loads(line[len('CPU_BATCH_RESPONSE='):]) for line in output.decode().splitlines() if line.startswith('CPU_BATCH_RESPONSE=')]
c.require(rows == [receipt['response']] and receipt['transport']['returncode'] == 0 and receipt['transport']['error'] is None, 'transport outcome differs')
for name, item in receipt['response']['result']['files'].items():
    c.require(c.sha(c.read(root / c.member(name))) == item['sha256'], 'downloaded bytes differ')
accounting = json.loads(c.read(root / 'ACCOUNTING.json'))
c.require(accounting == receipt['response']['result']['accounting'] and accounting['returncode'] == 0, 'accounting changed')
row, = accounting['stdout'].strip().splitlines()
columns = row.split('|')
c.require(columns[:4] == [job, 'COMPLETED', '0:0', '00:01:36'], 'scheduler completion differs')
c.tres(columns[4]); c.tres(columns[5])
held = json.loads(c.read(root / 'HELD.json'))
c.require(held['returncode'] == 0, 'held inspection failed')
c.job_check(held['stdout'], job, nonce, c.REMOTE, held=True)
checked = runtime.review(root, digest, nonce, 'NATIVE_BATCH', job)
c.require(json.loads(c.read(FOLDER / 'VERIFIED.json')) == checked, 'independent result differs')

# In-memory mutations only; never modify the recorded artifacts or source.
terminal_path = root / 'attempts/slurm-718727/TERMINAL.json'
terminal = json.loads(c.read(terminal_path))
original_read = c.read
rejected = []
for key, value in [('status', 'FAILED'), ('error', {'type': 'TimeoutError'}), ('source_postcheck', False),
                   ('temporary_directory_removed', False), ('home_unchanged', False), ('ready_for_gpu', True),
                   ('production_model_loaded', True), ('original_50_second_gate_passed', True),
                   ('job_id', '718726'), ('elapsed_seconds', 571)]:
    altered = copy.deepcopy(terminal)
    altered[key] = value
    def fake_read(path, limit=8 * 1024**2):
        return c.wire(altered) if path == terminal_path else original_read(path, limit)
    with patch.object(c, 'read', side_effect=fake_read):
        try:
            runtime.review(root, digest, nonce, 'NATIVE_BATCH', job)
        except RuntimeError:
            rejected.append(key)
        else:
            raise RuntimeError('invalid evidence accepted: ' + key)
print(json.dumps(dict(status='FIXED_CPU_BATCH_EVIDENCE_VERIFIED', job_id=job, rejection_checks=len(rejected),
                     check_names=rejected, result=checked, network_calls=0, jobs_submitted=0, files_modified=0), sort_keys=True))

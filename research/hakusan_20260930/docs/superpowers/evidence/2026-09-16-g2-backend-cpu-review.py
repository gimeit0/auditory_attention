"""Read-only recheck of fixed Job720730; no SSH, execution, or evidence rewrite."""
import base64
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
E = HERE / 'g2-backend-batch-20260916'
C = E / 'collect-20260916T033234Z-ipdssq7n'
R = C / 'recovered'
DIGEST = '9c20cfa1fdc96744fda9fb30bc83f1fe3eb4c95edf95e0c418290c3f4bbe6f88'
NONCE = 'dfbbe425b5c04cfd905192d846cf76d7'

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def pinned(path, digest):
    require(not any(p.is_symlink() for p in (path,*path.parents)) and path.is_file(), 'unsafe evidence path')
    raw = path.read_bytes()
    require(sha(raw) == digest,'fixed evidence changed: ' + str(path))
    return json.loads(raw)

def main():
    receipt = pinned(C/'RECEIPT.json','750ec59843332a63f69927ac005575518c39a54e2e35d50fc9db360ce3792d2d')
    accepted = pinned(C/'VERIFIED.json','05b6776ebe551647acbad86cf9030ae0c5423a23e4e9caefb604f585a99edade')
    manifest = pinned(R/'RELEASE.json',DIGEST)
    submission = pinned(E/'submit-20260916T032853Z-un005ydp/RECEIPT.json',
        'fdd9e6274bdbaf342cad3932d860a82c1551fa4785f18148ea8243a4c2dd79e2')
    require(submission['response']['result']['job_id'] == '720730' and submission['response']['ok']
            and submission['transport']['returncode'] == 0 and submission['transport']['error'] is None
            and submission['spec']['release_sha256'] == DIGEST and submission['spec']['nonce'] == NONCE,
            'submission outcome differs')
    for name,digest in manifest['files'].items():
        path = Path(name)
        require(not path.is_absolute() and '..' not in path.parts,'package path escape')
        for file in (R/'package'/path,):
            require(not any(p.is_symlink() for p in (file,*file.parents)) and sha(file.read_bytes()) == digest,
                    'frozen package changed')
    prefix = R/'package/docs/superpowers/prototypes/g2_backend_batch_20260916'
    sys.path.insert(0,str(prefix))
    import common as c
    import runtime
    require(receipt['transport']['returncode'] == 0 and receipt['transport']['error'] is None
            and receipt['spec']['action'] == 'collect' and receipt['spec']['release_sha256'] == DIGEST
            and receipt['response']['ok'],'collection unsuccessful')
    output = c.read(C/'output.log',limit=24*1024**2)
    require(c.sha(output) == receipt['output_sha256']
            and c.sha(c.read(C/'request.py')) == receipt['request_sha256'],'transport changed')
    lines = [json.loads(x.split('=',1)[1]) for x in output.decode().splitlines() if x.startswith('CPU_BATCH_RESPONSE=')]
    require(lines == [receipt['response']],'response differs')
    for name,item in receipt['response']['result']['files'].items():
        raw = c.read(R/c.member(name))
        require(c.sha(raw) == item['sha256'] and raw == base64.b64decode(item['data'],validate=True),'artifact changed')
    intent = json.loads(c.read(E/'LOCAL_SUBMIT_INTENT.json'))
    require(intent['nonce'] == NONCE and intent['release_sha256'] == DIGEST and intent['confirm'] == c.CONFIRM,
            'one-time intent differs')
    held = json.loads(c.read(R/'HELD.json'))
    require(held['returncode'] == 0,'held inspection failed')
    c.job_check(held['stdout'],'720730',NONCE,c.REMOTE,held=True)
    accounting = json.loads(c.read(R/'ACCOUNTING.json'))
    require(accounting == receipt['response']['result']['accounting'] and accounting['returncode'] == 0,
            'accounting changed')
    rows = [x.split('|') for x in accounting['stdout'].strip().splitlines()]
    require(len(rows) == 1 and rows[0][:4] == ['720730','COMPLETED','0:0','00:02:26']
            and rows[0][6] == 'lcpcc-065','terminal job identity differs')
    c.tres(rows[0][4]); c.tres(rows[0][5])
    checked = runtime.review(R,DIGEST,NONCE,'720730')
    require(checked == accepted and checked['status'] == 'NATIVE_CPU_PAIR_VERIFIED','independent review differs')
    print(json.dumps(dict(status='FIXED_CPU_RESULT_RECHECK_PASS',job_id='720730',verified=checked,
                          remote_calls=0,jobs_submitted=0,evidence_written=False),sort_keys=True))

if __name__ == '__main__':
    main()

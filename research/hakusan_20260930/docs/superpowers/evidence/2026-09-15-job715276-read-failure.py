"""Read-only bounded evidence collection for existing FAILED job 715276.

Reuses the exact reviewed prior read-only collector body, replacing only fixed
job/root/nonce/source-count literals. No model imports or remote file writes.
"""
import ast
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import uuid

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
sys.path.insert(0, str(WORKSPACE / 'docs/superpowers/prototypes/targeted_gpu_control_20260914_v4'))
import control


def main():
    old = HERE / 'gpu-control-20260914-v3/terminal-evidence-20260914T074214Z-eg9mkxdw/request.py'
    raw = old.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == 'bd2b0285abd1dce0ce661b139e1ca90f220f49e96211840b99e892012ad16d9d'
    tree = ast.parse(raw)
    nodes = [n for n in tree.body if isinstance(n, ast.Try)]
    assert len(nodes) == 1
    body = ast.unparse(nodes[0])
    body = body.replace('713897', '715276')
    body = body.replace('gpu_pair_2026-09-14_v3', 'gpu_pair_2026-09-14_v4')
    body = body.replace('899e59b8732346d782e54b091d6f05e6', '2afc1b76ca1f4a06b9cd921e071a0d1d')
    body = body.replace("'fixed_sources_verified': 55", "'fixed_sources_verified': 58")
    assert '713897' not in body and 'gpu_pair_2026-09-14_v3' not in body
    release_raw, release, files = control.package()
    release_sha = hashlib.sha256(release_raw).hexdigest()
    assert release_sha == 'abc075315541791c201ea637825a5f653253d4a0325126a63c73e560a64c6864'
    spec = {'action': 'terminal-evidence', 'request_id': uuid.uuid4().hex, 'release_sha256': release_sha}
    source = files[control.ops.OPS]
    code = 'import base64,hashlib,json,types\nSPEC=' + repr(spec) + '\n'
    code += 'source=base64.b64decode(' + repr(base64.b64encode(source).decode()) + ',validate=True)\n'
    code += 'assert hashlib.sha256(source).hexdigest()==' + repr(hashlib.sha256(source).hexdigest()) + '\n'
    code += "OPS=types.ModuleType('pinned_ops')\nexec(compile(source,'<pinned-ops>','exec'),OPS.__dict__)\n"
    code += body + '\n'
    code += "print('GPU_CONTROL='+json.dumps({**SPEC,**response}),flush=True)\n"
    code += "raise SystemExit(0 if response['ok'] else 2)\n"
    compile(code, '<read-only-evidence>', 'exec')
    control.master_check(control.SOCKET)
    control.payload = lambda *_: code.encode('ascii')
    with contextlib.redirect_stdout(io.StringIO()):
        receipt = control.operate(spec, files)
    control.package()
    folders = [p for p in control.EVIDENCE.glob('terminal-evidence-*')
               if (p / 'receipt.json').is_file()
               and json.loads((p / 'receipt.json').read_bytes())['request_id'] == spec['request_id']]
    assert len(folders) == 1
    print('EVIDENCE_DIRECTORY=' + str(folders[0]), flush=True)
    if receipt['returncode']:
        print(json.dumps(receipt, sort_keys=True))
        return receipt['returncode']
    value = receipt['remote']['result']
    # Keep raw bytes in the hash-bound response, without rewriting originals.
    print(json.dumps({k: v for k, v in value.items() if k != 'files'}, sort_keys=True))
    print('FILES=' + json.dumps({k: {f: r[f] for f in ('sha256', 'size')}
                                 for k, r in value['files'].items()}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

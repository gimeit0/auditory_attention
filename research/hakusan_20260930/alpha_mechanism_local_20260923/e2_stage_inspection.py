"""CPU-only, hash-bound restricted checkpoint inspection; no model construction."""
import gc
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import stat
import torch
from e2_archive_loader import load_bound_archive

def stage_summary(checkpoint, rounds, *, final_after_fit=False):
    if not isinstance(checkpoint, dict): raise ValueError('CHECKPOINT_MAPPING')
    epoch, step = checkpoint.get('epoch'), checkpoint.get('global_step')
    if type(epoch) is not int or type(step) is not int: raise ValueError('STAGE_FIELDS')
    if final_after_fit and rounds != 40: raise ValueError('FINAL_STAGE_SCOPE')
    expected_epoch = 40 if final_after_fit else max(0, rounds - 1)
    if step != rounds * 1736 or epoch != expected_epoch:
        raise ValueError('EPOCH_STEP_MISMATCH: '+repr((epoch, step, rounds)))
    state = checkpoint.get('state_dict')
    if not isinstance(state, dict) or not state: raise ValueError('STATE_DICT')
    signature = []
    for key, tensor in sorted(state.items()):
        if not isinstance(key, str) or not isinstance(tensor, torch.Tensor):
            raise ValueError('STATE_ENTRY')
        if tensor.device.type != 'cpu' or not torch.isfinite(tensor).all():
            raise ValueError('STATE_NONFINITE_OR_DEVICE')
        signature.append([key, list(tensor.shape), str(tensor.dtype)])
    encoded = json.dumps(signature, separators=(',', ':')).encode()
    return dict(epoch=epoch, global_step=step, completed_epochs=rounds,
                state_signature_sha256=hashlib.sha256(encoded).hexdigest(),
                state_entries=len(signature), state_numel=sum(t.numel() for t in state.values()),
                loops_present=isinstance(checkpoint.get('loops'), dict),
                optimizer_count=len(checkpoint.get('optimizer_states', [])),
                model_loaded=False, forward_executed=False,
                status='STAGE_FIELDS_AND_FINITE_STATE_PASS')

def inspect_record(row):
    path = Path(row['path'])
    for part in reversed((path, *path.parents)):
        if stat.S_ISLNK(part.lstat().st_mode): raise ValueError('SYMLINK')
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_size != row['size'] or st.st_size > 1024**3:
        raise ValueError('SIZE_OR_TYPE')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as f:
        raw = f.read(row['size'] + 1)
    if len(raw) != row['size'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
        raise ValueError('CHECKPOINT_SHA')
    checkpoint = load_bound_archive(raw, row['sha256'])
    is_final = path.name == 'formal-final.ckpt'
    if is_final and row['sha256'] != '2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff':
        raise ValueError('FINAL_SHA')
    result = stage_summary(checkpoint, row['completed_epochs_candidate'], final_after_fit=is_final)
    result.update(path=str(path), checkpoint_sha256=row['sha256'])
    return result

def run(rows):
    if torch.cuda.is_initialized(): raise ValueError('CUDA_INITIALIZED')
    torch.set_num_threads(1)
    results = []
    for row in rows:
        try:
            results.append(inspect_record(row))
        except Exception as exc:
            results.append(dict(path=row['path'], status='INSPECTION_REFUSED',
                                error_type=type(exc).__name__, error=str(exc)[:1500]))
            break
        gc.collect()
    success = len(results) == 8 and all(r['status']=='STAGE_FIELDS_AND_FINITE_STATE_PASS' for r in results)
    same = success and len({r['state_signature_sha256'] for r in results}) == 1
    return dict(status='E2_STAGE_INSPECTION_PASS' if same else 'E2_STAGE_INSPECTION_INCOMPLETE',
                records=results, signatures_equal=bool(same), model_loaded=False,
                cuda_initialized=torch.cuda.is_initialized(), jobs_submitted=0,
                limitation='Epoch/step and tensor signatures verified; no model load or inference')

def remote_main(rows):
    import pwd
    if pwd.getpwuid(os.getuid()).pw_name != 's2510040': raise ValueError('ACCOUNT')
    def timeout(*args): raise SystemExit('CPU_INSPECTION_TIMEOUT')
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(90)
    print(json.dumps(run(rows), sort_keys=True))

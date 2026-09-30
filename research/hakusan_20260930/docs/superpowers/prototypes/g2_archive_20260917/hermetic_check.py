"""Actual synthetic bridge/mmap -> disk -> separate-process content verification.

Reuses the pinned local lifetime fixture unchanged except inserting ONE callback
before its cleanup. No actual ProductionCell.run or production load is claimed.
"""
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import pass_store as store

FIXTURE = HERE.parent / 'g2_lifetime_20260917/hermetic_spill_check.py'


def write_once(path, value):
    with path.open('xb') as out:
        out.write(store.canonical(value))
        out.flush()
        os.fsync(out.fileno())


def write_archive(profile, folder):
    raw = FIXTURE.read_bytes()
    # Source SHA is also snapshotted by the bounded validation supervisor.
    require_sha = '41ecf32a39f959d73ffa8f24f6a2bf4c86634c8d5673a7a35b9862ee62a811f5'
    store.require(store.sha(raw) == require_sha, 'fixed actual mmap fixture differs')
    original = ast.parse(raw)
    tree = copy.deepcopy(original)
    inserted = []
    class Insert(ast.NodeTransformer):
        def visit_Assign(self,node):
            if ast.unparse(node).startswith('cleanup = object.__new__(cell.ProductionCell)'):
                call = ast.parse('_save(result, prepared, scratch, gate, expected, diag, bridge)').body[0]
                inserted.append(call)
                return [call,node]
            return node
    tree = Insert().visit(tree)
    store.require(len(inserted) == 1, 'one archive insertion required')
    code = compile(ast.fix_missing_locations(tree), str(FIXTURE), 'exec', dont_inherit=True)
    class Undo(ast.NodeTransformer):
        def visit_Expr(self,node):
            return None if node is inserted[0] else node
    tree = Undo().visit(tree)
    store.require(ast.dump(tree) == ast.dump(original), 'fixture altered beyond callback')

    def save(result, prepared, scratch, gate, trials, diag, bridge):
        metadata = dict(job_id='7770017',pid=os.getpid(),profile=profile,input_freeze_sha256='a'*64,
                        input_relation={'scope':'HERMETIC_FIXTURE_NOT_PRODUCTION_INPUTS'},
                        preparation=prepared['attestation'],scratch=dict(scratch.record))
        binding = store.bind(metadata,trials,store.sha((HERE/'pass_store.py').read_bytes()),'hermetic-test')
        callback = store.Consumer(folder/'arrays',bridge,diag,binding=binding,trials=trials)
        before = diag._get_trace().snapshot_rng_state()
        receipt = callback(result,metadata)
        store.require(diag._get_trace().snapshot_rng_state() == before, 'archive changed RNG')
        with gate._scope():
            gate._live('hermetic_after_real_archive')
        scratch.verify_spills()
        try: callback(result,metadata)
        except ValueError as error: store.require('single use' in str(error), 'wrong retry failure')
        else: raise AssertionError('archive callback repeated')
        write_once(folder/'RECEIPT.json',receipt)
        write_once(folder/'EXPECTED.json',dict(binding=binding,trials=trials,
                                             receipt_sha256=store.sha(store.canonical(receipt))))
        print('G2_ARCHIVE_WRITER_REPORT=' + json.dumps(dict(profile=profile,pid=os.getpid(),
              manifest_sha256=receipt['archive_manifest_sha256'], receipt_sha256=store.sha(store.canonical(receipt)),
              arrays=40, original_gate_live_after_storage=True, rng_unchanged=True,
              scope='LOCAL_SYNTHETIC_MMAP_NO_PRODUCTION_LIFETIME',production_model_loaded=False,
              ready_for_gpu=False,jobs_submitted=0),sort_keys=True),flush=True)

    namespace = dict(__name__='g2_archive_fixed_fixture',__file__=str(FIXTURE),_save=save)
    exec(code,namespace)
    namespace['main'](profile,'pass')


def verify_archive(folder):
    lifetime = HERE.parent / 'g2_lifetime_20260917'
    sys.path.insert(0,str(lifetime))
    store.require(store.sha((lifetime/'production_cell.py').read_bytes()) ==
        '602d90cc26ee5900ed801e45a15b4f30ebbbe3bd9edf5f9ccb65a93f8982be24', 'lifetime source changed')
    import production_cell as cell
    spec = importlib.util.spec_from_file_location('g2_archive_bridge', lifetime.parent/'g2_worker_20260916/cell_bridge.py')
    bridge = importlib.util.module_from_spec(spec)
    raw = cell.input_api.read_stable(Path(spec.origin),2*1024**2)
    store.require(store.sha(raw) == cell.input_api.BRIDGE_SHA, 'bridge source changed')
    exec(compile(raw,spec.origin,'exec'),vars(bridge))
    expected = json.loads((folder/'EXPECTED.json').read_bytes())
    profile = expected['binding']['profile']
    fixed = store.ROOT/'docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu'
    diag = bridge.load_candidate(fixed/profile/'diagnose_batch_invariance.py',profile)
    receipt = json.loads((folder/'RECEIPT.json').read_bytes())
    report = store.verify(folder/'arrays',receipt,receipt_sha=expected['receipt_sha256'],
                         expected_binding=expected['binding'],trials=expected['trials'],bridge=bridge,diag=diag)
    import torch
    store.require(not torch.cuda.is_initialized() and not diag._ISSUED_FORMAL40_ATTESTATIONS,
                  'offline verifier loaded model authority or CUDA')
    print('G2_ARCHIVE_VERIFY_REPORT='+json.dumps(dict(report,verifier_pid=os.getpid(),
           cuda_initialized=False,production_model_loaded=False),sort_keys=True),flush=True)
    return report


if __name__ == '__main__':
    os.umask(0o077)
    store.require(sys.flags.isolated and sys.dont_write_bytecode, 'isolated test required')
    if len(sys.argv)==4 and sys.argv[1]=='write' and sys.argv[2] in ('D','E'):
        write_archive(sys.argv[2],Path(sys.argv[3]).resolve())
    elif len(sys.argv)==3 and sys.argv[1]=='verify':
        verify_archive(Path(sys.argv[2]).resolve())
    else: raise SystemExit('usage: hermetic_check.py write D|E FOLDER | verify FOLDER')

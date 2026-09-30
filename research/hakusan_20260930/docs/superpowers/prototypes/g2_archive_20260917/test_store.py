"""Content corruption tests against copied actual synthetic artifacts, not a model test."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import pass_store as store
import numpy as np

SOURCE = Path(sys.argv.pop(1)).resolve()
BRIDGE_PATH = HERE.parent/'g2_worker_20260916/cell_bridge.py'
raw = store.pinned(BRIDGE_PATH,'9b7e033ac8796e142782ea4dcc59ec527bd97538f51ccf8d4bea0caa1cd7d59d')
spec = importlib.util.spec_from_file_location('g2_archive_test_bridge',BRIDGE_PATH)
bridge = importlib.util.module_from_spec(spec)
exec(compile(raw,str(BRIDGE_PATH),'exec'),vars(bridge))
FIXED = store.ROOT/'docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu'
diag = bridge.load_candidate(FIXED/'D/diagnose_batch_invariance.py','D')
codec = store.build_codec()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='g2-archive-negative-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.arrays = self.root/'arrays'
        shutil.copytree(SOURCE/'arrays',self.arrays)
        self.receipt = json.loads((SOURCE/'RECEIPT.json').read_bytes())
        self.expected = json.loads((SOURCE/'EXPECTED.json').read_bytes())
        self.manifest = json.loads((self.arrays/'manifest.json').read_bytes())

    def verify(self):
        return store.verify(self.arrays,self.receipt,receipt_sha=self.expected['receipt_sha256'],
            expected_binding=self.expected['binding'],trials=self.expected['trials'],bridge=bridge,diag=diag)

    def resign(self, manifest=False, commitment=False):
        # Explicit corruption-test re-signing. Production code never re-signs passes.
        if commitment:
            for i,p in enumerate(self.manifest['passes']):
                original = p['original_pass_evidence']
                digest = store.sha(store.canonical(original['payload']))
                original['commitment']['binding_sha256'] = digest
                self.receipt['pass_commitments'][i] = digest
                self.receipt['cell_summary']['pass_commitments'][i] = digest
        if manifest or commitment:
            raw = store.canonical(self.manifest)
            (self.arrays/'manifest.json').write_bytes(raw)
            self.receipt['archive_manifest_size'] = len(raw)
            self.receipt['archive_manifest_sha256'] = store.sha(raw)
        self.expected['receipt_sha256'] = store.sha(store.canonical(self.receipt))

    def reject(self):
        with self.assertRaises((ValueError,RuntimeError,OSError,KeyError,TypeError)):
            self.verify()

    def test_actual_archive(self):
        result=self.verify()
        self.assertEqual(result['arrays_rehashed'],40)
        self.assertEqual(result['per_trial_hashes_checked'],1280)
        self.assertFalse(result['execution_authority_verified'])

    def test_corrupted_bytes(self):
        path=self.arrays/'000.bin'
        raw=path.read_bytes()
        path.write_bytes(bytes([raw[0]^1])+raw[1:])
        self.reject()

    def test_truncated_bytes(self):
        path=self.arrays/'000.bin'
        path.write_bytes(path.read_bytes()[:-1])
        self.reject()

    def test_missing_array(self):
        (self.arrays/'000.bin').unlink()
        self.reject()

    def test_extra_file(self):
        (self.arrays/'extra.bin').write_bytes(b'x')
        self.reject()

    def test_symlink_array(self):
        path=self.arrays/'000.bin'
        path.rename(self.root/'moved.bin')
        path.symlink_to(self.root/'moved.bin')
        self.reject()

    def test_hardlink_array(self):
        os.link(self.arrays/'000.bin',self.root/'alias.bin')
        self.reject()

    def test_symlink_directory(self):
        self.arrays.rename(self.root/'moved')
        self.arrays.symlink_to(self.root/'moved',target_is_directory=True)
        self.reject()

    def test_permissions(self):
        (self.arrays/'000.bin').chmod(0o644)
        self.reject()

    def test_receipt_digest(self):
        self.expected['receipt_sha256']='0'*64
        self.reject()

    def test_profile_binding(self):
        self.expected['binding']['profile']='E'
        self.reject()

    def test_job_binding(self):
        self.expected['binding']['job_id']='7770018'
        self.reject()

    def test_freeze_binding(self):
        self.expected['binding']['input_freeze_sha256']='f'*64
        self.reject()

    def test_full_trial_identity(self):
        self.expected['trials'][0]['identity']['target_speaker']='wrong-speaker'
        self.reject()

    def test_forged_numeric_pass(self):
        self.receipt['cell_summary']['numeric']['comparisons']['nll']['max_abs']=0.2
        self.resign()
        self.reject()

    def test_scope_overclaim(self):
        self.receipt['cell_summary']['production_ready']=True
        self.resign()
        self.reject()

    def test_commitment_tamper(self):
        self.manifest['passes'][0]['original_pass_evidence']['payload']['trial_ids'][0]=99999
        self.resign(manifest=True)
        self.reject()

    def test_rebound_row_hash_still_requires_real_bytes(self):
        p=self.manifest['passes'][0]['original_pass_evidence']['payload']
        p['boundaries']['scene_features']['per_trial'][0]['sha256']='0'*64
        self.resign(commitment=True)
        self.reject()

    def test_duplicate_file_name(self):
        self.manifest['passes'][0]['boundaries']['raw_cue']['file']='000.bin'
        self.resign(manifest=True)
        self.reject()

    def test_wrong_dtype(self):
        self.manifest['passes'][0]['boundaries']['raw_scene']['dtype']='<f8'
        self.resign(manifest=True)
        self.reject()

    def test_manifest_noncanonical(self):
        path=self.arrays/'manifest.json'
        raw=path.read_bytes()+b' '
        path.write_bytes(raw)
        self.receipt['archive_manifest_size']=len(raw)
        self.receipt['archive_manifest_sha256']=store.sha(raw)
        self.resign()
        self.reject()

    def test_nonfinite_before_writing(self):
        with self.assertRaises(ValueError):
            list(codec.array_chunks(np.array([np.nan],dtype=np.float32)))

    def test_oversize_rejected_before_copy(self):
        huge=np.broadcast_to(np.zeros(1,dtype=np.float32),(32,1600001))
        with mock.patch.object(np,'nditer',side_effect=AssertionError('must check before copy')):
            with self.assertRaises(ValueError):
                list(codec.array_chunks(huge))

    def test_reviewed_real_feature_capacity(self):
        codec.metadata(dict(dtype='<f4',shape=[32,2,200,4000],nbytes=204800000,sha256='0'*64))
        self.assertEqual(codec.MAX_ARRAY,204800000)
        self.assertEqual(codec.MAX_TOTAL,2*1024**3)
        self.assertEqual(codec.CHUNK,1024**2)

    def test_writer_failure_poisoned(self):
        binding=dict(self.expected['binding'],pid=os.getpid())
        writer=codec.PassArchive(self.root/'partial',binding)
        self.addCleanup(writer.close)
        with self.assertRaises(ValueError): writer.capture_pass('pass2',1,[],{}, {},{})
        self.assertTrue(writer.failed)
        with self.assertRaises(ValueError): writer.finish()
        self.assertFalse((self.root/'partial/manifest.json').exists())

    def test_consumer_failure_is_single_use(self):
        callback=store.Consumer(self.root/'partial',bridge,diag,binding=self.expected['binding'],
                                trials=self.expected['trials'])
        with self.assertRaises(KeyError): callback({}, {})
        with self.assertRaisesRegex(ValueError,'single use'): callback({}, {})

    def test_numeric_diff_is_valid_not_execution_error(self):
        original=self.manifest['passes'][0]['original_pass_evidence']
        one=diag.decode_pass_evidence(original)['outputs']
        two={k:v.copy() for k,v in one.items()}
        two['nll'][0]+=np.float32(.002)
        summary=store.numeric_summary([one,two])
        self.assertEqual(summary['status'],'NUMERIC_DIFF')
        self.assertEqual(summary['comparisons']['nll']['above_atol'],1)
        self.assertEqual(summary['atol'],1e-6)


if __name__=='__main__':
    os.umask(0o077)
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(StoreTests))
    print('G2_ARCHIVE_TEST_REPORT='+json.dumps(dict(tests=result.testsRun,failures=len(result.failures),
        errors=len(result.errors),skipped=len(result.skipped),scope='LOCAL_SYNTHETIC_ARCHIVE_CONTENT_ONLY',
        production_model_loaded=False,jobs_submitted=0),sort_keys=True),flush=True)
    raise SystemExit(0 if result.wasSuccessful() else 2)

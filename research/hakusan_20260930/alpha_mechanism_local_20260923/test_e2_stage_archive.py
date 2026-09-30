import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from e1_inputs import build_contract
from e2_catalog import stage_record
from e2_matrix import expected_records
from e2_stage_archive import archive_stage,verify_stage_archive

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'stage'; self.c=build_contract()
        records={k:dict(trial_ids=ids,logits=np.zeros((len(ids),800),np.float32),
                       nll=np.full(len(ids),np.log(800),np.float32)) for k,ids in expected_records(self.c,1).items()}
        archive_stage(self.root,self.c,1,records,dict(checkpoint_sha256=stage_record(1)['sha256'],completed_epochs=1),{'synthetic':True})
    def test_roundtrip(self):
        result,records=verify_stage_archive(self.root,self.c,1)
        self.assertEqual(result['predictions'],3600)
        self.assertFalse(result['production_verified'])
    def test_tamper(self):
        p=self.root/'record-000.npz'; p.write_bytes(p.read_bytes()+b'x')
        with self.assertRaises(ValueError): verify_stage_archive(self.root,self.c,1)
    def test_wrong_stage(self):
        with self.assertRaises(ValueError): verify_stage_archive(self.root,self.c,2)
    def test_extra_file(self):
        (self.root/'extra').write_text('x')
        with self.assertRaises(ValueError): verify_stage_archive(self.root,self.c,1)
    def test_changed_load_identity(self):
        p=self.root/'STAGE.json'; value=json.loads(p.read_text()); value['load_report']['completed_epochs']=2
        p.write_text(json.dumps(value))
        with self.assertRaises(ValueError): verify_stage_archive(self.root,self.c,1)

if __name__=='__main__': unittest.main()

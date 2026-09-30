import tempfile
import unittest
from pathlib import Path
from check_e1_v3_handoff import check_documents,identity

class HandoffTests(unittest.TestCase):
    def fixture(self,root):
        p=root/'contract.md';p.write_text('unsigned candidate')
        return {'decision_record':{'documents':{k:dict(file=p.name,**identity(p)) for k in
            ('statistics_contract_v2','statistics_contract_v3_correction')}}}
    def test_bound_documents(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);r=self.fixture(root)
            self.assertEqual(len(check_documents(r,root)),2)
    def test_changed_document_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);r=self.fixture(root);(root/'contract.md').write_text('changed')
            with self.assertRaisesRegex(ValueError,'DOCUMENT_CHANGED'):check_documents(r,root)
    def test_missing_correction_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);r=self.fixture(root)
            del r['decision_record']['documents']['statistics_contract_v3_correction']
            with self.assertRaisesRegex(ValueError,'BOTH_CONTRACTS'):check_documents(r,root)
    def test_escaping_path_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);r=self.fixture(root)
            r['decision_record']['documents']['statistics_contract_v2']['file']='../contract.md'
            with self.assertRaisesRegex(ValueError,'DOCUMENT_PATH'):check_documents(r,root)

if __name__=='__main__':unittest.main()

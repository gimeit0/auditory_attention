import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import e2_checkpoint_inventory as m

class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_hash(self):
        p = self.root / 'weights'; p.write_bytes(b'example')
        self.assertEqual(m.hash_regular(p)['sha256'], hashlib.sha256(b'example').hexdigest())

    def test_size_rejected(self):
        p = self.root / 'weights'; p.write_bytes(b'ab')
        with self.assertRaises(ValueError): m.hash_regular(p, limit=1)

    def test_symlink_rejected(self):
        p = self.root / 'weights'; p.write_bytes(b'ab')
        link = self.root / 'link'; link.symlink_to(p)
        with self.assertRaises(ValueError): m.hash_regular(link)

    def test_directory_rejected(self):
        with self.assertRaises(ValueError): m.hash_regular(self.root)

    def test_missing_is_not_success(self):
        result = m.inventory(self.root)
        self.assertEqual(result['status'], 'E2_CHECKPOINT_GAP_RECORDED')
        self.assertEqual(len(result['records']), 8)

    def test_formal_identity_mismatch(self):
        for _, name in m.CANDIDATES: (self.root / name).write_bytes(b'x')
        result = m.inventory(self.root)
        self.assertEqual(result['records'][-1]['error'], 'FORMAL40_IDENTITY_MISMATCH')

    def test_success_still_not_stage_verified(self):
        for _, name in m.CANDIDATES: (self.root / name).write_bytes(b'x')
        with patch.object(m, 'FORMAL_SHA', hashlib.sha256(b'x').hexdigest()):
            result = m.inventory(self.root)
        self.assertEqual(result['status'], 'E2_BYTES_HASHED_STAGE_UNVERIFIED')
        self.assertTrue(all(not r['stage_semantics_verified'] for r in result['records']))

if __name__ == '__main__': unittest.main()

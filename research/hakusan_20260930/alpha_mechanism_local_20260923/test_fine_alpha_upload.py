"""Local temporary-directory transfer tests; no SSH or scheduler commands."""
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from fine_alpha_upload_transport import validate_transport, publish

def sha(data): return hashlib.sha256(data).hexdigest()

def fixture(extra=None, duplicate=False, symlink=False):
    data = {'fine_alpha_entry.py': b'# test entry', 'reference/test.npz': b'test bytes'}
    release = json.dumps(dict(scope='FINE_ALPHA_001_20260928_V1', files={
        n: dict(size=len(v), sha256=sha(v)) for n, v in data.items()})).encode()
    data['RELEASE.json'] = release
    if extra: data.update(extra)
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:') as archive:
        for name, raw in data.items():
            member = tarfile.TarInfo(name); member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
        if duplicate:
            member = tarfile.TarInfo('fine_alpha_entry.py'); archive.addfile(member, io.BytesIO())
        if symlink:
            member = tarfile.TarInfo('link'); member.type = tarfile.SYMTYPE; member.linkname = '/tmp/x'
            archive.addfile(member)
    return stream.getvalue(), sha(release), sha(data['fine_alpha_entry.py'])

class UploadTests(unittest.TestCase):
    def test_nested_reference_files(self):
        blob, release, entry = fixture()
        self.assertEqual(set(validate_transport(blob, release, entry)), {'fine_alpha_entry.py', 'reference/test.npz', 'RELEASE.json'})
    def test_publish_verify_and_no_overwrite(self):
        blob, release, entry = fixture(); previous_umask = os.umask(0o077)
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()/'private-base'/'new-root'
                result = publish(blob, root, release, entry)
                self.assertEqual(result['files'], 3)
                self.assertEqual((root/'package/reference/test.npz').read_bytes(), b'test bytes')
                self.assertFalse((root/'.upload-staging').exists())
                self.assertEqual((root/'package/reference/test.npz').stat().st_mode & 0o777, 0o600)
                with self.assertRaisesRegex(ValueError, 'TARGET_EXISTS'): publish(blob, root, release, entry)
        finally: os.umask(previous_umask)
    def test_bad_hash_no_directory_created(self):
        blob, release, entry = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()/'base'/'root'
            with self.assertRaisesRegex(ValueError, 'RELEASE_SHA'): publish(blob, root, '0'*64, entry)
            self.assertFalse(root.parent.exists())
    def test_traversal_duplicate_and_symlink_rejected(self):
        for kwargs in ({'extra': {'../bad': b'x'}}, {'extra': {'/bad': b'x'}}, {'duplicate': True}, {'symlink': True}):
            blob, release, entry = fixture(**kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, 'TRANSPORT_MEMBER'):
                validate_transport(blob, release, entry)
    def test_extra_file(self):
        blob, release, entry = fixture(extra={'extra': b'x'})
        with self.assertRaisesRegex(ValueError, 'INVENTORY'): validate_transport(blob, release, entry)
    def test_entry_external_binding(self):
        blob, release, entry = fixture()
        with self.assertRaisesRegex(ValueError, 'ENTRY_SHA'): validate_transport(blob, release, '0'*64)

if __name__ == '__main__': unittest.main()

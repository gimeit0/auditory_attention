"""Descriptor-handoff regressions, including a synthetic NFS unlink lifecycle."""

import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    'nfs_publication_tests', Path(__file__).with_name('diagnose_batch_invariance.py')
)
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'attempts' / 'slurm-123'
        self.root.mkdir(parents=True, mode=0o700)
        self.relative = 'reference_cold/REFERENCE_INPUTS.json'
        self.target = self.root / self.relative
        self.payload = b'{"test":1}\n'

    def publish(self):
        with diag._AttemptArtifactStore(self.root) as store:
            return store.publish_bytes(self.relative, self.payload)

    def test_nfs_unlink_does_not_keep_private_descriptor_open(self):
        opened = {}
        real_open, real_close, real_unlink, real_link = (
            os.open, os.close, os.unlink, os.link
        )
        observed = []

        def track_open(name, flags, *args, **kwargs):
            descriptor = real_open(name, flags, *args, **kwargs)
            opened[descriptor] = str(name)
            return descriptor

        def track_close(descriptor):
            opened.pop(descriptor, None)
            return real_close(descriptor)

        def emulate_unlink(name, *args, **kwargs):
            if str(name).endswith('.partial'):
                private_open = str(name) in opened.values()
                final_open = self.target.name in opened.values()
                observed.append((private_open, final_open))
                if private_open:
                    real_link(name, '.nfs_synthetic_open_private',
                              src_dir_fd=kwargs['dir_fd'],
                              dst_dir_fd=kwargs['dir_fd'])
            return real_unlink(name, *args, **kwargs)

        with (
            mock.patch.object(diag.os, 'open', side_effect=track_open),
            mock.patch.object(diag.os, 'close', side_effect=track_close),
            mock.patch.object(diag.os, 'unlink', side_effect=emulate_unlink),
        ):
            record = self.publish()
        self.assertEqual(observed, [(False, True)])
        self.assertEqual(record['sha256'], hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(self.target.stat().st_nlink, 1)
        self.assertEqual(opened, {})

    def test_final_replacement_at_link_rejected_and_preserved(self):
        real_link = os.link

        def replace(*args, **kwargs):
            real_link(*args, **kwargs)
            self.target.unlink()
            self.target.write_bytes(b'FOREIGN')
            self.target.chmod(0o600)

        with mock.patch.object(diag.os, 'link', side_effect=replace):
            with self.assertRaises(diag.DiagnosticError):
                self.publish()
        self.assertEqual(self.target.read_bytes(), b'FOREIGN')

    def test_extra_hardlink_at_handoff_rejected(self):
        real_link = os.link
        alias = self.root / 'external_alias'

        def add_alias(*args, **kwargs):
            real_link(*args, **kwargs)
            real_link(self.target, alias)

        with mock.patch.object(diag.os, 'link', side_effect=add_alias):
            with self.assertRaises(diag.DiagnosticError):
                self.publish()
        self.assertTrue(alias.exists())
        self.assertEqual(alias.read_bytes(), self.payload)

    def _on_private_close(self, action):
        opened = {}
        real_open, real_close = os.open, os.close
        acted = False

        def opening(name, flags, *args, **kwargs):
            fd = real_open(name, flags, *args, **kwargs)
            opened[fd] = str(name)
            return fd

        def closing(fd):
            nonlocal acted
            name = opened.pop(fd, '')
            result = real_close(fd)
            if name.endswith('.partial') and not acted:
                acted = True
                action(name)
            return result

        with (
            mock.patch.object(diag.os, 'open', side_effect=opening),
            mock.patch.object(diag.os, 'close', side_effect=closing),
        ):
            with self.assertRaises(diag.DiagnosticError):
                self.publish()
        self.assertTrue(acted)
        self.assertEqual(opened, {})

    def test_private_replacement_after_close_preserved(self):
        replaced = []

        def action(name):
            private = self.target.parent / name
            private.unlink()
            private.write_bytes(b'FOREIGN_PRIVATE')
            private.chmod(0o600)
            replaced.append(private)

        self._on_private_close(action)
        self.assertEqual(replaced[0].read_bytes(), b'FOREIGN_PRIVATE')
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_final_replacement_after_close_preserved(self):
        def action(_):
            self.target.unlink()
            self.target.write_bytes(b'FOREIGN_FINAL')
            self.target.chmod(0o600)

        self._on_private_close(action)
        self.assertEqual(self.target.read_bytes(), b'FOREIGN_FINAL')

    def test_permission_change_after_handoff_rejected(self):
        self._on_private_close(lambda _: self.target.chmod(0o644))
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o644)

    def test_link_failure_cleans_only_own_private(self):
        with mock.patch.object(diag.os, 'link', side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):
                self.publish()
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.target.parent.iterdir()), [])

    def test_existing_destination_never_overwritten(self):
        self.target.parent.mkdir(mode=0o700)
        self.target.write_bytes(b'EXISTING')
        with self.assertRaises(FileExistsError):
            self.publish()
        self.assertEqual(self.target.read_bytes(), b'EXISTING')

    def test_short_writes_are_completed(self):
        real_write = os.write

        def short(fd, view):
            return real_write(fd, view[:2])

        with mock.patch.object(diag.os, 'write', side_effect=short):
            record = self.publish()
        self.assertEqual(record['size'], len(self.payload))
        self.assertEqual(self.target.read_bytes(), self.payload)


if __name__ == '__main__':
    unittest.main()

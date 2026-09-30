"""Archive-only unit cases; temporary artificial files, no model checkpoint."""

from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import trace_archive as a
from cold_worker import fixtures
import torch


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(20260911)
        self.tmp = tempfile.TemporaryDirectory(prefix='audattn-archive-unit-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = fixtures.plan()
        self.binding = {'scope': 'UNIT_TEST_ONLY', 'pair_id': 'a' * 32}
        self.receipts = {}

    def bundle(self, role='observed'):
        root = self.root / role
        root.mkdir(mode=0o700)
        model = fixtures.Toy(True)
        if role == 'reference':
            batches = fixtures.baseline(model, self.plan)
            receipt = a.seal_archive(root, role=role, binding=self.binding, plan=self.plan, batches=batches)
        else:
            with a.stream.CaptureStore(root / 'captures', chunk_bytes=16) as store:
                with a.stream.StreamObserver(model, self.plan, store) as observer:
                    for p, i, ids in self.plan.schedule():
                        observer.record(model, p, i, ids, *fixtures.inputs(ids))
                    batches = observer.finish()
                receipt = a.seal_archive(root, role=role, binding=self.binding,
                                         plan=self.plan, batches=batches, store=store)
        self.receipts[role] = receipt
        return root

    def reader(self, role='observed', **kwargs):
        args = {'expected_sha256': self.receipts[role]['manifest_sha256'],
                'expected_binding': self.binding, 'expected_plan': self.plan, 'expected_role': role}
        args.update(kwargs)
        reader = a.ArchiveReader(self.root / role, **args)
        self.addCleanup(reader.close)
        return reader

    def rewrite(self, change, role='observed', canonical=True):
        path = self.root / role / 'archive.json'
        value = json.loads(path.read_bytes())
        change(value)
        raw = a.canonical(value) if canonical else json.dumps(value, indent=2).encode()
        path.write_bytes(raw)
        self.receipts[role]['manifest_sha256'] = a.digest(raw)

    def test_reference_roundtrip(self):
        self.bundle('reference')
        reader = self.reader('reference')
        self.assertEqual(len(reader.batches), len(self.plan.schedule()))
        self.assertEqual(reader.refs, ())

    def test_observed_roundtrip_full_bytes(self):
        self.bundle()
        reader = self.reader()
        self.assertEqual(len(reader.refs), 2 * 4 * 4)
        for ref in reader.refs:
            self.assertEqual(a.digest(b''.join(reader.chunks(ref))), ref.sha256)

    def test_requires_external_hash(self):
        self.bundle()
        for sha in ('', None, '0' * 64):
            with self.assertRaises(RuntimeError):
                self.reader(expected_sha256=sha)

    def test_external_role_binding_and_plan(self):
        self.bundle()
        for kw in ({'expected_role': 'reference'}, {'expected_binding': {}},
                   {'expected_plan': replace(self.plan, targets=(9000,))}):
            with self.assertRaises(RuntimeError):
                self.reader(**kw)

    def test_noncanonical_manifest(self):
        self.bundle()
        self.rewrite(lambda _: None, canonical=False)
        with self.assertRaisesRegex(RuntimeError, 'canonical'):
            self.reader()

    def test_duplicate_json_key(self):
        root = self.bundle()
        path = root / 'archive.json'
        raw = path.read_bytes().replace(b'{', b'{"schema_version":1,', 1)
        path.write_bytes(raw)
        self.receipts['observed']['manifest_sha256'] = a.digest(raw)
        with self.assertRaisesRegex(RuntimeError, 'duplicate JSON'):
            self.reader()

    def test_unknown_constructor_rejected(self):
        self.bundle()
        self.rewrite(lambda x: x['plan'].update(type='os.system'))
        with self.assertRaisesRegex(RuntimeError, 'unknown wire'):
            self.reader()

    def test_cannot_promote_to_production_authority(self):
        self.bundle()
        self.rewrite(lambda x: x.update(production_execution_authority_verified=True))
        with self.assertRaisesRegex(RuntimeError, 'scope/version'):
            self.reader()

    def test_missing_batch_rejected(self):
        self.bundle()
        self.rewrite(lambda x: x['batches']['tuple'].pop())
        with self.assertRaisesRegex(RuntimeError, 'schedule'):
            self.reader()

    def test_relabelled_event_rejected(self):
        self.bundle()
        self.rewrite(lambda x: x['batches']['tuple'][0]['fields']['events']['tuple'][0]['fields']
                     .update(trial_id=999))
        with self.assertRaises((RuntimeError, a.base.TraceError)):
            self.reader()

    def test_reordered_ledger_rejected(self):
        self.bundle()
        self.rewrite(lambda x: x['refs']['tuple'].reverse())
        with self.assertRaisesRegex(RuntimeError, 'unreferenced/reordered'):
            self.reader()

    def test_manifest_extra_field_rejected(self):
        self.bundle()
        self.rewrite(lambda x: x.update(ignored='do not ignore'))
        with self.assertRaisesRegex(RuntimeError, 'schema'):
            self.reader()

    def test_root_extra_file_rejected(self):
        root = self.bundle()
        (root / 'extra').write_bytes(b'x')
        with self.assertRaisesRegex(RuntimeError, 'inventory'):
            self.reader()

    def test_capture_extra_file_rejected(self):
        root = self.bundle()
        (root / 'captures/extra').write_bytes(b'x')
        with self.assertRaisesRegex(RuntimeError, 'inventory'):
            self.reader()

    def test_missing_capture_rejected(self):
        root = self.bundle()
        (root / 'captures/00000000.bin').unlink()
        with self.assertRaisesRegex(RuntimeError, 'inventory'):
            self.reader()

    def test_symlink_capture_rejected(self):
        root = self.bundle()
        path = root / 'captures/00000000.bin'
        backup = self.root / 'original.bin'
        path.rename(backup)
        path.symlink_to(backup)
        with self.assertRaises(OSError):
            self.reader()

    def test_hardlink_capture_rejected(self):
        root = self.bundle()
        os.link(root / 'captures/00000000.bin', self.root / 'linked.bin')
        with self.assertRaisesRegex(RuntimeError, 'metadata'):
            self.reader()

    def test_mode_and_truncation_rejected(self):
        root = self.bundle()
        path = root / 'captures/00000000.bin'
        path.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, 'metadata'):
            self.reader()
        path.chmod(0o600)
        with path.open('r+b') as output:
            output.truncate(1)
        with self.assertRaisesRegex(RuntimeError, 'metadata'):
            self.reader()

    def test_modified_bytes_rejected(self):
        root = self.bundle()
        path = root / 'captures/00000000.bin'
        raw = bytearray(path.read_bytes())
        raw[0] ^= 1
        path.write_bytes(raw)
        with self.assertRaisesRegex(RuntimeError, 'digest'):
            self.reader()

    def test_late_modification_after_open_rejected(self):
        root = self.bundle()
        reader = self.reader()
        one = next(r for r in reader.refs if r.key == ('pass1', 0, 2, 9000))
        two = next(r for r in reader.refs if r.key == ('pass2', 0, 2, 9000))
        self.assertFalse(reader.compare(one, two))
        path = root / 'captures' / f'{two.ordinal:08d}.bin'
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        with self.assertRaisesRegex(RuntimeError, 'digest'):
            reader.compare(one, two)

    def test_manifest_change_after_open_rejected(self):
        root = self.bundle()
        reader = self.reader()
        with (root / 'archive.json').open('ab') as output:
            output.write(b' ')
        with self.assertRaisesRegex(RuntimeError, 'manifest changed'):
            reader.check_inventory()

    def test_root_replacement_rejected(self):
        root = self.bundle()
        reader = self.reader()
        root.rename(self.root / 'saved')
        root.mkdir(mode=0o700)
        with self.assertRaisesRegex(RuntimeError, 'root replaced'):
            reader.check_inventory()

    def test_closed_reader_rejected(self):
        self.bundle()
        reader = self.reader()
        reader.close()
        with self.assertRaises(RuntimeError):
            reader.check_inventory()

    def test_same_process_not_cold_pair(self):
        self.bundle('reference')
        self.bundle('observed')
        with self.assertRaisesRegex(RuntimeError, 'independent writer'):
            a.compare_archives(self.reader('reference'), self.reader('observed'))

    def test_cannot_overwrite_committed_archive(self):
        root = self.bundle('reference')
        raw = (root / 'archive.json').read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'not fresh'):
            a.seal_archive(root, role='reference', binding=self.binding, plan=self.plan,
                           batches=fixtures.baseline(fixtures.Toy(True), self.plan))
        self.assertEqual((root / 'archive.json').read_bytes(), raw)

    def test_short_os_reads_are_completed(self):
        self.bundle()
        original = a.os.read
        with patch.object(a.os, 'read', side_effect=lambda fd, n: original(fd, min(n, 5))):
            reader = self.reader()
            self.assertEqual(len(reader.refs), 32)

    def test_inline_and_total_budgets(self):
        with self.assertRaisesRegex(RuntimeError, 'inline'):
            a.wire(b'x' * (a.CHUNK + 1))
        with self.assertRaisesRegex(RuntimeError, 'byte length'):
            a.valid_tensor('torch.float32', (a.CHUNK * 100,), (1,), 400 * a.CHUNK)
        value = None
        for _ in range(30):
            value = {'tuple': [value]}
        with self.assertRaisesRegex(RuntimeError, 'depth'):
            a.unwire(value)

    def test_nonfinite_endpoint_rejected(self):
        batches = fixtures.baseline(fixtures.Toy(True), self.plan)
        first = batches[0]
        invalid = replace(first.logits, data=a.np.full(first.logits.shape, a.np.nan, dtype='<f8').tobytes())
        changed = a.base.seal(replace(first, logits=invalid))
        with self.assertRaisesRegex(RuntimeError, 'nonfinite endpoint'):
            a.valid_records(self.plan, (changed,) + batches[1:], (), 'reference')

    def test_nonfinite_capture_even_with_updated_digests_rejected(self):
        root = self.bundle()
        path = root / 'archive.json'
        manifest = json.loads(path.read_bytes())
        refs, batches = a.unwire(manifest['refs']), a.unwire(manifest['batches'])
        raw = a.np.full(refs[0].shape, a.np.nan, dtype='<f8').tobytes()
        (root / 'captures/00000000.bin').write_bytes(raw)
        altered = replace(refs[0], sha256=a.digest(raw))
        first = batches[0]
        events = (replace(first.events[0], tensor=altered),) + first.events[1:]
        batches = (a.base.seal(replace(first, events=events)),) + batches[1:]
        manifest.update(refs=a.wire((altered,) + refs[1:]), batches=a.wire(batches))
        raw = a.canonical(manifest)
        path.write_bytes(raw)
        self.receipts['observed']['manifest_sha256'] = a.digest(raw)
        with self.assertRaisesRegex(RuntimeError, 'nonfinite capture'):
            self.reader()

    def test_oversized_manifest_rejected_before_read(self):
        root = self.bundle('reference')
        with (root / 'archive.json').open('r+b') as output:
            output.truncate(a.MAX_MANIFEST + 1)
        with self.assertRaisesRegex(RuntimeError, 'manifest size'):
            self.reader('reference')

    def test_unsupported_tensor_metadata(self):
        for dtype, shape, stride, size in (
            ('torch.int64', (1,), (1,), 8), ('torch.float64', (True,), (1,), 8),
            ('torch.float64', (1,), (-1,), 8), ('torch.float64', (1,), (1,), 7)):
            with self.assertRaises(RuntimeError):
                a.valid_tensor(dtype, shape, stride, size)


if __name__ == '__main__':
    unittest.main(verbosity=2)

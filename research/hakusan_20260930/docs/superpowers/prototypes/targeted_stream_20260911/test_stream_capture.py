"""Synthetic CPU only; all writes confined to unittest temporary directories."""

from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from stream_capture import BlobRef, CaptureError, CaptureStore, tensor_chunks
from stream_observer import StreamObserver, base, bind_compiled_outer, compare_streamed
import test_trace_observer as fixtures


class Outer(torch.nn.Module):
    def __init__(self, dependent=False, compile_inner=True):
        super().__init__()
        self.model = fixtures.Toy(dependent)
        if compile_inner:
            self.model = torch.compile(self.model, backend="eager")
        self.eval().requires_grad_(False)

    def forward(self, cue, mixture):
        return self.model(cue, mixture)


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="audattn-stream-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def store(self, **kwargs):
        store = CaptureStore(self.root / "captures", chunk_bytes=16, **kwargs)
        self.addCleanup(store.close)
        return store

    def pair(self, store, one, two):
        return store.capture(one, ("pass1", 0, 0, 7)), store.capture(two, ("pass2", 0, 0, 7))

    def synthetic(self, dependent=False, compiled=False):
        relative_plan = fixtures.plan()
        if compiled:
            torch._dynamo.reset()
            self.addCleanup(torch._dynamo.reset)
            model = Outer(dependent)
            binding = bind_compiled_outer(model, relative_plan,
                                          expected_outer_type=Outer,
                                          expected_cnn_type=fixtures.Toy)
            plan = binding.plan
            reference = fixtures.baseline(model, plan)
            torch._dynamo.reset()  # synthetic isolation, never a production setting
            model = Outer(dependent)
            binding = bind_compiled_outer(model, relative_plan,
                                          expected_outer_type=Outer,
                                          expected_cnn_type=fixtures.Toy)
        else:
            plan, binding = relative_plan, None
            reference = fixtures.baseline(fixtures.Toy(dependent), plan)
            model = fixtures.Toy(dependent)
        store = self.store()
        with StreamObserver(model, plan, store, binding) as observer:
            for p, i, ids in plan.schedule():
                observer.record(model, p, i, ids, *fixtures.inputs(ids))
            observed = observer.finish()
        return plan, reference, observed, store

    def test_stream_bytes_match_contiguous(self):
        for dtype in (torch.float16, torch.float32, torch.float64):
            x = torch.arange(127, dtype=dtype)
            chunks = list(tensor_chunks(x, 24))
            self.assertLessEqual(max(map(len, chunks)), 24)
            self.assertEqual(b"".join(chunks), x.numpy().tobytes())

    def test_noncontiguous_recursive_slices(self):
        x = torch.arange(420, dtype=torch.float32).reshape(5, 7, 12).permute(2, 0, 1)
        chunks = list(tensor_chunks(x, 16))
        self.assertEqual(b"".join(chunks), x.contiguous().numpy().tobytes())
        self.assertLessEqual(max(map(len, chunks)), 16)

    def test_scalar_and_expanded_views(self):
        for x in (torch.tensor(3.), torch.tensor([3.]).expand(500),
                  torch.arange(60.).reshape(5, 12)[:, ::3]):
            self.assertEqual(b"".join(tensor_chunks(x, 16)), x.contiguous().numpy().tobytes())

    def test_invalid_chunks_and_types(self):
        for budget in (0, 7, True, 1024**2 + 1):
            with self.assertRaises(CaptureError):
                list(tensor_chunks(torch.zeros(3), budget))
        for x in (torch.tensor([1]), torch.tensor([1j]), torch.empty(0),
                  torch.empty(1, device="meta"), torch.ones((1,) * 9)):
            with self.assertRaises(CaptureError):
                list(tensor_chunks(x, 16))

    def test_nonfinite_late_chunk_rejected(self):
        store = self.store()
        x = torch.zeros(100)
        x[-1] = float("nan")
        with self.assertRaisesRegex(CaptureError, "nonfinite"):
            store.capture(x, ("pass1", 0, 0, 7))
        self.assertTrue(store.failed)
        self.assertEqual(store.refs, [])
        self.assertGreater((store.root / "00000000.bin").stat().st_size, 0)

    def test_same_values_different_layout(self):
        store = self.store()
        a = torch.arange(60.).reshape(5, 12).t()
        one, two = self.pair(store, a, a.contiguous())
        self.assertNotEqual(one.stride, two.stride)
        self.assertTrue(store.compare(one, two))
        self.assertFalse(hasattr(one, "data"))
        self.assertEqual(store.peak_payload_bytes, 16)

    def test_immutable_capture_after_input_mutation(self):
        store = self.store()
        x = torch.arange(12.)
        a = store.capture(x, ("pass1", 0, 0, 7))
        x.add_(1)
        b = store.capture(x, ("pass2", 0, 0, 7))
        self.assertFalse(store.compare(a, b))

    def test_cumulative_disk_budget_before_copy(self):
        store = self.store(total_bytes=50)
        store.capture(torch.zeros(10), ("pass1", 0, 0, 7))
        with patch("stream_capture.tensor_chunks", side_effect=AssertionError("copy called")):
            with self.assertRaisesRegex(CaptureError, "byte budget"):
                store.capture(torch.zeros(10), ("pass2", 0, 0, 7))
        self.assertFalse((store.root / "00000001.bin").exists())

    def test_tensor_budget_and_cannot_resume(self):
        store = self.store(tensor_bytes=8)
        with self.assertRaisesRegex(CaptureError, "byte budget"):
            store.capture(torch.zeros(3), ("pass1", 0, 0, 7))
        with self.assertRaisesRegex(CaptureError, "closed or failed"):
            store.capture(torch.zeros(1), ("pass1", 0, 0, 7))

    def test_record_limit(self):
        store = self.store(max_records=1)
        store.capture(torch.zeros(1), ("pass1", 0, 0, 7))
        with self.assertRaisesRegex(CaptureError, "record budget"):
            store.capture(torch.zeros(1), ("pass2", 0, 0, 7))

    def test_duplicate_key(self):
        store = self.store()
        store.capture(torch.zeros(1), ("pass1", 0, 0, 7))
        with self.assertRaisesRegex(CaptureError, "duplicate"):
            store.capture(torch.zeros(1), ("pass1", 0, 0, 7))

    def test_invalid_event_key(self):
        store = self.store()
        with self.assertRaisesRegex(CaptureError, "event key"):
            store.capture(torch.zeros(1), ("pass1", True, 0, 7))

    def test_invalid_budget(self):
        for kw in ({"chunk_bytes": True}, {"total_bytes": 0},
                   {"tensor_bytes": 128 * 1024**2 + 1}, {"max_records": 8193}):
            with self.assertRaises(CaptureError):
                CaptureStore(self.root / "invalid", **kw)
        self.assertFalse((self.root / "invalid").exists())

    def test_existing_root_preserved(self):
        store = self.store()
        with self.assertRaises(FileExistsError):
            CaptureStore(store.root)

    def test_symlink_parent_rejected(self):
        (self.root / "alias").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(CaptureError, "parent"):
            CaptureStore(self.root / "alias" / "new")

    def test_symlink_capture_rejected(self):
        store = self.store()
        a, b = self.pair(store, torch.zeros(10), torch.zeros(10))
        original = store.root / "00000000.bin"
        original.rename(store.root / "saved.bin")
        original.symlink_to(store.root / "saved.bin")
        with self.assertRaises(OSError):
            store.compare(a, b)

    def test_hardlink_capture_rejected(self):
        store = self.store()
        a, b = self.pair(store, torch.zeros(10), torch.zeros(10))
        os.link(store.root / "00000000.bin", store.root / "extra.bin")
        with self.assertRaisesRegex(CaptureError, "metadata"):
            store.compare(a, b)

    def test_changed_bytes_after_known_difference_rejected(self):
        store = self.store()
        a, b = self.pair(store, torch.zeros(100), torch.ones(100))
        with (store.root / "00000001.bin").open("r+b") as f:
            f.seek(-1, 2)
            f.write(b"x")
        with self.assertRaisesRegex(CaptureError, "digest"):
            store.compare(a, b)

    def test_truncated_capture_rejected(self):
        store = self.store()
        a, b = self.pair(store, torch.zeros(10), torch.zeros(10))
        with (store.root / "00000000.bin").open("r+b") as f:
            f.truncate(2)
        with self.assertRaisesRegex(CaptureError, "metadata"):
            store.compare(a, b)

    def test_changed_ref_and_wrong_store_rejected(self):
        for field in ({"key": ("pass1", 0, 0, 8)}, {"store_id": "foreign"}):
            with tempfile.TemporaryDirectory(dir=self.root) as temp:
                with CaptureStore(Path(temp) / "captures", chunk_bytes=16) as store:
                    a, b = self.pair(store, torch.zeros(10), torch.zeros(10))
                    with self.assertRaisesRegex(CaptureError, "reference"):
                        store.compare(replace(a, **field), b)

    def test_directory_replacement_rejected(self):
        store = self.store()
        a, b = self.pair(store, torch.zeros(10), torch.zeros(10))
        store.root.rename(self.root / "original")
        store.root.mkdir(mode=0o700)
        with self.assertRaisesRegex(CaptureError, "directory changed"):
            store.compare(a, b)

    def test_write_error_poisoned(self):
        store = self.store()
        with patch("stream_capture.os.fsync", side_effect=OSError("disk unavailable")):
            with self.assertRaisesRegex(OSError, "disk unavailable"):
                store.capture(torch.zeros(10), ("pass1", 0, 0, 7))
        self.assertTrue(store.failed)
        self.assertEqual(store.refs, [])

    def test_chunk_size_independent_bytes(self):
        x = torch.arange(1024.).reshape(32, 32).t()
        self.assertEqual(b"".join(tensor_chunks(x, 16)), b"".join(tensor_chunks(x, 4096)))

    def test_first_layer_sized_synthetic_capture(self):
        # Same SHAPE as the first real B2 block, but synthetic broadcast zeros;
        # no model forward, audio, checkpoint or full-sized input allocation.
        with CaptureStore(self.root / "large", chunk_bytes=1024**2) as store:
            x = torch.zeros(1).expand(32, 39, 19967)
            a, b = self.pair(store, x, x)
            self.assertEqual(a.size, 99675264)
            self.assertEqual(store.used_bytes, 199350528)
            self.assertLessEqual(store.peak_payload_bytes, 1024**2)
            self.assertTrue(store.compare(a, b))

    def test_all_32_trials_16_then_1_kept(self):
        trial_ids = tuple(range(32))
        p = replace(fixtures.plan(), trials=trial_ids, targets=(0, 28), batch_sizes=(16, 1))
        reference = fixtures.baseline(fixtures.Toy(True), p)
        store, model = self.store(), fixtures.Toy(True)
        with StreamObserver(model, p, store) as observer:
            for pass_id, batch_index, ids in p.schedule():
                observer.record(model, pass_id, batch_index, ids, *fixtures.inputs(ids))
            observed = observer.finish()
        result = compare_streamed(p, reference, observed, store)
        self.assertEqual(len(observed), 34)
        self.assertEqual([len(b.trials) for b in observed], [16, 16] + [1] * 32)
        self.assertEqual(len(store.refs), 2 * 2 * 4)
        self.assertTrue(all(x["first_observed_boundary"]["index"] == 2 for x in result["targets"]))

    def test_streamed_endpoint_equivalent_to_original(self):
        p, reference, observed, store = self.synthetic()
        result = compare_streamed(p, reference, observed, store)
        self.assertEqual(store.used_bytes, 2 * 4 * 4 * 3 * 8)
        self.assertTrue(all(x["first_observed_boundary"] is None for x in result["targets"]))
        self.assertTrue(all(type(e.tensor) is BlobRef for b in observed for e in b.events))

    def test_streamed_known_first_boundary(self):
        p, reference, observed, store = self.synthetic(dependent=True)
        result = compare_streamed(p, reference, observed, store)
        self.assertTrue(all(x["first_observed_boundary"]["index"] == 2 for x in result["targets"]))

    def test_compiled_outer_binding_and_streamed_endpoint(self):
        p, reference, observed, store = self.synthetic(compiled=True)
        result = compare_streamed(p, reference, observed, store)
        self.assertTrue(all(s.module.startswith("model._orig_mod.") for s in p.stages))
        self.assertFalse(result["ready_for_gpu"])
        self.assertFalse(result["intermediate_equivalence_to_uninstrumented_compilation_proven"])

    def test_missing_compiled_wrapper_rejected(self):
        with self.assertRaisesRegex(base.TraceError, "compiled inner"):
            bind_compiled_outer(Outer(compile_inner=False), fixtures.plan(),
                                expected_outer_type=Outer, expected_cnn_type=fixtures.Toy)

    def test_stage_replacement_rejected(self):
        model = Outer()
        binding = bind_compiled_outer(model, fixtures.plan(),
                                      expected_outer_type=Outer, expected_cnn_type=fixtures.Toy)
        model.model._orig_mod.shared = torch.nn.Identity()
        with self.assertRaisesRegex(base.TraceError, "stage module"):
            binding.check()

    def test_wrapper_replacement_rejected(self):
        model = Outer()
        binding = bind_compiled_outer(model, fixtures.plan(),
                                      expected_outer_type=Outer, expected_cnn_type=fixtures.Toy)
        model.model = fixtures.Toy()
        with self.assertRaisesRegex(base.TraceError, "wrapper binding"):
            binding.check()

    def test_streamed_tampered_event_rejected(self):
        p, reference, observed, store = self.synthetic()
        event = observed[0].events[0]
        changed = replace(event, tensor=replace(event.tensor, key=("pass1", 0, 0, 999)))
        first = base.seal(replace(observed[0], events=(changed,) + observed[0].events[1:]))
        with self.assertRaisesRegex(base.TraceError, "capture/event"):
            compare_streamed(p, reference, (first,) + observed[1:], store)

    def test_unreferenced_record_rejected(self):
        p, reference, observed, store = self.synthetic()
        store.capture(torch.zeros(1), ("pass2", 999, 999, 999))
        with self.assertRaisesRegex(base.TraceError, "unreferenced"):
            compare_streamed(p, reference, observed, store)

    def test_streamed_endpoint_interference_rejected(self):
        p, reference, observed, store = self.synthetic()
        wrong = base.seal(replace(observed[0], logits=base.copy_tensor(torch.ones(2, 3))))
        with self.assertRaisesRegex(base.TraceError, "INTERFERENCE"):
            compare_streamed(p, reference, (wrong,) + observed[1:], store)


if __name__ == "__main__":
    unittest.main(verbosity=2)

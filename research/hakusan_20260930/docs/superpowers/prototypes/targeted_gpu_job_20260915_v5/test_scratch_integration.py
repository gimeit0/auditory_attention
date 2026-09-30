"""Original hermetic CPU lifetime with real spill/mmap; no Linux mount/GPU claim."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / "targeted_worker_20260915_scan"
FIXTURE_SHA = "49f7abb45fbea416c4a8b3e5a82b41de1b6b669fb5f1b24e1faa8d55fc1e40bb"
if hashlib.sha256((PRIOR / "test_baseline_bridge.py").read_bytes()).hexdigest() != FIXTURE_SHA:
    raise RuntimeError("pinned synthetic fixture differs")
sys.path.insert(0, str(PRIOR))
sys.path.insert(0, str(HERE.parent / "targeted_gpu_pair_20260915_scan"))
sys.path.insert(0, str(HERE))
import test_baseline_bridge as fixture  # noqa: E402
import archive_adapter  # noqa: E402
import pass_archive as archive  # noqa: E402
import scratch_adapter  # noqa: E402
import stage_timing
import io
from test_pair_archive import binding  # noqa: E402


class ScratchTests(unittest.TestCase):
    def test_original_globals_preserved_and_exact_type_substitution(self):
        original = fixture.diag._WORKER_WRITE_PATHS
        values = dict(original)
        private, _, paths = scratch_adapter.build(fixture.diag)
        _, audit = scratch_adapter.reference_loop(archive_adapter, private)
        self.assertEqual(audit["scratch_type_substitutions"], 1)
        self.assertTrue(audit["original_ast_restored_exactly"])
        self.assertEqual(len(paths), 10)
        self.assertNotIn("HOME", paths)
        self.assertIs(original, fixture.diag._WORKER_WRITE_PATHS)
        self.assertEqual(values, original)

    def test_real_mmap_two_pass_original_cpu_lifetime(self):
        fixture.torch.set_num_threads(1)
        original_home = os.environ["HOME"]
        parent = fixture.expected_contract()
        wire = fixture.replay.canonical(parent)
        private, _, paths = scratch_adapter.build(fixture.diag)
        with tempfile.TemporaryDirectory(prefix="candidate-real-mmap-test-") as temporary:
            root = Path(temporary).resolve()
            scratch_root = root / "scratch"
            scratch_root.mkdir(mode=0o700)
            for name in set(paths.values()) | {"intermediates"}:
                (scratch_root / name).mkdir(mode=0o700)
            # Only ten cache variables are patched, never HOME. The original
            # Linux mount factory is NOT invoked on macOS and is not attested.
            with mock.patch.dict(os.environ, {key: str(scratch_root / name) for key, name in paths.items()}), \
                    fixture.diag._PinnedArtifactDirectory(scratch_root) as anchor, \
                    fixture.worker("B2") as (context, trials, evaluator, scene):
                scratch = private(scratch_root, [anchor], {"scope": "local synthetic mmap only"})
                gate = fixture.bridge.BaselineBridge(fixture.diag, context, trials, wire,
                                                     fixture.replay.sha(wire), "B2", hermetic_test=True)
                writer = archive.PassArchive(root / "reference", binding())
                try:
                    collector = archive_adapter.PassCollector(gate, scratch, writer, spill=False)
                    collector.names = (fixture.replay.BOUNDARIES, fixture.replay.COARSE)
                    tree, _ = scratch_adapter.reference_loop(archive_adapter, private)
                    tree, _ = stage_timing.instrument(tree, loop=True)
                    timing_log = io.StringIO()
                    namespace = {**vars(fixture.bridge), "_private_scratch_type": private,
                                 '_timing': stage_timing.Recorder(timing_log)}
                    exec(compile(tree, "<synthetic-real-mmap-test>", "exec"), namespace)
                    result = namespace["archived_reference"](gate, scratch=scratch, _archiver=collector)
                    self.assertEqual(result["status"], "HERMETIC_V19_BASELINE_BRIDGE_PASS")
                    self.assertIn('"phase": "diag.run_trace_pass"', timing_log.getvalue())
                    self.assertIn('"pass_id": "pass2"', timing_log.getvalue())
                    self.assertEqual(evaluator.calls.count("model"), 34)
                    self.assertEqual(len(evaluator.load_calls), 1)
                    self.assertEqual(len(scratch.spills), 4)
                    self.assertEqual(len(scratch._maps), 4)
                    self.assertEqual(len(list((scratch_root / "intermediates").iterdir())), 4)
                    scratch.verify_spills()
                    document = archive.verify_archive(writer.root, writer.finish(), writer.binding, parent)
                    for part in document["passes"]:
                        fixture.diag.decode_pass_evidence(part["original_pass_evidence"])
                    self.assertEqual(os.environ["HOME"], original_home)
                    self.assertFalse(fixture.torch.cuda.is_initialized())
                    with mock.patch.dict(os.environ, {"TMPDIR": str(root / "wrong")}):
                        with self.assertRaisesRegex(RuntimeError, "cache environment"):
                            scratch.check()
                finally:
                    writer.close()
                    fixture.diag._revoke_attestation(gate.attestation)
        self.assertEqual(os.environ["HOME"], original_home)


if __name__ == "__main__":
    unittest.main()

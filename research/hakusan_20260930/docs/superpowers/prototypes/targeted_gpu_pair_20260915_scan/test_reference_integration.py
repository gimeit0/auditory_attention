"""One hermetic toy CPU lifetime through original v18 and new archiving.

Scratch uses an explicit test double: real mmap/CUDA/compiler/production scope
are NOT validated by this test. The public CUDA entry is never invoked.
"""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / "targeted_worker_20260915_scan"
FIXTURE_SHA = "49f7abb45fbea416c4a8b3e5a82b41de1b6b669fb5f1b24e1faa8d55fc1e40bb"
if hashlib.sha256((PRIOR / "test_baseline_bridge.py").read_bytes()).hexdigest() != FIXTURE_SHA:
    raise RuntimeError("original synthetic fixture differs")
sys.path.insert(0, str(PRIOR))
sys.path.insert(0, str(HERE))
import test_baseline_bridge as fixture  # noqa: E402
import archive_adapter as adapter  # noqa: E402
import pass_archive as archive  # noqa: E402
from test_pair_archive import binding  # noqa: E402


class ReferenceIntegration(unittest.TestCase):
    def test_original_two_pass_commitments_survive_archive(self):
        fixture.torch.set_num_threads(1)
        parent = fixture.expected_contract()
        wire = fixture.replay.canonical(parent)
        with tempfile.TemporaryDirectory(prefix="archived-original-cpu-") as temporary:
            with fixture.worker("B2") as (context, trials, evaluator, scene):
                gate = fixture.bridge.BaselineBridge(fixture.diag, context, trials, wire,
                                                     fixture.replay.sha(wire), "B2", hermetic_test=True)
                writer = archive.PassArchive(Path(temporary).resolve() / "reference", binding())
                try:
                    scratch = mock.Mock()  # not original _WorkerScratch; no real spill claim
                    collector = adapter.PassCollector(gate, scratch, writer, spill=False)
                    collector.names = (fixture.replay.BOUNDARIES, fixture.replay.COARSE)
                    tree, _ = adapter.derive("reference")
                    namespace = dict(vars(fixture.bridge))
                    exec(compile(tree, "<hermetic-archive-test>", "exec"), namespace)
                    result = namespace["archived_reference"](gate, scratch=scratch, _archiver=collector)
                    self.assertEqual(result["status"], "HERMETIC_V19_BASELINE_BRIDGE_PASS")
                    self.assertEqual(evaluator.calls.count("model"), 34)
                    self.assertEqual(len(evaluator.load_calls), 1)
                    self.assertEqual(scratch.spill.call_count, 2)
                    self.assertEqual(collector.count, 2)
                    receipt = writer.finish()
                    value = archive.verify_archive(writer.root, receipt, writer.binding, parent)
                    for part in value["passes"]:
                        decoded = fixture.diag.decode_pass_evidence(part["original_pass_evidence"])
                        self.assertEqual(decoded["payload"]["pass_id"], part["pass_id"])
                    self.assertFalse(fixture.torch.cuda.is_initialized())
                finally:
                    writer.close()
                    fixture.diag._revoke_attestation(gate.attestation)


if __name__ == "__main__":
    unittest.main()

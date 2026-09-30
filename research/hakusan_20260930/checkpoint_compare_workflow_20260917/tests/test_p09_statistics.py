"""P09 wrapper tests on the synthetic v3 full10k archive; bootstrap reduced for speed."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P09 = load("p09_under_test", ROOT / "checkpoint_compare_workflow_20260917/p09_statistics.py")


class StatisticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = load("p09_fixture", ROOT / "same_bank_compare_2026_09_19_full_v3/tests/test_layouts.py")
        cls.case = fixture.ReviewTests("test_pinned_core")
        cls.case.setUp()
        cls.archive, cls.receipt, _ = cls.case.archive("full10k")
        cls.self32, cls.self32_receipt, _ = cls.case.archive("self32")
        cls.stats = P09.compute(cls.archive, cls.receipt, repetitions=25)

    @classmethod
    def tearDownClass(cls):
        cls.case.doCleanups()

    def test_v4_semantics_and_structure(self):
        s = self.stats["v4_summary"]
        self.assertTrue(s["bootstrap"]["performed"])
        self.assertEqual(s["bootstrap"]["seed"], 20260829)
        self.assertEqual(set(s["models"]), {"formal40", "author_external", "valbest33"})
        self.assertEqual(
            set(s["paired_model_differences"]),
            {"formal40_vs_valbest33", "formal40_vs_author_external", "valbest33_vs_author_external"},
        )
        overall = s["paired_model_differences"]["formal40_vs_author_external"]["strata"]["overall"]
        self.assertEqual(overall["trials"], 10000)
        ci = overall["cross_entropy_improvement_b_minus_a_positive_favors_a"]["target_speaker_cluster_bootstrap_95ci"]
        self.assertLessEqual(ci[0], ci[1])
        self.assertEqual(s["models"]["formal40"]["cue_controls"]["trials"], 2000)
        self.assertEqual(self.stats["source"]["predictions"], 48000)

    def test_p06_sections_present(self):
        bounds = self.stats["p06_4_accuracy_uncertainty_upper_bound"]
        self.assertEqual(set(bounds), {"formal40", "author_external", "valbest33"})
        self.assertTrue(all(0.0 <= b <= 1.0 for b in bounds.values()))
        budget = self.stats["p06_5_error_budget"]
        self.assertIn("formal40_vs_author_external/overall", budget)
        self.assertIsInstance(budget["formal40_vs_author_external/overall"]["numeric_perturbation_negligible"], bool)
        self.assertEqual(self.stats["margin_strata"]["by_model_condition"]["formal40__correct"]["trials"], 10000)

    def test_outputs_written_and_json_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "p09"
            result = P09.write_outputs(self.stats, out)
            self.assertEqual(len(result["statistics_sha256"]), 64)
            json.loads((out / "STATISTICS.json").read_text())
            report = (out / "REPORT.md").read_text(encoding="utf-8")
            for token in ("formal40", "author_external", "valbest33", "P06-4", "P06-5", "bootstrap"):
                self.assertIn(token, report)
            self.assertGreater(len((out / "paired_strata.csv").read_text().splitlines()), 100)
            with self.assertRaises(FileExistsError):
                P09.write_outputs(self.stats, out)

    def test_wrong_receipt_or_non_full_archive_rejected(self):
        with self.assertRaises((ValueError, RuntimeError)):
            P09.compute(self.archive, "0" * 64, repetitions=5)
        with self.assertRaises((ValueError, RuntimeError)):
            P09.compute(self.self32, self.self32_receipt, repetitions=5)


if __name__ == "__main__":
    unittest.main()

"""Synthetic archive tests. Native declarations below are TEST DATA, not evidence.

The production checkpoint/GPU is never loaded. Fixtures use the existing tiny
disk-checkpoint/strict-load/forward path and are deleted after every test.
"""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest

import torch

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "same_bank_compare_2026_09_19_full_v3"
V2_TESTS = ROOT / "same_bank_compare_2026_09_19_confirm_v2/tests/test_layouts.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REVIEW = load("archive_review_tests_v3", PACKAGE / "review_layouts.py")
FIXTURE = load("candidate_fixture_tests_v3", PACKAGE / "tests/test_eager_compare.py")
E, BASE = FIXTURE.E, FIXTURE.BASE
SUBSET = ("full10k", "self32", "subset-repeat")
_FULL10K_CACHE = {}


class ReviewTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.fixture = FIXTURE.CandidateTests("test_exclusive_artifact_creation")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.counter = 0

    def archive(
        self, layout="self32", modify_run=None, modify_details=None, flip=False
    ):
        self.counter += 1
        output = self.fixture.root / f"archive-{self.counter}"
        if layout == "full10k":
            # The synthetic 10k archive is built once per process and copied; it is
            # byte-identical across fixtures (seeded weights, id-derived audio).
            assert modify_run is None and modify_details is None and not flip
            if "path" not in _FULL10K_CACHE:
                _FULL10K_CACHE["keep"] = tempfile.TemporaryDirectory()
                cache_root = Path(_FULL10K_CACHE["keep"].name)
                (cache_root / "full10k").mkdir()
                started = time.monotonic()
                built = self._build(cache_root / "full10k", "full10k", pid=999)
                _FULL10K_CACHE.update(path=built[0], receipt=built[1], layout_sha=built[2],
                                      build_seconds=time.monotonic() - started)
            shutil.copytree(_FULL10K_CACHE["path"], output)
            return output, _FULL10K_CACHE["receipt"], _FULL10K_CACHE["layout_sha"]
        output.mkdir()
        return self._build(output, layout, modify_run, modify_details, flip, 1000 + self.counter)

    def _build(self, output, layout, modify_run=None, modify_details=None, flip=False, pid=1000):
        spec = E.layout_spec(layout)
        batch = spec["batch_size"]
        selected = E.select_trials(self.fixture.full_bank, layout)
        results, arrays, details = self.fixture.run_pass(batch, bank=selected)
        if flip:
            key = "formal40__correct"
            row = arrays[key][0]
            row[(int(row.argmax()) + 1) % 800] = row.max() + 20
            logits = torch.from_numpy(arrays[key])
            logp = logits.log_softmax(-1)
            labels = torch.tensor(selected.target_label.to_numpy())
            probes = torch.tensor(
                BASE._prepare_result_frame(selected).probe_distractor_label.to_numpy(
                    dtype=int
                )
            )
            rows = torch.arange(len(logits))
            results["formal40_pred_label"] = logits.argmax(1).numpy()
            results["formal40_correct"] = (logits.argmax(1) == labels).long().numpy()
            results["formal40_nll"] = (-logp[rows, labels]).numpy()
            results["formal40_p_target"] = logp[rows, labels].exp().numpy()
            results["formal40_p_probe_distractor"] = logp[rows, probes].exp().numpy()
        if modify_details:
            modify_details(details)
        E.save_pass(output, selected, results, arrays, details)
        E.create_bytes(output / "LAYOUT.json", E.layout_bytes(spec))
        layout_sha = E.sha256(output / "LAYOUT.json")
        run = {
            "scope": "SYNTHETIC_TEST_NATIVE_DECLARATIONS_ARE_FIXTURES",
            "protocol": E.PROTOCOL,
            "role": E.ROLE,
            "candidate_sha256": REVIEW.CANDIDATE_SHA,
            "v4_source_sha256": E.V4_SHA,
            "v4_manifest_sha256": E.MANIFEST_SHA,
            "models": {
                m: {"sha256": BASE.EXPECTED_HASHES[m], "role": BASE.MODEL_ROLES[m]}
                for m in E.MODEL_ORDER
            },
            "model_order": list(E.MODEL_ORDER),
            "trial_ids": spec["trial_ids"],
            "layout_id": layout,
            "layout_sha256": layout_sha,
            "batches": spec["batches"],
            "historical_scene_hashes": {
                str(i): self.fixture.hashes[i] for i in spec["trial_ids"]
            },
            "runtime": copy.deepcopy(REVIEW.RUNTIME),
            "amp": False,
            "compiled_forward": False,
            "batch_size": batch,
            "tail_policy": "unmodified smaller final batch",
            "job_id": "123456",
            "pid": pid,
            "started_utc": "2026-09-17T12:00:00+00:00",
            "environment": {
                "python": "3.11.5",
                "torch": "2.1.1+cu118",
                "cuda": "11.8",
                "cudnn": 8700,
                "hostname": "synthetic-test-only",
                "device": "NVIDIA A100-PCIE-40GB",
            },
        }
        if modify_run:
            modify_run(run)
        E.create_json(output / "RUN.json", run)
        loads = {}
        for model_id, model in self.fixture.models.items():
            size = sum(p.numel() for p in model.parameters())
            loads[model_id] = {
                "scope": "synthetic fixture load report",
                "loaded_trainable_numel_ratio": 1.0,
                "loaded_trainable_numel": size,
                "trainable_numel": size,
                "eager_unwrap": {
                    "known_wrapper_removed": True,
                    "state_bindings_preserved": len(list(model.named_parameters()))
                    + len(list(model.named_buffers())),
                },
            }
        E.create_json(output / "LOAD_REPORTS.json", loads)
        E.create_json(
            output / "PROFILE.json",
            {
                "scope": "synthetic fixture cost record",
                "trials": len(selected),
                "control_trials": int(selected.control_subset.sum()),
                "batch_size": batch,
                "wall_seconds_process": 1.0,
                "cuda_max_memory_allocated_bytes": 0,
                "cuda_max_memory_reserved_bytes": 0,
                "host_max_rss_kib": 0,
            },
        )
        E.create_json(
            output / "RECEIPT.json",
            {
                "protocol": E.PROTOCOL,
                "status": "SMALL_RUN_COMPLETE_NOT_QUALIFIED",
                "files": {p.name: E.sha256(p) for p in output.iterdir()},
            },
        )
        return output, E.sha256(output / "RECEIPT.json"), layout_sha

    def read(self, artifact):
        return REVIEW.read_archive(E, BASE, *artifact)

    def pair(self, left, right, kind, **right_changes):
        a = self.read(self.archive(left))
        b = self.read(self.archive(right, **right_changes))
        return a, b, kind

    def v2_bridge_archive(self):
        """Synthetic v2-protocol archive standing in for Job 728280 bridge16."""
        v2 = load("v2_archive_fixture", V2_TESTS).ReviewTests("test_pinned_core")
        v2.setUp()
        self.addCleanup(v2.doCleanups)
        # Same synthetic bank columns as this package (real archives share one bank).
        v2.fixture.full_bank = self.fixture.full_bank
        return v2.archive("bridge16")

    def r1_full_archive(self):
        """Copy of the cached full10k archive relabelled as the r1 executor (728378)."""
        path, _, layout_sha = self.archive("full10k")
        run = json.loads((path / "RUN.json").read_text())
        run["candidate_sha256"] = REVIEW.V3R1_CANDIDATE_SHA
        run["pid"] = 998
        (path / "RUN.json").write_bytes(E.layout_bytes(run))
        receipt = json.loads((path / "RECEIPT.json").read_text())
        receipt["files"]["RUN.json"] = E.sha256(path / "RUN.json")
        (path / "RECEIPT.json").write_bytes(E.layout_bytes(receipt))
        return path, E.sha256(path / "RECEIPT.json"), layout_sha

    def test_full_repeat_against_r1_baseline(self):
        left = self.read(self.r1_full_archive())
        self.assertEqual(REVIEW.layout_name(E, left), "v3r1_full10k")
        right = self.read(self.archive("full10k"))
        report = REVIEW.compare_archives(E, BASE, left, right, "full-repeat")
        self.assertEqual(len(report["compared_trial_ids"]), 10000)
        self.assertTrue(
            all(v["logits_bitwise_equal"] for v in report["by_model_condition"].values())
        )
        self.assertEqual(report["legacy_v4_result_table_canary_1e_6"]["status"], "PASS")
        self.assertEqual(len(report["paired_nll_rows"]), 48000)
        with self.assertRaisesRegex(ValueError, "Undeclared"):
            REVIEW.align_pair(E, right, left, "full-repeat")
        # An unknown executor SHA is still rejected outright.
        with self.assertRaisesRegex(ValueError, "candidate SHA"):
            self.read(self.archive("self32", modify_run=lambda r: r.update(candidate_sha256="0" * 64)))

    def test_pinned_core(self):
        candidate, base = REVIEW.load_core()
        self.assertEqual(candidate.PROTOCOL, E.PROTOCOL)
        self.assertEqual(base.PROTOCOL_ID, BASE.PROTOCOL_ID)

    def test_v2_baseline_reader_bridge(self):
        path, digest, layout_sha = self.v2_bridge_archive()
        left = REVIEW.read_baseline(path, digest, layout_sha)
        self.assertEqual(left["run"]["protocol"], REVIEW.V2_PROTOCOL)
        right = self.read(self.archive("self32"))
        # Synthetic helpers independently start their counters at 1.
        right["run"]["pid"] += 100
        report = REVIEW.compare_archives(E, BASE, left, right, "bridge")
        self.assertTrue(
            all(v["logits_bitwise_equal"] for v in report["by_model_condition"].values())
        )
        self.assertEqual(report["left_layout"], "v2_bridge16")
        self.assertFalse(report["full_run_authorized"])
        with self.assertRaisesRegex((ValueError, RuntimeError), "Layout SHA"):
            REVIEW.read_baseline(path, digest, "0" * 64)

    def test_v2_baseline_cannot_pair_with_full_layout(self):
        path, digest, layout_sha = self.v2_bridge_archive()
        left = REVIEW.read_baseline(path, digest, layout_sha)
        right = self.read(self.archive("full10k"))
        with self.assertRaisesRegex(ValueError, "Undeclared"):
            REVIEW.align_pair(E, left, right, "bridge")

    def test_full10k_archive_is_validated_as_full_run(self):
        a = self.read(self.archive("full10k"))
        self.assertEqual(a["verification"]["trials"], 10000)
        self.assertEqual(a["verification"]["model_condition_predictions"], 48000)
        self.assertEqual(a["run"]["trial_ids"], list(range(10000)))
        self.assertEqual(len(a["run"]["batches"]), 625)
        self.assertGreater(_FULL10K_CACHE["build_seconds"], 0.0)
        print(f"[rehearsal] synthetic full10k archive build+save: {_FULL10K_CACHE['build_seconds']:.1f}s", flush=True)
        # A truncated full archive must not pass as a full run.
        path, receipt, layout_sha = self.archive("full10k")
        results = (path / "results.csv").read_text().splitlines()
        (path / "results.csv").write_text("\n".join(results[:-1]) + "\n")
        with self.assertRaises((ValueError, RuntimeError, BASE.EvaluationError)):
            REVIEW.read_archive(E, BASE, path, receipt, layout_sha)

    def test_control_subset_cannot_change(self):
        a, b, kind = self.pair(*SUBSET)
        b["bank"].loc[0, "control_subset"] = 1 - int(b["bank"].loc[0, "control_subset"])
        with self.assertRaises((ValueError, AssertionError)):
            REVIEW.align_pair(E, a, b, kind)

    def test_nonfinite_arrays_rejected_before_statistics(self):
        a, b, kind = self.pair(*SUBSET)
        b["arrays"]["formal40__correct"][0, 0] = float("nan")
        with self.assertRaisesRegex(ValueError, "Invalid logits"):
            REVIEW.compare_archives(E, BASE, a, b, kind)

    def test_layout_boolean_or_extra_fields_rejected(self):
        for key, value in (("batch_size", True), ("unknown", "extra")):
            spec = E.layout_spec("self32")
            spec[key] = value
            digest = hashlib.sha256(E.layout_bytes(spec)).hexdigest()
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(RuntimeError, "fixed definition"),
            ):
                E.validate_layout(spec, digest)

    def test_frozen_layout_files_are_pinned_and_canonical(self):
        for name, digest in E.LAYOUT_SHAS.items():
            path = PACKAGE / "layouts" / f"{name}.json"
            self.assertEqual(E.sha256(path), digest)
            self.assertEqual(E.layout_bytes(E.layout_spec(name)), path.read_bytes())
        with self.assertRaisesRegex(RuntimeError, "Unknown layout"):
            E.layout_spec("conf256")
        self.assertEqual(
            E.layout_spec("full10k")["selection_record_sha256"],
            "d03404f2bca5aeb8a5d096b84f6ef758b6b07d0ee5efbd44ded59135bced0091",
        )
        self.assertIsNone(E.layout_spec("self32")["selection_record_sha256"])

    def test_all_four_disk_archives_recomputed(self):
        for layout, count in (("full10k", 10000), ("self32", 32)):
            with self.subTest(layout=layout):
                a = self.read(self.archive(layout))
                self.assertEqual(a["verification"]["trials"], count)
                self.assertEqual(
                    a["run"]["trial_ids"], E.layout_spec(layout)["trial_ids"]
                )

    def test_self_check_compares_by_identity_not_position(self):
        a, b, kind = self.pair(*SUBSET)
        report = REVIEW.compare_archives(E, BASE, a, b, kind)
        self.assertEqual(len(report["paired_nll_rows"]), 159)
        self.assertEqual(report["compared_trial_ids"], list(E.TRIAL_IDS))
        # Correct-cue rows are gated bitwise; control rows sit in different control
        # sub-batches inside the full run and are only enveloped (P06-2/P06-3).
        self.assertTrue(
            all(
                v["logits_bitwise_equal"]
                for k, v in report["by_model_condition"].items()
                if k.endswith("__correct")
            )
        )
        controls = {k: v for k, v in report["by_model_condition"].items() if not k.endswith("__correct")}
        self.assertTrue(REVIEW.envelope_check(dict(report, by_model_condition=controls))["within_envelope"])
        self.assertFalse(report["full_run_authorized"])
        self.assertEqual(report["scientific_qualification"], "NOT_DECIDED")

    def test_batch_report_signed_statistics(self):
        a, b, kind = self.pair(*SUBSET)
        report = REVIEW.compare_archives(E, BASE, a, b, kind)
        for value in report["by_model_condition"].values():
            self.assertAlmostEqual(
                value["nll_signed_left_minus_right"]["mean"], -value["mean_nll_change"]
            )
        json.dumps(report, allow_nan=False)

    def test_valid_numeric_change_is_diff_not_automatic_pass(self):
        a, b, kind = self.pair(*SUBSET, flip=True)
        report = REVIEW.compare_archives(E, BASE, a, b, kind)
        self.assertEqual(report["legacy_v4_result_table_canary_1e_6"]["status"], "DIFF")
        value = report["by_model_condition"]["formal40__correct"]
        self.assertEqual(value["prediction_flips"], 1)
        self.assertEqual(value["flips"][0]["trial_id"], E.TRIAL_IDS[0])
        self.assertFalse(report["full_run_authorized"])
        envelope = REVIEW.envelope_check(report)
        self.assertFalse(envelope["within_envelope"])
        self.assertEqual(envelope["exceeded"], ["formal40__correct"])

    def test_envelope_and_margin_strata_reporting(self):
        a, b, kind = self.pair(*SUBSET)
        report = REVIEW.compare_archives(E, BASE, a, b, kind)
        envelope = REVIEW.envelope_check(report)
        self.assertTrue(envelope["within_envelope"])
        correct = {k: v for k, v in report["by_model_condition"].items() if k.endswith("__correct")}
        self.assertEqual(REVIEW.envelope_check(dict(report, by_model_condition=correct))["max_nll_abs_diff"], 0.0)
        strata = REVIEW.margin_strata(E, a)
        self.assertEqual(strata["edges"], list(REVIEW.MARGIN_EDGES))
        value = strata["by_model_condition"]["formal40__correct"]
        self.assertEqual(value["trials"], 10000)
        self.assertEqual(
            value["within_envelope_le_low"]
            + value["between_low_and_high"]
            + value["above_high"],
            10000,
        )
        self.assertGreaterEqual(value["minimum_margin"], 0.0)
        json.dumps(strata, allow_nan=False)

    def test_shuffled_result_rows_align_without_modifying_input(self):
        a, b, kind = self.pair(*SUBSET)
        b["results"] = b["results"].iloc[::-1].reset_index(drop=True)
        original = b["results"].trial_id.tolist()
        x, y = REVIEW.align_pair(E, a, b, kind)
        self.assertEqual(x["results"].trial_id.tolist(), y["results"].trial_id.tolist())
        self.assertEqual(b["results"].trial_id.tolist(), original)

    def test_duplicate_missing_and_extra_result_rejected(self):
        a, b, kind = self.pair(*SUBSET)
        for mode in ("duplicate", "missing", "extra"):
            c = copy.deepcopy(b)
            if mode == "duplicate":
                c["results"].loc[0, "trial_id"] = c["results"].loc[1, "trial_id"]
            elif mode == "missing":
                c["results"] = c["results"].iloc[:-1]
            else:
                c["results"].loc[0, "trial_id"] = 999999
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                REVIEW.align_pair(E, a, c, kind)

    def test_wrong_control_cue_rejected(self):
        a, b, kind = self.pair(*SUBSET)
        b["pass"]["cue_hashes"]["shuffled"][0] = "0" * 64
        with self.assertRaisesRegex(ValueError, "cue identities"):
            REVIEW.align_pair(E, a, b, kind)

    def test_cue_inventory_and_length_rejected(self):
        a, b, kind = self.pair(*SUBSET)
        for mode in ("missing", "length"):
            c = copy.deepcopy(b)
            if mode == "missing":
                c["pass"]["cue_hashes"].pop("silent")
            else:
                c["pass"]["cue_hashes"]["silent"].pop()
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                REVIEW.align_pair(E, a, c, kind)

    def test_wrong_layout_sha_and_run_batch_rejected(self):
        artifact = self.archive()
        with self.assertRaisesRegex(RuntimeError, "Layout SHA"):
            self.read((*artifact[:2], "0" * 64))
        with self.assertRaisesRegex(RuntimeError, "batch mismatch"):
            self.read(self.archive(modify_run=lambda r: r.update(batch_size=1)))

    def test_declared_layout_cannot_be_resampled(self):
        spec = E.layout_spec("self32")
        spec["trial_ids"][-1] = E.TRIAL_IDS[16]
        digest = hashlib.sha256(E.layout_bytes(spec)).hexdigest()
        with self.assertRaisesRegex(RuntimeError, "fixed definition"):
            E.validate_layout(spec, digest)

    def test_full_layout_is_frozen_bank_order_without_tail(self):
        full = E.layout_spec("full10k")
        self.assertEqual(full["trial_ids"], list(range(10000)))
        self.assertEqual([len(b) for b in full["batches"]], [16] * 625)
        self.assertEqual(E.layout_spec("self32")["trial_ids"], list(E.TRIAL_IDS))
        selected = E.select_trials(self.fixture.full_bank, "full10k")
        self.assertEqual(int(selected.control_subset.sum()), 2000)
        self.assertEqual(int((selected.scene_kind == "clean").sum()), 1000)

    def test_wrong_comparison_pair_rejected(self):
        a, b, kind = self.pair(*SUBSET)
        for wrong in ("bridge", "subset-batch-size", "peers"):
            with self.subTest(kind=wrong), self.assertRaisesRegex(ValueError, "Undeclared"):
                REVIEW.align_pair(E, a, b, wrong)

    def test_same_process_rejected(self):
        a, b, kind = self.pair(*SUBSET)
        b["run"]["pid"] = a["run"]["pid"]
        with self.assertRaisesRegex(ValueError, "Same process"):
            REVIEW.align_pair(E, a, b, kind)

    def test_wrong_amp_and_missing_state_rejected(self):
        with self.assertRaisesRegex(ValueError, "eager FP32"):
            self.read(self.archive(modify_run=lambda r: r.update(amp=True)))
        with self.assertRaisesRegex(ValueError, "state check"):
            self.read(
                self.archive(
                    modify_details=lambda r: r.update(model_state_unchanged=False)
                )
            )

    def test_scientific_functions_ast_unchanged(self):
        import ast

        old = ast.parse(
            (
                ROOT / "same_bank_compare_2026_09_17_eager_v1/eager_compare.py"
            ).read_text()
        )
        new = ast.parse(Path(E.__file__).read_text())

        def functions(tree):
            return {
                n.name: ast.dump(n, include_attributes=False)
                for n in tree.body
                if isinstance(n, ast.FunctionDef)
            }

        old, new = functions(old), functions(new)
        for name in old.keys() - {
            "main",
            "run_small",
            "select_trials",
            "verify_receipt",
        }:
            with self.subTest(function=name):
                self.assertEqual(old[name], new[name])

    def test_old_sources_and_readers_preserved(self):
        for relative, digest in (
            (
                "same_bank_compare_2026_09_17_eager_v1/eager_compare.py",
                "d6f8380de33acee4dd448cd3135eab556a935e32d86598e422e3ace1d29bc3d4",
            ),
            (
                "same_bank_compare_2026_09_19_confirm_v2/eager_compare.py",
                REVIEW.V2_CANDIDATE_SHA,
            ),
            (
                "same_bank_compare_2026_09_19_confirm_v2/review_layouts.py",
                REVIEW.V2_REVIEW_SHA,
            ),
        ):
            with self.subTest(file=relative):
                self.assertEqual(E.sha256(ROOT / relative), digest)


if __name__ == "__main__":
    unittest.main()

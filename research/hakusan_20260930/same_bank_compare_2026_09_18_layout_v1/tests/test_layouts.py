"""Synthetic archive tests. Native declarations below are TEST DATA, not evidence.

The production checkpoint/GPU is never loaded. Fixtures use the existing tiny
disk-checkpoint/strict-load/forward path and are deleted after every test.
"""

import copy
import importlib.util
import json
from pathlib import Path
import unittest

import torch

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REVIEW = load(
    "archive_review_tests",
    ROOT / "same_bank_compare_2026_09_18_layout_v1/review_layouts.py",
)
FIXTURE = load(
    "candidate_fixture_tests",
    ROOT / "same_bank_compare_2026_09_18_layout_v1/tests/test_eager_compare.py",
)
E, BASE = FIXTURE.E, FIXTURE.BASE


class ReviewTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.fixture = FIXTURE.CandidateTests("test_exclusive_artifact_creation")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.counter = 0

    def archive(
        self, layout="bridge16", modify_run=None, modify_details=None, flip=False
    ):
        self.counter += 1
        output = self.fixture.root / f"archive-{self.counter}"
        output.mkdir()
        spec = E.layout_spec(layout)
        batch = spec["batch_size"]
        selected = E.select_trials(self.fixture.bank, layout)
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
            "pid": 1000 + self.counter,
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

    def test_pinned_core(self):
        candidate, base = REVIEW.load_core()
        self.assertEqual(candidate.PROTOCOL, E.PROTOCOL)
        self.assertEqual(base.PROTOCOL_ID, BASE.PROTOCOL_ID)

    def test_baseline_reader_bridge_and_cold1(self):
        old_fixture = load(
            "old_archive_fixture",
            ROOT / "checkpoint_compare_workflow_20260917/tests/test_review_runs.py",
        )
        helper = old_fixture.ReviewTests("test_pinned_core_load")
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        for batch, layout, kind in (
            (16, "bridge16", "bridge"),
            (1, "cold1", "cold-repeat"),
        ):
            with self.subTest(kind=kind):
                path, digest = helper.archive(batch=batch)
                left = REVIEW.read_baseline(path, digest)
                right = self.read(self.archive(layout))
                # Synthetic helpers independently start their counters at 1.
                # Distinct test process declarations, never production evidence.
                right["run"]["pid"] += 100
                report = REVIEW.compare_archives(E, BASE, left, right, kind)
                self.assertTrue(
                    all(
                        v["logits_bitwise_equal"]
                        for v in report["by_model_condition"].values()
                    )
                )
                self.assertFalse(report["full_run_authorized"])

    def test_control_subset_cannot_change(self):
        a, b = self.read(self.archive()), self.read(self.archive("peers16"))
        b["bank"].loc[0, "control_subset"] = 1
        with self.assertRaises((ValueError, AssertionError)):
            REVIEW.align_pair(E, a, b, "peers")

    def test_nonfinite_arrays_rejected_before_statistics(self):
        a, b = self.read(self.archive()), self.read(self.archive("tail17"))
        b["arrays"]["formal40__correct"][0, 0] = float("nan")
        with self.assertRaisesRegex(ValueError, "Invalid logits"):
            REVIEW.compare_archives(E, BASE, a, b, "tail")

    def test_layout_boolean_or_extra_fields_rejected(self):
        import hashlib

        for key, value in (("batch_size", True), ("unknown", "extra")):
            spec = E.layout_spec("cold1")
            spec[key] = value
            digest = hashlib.sha256(E.layout_bytes(spec)).hexdigest()
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(RuntimeError, "fixed definition"),
            ):
                E.validate_layout(spec, digest)

    def test_all_four_disk_archives_recomputed(self):
        for layout, count in (
            ("bridge16", 32),
            ("cold1", 32),
            ("peers16", 32),
            ("tail17", 17),
        ):
            with self.subTest(layout=layout):
                a = self.read(self.archive(layout))
                self.assertEqual(a["verification"]["trials"], count)
                self.assertEqual(
                    a["run"]["trial_ids"], E.layout_spec(layout)["trial_ids"]
                )

    def test_peers_compare_by_identity_not_position(self):
        a, b = self.read(self.archive()), self.read(self.archive("peers16"))
        report = REVIEW.compare_archives(E, BASE, a, b, "peers")
        self.assertEqual(len(report["paired_nll_rows"]), 159)
        self.assertFalse(report["full_run_authorized"])
        self.assertEqual(report["scientific_qualification"], "NOT_DECIDED")
        self.assertTrue(
            all(
                v["prediction_flips"] == 0
                for v in report["by_model_condition"].values()
            )
        )
        self.assertEqual(b["run"]["trial_ids"], E.layout_spec("peers16")["trial_ids"])

    def test_tail_is_exact_subset_and_reports_no_padding(self):
        a, b = self.read(self.archive()), self.read(self.archive("tail17"))
        report = REVIEW.compare_archives(E, BASE, a, b, "tail")
        self.assertEqual(
            report["compared_trial_ids"], list(E.TRIAL_IDS[:16]) + [E.TRIAL_IDS[31]]
        )
        self.assertEqual([len(x) for x in b["run"]["batches"]], [16, 1])
        self.assertEqual(len(report["paired_nll_rows"]), 3 * (17 + 3 * 5))

    def test_batch_report_signed_statistics(self):
        a, b = self.read(self.archive()), self.read(self.archive("cold1"))
        report = REVIEW.compare_archives(E, BASE, a, b, "batch-size")
        for value in report["by_model_condition"].values():
            self.assertAlmostEqual(
                value["nll_signed_left_minus_right"]["mean"], -value["mean_nll_change"]
            )
        json.dumps(report, allow_nan=False)

    def test_valid_numeric_change_is_diff_not_automatic_pass(self):
        a = self.read(self.archive())
        b = self.read(self.archive("tail17", flip=True))
        report = REVIEW.compare_archives(E, BASE, a, b, "tail")
        self.assertEqual(report["legacy_v4_result_table_canary_1e_6"]["status"], "DIFF")
        value = report["by_model_condition"]["formal40__correct"]
        self.assertEqual(value["prediction_flips"], 1)
        self.assertEqual(value["flips"][0]["trial_id"], E.TRIAL_IDS[0])
        self.assertFalse(report["full_run_authorized"])

    def test_shuffled_result_rows_align_without_modifying_input(self):
        a, b = self.read(self.archive()), self.read(self.archive("peers16"))
        b["results"] = b["results"].iloc[::-1].reset_index(drop=True)
        original = b["results"].trial_id.tolist()
        x, y = REVIEW.align_pair(E, a, b, "peers")
        self.assertEqual(x["results"].trial_id.tolist(), y["results"].trial_id.tolist())
        self.assertEqual(b["results"].trial_id.tolist(), original)

    def test_duplicate_missing_and_extra_result_rejected(self):
        a, b = self.read(self.archive()), self.read(self.archive("peers16"))
        for mode in ("duplicate", "missing", "extra"):
            c = copy.deepcopy(b)
            if mode == "duplicate":
                c["results"].loc[0, "trial_id"] = c["results"].loc[1, "trial_id"]
            elif mode == "missing":
                c["results"] = c["results"].iloc[:-1]
            else:
                c["results"].loc[0, "trial_id"] = 999999
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                REVIEW.align_pair(E, a, c, "peers")

    def test_wrong_control_cue_rejected(self):
        a, b = self.read(self.archive()), self.read(self.archive("peers16"))
        b["pass"]["cue_hashes"]["shuffled"][0] = "0" * 64
        with self.assertRaisesRegex(ValueError, "cue identities"):
            REVIEW.align_pair(E, a, b, "peers")

    def test_cue_inventory_and_length_rejected(self):
        a, b = self.read(self.archive()), self.read(self.archive("tail17"))
        for mode in ("missing", "length"):
            c = copy.deepcopy(b)
            if mode == "missing":
                c["pass"]["cue_hashes"].pop("silent")
            else:
                c["pass"]["cue_hashes"]["silent"].pop()
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                REVIEW.align_pair(E, a, c, "tail")

    def test_wrong_layout_sha_and_run_batch_rejected(self):
        artifact = self.archive()
        with self.assertRaisesRegex(RuntimeError, "Layout SHA"):
            self.read((*artifact[:2], "0" * 64))
        with self.assertRaisesRegex(RuntimeError, "batch mismatch"):
            self.read(self.archive(modify_run=lambda r: r.update(batch_size=1)))

    def test_declared_layout_cannot_be_resampled(self):
        import hashlib

        spec = E.layout_spec("tail17")
        spec["trial_ids"][-1] = E.TRIAL_IDS[16]
        digest = hashlib.sha256(E.layout_bytes(spec)).hexdigest()
        with self.assertRaisesRegex(RuntimeError, "fixed definition"):
            E.validate_layout(spec, digest)

    def test_layout_really_changes_companions(self):
        original = E.layout_spec("bridge16")["batches"]
        peers = E.layout_spec("peers16")["batches"]
        self.assertNotEqual(set(original[0]), set(peers[0]))
        self.assertEqual(
            peers[0][:4],
            [E.TRIAL_IDS[0], E.TRIAL_IDS[16], E.TRIAL_IDS[1], E.TRIAL_IDS[17]],
        )
        self.assertEqual(set(sum(peers, [])), set(E.TRIAL_IDS))

    def test_wrong_comparison_pair_rejected(self):
        a, b = self.read(self.archive()), self.read(self.archive("peers16"))
        with self.assertRaisesRegex(ValueError, "Undeclared"):
            REVIEW.align_pair(E, a, b, "cold-repeat")

    def test_same_process_rejected(self):
        a, b = self.read(self.archive()), self.read(self.archive("peers16"))
        b["run"]["pid"] = a["run"]["pid"]
        with self.assertRaisesRegex(ValueError, "Same process"):
            REVIEW.align_pair(E, a, b, "peers")

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

    def test_old_source_and_reader_preserved(self):
        self.assertEqual(
            E.sha256(ROOT / "same_bank_compare_2026_09_17_eager_v1/eager_compare.py"),
            "d6f8380de33acee4dd448cd3135eab556a935e32d86598e422e3ace1d29bc3d4",
        )
        self.assertEqual(
            E.sha256(ROOT / "checkpoint_compare_workflow_20260917/review_runs.py"),
            "49076fd6d9436ba2af2179cdb376836e263e72079197c0a4fa618c6f6c06fd95",
        )


if __name__ == "__main__":
    unittest.main()

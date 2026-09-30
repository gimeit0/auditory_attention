"""In-memory SYNTHETIC v19 manifests, never a real freeze or deployment claim."""
import copy
import json
import unittest
from unittest import mock

import freeze_relation as relation


class FreezeRelationTests(unittest.TestCase):
    def setUp(self):
        self.parent = json.loads(relation.PARENT.read_bytes())
        self.value = copy.deepcopy(self.parent)
        self.value["diagnostic_protocol"] = relation.PROTOCOL
        self.value["roots"]["diagnostic_root"] = relation.REMOTE
        for record in self.value["production_files"]:
            raw = (relation.LOCAL / record["relative_path"]).read_bytes()
            record.update(size=len(raw), sha256=relation.sha(raw), mode=0o600, st_dev=1, st_ino=1, st_mtime_ns=1)

    def verify(self, value=None):
        raw = relation.canonical(self.value if value is None else value)
        return relation.verify(raw, relation.sha(raw))

    def test_synthetic_new_code_same_science_relation_only(self):
        result = self.verify()
        self.assertEqual(result["status"], "SCIENTIFIC_INPUT_RELATION_PASS")
        self.assertTrue(result["parent_is_data_reference_only"])
        self.assertFalse(result["production_live_inputs_verified"])
        self.assertFalse(result["ready_for_gpu"])

    def test_old_freeze_not_new_authority(self):
        with self.assertRaises(ValueError):
            relation.verify(relation.PARENT.read_bytes(), relation.PARENT_SHA)

    def test_wrong_expected_sha_rejected(self):
        with self.assertRaisesRegex(ValueError, "SHA differs"):
            relation.verify(relation.canonical(self.value), "a" * 64)

    def test_unreviewed_sha_format_rejected(self):
        for value in (None, "", "UNFROZEN", "A" * 64):
            with self.subTest(value=value), self.assertRaises(ValueError):
                relation.verify(relation.canonical(self.value), value)

    def test_pretty_json_rejected_even_if_hash_matches(self):
        raw = json.dumps(self.value, indent=2).encode()
        with self.assertRaisesRegex(ValueError, "canonical"):
            relation.verify(raw, relation.sha(raw))

    def test_duplicate_key_rejected(self):
        raw = b'{"x":1,"x":1}\n'
        with self.assertRaisesRegex(ValueError, "duplicate"):
            relation.verify(raw, relation.sha(raw))

    def test_changed_trial_or_order_rejected(self):
        for change in ("label", "order"):
            value = copy.deepcopy(self.value)
            if change == "label":
                value["trials"][0]["identity"]["target_label"] += 1
            else:
                value["trials"].reverse()
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "scientific inputs"):
                self.verify(value)

    def test_changed_checkpoint_bank_clip_or_snapshot_rejected(self):
        for collection in ("clip", "snapshot", "checkpoint", "bank"):
            value = copy.deepcopy(self.value)
            if collection in ("clip", "snapshot"):
                value["clips" if collection == "clip" else "snapshot_files"][0]["sha256"] = "b" * 64
            else:
                value["v4"]["verified_pinned_files"][18 if collection == "checkpoint" else 1]["sha256"] = "b" * 64
            with self.subTest(collection=collection), self.assertRaisesRegex(ValueError, "scientific inputs"):
                self.verify(value)

    def test_old_production_files_not_accepted(self):
        self.value["production_files"] = self.parent["production_files"]
        with self.assertRaisesRegex(ValueError, "new release"):
            self.verify()

    def test_production_duplicate_or_missing_rejected(self):
        for value in (self.value["production_files"][:3], [self.value["production_files"][0]] * 4):
            changed = {**self.value, "production_files": value}
            with self.subTest(length=len(value)), self.assertRaises(ValueError):
                self.verify(changed)

    def test_input_modes_and_uses_are_not_ignored(self):
        for key in ("mode", "uses"):
            value = copy.deepcopy(self.value)
            value["clips"][0][key] = 0 if key == "mode" else []
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "scientific inputs"):
                self.verify(value)

    def test_only_nfs_identity_diagnostics_may_differ(self):
        for name in ("clips", "snapshot_files"):
            for record in self.value[name]:
                for key in relation.IDENTITY:
                    record[key] += 1
        self.assertEqual(self.verify()["status"], "SCIENTIFIC_INPUT_RELATION_PASS")

    def test_invalid_metadata_not_ignored(self):
        self.value["clips"][0]["st_ino"] = True
        with self.assertRaisesRegex(ValueError, "metadata"):
            self.verify()

    def test_extra_contract_field_rejected(self):
        self.value["relax_tolerance"] = True
        with self.assertRaisesRegex(ValueError, "scientific inputs"):
            self.verify()

    def test_changed_source_manifest_rejected(self):
        original = relation.Path.read_bytes
        def changed(path):
            raw = original(path)
            return raw + b" " if path == relation.HERE / "SOURCE_MANIFEST.json" else raw
        with mock.patch.object(relation.Path, "read_bytes", changed):
            with self.assertRaisesRegex(ValueError, "reviewed source manifest"):
                self.verify()


if __name__ == "__main__":
    unittest.main()

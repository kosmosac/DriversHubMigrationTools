import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from drivershub_migration.user_state_import import build_user_state_stage


class UserStateImportTests(unittest.TestCase):
    def test_build_user_state_stage(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            (normalized / "profiles.json").write_text(json.dumps({"records": [{
                "uid": 7, "global_note": "global", "note": "private",
                "role_history": [{"historyid": 4, "added_roles": [20], "removed_roles": [], "timestamp": 1700000000}],
                "ban_history": [{"historyid": 5, "reason": "old", "expire_timestamp": 1700000100}],
            }]}))
            (normalized / "bans.json").write_text(json.dumps({"records": []}))
            sql, summary = build_user_state_stage(directory)
        self.assertIn("INSERT INTO `user_role_history`", sql)
        self.assertIn("INSERT INTO `ban_history`", sql)
        self.assertIn("VALUES (-1000,7", sql)
        self.assertEqual(summary["personal_notes_skipped"], 1)
        self.assertEqual(summary["role_history_records"], 1)

    def test_converts_personal_note_to_global_when_explicitly_enabled(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            (normalized / "profiles.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "uid": 7,
                                "global_note": "existing global",
                                "note": "personal note",
                            }
                        ]
                    }
                )
            )
            (normalized / "bans.json").write_text(json.dumps({"records": []}))
            sql, summary = build_user_state_stage(
                directory, convert_personal_notes_to_global=True
            )

        self.assertIn("4d6967726174656420706572736f6e616c2061646d696e6973747261746f72206e6f7465", sql)
        self.assertEqual(summary["global_notes"], 1)
        self.assertEqual(summary["personal_notes_converted"], 1)
        self.assertEqual(summary["personal_notes_skipped"], 0)

    def test_replaces_preexisting_state_for_matched_destination_accounts(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            (normalized / "profiles.json").write_text(json.dumps({"records": []}))
            (normalized / "bans.json").write_text(json.dumps({"records": []}))
            (directory / "target-preflight.json").write_text(
                json.dumps(
                    {
                        "bootstrap": {
                            "state": "ready",
                            "action": "merge-matching-destination-accounts",
                        }
                    }
                )
            )
            sql, summary = build_user_state_stage(directory)

        self.assertIn("DELETE FROM `user_note`;", sql)
        self.assertIn("DELETE FROM `user_role_history`;", sql)
        self.assertIn("DELETE FROM `banned`;", sql)
        self.assertIn("DELETE FROM `ban_history`;", sql)
        self.assertTrue(summary["replaced_destination_user_state"])

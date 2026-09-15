import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from drivershub_migration.import_plan import create_import_plan


class ImportPlanTests(unittest.TestCase):
    def _write_profiles(self, directory, records):
        normalized = directory / "normalized"
        normalized.mkdir()
        (normalized / "profiles.json").write_text(
            json.dumps({"format_version": 1, "resource": "profiles", "records": records})
        )

    @patch("drivershub_migration.import_plan.verify_export")
    @patch("drivershub_migration.import_plan.create_configuration_plan")
    def test_creates_claim_plan_and_allows_repeated_pending_userid(self, configuration, verify):
        verify.return_value = {"integrity": "valid", "export": "complete"}
        configuration.return_value = {
            "state": "complete",
            "backend": {"portable": {"perms": {"administrator": [20]}}},
        }
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._write_profiles(
                directory,
                [
                    {"uid": 1, "userid": -1, "name": "One", "steamid": "123", "roles": [20]},
                    {"uid": 2, "userid": -1, "name": "Two", "discordid": "456"},
                    {"uid": 3, "userid": 7, "name": "Three", "email": "three@example.com"},
                    {"uid": 4, "userid": 8, "name": "Four"},
                    {"uid": 5, "userid": None, "name": "Five", "steamid": "789"},
                ],
            )
            result = create_import_plan(directory)
            self.assertEqual(result["state"], "complete")
            self.assertEqual(result["summary"]["claimable"], 4)
            self.assertEqual(result["summary"]["manual_recovery_required"], 1)
            self.assertEqual(result["accounts"][0]["target_uid"], 1)
            self.assertEqual(result["accounts"][0]["claim_methods"], ["steam"])
            self.assertTrue(result["accounts"][0]["is_administrator"])
            self.assertEqual(result["summary"]["administrators"], 1)
            self.assertEqual(result["accounts"][2]["claim_methods"], ["email"])
            self.assertIsNone(result["accounts"][4]["target_userid"])

    @patch("drivershub_migration.import_plan.verify_export")
    @patch("drivershub_migration.import_plan.create_configuration_plan")
    def test_blocks_duplicate_claim_identity(self, configuration, verify):
        verify.return_value = {"integrity": "valid", "export": "complete"}
        configuration.return_value = {"state": "complete"}
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._write_profiles(
                directory,
                [
                    {"uid": 1, "userid": 1, "steamid": "123"},
                    {"uid": 2, "userid": 2, "steamid": "123"},
                ],
            )
            result = create_import_plan(directory)
            self.assertEqual(result["state"], "blocked")
            self.assertEqual(result["conflicts"][0]["field"], "steamid")

    @patch("drivershub_migration.import_plan.verify_export")
    @patch("drivershub_migration.import_plan.create_configuration_plan")
    def test_blocks_duplicate_email_case_insensitively(self, configuration, verify):
        verify.return_value = {"integrity": "valid", "export": "complete"}
        configuration.return_value = {"state": "complete"}
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._write_profiles(
                directory,
                [
                    {"uid": 1, "userid": 1, "email": "User@example.com"},
                    {"uid": 2, "userid": 2, "email": "user@example.com"},
                ],
            )
            result = create_import_plan(directory)
            self.assertEqual(result["state"], "blocked")
            self.assertEqual(result["conflicts"][0]["field"], "email")


if __name__ == "__main__":
    unittest.main()

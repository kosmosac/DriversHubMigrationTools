import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from drivershub_migration.target import preflight_target


class TargetPreflightTests(unittest.TestCase):
    @patch("drivershub_migration.target.create_import_plan")
    def test_reports_existing_accounts_and_id_collisions(self, create_plan):
        create_plan.return_value = {
            "state": "complete",
            "accounts": [
                {
                    "source_uid": 1,
                    "target_uid": 1,
                    "target_userid": 9,
                    "is_administrator": True,
                    "email": "owner@example.com",
                    "steamid": None,
                    "discordid": None,
                }
            ],
        }
        with TemporaryDirectory() as migration_temp, TemporaryDirectory() as target_temp:
            migration = Path(migration_temp)
            target = Path(target_temp)
            (target / "compose.yaml").write_text("services: {}\n")
            (target / ".env").write_text("DB_PASSWORD=test\n")

            def runner(*args, **kwargs):
                return subprocess.CompletedProcess(
                    args[0],
                    0,
                    stdout=json.dumps({"uid": 7, "userid": 9, "name": "Bootstrap"}) + "\n",
                    stderr="",
                )

            result = preflight_target(migration, target, runner=runner)
            self.assertEqual(result["state"], "action-required")
            self.assertEqual(result["collisions"][0]["fields"], ["userid"])
            self.assertEqual(result["bootstrap"]["action"], "retain-as-recovery-account")
            self.assertEqual(result["bootstrap"]["replacement_uid"], 8)
            self.assertEqual(result["bootstrap"]["replacement_userid"], 10)
            self.assertTrue((migration / "target-preflight.json").is_file())

    @patch("drivershub_migration.target.create_import_plan")
    def test_matches_single_bootstrap_to_source_administrator(self, create_plan):
        create_plan.return_value = {
            "state": "complete",
            "accounts": [
                {
                    "source_uid": 12,
                    "target_uid": 12,
                    "target_userid": 34,
                    "is_administrator": True,
                    "email": "owner@example.com",
                    "steamid": 123,
                    "discordid": None,
                }
            ],
        }
        with TemporaryDirectory() as migration_temp, TemporaryDirectory() as target_temp:
            migration = Path(migration_temp)
            target = Path(target_temp)
            (target / "compose.yaml").write_text("services: {}\n")
            (target / ".env").write_text("DB_PASSWORD=test\n")

            def runner(*args, **kwargs):
                return subprocess.CompletedProcess(
                    args[0],
                    0,
                    stdout=json.dumps(
                        {
                            "uid": 1,
                            "userid": 1,
                            "email": "OWNER@example.com",
                            "steamid": 123,
                        }
                    )
                    + "\n",
                    stderr="",
                )

            result = preflight_target(migration, target, runner=runner)
            self.assertEqual(
                result["bootstrap"]["action"],
                "merge-with-source-administrator",
            )
            self.assertEqual(result["bootstrap"]["source_uid"], 12)
            self.assertEqual(result["bootstrap"]["matched_by"], ["email", "steamid"])

    @patch("drivershub_migration.target._read_mariadb_accounts")
    @patch("drivershub_migration.target.create_import_plan")
    def test_supports_direct_mariadb_target(self, create_plan, read_accounts):
        create_plan.return_value = {
            "state": "complete",
            "accounts": [
                {"target_uid": 1, "target_userid": 1},
                {
                    "source_uid": 2,
                    "target_uid": 2,
                    "target_userid": None,
                    "is_administrator": False,
                },
            ],
        }
        read_accounts.return_value = []
        with TemporaryDirectory() as migration_temp:
            result = preflight_target(
                Path(migration_temp),
                mode="mariadb",
                database={"host": "db", "user": "hub", "database": "hub"},
            )
            self.assertEqual(result["state"], "complete")
            self.assertEqual(result["target_mode"], "mariadb")
            read_accounts.assert_called_once()


if __name__ == "__main__":
    unittest.main()

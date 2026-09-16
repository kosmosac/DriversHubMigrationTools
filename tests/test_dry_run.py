import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from drivershub_migration.dry_run import create_import_dry_run


class ImportDryRunTests(unittest.TestCase):
    @patch("drivershub_migration.dry_run.validate_import", return_value={"state": "ready", "committed_writes": 0})
    @patch("drivershub_migration.dry_run.preflight_target")
    def test_plans_placeholder_deliveries_without_target_writes(self, preflight, validate):
        preflight.return_value = {
            "state": "action-required",
            "bootstrap": {
                "state": "ready",
                "action": "retain-as-recovery-account",
            },
        }
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "import-plan.json").write_text(
                json.dumps(
                    {
                        "state": "complete",
                        "summary": {"accounts": 3, "administrators": 1},
                        "configuration": {
                            "state": "complete",
                            "backend": {
                                "portable": {"name": "Example"},
                                "protected": {"smtp_password": {}},
                            },
                            "branding": {"logo": {"state": "ready"}},
                        },
                    }
                )
            )
            (directory / "export.json").write_text(
                json.dumps(
                    {
                        "resources": {"profiles": {"state": "complete", "items": 3}},
                        "plugin_resources": {},
                        "deliveries": {
                            "csv": {
                                "state": "complete",
                                "items": 10,
                                "path": "raw/deliveries/export.csv",
                            },
                            "list": {
                                "state": "complete",
                                "items": 9,
                                "path": "normalized/deliveries.json",
                            },
                            "details": {"state": "skipped"},
                        },
                    }
                )
            )
            (directory / "normalized").mkdir()
            (directory / "raw" / "deliveries").mkdir(parents=True)
            (directory / "raw" / "deliveries" / "export.csv").write_text(
                "logid,time_submitted\n"
                + "".join(
                    f"{logid},2023-11-14 00:00:00\n" for logid in range(9)
                )
            )
            (directory / "normalized" / "deliveries.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {"logid": logid, "timestamp": 1_700_000_000 + logid}
                            for logid in range(9)
                        ]
                    }
                )
            )

            result = create_import_dry_run(directory, Path("/target"))

            self.assertEqual(result["state"], "ready")
            self.assertFalse(result["target_modified"])
            self.assertEqual(result["writes"], 0)
            self.assertEqual(result["stages"]["deliveries"]["placeholder_items"], 9)
            self.assertEqual(
                result["stages"]["deliveries"]["detail_strategy"],
                "frontend-placeholders-with-optional-backfill",
            )
            timestamp_policy = result["stages"]["deliveries"]["timestamp_policy"]
            self.assertEqual(timestamp_policy["state"], "ready")
            self.assertEqual(
                timestamp_policy["source"],
                "normalized/deliveries.json:timestamp",
            )
            self.assertEqual(timestamp_policy["csv_time_submitted"], "display-only")
            self.assertEqual(timestamp_policy["naive_datetime_conversion"], "forbidden")
            self.assertEqual(timestamp_policy["validated_records"], 9)
            self.assertEqual(timestamp_policy["covered_csv_logids"], 9)
            self.assertTrue((directory / "import-dry-run.json").is_file())

    @patch("drivershub_migration.dry_run.preflight_target")
    def test_blocks_delivery_import_without_numeric_timestamp_source(self, preflight):
        preflight.return_value = {
            "state": "ready",
            "bootstrap": {"state": "not-required"},
        }
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "import-plan.json").write_text(
                json.dumps(
                    {
                        "state": "complete",
                        "summary": {},
                        "configuration": {
                            "state": "complete",
                            "backend": {},
                            "branding": {},
                        },
                    }
                )
            )
            (directory / "export.json").write_text(
                json.dumps(
                    {
                        "resources": {},
                        "plugin_resources": {},
                        "deliveries": {
                            "csv": {"state": "complete", "items": 1},
                            "list": {"state": "skipped"},
                            "details": {"state": "skipped"},
                        },
                    }
                )
            )

            result = create_import_dry_run(directory, Path("/target"))

            deliveries = result["stages"]["deliveries"]
            self.assertEqual(deliveries["state"], "blocked")
            self.assertEqual(deliveries["timestamp_policy"]["state"], "blocked")

    @patch("drivershub_migration.dry_run.preflight_target")
    def test_blocks_naive_delivery_timestamp(self, preflight):
        preflight.return_value = {
            "state": "ready",
            "bootstrap": {"state": "not-required"},
        }
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "normalized").mkdir()
            (directory / "raw" / "deliveries").mkdir(parents=True)
            (directory / "raw" / "deliveries" / "export.csv").write_text(
                "logid,time_submitted\n1,2026-09-15 12:00:00\n"
            )
            (directory / "normalized" / "deliveries.json").write_text(
                json.dumps(
                    {"records": [{"logid": 1, "timestamp": "2026-09-15 12:00:00"}]}
                )
            )
            (directory / "import-plan.json").write_text(
                json.dumps(
                    {
                        "state": "complete",
                        "summary": {},
                        "configuration": {
                            "state": "complete",
                            "backend": {},
                            "branding": {},
                        },
                    }
                )
            )
            (directory / "export.json").write_text(
                json.dumps(
                    {
                        "resources": {},
                        "plugin_resources": {},
                        "deliveries": {
                            "csv": {
                                "state": "complete",
                                "items": 1,
                                "path": "raw/deliveries/export.csv",
                            },
                            "list": {
                                "state": "complete",
                                "items": 1,
                                "path": "normalized/deliveries.json",
                            },
                            "details": {"state": "skipped"},
                        },
                    }
                )
            )

            result = create_import_dry_run(directory, Path("/target"))

            self.assertEqual(result["state"], "blocked")
            policy = result["stages"]["deliveries"]["timestamp_policy"]
            self.assertEqual(policy["state"], "blocked")
            self.assertIn("Unix-seconds", policy["error"])


if __name__ == "__main__":
    unittest.main()

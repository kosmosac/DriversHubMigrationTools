import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from drivershub_migration.dry_run import create_import_dry_run


class ImportDryRunTests(unittest.TestCase):
    @patch("drivershub_migration.dry_run.preflight_target")
    def test_plans_placeholder_deliveries_without_target_writes(self, preflight):
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
                            "csv": {"state": "complete", "items": 10},
                            "list": {"state": "complete", "items": 9},
                            "details": {"state": "skipped"},
                        },
                    }
                )
            )

            result = create_import_dry_run(directory, Path("/target"))

            self.assertEqual(result["state"], "ready")
            self.assertFalse(result["target_modified"])
            self.assertEqual(result["writes"], 0)
            self.assertEqual(result["stages"]["deliveries"]["placeholder_items"], 10)
            self.assertEqual(
                result["stages"]["deliveries"]["detail_strategy"],
                "schema-placeholders-with-optional-backfill",
            )
            self.assertTrue((directory / "import-dry-run.json").is_file())


if __name__ == "__main__":
    unittest.main()

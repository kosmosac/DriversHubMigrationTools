import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from drivershub_migration.workflows import export_all, import_all


class WorkflowTests(unittest.TestCase):
    @patch("drivershub_migration.workflows.verify_export")
    @patch("drivershub_migration.workflows.export_source")
    def test_export_all_exports_then_verifies(self, export_source, verify_export):
        verify_export.return_value = {
            "integrity": "valid", "export": "complete", "checked_files": 4
        }
        result = export_all(
            "https://hub.example/api/", Path("migration"), "token",
            request_interval=1.1, export_delivery_details=False,
        )
        self.assertEqual(result["state"], "complete")
        export_source.assert_called_once()
        verify_export.assert_called_once_with(Path("migration"))

    @patch("drivershub_migration.workflows.verify_target", return_value={"state": "complete"})
    @patch("drivershub_migration.workflows.import_relationships")
    @patch("drivershub_migration.workflows.import_deliveries")
    @patch("drivershub_migration.workflows.import_economy_inventory")
    @patch("drivershub_migration.workflows.import_economy")
    @patch("drivershub_migration.workflows.import_polls_tasks")
    @patch("drivershub_migration.workflows.import_events_challenges")
    @patch("drivershub_migration.workflows.import_applications")
    @patch("drivershub_migration.workflows.import_content")
    @patch("drivershub_migration.workflows.import_user_state")
    @patch("drivershub_migration.workflows.import_configuration")
    @patch("drivershub_migration.workflows.import_accounts")
    @patch("drivershub_migration.workflows.create_import_dry_run", return_value={"state": "ready"})
    @patch("drivershub_migration.workflows.create_import_plan", return_value={"state": "complete"})
    def test_import_all_runs_complete_ordered_workflow(
        self, plan, dry_run, accounts, configuration, user_state, content,
        applications, events, polls, economy, inventory, deliveries,
        relationships, verify,
    ):
        with TemporaryDirectory() as temporary:
            result = import_all(
                Path(temporary), Path("/target"), mode="aio", database={},
                config_path=None, backup_confirmed=True, writers_stopped=False,
                convert_personal_notes=False,
            )
        self.assertEqual(result["state"], "complete")
        plan.assert_called_once()
        dry_run.assert_called_once()
        accounts.assert_called_once()
        configuration.assert_called_once()
        relationships.assert_called_once()
        verify.assert_called_once()

    @patch("drivershub_migration.workflows.verify_target", return_value={"state": "complete"})
    @patch("drivershub_migration.workflows.create_import_dry_run")
    def test_import_all_resumes_completed_journal_without_dry_run(self, dry_run, verify):
        stages = {
            name: {"state": "complete"}
            for name in (
                "accounts", "configuration", "user_state", "content",
                "applications", "events_challenges", "polls_tasks", "economy",
                "economy_inventory", "deliveries", "relationships",
            )
        }
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "import-journal.json").write_text(json.dumps({"stages": stages}))
            result = import_all(
                directory, Path("/target"), mode="aio", database={},
                config_path=None, backup_confirmed=False, writers_stopped=False,
                convert_personal_notes=False,
            )
        self.assertEqual(result["state"], "complete")
        dry_run.assert_not_called()
        verify.assert_called_once()


if __name__ == "__main__":
    unittest.main()

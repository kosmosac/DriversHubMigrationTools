from pathlib import Path
import unittest

from drivershub_migration.output import (
    render_import_dry_run,
    render_import_plan,
    render_target_preflight,
    render_verification,
)


class HumanOutputTests(unittest.TestCase):
    def test_dry_run_reports_placeholders_and_no_writes(self):
        text = render_import_dry_run(
            {
                "state": "ready",
                "bootstrap": {"action": "retain-as-recovery-account"},
                "stages": {
                    "configuration": {
                        "portable_backend_values": 4,
                        "protected_destination_values": ["smtp_password"],
                        "branding_assets": 3,
                    },
                    "accounts": {"items": 3},
                    "core_resources": {"profiles": 3},
                    "plugin_resources": {},
                    "economy": {},
                    "deliveries": {
                        "baseline_items": 10,
                        "placeholder_items": 10,
                        "timestamp_policy": {"state": "ready"},
                    },
                },
            },
            Path("migrations/example"),
        )
        self.assertIn("Import dry run ready.", text)
        self.assertIn("Target modified: no", text)
        self.assertIn("Deliveries using placeholders: 10", text)
        self.assertIn("Delivery timestamps: verified Unix seconds", text)

    def test_verification_includes_result_and_next_step(self):
        text = render_verification(
            {
                "integrity": "valid",
                "export": "complete",
                "checked_files": 25,
                "export_issues": {},
                "failures": [],
            }
        )
        self.assertIn("Export verification passed.", text)
        self.assertIn("Checked files: 25", text)
        self.assertIn("plan-import", text)

    def test_import_plan_does_not_render_account_details(self):
        text = render_import_plan(
            {
                "state": "complete",
                "summary": {
                    "accounts": 436,
                    "administrators": 22,
                    "claimable": 436,
                    "manual_recovery_required": 0,
                    "conflicts": 0,
                },
                "configuration": {"state": "complete"},
                "accounts": [{"email": "private@example.com"}],
            },
            Path("migrations/example"),
        )
        self.assertIn("Accounts: 436", text)
        self.assertNotIn("private@example.com", text)
        self.assertIn("preflight-target", text)

    def test_target_preflight_explains_bootstrap_review(self):
        text = render_target_preflight(
            {
                "state": "action-required",
                "target_mode": "aio",
                "source_accounts": 3,
                "target_accounts": [{"uid": 1}],
                "collisions": [{"fields": ["uid"]}],
                "bootstrap": {
                    "state": "ready",
                    "action": "retain-as-recovery-account",
                    "original_uid": 1,
                    "replacement_uid": 1900,
                    "original_userid": 1,
                    "replacement_userid": 1493,
                },
            }
        )
        self.assertIn("Bootstrap action: retain-as-recovery-account", text)
        self.assertIn("Recovery UID: 1 -> 1900", text)
        self.assertIn("Recovery member ID: 1 -> 1493", text)
        self.assertIn("run drivershub-migrate dry-run-import", text)
        self.assertIn("import-accounts --approve", text)

    def test_target_conflict_explains_that_no_override_exists(self):
        text = render_target_preflight(
            {
                "state": "action-required",
                "target_mode": "aio",
                "source_accounts": 3,
                "target_accounts": [{"uid": 1}, {"uid": 2}],
                "collisions": [],
                "bootstrap": {
                    "state": "manual-decision-required",
                    "conflicts": [{"target_uid": 2}],
                },
            }
        )
        self.assertIn("Import cannot continue", text)
        self.assertIn("No manual mapping override is supported", text)
        self.assertIn("run drivershub-migrate preflight-target again", text)


if __name__ == "__main__":
    unittest.main()

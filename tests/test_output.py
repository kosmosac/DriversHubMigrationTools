from pathlib import Path
import unittest

from drivershub_migration.output import (
    render_import_plan,
    render_target_preflight,
    render_verification,
)


class HumanOutputTests(unittest.TestCase):
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
                },
            }
        )
        self.assertIn("Bootstrap action: retain-as-recovery-account", text)
        self.assertIn("review and approve", text)


if __name__ == "__main__":
    unittest.main()

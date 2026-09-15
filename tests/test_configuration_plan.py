import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from drivershub_migration.configuration_plan import create_configuration_plan


class ConfigurationPlanTests(unittest.TestCase):
    def test_separates_portable_protected_and_runtime_values(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            assessment = directory / "raw" / "assessment"
            assessment.mkdir(parents=True)
            (assessment / "backend-config.json").write_text(
                json.dumps(
                    {
                        "config": {
                            "name": "Example VTC",
                            "smtp_host": "mail.example.com",
                            "smtp_password": "",
                            "trackers": [
                                {
                                    "type": "custom",
                                    "company_id": "example",
                                    "api_token": "available-token",
                                    "webhook_secret": "available-secret",
                                }
                            ],
                        },
                        "backup": {},
                    }
                )
            )
            (assessment / "client-config.json").write_text(
                json.dumps(
                    {
                        "abbr": "example",
                        "name": "Example VTC",
                        "domain": "hub.example.com",
                        "api_host": "https://hub.example.com",
                        "plugins": ["application"],
                        "logo_key": "old-logo",
                        "color": "112233",
                    }
                )
            )
            (directory / "export.json").write_text(
                json.dumps(
                    {
                        "assets": {
                            "logo": {
                                "state": "complete",
                                "path": "raw/branding/logo.png",
                                "sha256": "abc",
                            },
                            "banner": {"state": "unavailable"},
                        }
                    }
                )
            )

            result = create_configuration_plan(directory)

            self.assertEqual(result["state"], "complete")
            self.assertEqual(result["backend"]["portable"]["name"], "Example VTC")
            self.assertNotIn("smtp_password", result["backend"]["portable"])
            self.assertEqual(
                result["backend"]["protected"]["smtp_password"]["state"],
                "destination-value-required",
            )
            self.assertEqual(
                result["backend"]["portable"]["trackers"][0]["api_token"],
                "available-token",
            )
            self.assertEqual(result["frontend"]["portable"]["color"], "112233")
            self.assertNotIn("abbr", result["frontend"]["portable"])
            self.assertEqual(
                result["frontend"]["runtime_managed"]["abbr"],
                "derive-from-destination-backend",
            )
            self.assertEqual(result["branding"]["logo"]["state"], "ready")
            self.assertEqual(result["branding"]["banner"]["state"], "unavailable")


if __name__ == "__main__":
    unittest.main()

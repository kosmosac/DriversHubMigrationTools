import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from drivershub_migration.configuration_writer import import_configuration


class ConfigurationWriterTests(unittest.TestCase):
    @patch(
        "drivershub_migration.configuration_writer._compressed_asset",
        return_value="compressed",
    )
    def test_retains_destination_integrations_and_imports_branding(self, compressed):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            if "ps" in command:
                return type("Result", (), {"stdout": "mariadb\nvalkey\n"})()
            return type("Result", (), {"stdout": ""})()

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            migration = root / "migration"
            target = root / "target"
            assessment = migration / "raw" / "assessment"
            branding = migration / "raw" / "branding"
            assessment.mkdir(parents=True)
            branding.mkdir(parents=True)
            (target / "config").mkdir(parents=True)
            target_config = {
                "name": "New Hub",
                "abbr": "new",
                "domain": "https://new.example.invalid",
                "plugins": ["application"],
                "trackers": [{"type": "custom", "api_token": "target-token"}],
                "discord_client_id": "target-client",
                "smtp_host": "target-mail",
                "roles": [{"id": 20, "name": "Admin", "discord_role_id": "target-role"}],
            }
            (target / "config" / "config.json").write_text(json.dumps(target_config))
            (assessment / "backend-config.json").write_text(
                json.dumps(
                    {
                        "config": {
                            "name": "Source Hub",
                            "trackers": [{"type": "custom", "api_token": "source-token"}],
                            "discord_client_id": "source-client",
                            "smtp_host": "source-mail",
                            "roles": [{"id": 20, "name": "Admin", "discord_role_id": "source-role"}],
                        }
                    }
                )
            )
            (assessment / "client-config.json").write_text(
                json.dumps({"name": "Source Hub", "abbr": "old", "gallery": []})
            )
            (branding / "logo.png").write_bytes(b"image")
            (migration / "export.json").write_text(
                json.dumps(
                    {
                        "assets": {
                            "logo": {
                                "state": "complete",
                                "path": "raw/branding/logo.png",
                                "sha256": "abcdef123456",
                            }
                        }
                    }
                )
            )
            (migration / "import-journal.json").write_text(
                json.dumps({"stages": {"accounts": {"state": "complete"}}})
            )

            result = import_configuration(
                migration,
                target,
                None,
                mode="aio",
                database={},
                approved=True,
                backup_confirmed=True,
                writers_stopped=False,
                runner=runner,
            )
            written = json.loads((target / "config" / "config.json").read_text())

        self.assertEqual(result["state"], "complete")
        self.assertEqual(written["name"], "Source Hub")
        self.assertEqual(written["trackers"], target_config["trackers"])
        self.assertEqual(written["discord_client_id"], "target-client")
        self.assertEqual(written["smtp_host"], "target-mail")
        self.assertEqual(written["roles"][0]["discord_role_id"], "target-role")
        sql = calls[-1][1]["input"]
        self.assertNotIn("source-token", sql)
        self.assertNotIn("source-client", sql)
        compressed.assert_called_once_with(b"image")


if __name__ == "__main__":
    unittest.main()

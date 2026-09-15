import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from drivershub_migration.account_writer import import_accounts


class AccountWriterTests(unittest.TestCase):
    @patch("drivershub_migration.account_writer.build_account_stage")
    @patch("drivershub_migration.account_writer.preflight_target")
    def test_writes_aio_transaction_once(self, preflight, build):
        preflight.return_value = {"state": "action-required"}
        build.return_value = (
            "SET time_zone = '+00:00';\nSTART TRANSACTION;\nCOMMIT;\n",
            {"inserted_accounts": 3, "merged_accounts": 0},
        )
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            if "ps" in command:
                return type("Result", (), {"stdout": "mariadb\nvalkey\n"})()
            if "-e" in command[-1]:
                return type("Result", (), {"stdout": "3\n"})()
            return type("Result", (), {"stdout": ""})()

        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "import-plan.json").write_text(
                json.dumps(
                    {
                        "accounts": [
                            {"target_uid": 1},
                            {"target_uid": 2},
                            {"target_uid": 3},
                        ]
                    }
                )
            )
            target = directory / "target"
            target.mkdir()
            result = import_accounts(
                directory,
                target,
                mode="aio",
                database={},
                approved=True,
                backup_confirmed=True,
                writers_stopped=False,
                runner=runner,
            )
            journal = json.loads((directory / "import-journal.json").read_text())

        self.assertEqual(result["stages"]["accounts"]["state"], "complete")
        self.assertEqual(journal["state"], "partial")
        self.assertEqual(journal["stages"]["accounts"]["verified_accounts"], 3)
        self.assertIn("SET time_zone", calls[-2][1]["input"])

    @patch("drivershub_migration.account_writer.preflight_target")
    def test_refuses_running_backend(self, preflight):
        preflight.return_value = {"state": "action-required"}

        def runner(command, **kwargs):
            return type("Result", (), {"stdout": "mariadb\nbackend\n"})()

        with TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "Stop destination writer"):
                import_accounts(
                    Path(temporary),
                    Path(temporary),
                    mode="aio",
                    database={},
                    approved=True,
                    backup_confirmed=True,
                    writers_stopped=False,
                    runner=runner,
                )


if __name__ == "__main__":
    unittest.main()

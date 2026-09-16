from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from drivershub_migration.cli import main


class CliTests(unittest.TestCase):
    @patch("drivershub_migration.cli.import_user_state")
    def test_routes_personal_note_conversion_setting_to_user_state(self, import_user_state):
        import_user_state.return_value = {
            "global_notes": 1,
            "personal_notes_converted": 1,
            "personal_notes_skipped": 0,
        }
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = root / ".env"
            env.write_text(
                "DRIVERSHUB_MIGRATION_DIRECTORY=" + str(root / "migration") + "\n"
                "DRIVERSHUB_TARGET_DIRECTORY=" + str(root / "target") + "\n"
                "DRIVERSHUB_TARGET_MODE=aio\n"
                "DRIVERSHUB_CONVERT_PERSONAL_NOTES_TO_GLOBAL=true\n"
            )
            result = main(
                [
                    "--env-file",
                    str(env),
                    "import-user-state",
                    "--approve",
                    "--backup-confirmed",
                ]
            )

        self.assertEqual(result, 0)
        self.assertTrue(
            import_user_state.call_args.kwargs["convert_personal_notes_to_global"]
        )


if __name__ == "__main__":
    unittest.main()

from contextlib import redirect_stdout
import inspect
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from drivershub_migration.cli import main
from drivershub_migration.assess import assess
from drivershub_migration.exporter import export_source


class CliTests(unittest.TestCase):
    def test_source_operations_stay_below_sixty_requests_per_minute(self):
        self.assertGreaterEqual(
            inspect.signature(assess).parameters["request_interval"].default,
            1.0,
        )
        self.assertGreaterEqual(
            inspect.signature(export_source).parameters["request_interval"].default,
            1.0,
        )

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
            with redirect_stdout(StringIO()):
                result = main(
                    [
                        "--env-file",
                        str(env),
                        "import-user-state",
                    ]
                )

        self.assertEqual(result, 0)
        self.assertTrue(
            import_user_state.call_args.kwargs["convert_personal_notes_to_global"]
        )


if __name__ == "__main__":
    unittest.main()

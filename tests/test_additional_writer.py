import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from drivershub_migration.additional_writer import (
    import_economy_inventory,
    import_polls_tasks,
)


class AdditionalWriterTests(unittest.TestCase):
    def _run_without_explicit_runner(self, function, builder_name, prerequisite):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "import-journal.json").write_text(
                json.dumps(
                    {
                        "state": "partial",
                        "stages": {prerequisite: {"state": "complete"}},
                    }
                )
            )
            with (
                patch(builder_name, return_value=("START TRANSACTION;\nCOMMIT;\n", {"items": 1})),
                patch("drivershub_migration.additional_writer._execute_mariadb") as execute,
            ):
                result = function(
                    directory,
                    None,
                    mode="mariadb",
                    database={},
                    writers_stopped=True,
                )
        execute.assert_called_once()
        self.assertEqual(result["state"], "complete")

    def test_polls_tasks_uses_default_runner(self):
        self._run_without_explicit_runner(
            import_polls_tasks,
            "drivershub_migration.additional_writer.build_poll_task_stage",
            "events_challenges",
        )

    def test_economy_inventory_uses_default_runner(self):
        self._run_without_explicit_runner(
            import_economy_inventory,
            "drivershub_migration.additional_writer.build_economy_inventory_stage",
            "economy",
        )


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest
from unittest.mock import patch

from drivershub_migration.import_validation import validate_import


class ImportValidationTests(unittest.TestCase):
    @patch("drivershub_migration.import_validation._inspect_aio_safety", return_value={"state": "ready"})
    @patch("drivershub_migration.import_validation._configuration_validation")
    @patch("drivershub_migration.import_validation._stage_sql")
    def test_aio_runs_full_transaction_with_rollback(self, stage_sql, configuration, safety):
        configuration.return_value = ({"state": "ready"}, "unused")
        stage_sql.return_value = (
            "SET time_zone = '+00:00';\nSTART TRANSACTION;\nSELECT 1;\nROLLBACK;\n",
            {"accounts": {"state": "ready"}},
        )
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            if "ps" in command:
                return subprocess.CompletedProcess(command, 0, stdout="mariadb\n", stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with TemporaryDirectory() as temporary:
            target = Path(temporary)
            report = validate_import(
                target, target, mode="aio", database={}, config_path=None,
                convert_personal_notes=False, writers_stopped=False, runner=runner,
            )

        self.assertEqual(report["state"], "ready")
        self.assertEqual(report["committed_writes"], 0)
        self.assertIn("ROLLBACK;", calls[-1][1]["input"])

    def test_rejects_non_transactional_tables_and_triggers(self):
        from drivershub_migration.import_validation import _validate_safety_rows

        with self.assertRaisesRegex(ValueError, "transactional destination tables"):
            _validate_safety_rows([["user", "MyISAM"]], [], {"user"})
        with self.assertRaisesRegex(ValueError, "does not support triggers"):
            _validate_safety_rows(
                [["user", "InnoDB"]], [["user_audit", "user"]], {"user"}
            )


if __name__ == "__main__":
    unittest.main()

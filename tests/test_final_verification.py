import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from drivershub_migration.final_verification import REQUIRED_STAGES, verify_target


class FinalVerificationTests(unittest.TestCase):
    @patch("drivershub_migration.final_verification._query_aio")
    @patch("drivershub_migration.final_verification._check_aio_writers")
    def test_marks_matching_import_complete(self, check_writers, query_aio):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            stages = {name: {"state": "complete"} for name in REQUIRED_STAGES}
            stages["accounts"]["verified_accounts"] = 1
            stages["content"]["resources"] = {}
            (directory / "import-journal.json").write_text(json.dumps({"stages": stages}))
            (directory / "import-plan.json").write_text(json.dumps({"accounts": [{"target_uid": 7}]}))

            def values(_target, queries, _runner):
                return {name: (1 if name == "imported_accounts" else 0) for name in queries}
            query_aio.side_effect = values
            result = verify_target(directory, Path("/target"), mode="aio", database={}, writers_stopped=False)

            self.assertEqual(result["state"], "complete")
            self.assertEqual(json.loads((directory / "import-journal.json").read_text())["state"], "complete")

    def test_rejects_incomplete_journal(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "import-journal.json").write_text(json.dumps({"stages": {}}))
            with self.assertRaisesRegex(ValueError, "Complete these import stages"):
                verify_target(directory, None, mode="mariadb", database={}, writers_stopped=True)

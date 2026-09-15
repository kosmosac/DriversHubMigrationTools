import json
from pathlib import Path
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import patch

from drivershub_migration.application_import import build_application_stage


class ApplicationImportTests(unittest.TestCase):
    def test_builds_application_row(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            (normalized / "applications-details.json").write_text(json.dumps({"records": [{
                "applicationid": 9, "type": 2, "status": 1,
                "submit_timestamp": 1700000000, "respond_timestamp": 1700000100,
                "creator": {"uid": 7}, "last_respond_staff": {"userid": 4},
                "application": {"Question": "Answer"},
            }]}))
            zstd = types.ModuleType("zstandard")
            zstd.ZstdCompressor = lambda: type("C", (), {"compress": lambda self, value: b"z" + value})()
            with patch.dict("sys.modules", {"zstandard": zstd}):
                sql, summary = build_application_stage(directory)
        self.assertIn("INSERT INTO `application`", sql)
        self.assertNotIn("Question", sql)
        self.assertEqual(summary["applications"], 1)
        self.assertEqual(summary["pending_applications"], 0)

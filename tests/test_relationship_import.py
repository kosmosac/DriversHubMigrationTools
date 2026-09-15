import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from drivershub_migration.relationship_import import build_relationship_stage


class RelationshipImportTests(unittest.TestCase):
    def test_builds_delivery_relationships(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            (normalized / "deliveries.json").write_text(json.dumps({"records": [{"logid": 10}]}))
            (normalized / "challenges-details.json").write_text(json.dumps({"records": [{"challengeid": 3, "record": [{"user": {"userid": 7}, "dlog": [10], "is_completed": True, "points": 5, "complete_timestamp": 1700000000}]}]}))
            (normalized / "division-pending.json").write_text(json.dumps({"records": [{"logid": 10, "divisionid": 2, "user": {"userid": 7}}]}))
            sql, summary = build_relationship_stage(directory)
        self.assertIn("INSERT INTO `challenge_record`", sql)
        self.assertIn("INSERT INTO `challenge_completed`", sql)
        self.assertIn("INSERT INTO `division`", sql)
        self.assertEqual(summary["challenge_delivery_links"], 1)
        self.assertEqual(summary["challenge_completions"], 1)

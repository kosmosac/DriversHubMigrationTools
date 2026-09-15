import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from drivershub_migration.delivery_import import build_delivery_stage


class DeliveryImportTests(unittest.TestCase):
    def test_builds_baseline_and_reports_snapshot_differences(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            delivery = {"logid": 1, "user": {"userid": 7}, "max_speed": 80.5, "timestamp": 1700000000, "status": 1, "profit": 10.5, "unit": 1, "fuel": 4.2, "distance": 20.3, "views": 2, "source_city": "A", "source_company": "B", "destination_city": "C", "destination_company": "D", "cargo": "E", "cargo_mass": 100}
            csv = {"logid": "1", " trackerid": "9", " tracker": "tracksim"}
            (normalized / "deliveries.json").write_text(json.dumps({"records": [delivery]}))
            (normalized / "deliveries-csv.json").write_text(json.dumps({"records": [csv, csv]}))
            sql, summary = build_delivery_stage(directory)
        self.assertIn("INSERT INTO `dlog`", sql)
        self.assertIn("INSERT INTO `dlog_meta`", sql)
        self.assertIn("1700000000", sql)
        self.assertEqual(summary["deliveries"], 1)
        self.assertEqual(summary["duplicate_csv_rows_ignored"], 1)

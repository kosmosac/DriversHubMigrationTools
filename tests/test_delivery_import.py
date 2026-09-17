from base64 import b64decode
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from drivershub_migration.delivery_import import build_delivery_stage, placeholder_detail
from drivershub_migration.relationship_import import build_relationship_stage


class DeliveryImportTests(unittest.TestCase):
    def test_builds_delivery_relationships(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            (normalized / "deliveries.json").write_text(
                json.dumps({"records": [{"logid": 10}]})
            )
            (normalized / "challenges-details.json").write_text(json.dumps({
                "records": [{
                    "challengeid": 3,
                    "record": [{
                        "user": {"userid": 7}, "dlog": [10],
                        "is_completed": True, "points": 5,
                        "complete_timestamp": 1700000000,
                    }],
                }],
            }))
            (normalized / "division-pending.json").write_text(json.dumps({
                "records": [{
                    "logid": 10, "divisionid": 2, "user": {"userid": 7},
                }],
            }))
            sql, summary = build_relationship_stage(directory)
        self.assertIn("INSERT INTO `challenge_record`", sql)
        self.assertIn("INSERT INTO `challenge_completed`", sql)
        self.assertIn("INSERT INTO `division`", sql)
        self.assertEqual(summary["challenge_delivery_links"], 1)
        self.assertEqual(summary["challenge_completions"], 1)

    def test_placeholder_matches_frontend_shape(self):
        class Compressor:
            def compress(self, value):
                return value

        with patch.dict(
            "sys.modules",
            {"zstandard": type("Zstd", (), {"ZstdCompressor": Compressor})},
        ):
            encoded = placeholder_detail(delivered=True, ats=False)
        payload = json.loads(b64decode(encoded))
        detail = payload["data"]["object"]
        self.assertEqual(payload["type"], "job.delivered")
        self.assertEqual(detail["game"]["short_name"], "eut2")
        self.assertTrue(detail["events"])
        self.assertIn("driver", detail)
        self.assertTrue(detail["trailers"])

    def test_builds_baseline_and_reports_snapshot_differences(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            delivery = {"logid": 1, "user": {"userid": 7}, "max_speed": 80.5, "timestamp": 1700000000, "status": 1, "profit": 10.5, "unit": 1, "fuel": 4.2, "distance": 20.3, "views": 2, "source_city": "A", "source_company": "B", "destination_city": "C", "destination_company": "D", "cargo": "E", "cargo_mass": 100}
            csv = {"logid": "1", " trackerid": "9", " tracker": "tracksim"}
            (normalized / "deliveries.json").write_text(json.dumps({"records": [delivery]}))
            (normalized / "deliveries-csv.json").write_text(json.dumps({"records": [csv, csv]}))
            class Compressor:
                def compress(self, value):
                    return b"compressed:" + value

            with patch.dict("sys.modules", {"zstandard": type("Zstd", (), {"ZstdCompressor": Compressor})}):
                sql, summary = build_delivery_stage(directory)
        self.assertIn("INSERT INTO `dlog`", sql)
        self.assertIn("INSERT INTO `dlog_meta`", sql)
        self.assertIn("1700000000", sql)
        self.assertEqual(summary["deliveries"], 1)
        self.assertEqual(summary["duplicate_csv_rows_ignored"], 1)

    def test_imports_exported_detail_and_telemetry_instead_of_placeholder(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            delivery = {"logid": 1, "user": {"userid": 7}, "max_speed": 80, "timestamp": 1700000000, "status": 1, "profit": 10, "unit": 1, "fuel": 4, "distance": 20, "views": 2, "source_city": "A", "source_company": "B", "destination_city": "C", "destination_company": "D", "cargo": "E", "cargo_mass": 100}
            (normalized / "deliveries.json").write_text(json.dumps({"records": [delivery]}))
            (normalized / "deliveries-csv.json").write_text(json.dumps({"records": []}))
            (normalized / "deliveries-details.json").write_text(json.dumps({"records": [{
                "logid": 1,
                "detail": {"object": "event", "type": "job.delivered", "data": {"object": {"events": []}}},
                "telemetry": "v21,mods;route",
            }]}))

            class Compressor:
                def compress(self, value):
                    return b"compressed:" + value

            with patch.dict("sys.modules", {"zstandard": type("Zstd", (), {"ZstdCompressor": Compressor})}):
                sql, summary = build_delivery_stage(directory)

        self.assertIn("INSERT INTO `telemetry`", sql)
        self.assertEqual(summary["imported_details"], 1)
        self.assertEqual(summary["imported_telemetry"], 1)
        self.assertEqual(summary["detail_placeholders"], 0)

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from drivershub_migration.enrichment import (
    _csv_timestamp,
    _source_offsets,
    backfill_delivery_details,
    enrich_economy_transactions,
)
from drivershub_migration.http import Response


class Compressor:
    def compress(self, value):
        return b"compressed:" + value


class DetailClient:
    authorizations = []

    def __init__(self, *args, **kwargs):
        self.authorizations.append(args[0])

    def get(self, url, expect_json=True):
        body = json.dumps({
            "logid": 7,
            "detail": {"object": "event", "data": {"object": {"events": []}}},
            "telemetry": "v2route",
        }).encode()
        return Response(200, {"content-type": "application/json"}, body)


class CsvClient:
    def __init__(self, *args, **kwargs):
        pass

    def get(self, url, expect_json=True):
        body = (
            "txid, from_userid, to_userid, executor_userid, amount, message, "
            "from_new_balance, to_new_balance, time\n"
            '9,"company",1,"company",100,"test",0,100,"2024-03-31 03:30:00"\n'
        ).encode()
        return Response(200, {"content-type": "text/csv"}, body)


def import_journal(directory, stage):
    (directory / "import-journal.json").write_text(json.dumps({
        "stages": {stage: {"state": "complete"}}
    }))


class EnrichmentTests(unittest.TestCase):
    def test_derives_only_unambiguous_daily_source_offsets(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            (normalized / "deliveries.json").write_text(json.dumps({"records": [
                {"logid": 1, "timestamp": 1704067200},
                {"logid": 2, "timestamp": 1704070800},
            ]}))
            (normalized / "deliveries-csv.json").write_text(json.dumps({"records": [
                {"logid": "1", " time_submitted": "2024-01-01 01:00:00"},
                {"logid": "2", " time_submitted": "2024-01-01 02:00:00"},
            ]}))
            self.assertEqual(_source_offsets(directory), {"2024-01-01": 3600})

    def test_converts_timestamp_with_derived_daily_offset(self):
        self.assertIsNone(_csv_timestamp("2024-10-27 02:30:00", {}))
        self.assertEqual(_csv_timestamp("2024-10-27 03:30:00", {"2024-10-27": 3600}), 1729996200)

    def test_delivery_backfill_writes_only_conditionally_and_clears_marker(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            import_journal(directory, "deliveries")
            queries = iter([[['7', '1', '1']], [['7']], [['0']], [['0']]])
            sql = []
            with (
                patch("drivershub_migration.enrichment.query_rows", side_effect=lambda *a, **k: next(queries)),
                patch("drivershub_migration.enrichment.execute_live", side_effect=lambda value, *a, **k: sql.append(value)),
                patch("drivershub_migration.enrichment.HttpClient", DetailClient),
                patch.dict("sys.modules", {"zstandard": type("Zstd", (), {"ZstdCompressor": Compressor})}),
            ):
                report = backfill_delivery_details(
                    directory, Path("/target"), source="https://source/api", token="token",
                    mode="aio", database={}, approved=True, allow_view_updates=True,
                    request_interval=0,
                )
            self.assertEqual(report["state"], "complete")
            self.assertEqual(report["completed"], 1)
            self.assertEqual(DetailClient.authorizations[-1], "Application token")
            self.assertIn("@migration_eligible", sql[0])
            self.assertIn("JOIN dlog_meta", sql[0])
            self.assertIn("AND d.data=", sql[0])
            self.assertTrue((directory / "enrichment/deliveries/raw/logid-7.json").is_file())

    def test_economy_enrichment_is_limited_and_marks_csv_rows(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            import_journal(directory, "economy")
            normalized = directory / "normalized"
            normalized.mkdir()
            (normalized / "economy-balances.json").write_text(json.dumps({"records": [{"userid": 1}]}))
            (normalized / "deliveries.json").write_text(json.dumps({"records": [{"logid": 1, "timestamp": 1711843200}]}))
            (normalized / "deliveries-csv.json").write_text(json.dumps({"records": [{"logid": "1", " time_submitted": "2024-03-31 01:00:00"}]}))
            (directory / "export.json").write_text(json.dumps({"created_at": "2024-04-02T00:00:00+00:00"}))
            sql = []
            pending = iter([[['1']], [['0']]])
            with (
                patch("drivershub_migration.enrichment.query_rows", side_effect=lambda *a, **k: next(pending)),
                patch("drivershub_migration.enrichment.execute_live", side_effect=lambda value, *a, **k: sql.append(value)),
                patch("drivershub_migration.enrichment.HttpClient", CsvClient),
            ):
                report = enrich_economy_transactions(
                    directory, Path("/target"), source="https://source/api", token="token",
                    mode="aio", database={}, approved=True,
                    limit=1,
                )
            self.assertEqual(report["attempted_windows"], 1)
            self.assertIn("UPDATE economy_transaction SET timestamp=1711852200", sql[0])
            self.assertIn("WHERE txid=9 AND note=", sql[0])


if __name__ == "__main__":
    unittest.main()

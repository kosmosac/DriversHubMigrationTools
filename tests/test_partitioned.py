import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from drivershub_migration.exporter import _export_partitioned_pages
from drivershub_migration.http import Response
from drivershub_migration.storage import WorkJournal


class Client:
    def __init__(self):
        self.calls = []

    def get(self, url, *, expect_json=True):
        self.calls.append(url)
        partition = "one" if "/one?" in url else "two"
        records = (
            [{"txid": 1}, {"txid": 2}]
            if partition == "one"
            else [{"txid": 2}, {"txid": 3}]
        )
        body = json.dumps(
            {"list": records, "total_items": 0, "total_pages": 0}
        ).encode()
        return Response(200, {"content-type": "application/json"}, body)


class PartitionedExportTests(unittest.TestCase):
    def test_ignores_totals_and_deduplicates_partitions(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            client = Client()
            result = _export_partitioned_pages(
                name="transactions",
                source="https://example.test/api/",
                partitions=[("one", "one", None), ("two", "two", None)],
                output=output,
                client=client,
                journal=WorkJournal(output),
                deduplicate_by="txid",
                page_size=500,
            )
            self.assertEqual(result["state"], "complete")
            self.assertEqual(result["items"], 3)
            self.assertEqual(len(client.calls), 2)


if __name__ == "__main__":
    unittest.main()

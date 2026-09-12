import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from drivershub_migration.exporter import _export_delivery_csv
from drivershub_migration.http import Response
from drivershub_migration.storage import WorkJournal


class Client:
    def __init__(self):
        self.calls = 0

    def get(self, url, *, expect_json=True):
        self.calls += 1
        self.url = url
        self.expect_json = expect_json
        return Response(
            200,
            {"content-type": "text/csv; charset=utf-8"},
            b"logid,tracker,user_id\n1,tracksim,7\n",
        )


class DeliveryExportTests(unittest.TestCase):
    def test_exports_csv_normalizes_and_resumes(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            client = Client()
            result = _export_delivery_csv(
                "https://example.test/api/", output, client, WorkJournal(output)
            )
            self.assertEqual(result["state"], "complete")
            self.assertEqual(result["items"], 1)
            self.assertFalse(client.expect_json)
            self.assertTrue(client.url.endswith("dlog/export?include_ids=true"))
            normalized = json.loads(
                (output / "normalized" / "deliveries-csv.json").read_text()
            )
            self.assertEqual(normalized["records"][0]["logid"], "1")

            resumed = _export_delivery_csv(
                "https://example.test/api/", output, client, WorkJournal(output)
            )
            self.assertEqual(resumed["items"], 1)
            self.assertEqual(client.calls, 1)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from drivershub_migration.details import export_details
from drivershub_migration.http import Response
from drivershub_migration.storage import WorkJournal


class Client:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        identifier = int(url.rsplit("/", 1)[-1])
        body = f'{{"itemid":{identifier},"value":"complete"}}'.encode()
        return Response(200, {"content-type": "application/json"}, body)


class DetailTests(unittest.TestCase):
    def test_exports_unique_details_and_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            client = Client()
            result = export_details(
                name="items",
                id_key="itemid",
                records=[{"itemid": 1}, {"itemid": 1}, {"itemid": 2}],
                url_for=lambda identifier: f"https://example.test/items/{identifier}",
                output=output,
                client=client,
                journal=WorkJournal(output),
            )
            self.assertEqual(result["state"], "complete")
            self.assertEqual(result["items"], 2)
            self.assertEqual(len(client.urls), 2)

            resumed_client = Client()
            resumed = export_details(
                name="items",
                id_key="itemid",
                records=[{"itemid": 1}, {"itemid": 2}],
                url_for=lambda identifier: f"https://example.test/items/{identifier}",
                output=output,
                client=resumed_client,
                journal=WorkJournal(output),
            )
            self.assertEqual(resumed["state"], "complete")
            self.assertEqual(resumed_client.urls, [])


if __name__ == "__main__":
    unittest.main()

import unittest
import tempfile
from pathlib import Path

from drivershub_migration.http import Response
from drivershub_migration.pagination import InvalidPage, export_paginated, validate_page
from drivershub_migration.storage import WorkJournal


class Client:
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return Response(200, {"content-type": "application/json"}, self.bodies.pop(0))


class PaginationTests(unittest.TestCase):
    def test_accepts_page(self):
        page = {"list": [{"uid": 1}], "total_items": 1, "total_pages": 1}
        self.assertIs(validate_page(page), page)

    def test_accepts_empty_page_set(self):
        page = {"list": [], "total_items": 0, "total_pages": 0}
        self.assertIs(validate_page(page), page)

    def test_rejects_error_response(self):
        with self.assertRaises(InvalidPage):
            validate_page({"error": "denied"})

    def test_rejects_non_integer_totals(self):
        with self.assertRaises(InvalidPage):
            validate_page({"list": [], "total_items": "0", "total_pages": 0})

    def test_exports_and_resumes_multiple_pages(self):
        bodies = [
            b'{"list":[{"uid":1}],"total_items":2,"total_pages":2}',
            b'{"list":[{"uid":2}],"total_items":2,"total_pages":2}',
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            journal = WorkJournal(output)
            client = Client(bodies)
            result = export_paginated(
                name="users",
                source="https://example.test/api/",
                relative_url="user/list",
                output=output,
                client=client,
                journal=journal,
            )
            self.assertEqual(result["state"], "complete")
            self.assertEqual(result["items"], 2)
            self.assertEqual(len(client.urls), 2)

            resumed_client = Client([])
            resumed = export_paginated(
                name="users",
                source="https://example.test/api/",
                relative_url="user/list",
                output=output,
                client=resumed_client,
                journal=WorkJournal(output),
            )
            self.assertEqual(resumed["state"], "complete")
            self.assertEqual(resumed["items"], 2)
            self.assertEqual(resumed_client.urls, [])


if __name__ == "__main__":
    unittest.main()

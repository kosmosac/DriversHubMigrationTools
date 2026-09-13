import io
import unittest
import urllib.error
from email.message import Message
from unittest.mock import patch

from drivershub_migration.http import HttpClient, RequestFailed, Response


class Result:
    status = 200

    def __init__(self, body=b'{"ok":true}', content_type="application/json"):
        self.body = body
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.body


class HttpClientTests(unittest.TestCase):
    def test_reports_request_progress(self):
        messages = []
        client = HttpClient(None, progress=messages.append)
        response = Response(200, {"content-type": "application/json"}, b"{}")
        with patch.object(client, "_once", return_value=response):
            client.get("https://example.test/api/status")
        self.assertEqual(messages[0], "GET https://example.test/api/status")
        self.assertEqual(messages[-1], "HTTP 200 complete")

    def test_accepts_json_response(self):
        with patch("urllib.request.urlopen", return_value=Result()):
            response = HttpClient(None, minimum_interval=0).get(
                "https://example.test/status"
            )
        self.assertEqual(response.json(), {"ok": True})

    def test_rejects_html_with_success_status(self):
        with patch(
            "urllib.request.urlopen",
            return_value=Result(b"<html></html>", "text/html"),
        ):
            with self.assertRaises(RequestFailed):
                HttpClient(None, minimum_interval=0, max_attempts=1).get(
                    "https://example.test/status"
                )

    def test_honors_retry_after(self):
        headers = Message()
        headers["Content-Type"] = "application/json"
        headers["Retry-After"] = "7"
        error = urllib.error.HTTPError(
            "https://example.test/status",
            429,
            "rate limited",
            headers,
            io.BytesIO(b'{"error":"slow"}'),
        )
        sleeps = []
        with patch("urllib.request.urlopen", side_effect=[error, Result()]):
            HttpClient(
                None,
                minimum_interval=0,
                max_attempts=2,
                sleeper=sleeps.append,
            ).get("https://example.test/status")
        self.assertEqual(sleeps, [7.0])


if __name__ == "__main__":
    unittest.main()

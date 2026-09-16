from base64 import b64decode
import json
import unittest
from unittest.mock import patch

from drivershub_migration.delivery_import import placeholder_detail


class DeliveryPlaceholderTests(unittest.TestCase):
    def test_placeholder_matches_frontend_shape(self):
        class Compressor:
            def compress(self, value):
                return value

        with patch.dict("sys.modules", {"zstandard": type("Zstd", (), {"ZstdCompressor": Compressor})}):
            encoded = placeholder_detail(delivered=True, ats=False)
        payload = json.loads(b64decode(encoded))
        detail = payload["data"]["object"]
        self.assertEqual(payload["type"], "job.delivered")
        self.assertEqual(detail["game"]["short_name"], "eut2")
        self.assertTrue(detail["events"])
        self.assertIn("driver", detail)
        self.assertTrue(detail["trailers"])

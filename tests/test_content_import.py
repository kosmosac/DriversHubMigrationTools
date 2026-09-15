import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from drivershub_migration.content_import import build_content_stage


class ContentImportTests(unittest.TestCase):
    def test_builds_announcement_and_download_rows(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            (normalized / "announcements.json").write_text(json.dumps({"records": [{
                "announcementid": 2, "author": {"userid": 4}, "title": "News",
                "content": "Text", "type": {"id": 1}, "timestamp": 1700000000,
                "is_private": False, "orderid": 3, "is_pinned": True,
            }]}))
            (normalized / "downloads.json").write_text(json.dumps({"records": [{
                "downloadsid": 6, "creator": {"userid": 4}, "title": "File",
                "description": "Description", "link": "https://example.invalid",
                "orderid": 1, "is_pinned": False, "timestamp": 1700000001,
                "click_count": 8,
            }]}))
            class Compressor:
                def compress(self, value):
                    return b"compressed:" + value

            with patch.dict("sys.modules", {"zstandard": type("Zstd", (), {"ZstdCompressor": Compressor})}):
                sql, summary = build_content_stage(directory)
        self.assertIn("INSERT INTO `announcement`", sql)
        self.assertIn("INSERT INTO `downloads`", sql)
        self.assertNotIn("Text", sql)
        self.assertEqual(summary["records"], 2)

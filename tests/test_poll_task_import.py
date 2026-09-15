import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from drivershub_migration.poll_task_import import build_poll_task_stage


class PollTaskImportTests(unittest.TestCase):
    def test_builds_poll_votes_and_task_with_explicit_timestamp_placeholders(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            poll = {
                "pollid": 2, "creator": {"userid": 7}, "title": "Question",
                "description": "Description", "config": {
                    "max_choice": 1, "allow_modify_vote": False,
                    "show_stats": True, "show_stats_before_vote": False,
                    "show_voter": True, "show_stats_when_ended": True,
                }, "orderid": 0, "is_pinned": False, "end_time": None,
                "timestamp": 1700000000, "choices": [{
                    "choiceid": 3, "orderid": 0, "content": "Yes",
                    "voters": [{"userid": 8}],
                }],
            }
            task = {
                "taskid": 4, "creator": {"userid": 7}, "title": "Task",
                "description": "Do it", "priority": 1, "bonus": 5,
                "due_timestamp": 1700000100, "remind_timestamp": 1700000050,
                "recurring": 0, "assign_mode": 1, "assign_to": [8],
                "mark_completed": True, "mark_note": "done",
                "mark_timestamp": 1700000060, "confirm_completed": False,
                "confirm_note": "", "confirm_timestamp": None,
            }
            (normalized / "polls-details.json").write_text(json.dumps({"records": [poll]}))
            (normalized / "tasks-details.json").write_text(json.dumps({"records": [task]}))

            class Compressor:
                def compress(self, value):
                    return b"compressed:" + value

            with patch.dict("sys.modules", {"zstandard": type("Zstd", (), {"ZstdCompressor": Compressor})}):
                sql, summary = build_poll_task_stage(directory)

        self.assertIn("INSERT INTO `poll_vote`", sql)
        self.assertIn("INSERT INTO `task`", sql)
        self.assertEqual(summary["poll_votes"], 1)
        self.assertEqual(summary["task_placeholder_create_timestamps"], 1)


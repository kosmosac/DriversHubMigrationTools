import json
from pathlib import Path
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import patch

from drivershub_migration.application_import import build_application_stage
from drivershub_migration.content_import import build_content_stage
from drivershub_migration.event_challenge_import import (
    JOB_REQUIREMENTS,
    build_event_challenge_stage,
)
from drivershub_migration.poll_task_import import build_poll_task_stage


def fake_zstandard():
    module = types.ModuleType("zstandard")
    module.ZstdCompressor = lambda: type(
        "Compressor", (), {"compress": lambda self, value: b"z" + value}
    )()
    return patch.dict("sys.modules", {"zstandard": module})


class PluginImportTests(unittest.TestCase):
    def test_builds_application_row(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            (normalized / "applications-details.json").write_text(json.dumps({"records": [{
                "applicationid": 9, "type": 2, "status": 1,
                "submit_timestamp": 1700000000, "respond_timestamp": 1700000100,
                "creator": {"uid": 7}, "last_respond_staff": {"userid": 4},
                "application": {"Question": "Answer"},
            }]}))
            with fake_zstandard():
                sql, summary = build_application_stage(directory)
        self.assertIn("INSERT INTO `application`", sql)
        self.assertNotIn("Question", sql)
        self.assertEqual(summary["applications"], 1)
        self.assertEqual(summary["pending_applications"], 0)

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
            with fake_zstandard():
                sql, summary = build_content_stage(directory)
        self.assertIn("INSERT INTO `announcement`", sql)
        self.assertIn("INSERT INTO `downloads`", sql)
        self.assertNotIn("Text", sql)
        self.assertEqual(summary["records"], 2)

    def test_builds_events_and_challenges(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            challenge = {
                "challengeid": 1, "creator": {"userid": 2}, "title": "C",
                "description": "D", "start_time": 10, "end_time": 20,
                "type": 1, "orderid": 0, "is_pinned": False,
                "delivery_count": 1, "required_roles": [20],
                "required_distance": 0, "reward_points": 5,
                "public_details": True,
                "job_requirements": {key: "" for key in JOB_REQUIREMENTS},
                "timestamp": 9, "record": [{"dlog": [4, 5]}],
            }
            event = {
                "eventid": 3, "creator": {"userid": None}, "title": "E",
                "description": "D", "link": "", "departure": "A",
                "destination": "B", "distance": "10", "meetup_timestamp": 30,
                "departure_timestamp": -1, "is_private": False, "orderid": 0,
                "is_pinned": False, "timestamp": 8, "votes": [{"userid": 2}],
                "attendees": [{"userid": 2}], "points": 0,
            }
            (normalized / "challenges-details.json").write_text(
                json.dumps({"records": [challenge]})
            )
            (normalized / "events-details.json").write_text(
                json.dumps({"records": [event]})
            )
            with fake_zstandard():
                sql, summary = build_event_challenge_stage(directory)
        self.assertIn("INSERT INTO `challenge`", sql)
        self.assertIn("INSERT INTO `event`", sql)
        self.assertEqual(summary["challenge_delivery_links_deferred"], 2)
        self.assertEqual(summary["event_creators_unavailable"], 1)

    def test_builds_poll_votes_and_tasks(self):
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
            (normalized / "polls-details.json").write_text(
                json.dumps({"records": [poll]})
            )
            (normalized / "tasks-details.json").write_text(
                json.dumps({"records": [task]})
            )
            with fake_zstandard():
                sql, summary = build_poll_task_stage(directory)
        self.assertIn("INSERT INTO `poll_vote`", sql)
        self.assertIn("INSERT INTO `task`", sql)
        self.assertEqual(summary["poll_votes"], 1)
        self.assertEqual(summary["task_placeholder_create_timestamps"], 1)


if __name__ == "__main__":
    unittest.main()

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import patch

from drivershub_migration.event_challenge_import import JOB_REQUIREMENTS, build_event_challenge_stage


class EventChallengeImportTests(unittest.TestCase):
    def test_builds_definitions_and_defers_delivery_links(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            challenge = {"challengeid": 1, "creator": {"userid": 2}, "title": "C", "description": "D", "start_time": 10, "end_time": 20, "type": 1, "orderid": 0, "is_pinned": False, "delivery_count": 1, "required_roles": [20], "required_distance": 0, "reward_points": 5, "public_details": True, "job_requirements": {key: "" for key in JOB_REQUIREMENTS}, "timestamp": 9, "record": [{"dlog": [4, 5]}]}
            event = {"eventid": 3, "creator": {"userid": None}, "title": "E", "description": "D", "link": "", "departure": "A", "destination": "B", "distance": "10", "meetup_timestamp": 30, "departure_timestamp": -1, "is_private": False, "orderid": 0, "is_pinned": False, "timestamp": 8, "votes": [{"userid": 2}], "attendees": [{"userid": 2}], "points": 0}
            (normalized / "challenges-details.json").write_text(json.dumps({"records": [challenge]}))
            (normalized / "events-details.json").write_text(json.dumps({"records": [event]}))
            zstd = types.ModuleType("zstandard")
            zstd.ZstdCompressor = lambda: type("C", (), {"compress": lambda self, value: b"z" + value})()
            with patch.dict("sys.modules", {"zstandard": zstd}):
                sql, summary = build_event_challenge_stage(directory)
        self.assertIn("INSERT INTO `challenge`", sql)
        self.assertIn("INSERT INTO `event`", sql)
        self.assertEqual(summary["challenge_delivery_links_deferred"], 2)
        self.assertEqual(summary["event_creators_unavailable"], 1)

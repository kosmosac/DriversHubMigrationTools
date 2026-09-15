import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from drivershub_migration.economy_inventory_import import build_economy_inventory_stage


class EconomyInventoryImportTests(unittest.TestCase):
    def test_builds_exported_inventory_with_reported_placeholders(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            (normalized / "economy-trucks.json").write_text(json.dumps({"records": [{
                "vehicleid": 1, "truck": {"id": "truck.id"}, "garageid": "berlin",
                "slotid": 2, "owner": {"userid": 7}, "assignee": {"userid": 8},
                "price": 100, "income": 10, "service": 2, "odometer": 500,
                "damage": 0.1, "purchase_timestamp": 1700000000, "status": "active",
            }]}))
            (normalized / "economy-garage-slots.json").write_text(json.dumps({"records": [{
                "slotid": 2, "garageid": "berlin", "slot_owner": {"userid": 7},
                "purchase_timestamp": 1700000000, "note": "garage-owner",
            }]}))
            (normalized / "economy-merch.json").write_text(json.dumps({"records": [{
                "itemid": 3, "merchid": "shirt", "owner": {"userid": 7},
                "price": 20, "purchase_timestamp": 1700000001,
            }]}))
            sql, summary = build_economy_inventory_stage(directory)

        self.assertIn("INSERT INTO `economy_truck`", sql)
        self.assertIn("INSERT INTO `economy_garage`", sql)
        self.assertIn("INSERT INTO `economy_merch`", sql)
        self.assertEqual(summary["garage_slot_placeholder_prices"], 1)
        self.assertEqual(summary["merchandise_placeholder_sell_prices"], 1)

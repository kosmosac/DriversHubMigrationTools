import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from drivershub_migration.economy_import import build_economy_stage


class EconomyImportTests(unittest.TestCase):
    def test_imports_balances_and_reports_transactions(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            (normalized / "economy-balances.json").write_text(json.dumps({"records": [{"userid": 2, "balance": 50, "visibility": "private"}]}))
            (normalized / "economy-transactions.json").write_text(json.dumps({"records": [{"txid": 1}]}))
            sql, summary = build_economy_stage(directory)
        self.assertIn("INSERT INTO `economy_balance`", sql)
        self.assertNotIn("economy_transaction`", sql)
        self.assertEqual(summary["balances"], 1)
        self.assertEqual(summary["transactions_not_importable"], 1)

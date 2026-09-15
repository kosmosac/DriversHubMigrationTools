import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from drivershub_migration.economy_import import build_economy_stage


class EconomyImportTests(unittest.TestCase):
    def test_imports_balances_and_placeholder_transactions(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normalized = directory / "normalized"
            normalized.mkdir()
            (normalized / "economy-balances.json").write_text(json.dumps({"records": [{"userid": 2, "balance": 50, "visibility": "private"}]}))
            (normalized / "economy-transactions.json").write_text(json.dumps({"records": [{"txid": 1, "from_user": {"userid": 2}, "to_user": {"userid": None}, "amount": 5, "message": "visible", "from_new_balance": 45, "to_new_balance": None}]}))
            sql, summary = build_economy_stage(directory)
        self.assertIn("INSERT INTO `economy_balance`", sql)
        self.assertIn("INSERT INTO `economy_transaction`", sql)
        self.assertIn("6d6967726174696f6e2d696d706f72742f70656e64696e672d656e726963686d656e74", sql)
        self.assertEqual(summary["balances"], 1)
        self.assertEqual(summary["transactions"], 1)
        self.assertEqual(summary["transactions_pending_enrichment"], 1)

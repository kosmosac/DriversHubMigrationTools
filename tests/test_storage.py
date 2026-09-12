import json
import tempfile
import unittest
from pathlib import Path

from drivershub_migration.storage import WorkJournal, atomic_write, sha256


class StorageTests(unittest.TestCase):
    def test_atomic_write_and_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "value.json"
            atomic_write(path, b'{"value":1}')
            self.assertEqual(path.read_bytes(), b'{"value":1}')
            self.assertEqual(
                sha256(path.read_bytes()),
                "48208f9428d64634bd8e28ff345bf0eab60d53c18fa2fbdb0b9bc1e84df2b5f6",
            )

    def test_journal_survives_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            journal = WorkJournal(path)
            journal.record("assessment/status", {"state": "complete"})
            self.assertTrue(WorkJournal(path).completed("assessment/status"))
            self.assertEqual(
                WorkJournal(path).entry("assessment/status"),
                {"state": "complete"},
            )
            self.assertEqual(
                json.loads((path / "work-journal.json").read_text())["format_version"],
                1,
            )


if __name__ == "__main__":
    unittest.main()

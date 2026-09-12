import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from drivershub_migration.storage import sha256
from drivershub_migration.verify import verify_export


class VerifyTests(unittest.TestCase):
    def test_verifies_referenced_files(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            data = b"source data\n"
            (directory / "data.json").write_bytes(data)
            (directory / "export.json").write_text(
                json.dumps(
                    {
                        "format_version": 1,
                        "resource": {
                            "path": "data.json",
                            "sha256": sha256(data),
                        },
                    }
                )
            )
            self.assertEqual(verify_export(directory)["state"], "complete")

            (directory / "data.json").write_bytes(b"changed")
            result = verify_export(directory)
            self.assertEqual(result["state"], "failed")
            self.assertEqual(result["failures"][0]["error"], "Checksum mismatch")

    def test_rejects_path_outside_directory(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "export.json").write_text(
                json.dumps(
                    {
                        "format_version": 1,
                        "resource": {"path": "../outside", "sha256": "invalid"},
                    }
                )
            )
            result = verify_export(directory)
            self.assertEqual(result["state"], "failed")
            self.assertEqual(result["failures"][0]["error"], "Path leaves migration directory")


if __name__ == "__main__":
    unittest.main()

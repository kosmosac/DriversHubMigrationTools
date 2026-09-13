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
            result = verify_export(directory)
            self.assertEqual(result["integrity"], "valid")
            self.assertEqual(result["manifest_states"], {})

            (directory / "data.json").write_bytes(b"changed")
            result = verify_export(directory)
            self.assertEqual(result["integrity"], "invalid")
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
            self.assertEqual(result["integrity"], "invalid")
            self.assertEqual(result["failures"][0]["error"], "Path leaves migration directory")

    def test_reports_manifest_states_separately_from_integrity(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "export.json").write_text(
                json.dumps(
                    {
                        "format_version": 1,
                        "resource": {"state": "complete"},
                        "optional": {"state": "skipped"},
                    }
                )
            )
            result = verify_export(directory)
            self.assertEqual(result["integrity"], "valid")
            self.assertEqual(
                result["manifest_states"], {"complete": 1, "skipped": 1}
            )


if __name__ == "__main__":
    unittest.main()

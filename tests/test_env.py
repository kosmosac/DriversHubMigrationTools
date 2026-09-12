import tempfile
import unittest
from pathlib import Path

from drivershub_migration.env import EnvFileError, read_env


class EnvFileTests(unittest.TestCase):
    def test_reads_plain_and_quoted_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "# comment\nTOKEN=secret\nURL=\"https://example.test/api\"\n",
                encoding="utf-8",
            )
            self.assertEqual(
                read_env(path),
                {"TOKEN": "secret", "URL": "https://example.test/api"},
            )

    def test_missing_file_is_empty(self):
        self.assertEqual(read_env(Path("does-not-exist.env")), {})

    def test_rejects_invalid_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("invalid\n", encoding="utf-8")
            with self.assertRaises(EnvFileError):
                read_env(path)


if __name__ == "__main__":
    unittest.main()

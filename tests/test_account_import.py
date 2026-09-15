import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from drivershub_migration.account_import import build_account_stage


class AccountImportTests(unittest.TestCase):
    def _directory(self, bootstrap):
        temporary = TemporaryDirectory()
        directory = Path(temporary.name)
        (directory / "normalized").mkdir()
        (directory / "target-preflight.json").write_text(
            json.dumps({"bootstrap": bootstrap})
        )
        (directory / "import-plan.json").write_text(
            json.dumps(
                {
                    "state": "complete",
                    "accounts": [{"source_uid": 1, "target_userid": 1}],
                }
            )
        )
        (directory / "normalized" / "profiles.json").write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "uid": 1,
                            "userid": 1,
                            "name": "Example O'Brian",
                            "email": "admin@example.invalid",
                            "avatar": "",
                            "bio": "Backslash \\",
                            "roles": [20, 21],
                            "discordid": "123456",
                            "steamid": "76561190000000000",
                            "truckersmpid": 42,
                            "join_timestamp": 1_700_000_000,
                            "tracker": "tracksim",
                        }
                    ]
                }
            )
        )
        return temporary, directory

    def test_relocates_bootstrap_and_inserts_source_account(self):
        temporary, directory = self._directory(
            {
                "state": "ready",
                "action": "retain-as-recovery-account",
                "original_uid": 1,
                "original_userid": 1,
                "replacement_uid": 100,
                "replacement_userid": 200,
            }
        )
        with temporary:
            sql, summary = build_account_stage(directory)

        self.assertTrue(sql.startswith("SET time_zone = '+00:00';\nSTART TRANSACTION;"))
        self.assertIn("UPDATE `user_password` SET `uid`=100 WHERE `uid`=1", sql)
        self.assertIn("UPDATE `dlog` SET `userid`=200 WHERE `userid`=1", sql)
        self.assertIn("INSERT INTO `user`", sql)
        self.assertIn("CONVERT(0x4578616d706c65204f27427269616e USING utf8mb4)", sql)
        self.assertIn(
            "`join_timestamp`,`mfa_secret`,`tracker_in_use`", sql
        )
        self.assertIn(
            "1700000000,CONVERT(0x USING utf8mb4),2", sql
        )
        self.assertTrue(sql.endswith("COMMIT;\n"))
        self.assertEqual(summary["inserted_accounts"], 1)

    def test_merges_matching_bootstrap_without_replacing_password(self):
        temporary, directory = self._directory(
            {
                "state": "ready",
                "action": "merge-with-source-administrator",
                "source_uid": 1,
                "target_uid": 50,
                "target_userid": -1,
            }
        )
        with temporary:
            sql, summary = build_account_stage(directory)

        self.assertIn("UPDATE `user_password` SET `uid`=1 WHERE `uid`=50", sql)
        self.assertIn("UPDATE `dlog` SET `userid`=1 WHERE `userid`=-1", sql)
        self.assertIn("UPDATE `user` SET `userid`=1", sql)
        self.assertNotIn("INSERT INTO `user`", sql)
        self.assertNotIn("`mfa_secret`", sql)
        self.assertEqual(summary["merged_accounts"], 1)
        self.assertEqual(summary["preserved_passwords"], 1)


if __name__ == "__main__":
    unittest.main()

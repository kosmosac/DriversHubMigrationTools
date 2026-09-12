import unittest

from drivershub_migration.assess import derive_capabilities


class CapabilityTests(unittest.TestCase):
    def test_detects_administrative_configuration_and_plugins(self):
        results = {
            "backend-config": {
                "config": {
                    "plugins": ["announcement"],
                    "external_plugins": ["client-config", "private-plugin"],
                },
                "backup": {},
                "config_last_modified": 1,
                "backup_last_modified": 1,
            },
            "client-config": {"abbr": "example"},
        }
        self.assertEqual(
            derive_capabilities(results),
            {
                "administrative_config": True,
                "standard_plugins": ["announcement"],
                "external_plugins": ["client-config", "private-plugin"],
                "client_config": True,
            },
        )

    def test_rejects_public_configuration_as_administrative(self):
        capabilities = derive_capabilities(
            {"backend-config": {"config": {"name": "Example"}}}
        )
        self.assertFalse(capabilities["administrative_config"])


if __name__ == "__main__":
    unittest.main()

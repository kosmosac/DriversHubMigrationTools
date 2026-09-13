import inspect
import unittest

from drivershub_migration.assess import assess
from drivershub_migration.exporter import export_source


class RequestIntervalDefaultsTests(unittest.TestCase):
    def test_source_operations_stay_below_sixty_requests_per_minute(self):
        self.assertGreaterEqual(
            inspect.signature(assess).parameters["request_interval"].default,
            1.0,
        )
        self.assertGreaterEqual(
            inspect.signature(export_source).parameters["request_interval"].default,
            1.0,
        )


if __name__ == "__main__":
    unittest.main()

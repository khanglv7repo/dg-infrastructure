from __future__ import annotations

import unittest

import sys
from pathlib import Path


RANGER_DIR = Path(__file__).resolve().parents[1]
if str(RANGER_DIR) not in sys.path:
    sys.path.insert(0, str(RANGER_DIR))


import config


class BootstrapConfigTests(unittest.TestCase):
    def test_single_file_contains_resource_and_tag_services(self) -> None:
        value = config.load_bootstrap_config()
        self.assertEqual(value["version"], 5)
        self.assertEqual(value["resource_service"]["type"], "trino")
        self.assertEqual(value["tag_service"]["type"], "tag")
        self.assertEqual(len(value["technical_data_grants"]), 1)
        self.assertEqual(
            value["technical_data_grants"][0]["resources"]["catalog"],
            "financial",
        )

    def test_resource_service_no_longer_depends_on_legacy_yaml(self) -> None:
        value = config.load_bootstrap_config()
        service = config.resolved_resource_service(value)
        self.assertEqual(service["type"], "trino")
        self.assertTrue(service["name"])


if __name__ == "__main__":
    unittest.main()

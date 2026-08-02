from __future__ import annotations

import unittest

import config


class BootstrapConfigTests(unittest.TestCase):
    def test_single_file_contains_resource_and_tag_services(self) -> None:
        value = config.load_bootstrap_config()
        self.assertEqual(value["version"], 4)
        self.assertEqual(value["resource_service"]["type"], "trino")
        self.assertEqual(value["tag_service"]["type"], "tag")

    def test_resource_service_no_longer_depends_on_legacy_yaml(self) -> None:
        value = config.load_bootstrap_config()
        service = config.resolved_resource_service(value)
        self.assertEqual(service["type"], "trino")
        self.assertTrue(service["name"])


if __name__ == "__main__":
    unittest.main()

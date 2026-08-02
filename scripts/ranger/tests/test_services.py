from __future__ import annotations

import unittest

from reconcilers.services import _configs_match


class ServiceConfigTests(unittest.TestCase):
    def test_blank_password_does_not_force_update(self) -> None:
        current = {
            "username": "trino",
            "password": "*****",
            "jdbc.url": "jdbc:trino://trino:8080",
        }
        desired = {
            "username": "trino",
            "password": "",
            "jdbc.url": "jdbc:trino://trino:8080",
        }
        self.assertTrue(_configs_match(current, desired))

    def test_non_secret_config_mismatch_is_detected(self) -> None:
        self.assertFalse(
            _configs_match(
                {"jdbc.url": "jdbc:trino://old:8080"},
                {"jdbc.url": "jdbc:trino://trino:8080"},
            )
        )


if __name__ == "__main__":
    unittest.main()

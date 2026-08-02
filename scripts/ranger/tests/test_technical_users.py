from __future__ import annotations

import sys
import unittest
from pathlib import Path


RANGER_DIR = Path(__file__).resolve().parents[1]
if str(RANGER_DIR) not in sys.path:
    sys.path.insert(0, str(RANGER_DIR))

from reconcilers.technical_users import reconcile_technical_user  # noqa: E402


class FakeClient:
    def __init__(self, current=None):
        self.current = current
        self.created = None

    def find_user(self, name):
        if self.current and self.current.get("name") == name:
            return self.current
        return None

    def create_external_user(self, payload):
        self.created = dict(payload)
        self.current = {**payload, "id": 101}
        return self.current


class TechnicalUsersTest(unittest.TestCase):
    def test_existing_user_is_not_mutated(self):
        current = {
            "name": "governance-verifier-bot",
            "userSource": 4,
            "status": 1,
        }
        client = FakeClient(current=current)

        action, value = reconcile_technical_user(
            client,
            {"name": "governance-verifier-bot", "userSource": 1},
        )

        self.assertEqual("unchanged", action)
        self.assertEqual(current, value)
        self.assertIsNone(client.created)

    def test_missing_user_is_created_as_external_without_password(self):
        client = FakeClient()

        action, value = reconcile_technical_user(
            client,
            {
                "name": "governance-verifier-bot",
                "description": "technical principal",
            },
        )

        self.assertEqual("created", action)
        self.assertEqual(1, value["userSource"])
        self.assertEqual(1, value["status"])
        self.assertNotIn("password", client.created)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path


RANGER_DIR = Path(__file__).resolve().parents[1]
if str(RANGER_DIR) not in sys.path:
    sys.path.insert(0, str(RANGER_DIR))

from reconcilers.system_grants import reconcile_system_grant  # noqa: E402


SERVICE_DEF = {
    "resources": [
        {"name": "queryid", "label": "Query ID"},
        {"name": "trinouser", "label": "Trino User"},
    ],
    "accessTypes": [
        {"name": "execute", "label": "Execute"},
        {"name": "impersonate", "label": "Impersonate"},
    ],
}

EXECUTE_GRANT = {
    "name": "dg-system-governance-verifier-execute",
    "description": "execute",
    "users": ["governance-verifier-bot"],
    "resource": {
        "semantic": "query_id",
        "aliases": ["queryid", "query id"],
        "values": ["*"],
    },
    "accesses": ["execute"],
}


class FakeClient:
    def __init__(self, policies=None, user_exists=True):
        self.policies = list(policies or [])
        self.user_exists = user_exists
        self.updated = None
        self.created = None

    def find_user(self, name):
        if self.user_exists:
            return {"name": name}
        return None

    def find_group(self, name):
        return {"name": name}

    def list_policies(self, service):
        return self.policies

    def update_policy(self, service, name, payload):
        self.updated = payload
        return payload

    def create_policy(self, payload):
        self.created = payload
        return payload


class SystemGrantsTest(unittest.TestCase):
    def test_merges_into_existing_exact_resource_policy(self):
        existing = {
            "service": "dev_trino",
            "name": "all - queryid",
            "resources": {
                "queryid": {
                    "values": ["*"],
                    "isExcludes": False,
                    "isRecursive": False,
                }
            },
            "policyItems": [],
        }
        client = FakeClient([existing])

        action, value = reconcile_system_grant(
            client,
            EXECUTE_GRANT,
            service_name="dev_trino",
            service_def=SERVICE_DEF,
        )

        self.assertEqual("updated", action)
        self.assertEqual("all - queryid", value["name"])
        self.assertEqual(
            ["governance-verifier-bot"],
            value["policyItems"][-1]["users"],
        )
        self.assertEqual(
            "execute",
            value["policyItems"][-1]["accesses"][0]["type"],
        )

    def test_second_run_is_idempotent(self):
        existing = {
            "service": "dev_trino",
            "name": "all - queryid",
            "resources": {
                "queryid": {
                    "values": ["*"],
                    "isExcludes": False,
                    "isRecursive": False,
                }
            },
            "policyItems": [
                {
                    "users": ["governance-verifier-bot"],
                    "groups": [],
                    "accesses": [
                        {"type": "execute", "isAllowed": True}
                    ],
                }
            ],
        }
        client = FakeClient([existing])

        action, _ = reconcile_system_grant(
            client,
            EXECUTE_GRANT,
            service_name="dev_trino",
            service_def=SERVICE_DEF,
        )

        self.assertEqual("unchanged", action)
        self.assertIsNone(client.updated)

    def test_creates_fallback_when_exact_resource_policy_absent(self):
        client = FakeClient([])

        action, value = reconcile_system_grant(
            client,
            EXECUTE_GRANT,
            service_name="dev_trino",
            service_def=SERVICE_DEF,
        )

        self.assertEqual("created", action)
        self.assertEqual(EXECUTE_GRANT["name"], value["name"])
        self.assertEqual(["*"], value["resources"]["queryid"]["values"])

    def test_missing_user_fails_before_policy_write(self):
        client = FakeClient([], user_exists=False)

        with self.assertRaisesRegex(RuntimeError, "missing Ranger user"):
            reconcile_system_grant(
                client,
                EXECUTE_GRANT,
                service_name="dev_trino",
                service_def=SERVICE_DEF,
            )

        self.assertIsNone(client.created)
        self.assertIsNone(client.updated)


if __name__ == "__main__":
    unittest.main()

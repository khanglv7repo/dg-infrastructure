from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


RANGER_DIR = Path(__file__).resolve().parents[1]
if str(RANGER_DIR) not in sys.path:
    sys.path.insert(0, str(RANGER_DIR))

from reconcilers.technical_data_grants import (  # noqa: E402
    reconcile_technical_data_grant,
)


SERVICE_DEF = {
    "resources": [
        {
            "name": "catalog",
            "label": "Trino Catalog",
            "parent": "",
            "isValidLeaf": True,
        },
        {
            "name": "schema",
            "label": "Trino Schema",
            "parent": "catalog",
            "isValidLeaf": True,
        },
        {
            "name": "table",
            "label": "Trino Table",
            "parent": "schema",
            "isValidLeaf": True,
        },
        {
            "name": "column",
            "label": "Trino Column",
            "parent": "table",
            "isValidLeaf": True,
        },
    ],
    "accessTypes": [
        {"name": "select", "label": "Select"},
    ],
}


GRANT = {
    "name": "dg-technical-governance-verifier-financial-read",
    "description": "read financial",
    "users": ["governance-verifier-bot"],
    "resources": {
        "catalog": "financial",
        "schema": "*",
        "table": "*",
        "column": "*",
    },
    "accesses": ["select"],
}


class FakeClient:
    def __init__(self, policies=None):
        self.policies = copy.deepcopy(policies or [])
        self.created = []
        self.updated = []

    def find_user(self, name):
        if name == "governance-verifier-bot":
            return {"name": name, "id": 1}
        return None

    def find_group(self, name):
        return None

    def list_policies(self, service):
        return [
            copy.deepcopy(policy)
            for policy in self.policies
            if policy.get("service") == service
        ]

    def create_policy(self, payload):
        value = {**copy.deepcopy(payload), "id": len(self.policies) + 1}
        self.policies.append(value)
        self.created.append(value)
        return copy.deepcopy(value)

    def update_policy(self, service, name, payload):
        value = copy.deepcopy(payload)
        for index, policy in enumerate(self.policies):
            if policy.get("service") == service and policy.get("name") == name:
                self.policies[index] = value
                break
        else:
            raise AssertionError("policy not found")
        self.updated.append(value)
        return copy.deepcopy(value)


class TechnicalDataGrantTests(unittest.TestCase):
    def test_expands_one_logical_grant_to_each_trino_resource_depth(self):
        client = FakeClient()

        results = reconcile_technical_data_grant(
            client,
            GRANT,
            service_name="dev_trino",
            service_def=SERVICE_DEF,
        )

        self.assertEqual(["created"] * 4, [action for action, _ in results])
        self.assertEqual(
            [
                "dg-technical-governance-verifier-financial-read-catalog",
                "dg-technical-governance-verifier-financial-read-schema",
                "dg-technical-governance-verifier-financial-read-table",
                "dg-technical-governance-verifier-financial-read-column",
            ],
            [policy["name"] for _, policy in results],
        )
        self.assertEqual(
            ["catalog"],
            list(results[0][1]["resources"]),
        )
        self.assertEqual(
            ["catalog", "schema"],
            list(results[1][1]["resources"]),
        )
        self.assertEqual(
            ["catalog", "schema", "table", "column"],
            list(results[3][1]["resources"]),
        )
        self.assertEqual(
            ["financial"],
            results[3][1]["resources"]["catalog"]["values"],
        )
        self.assertEqual(
            ["*"],
            results[3][1]["resources"]["column"]["values"],
        )

    def test_second_run_is_idempotent(self):
        client = FakeClient()
        reconcile_technical_data_grant(
            client,
            GRANT,
            service_name="dev_trino",
            service_def=SERVICE_DEF,
        )

        second = reconcile_technical_data_grant(
            client,
            GRANT,
            service_name="dev_trino",
            service_def=SERVICE_DEF,
        )

        self.assertEqual(["unchanged"] * 4, [action for action, _ in second])
        self.assertEqual(4, len(client.created))
        self.assertEqual([], client.updated)

    def test_existing_exact_resource_policy_is_merged_not_duplicated(self):
        existing = {
            "id": 10,
            "service": "dev_trino",
            "name": "existing-financial-catalog-policy",
            "resources": {
                "catalog": {
                    "values": ["financial"],
                    "isExcludes": False,
                    "isRecursive": False,
                }
            },
            "policyItems": [],
        }
        client = FakeClient([existing])

        results = reconcile_technical_data_grant(
            client,
            {**GRANT, "resources": {"catalog": "financial"}},
            service_name="dev_trino",
            service_def=SERVICE_DEF,
        )

        self.assertEqual("updated", results[0][0])
        self.assertEqual("existing-financial-catalog-policy", results[0][1]["name"])
        self.assertEqual([], client.created)
        self.assertEqual(1, len(client.updated))
        item = client.updated[0]["policyItems"][0]
        self.assertEqual(["governance-verifier-bot"], item["users"])
        self.assertEqual("select", item["accesses"][0]["type"])

    def test_rejects_non_contiguous_resource_path(self):
        client = FakeClient()
        bad = {
            **GRANT,
            "resources": {
                "catalog": "financial",
                "table": "*",
            },
        }

        with self.assertRaisesRegex(RuntimeError, "contiguous hierarchy"):
            reconcile_technical_data_grant(
                client,
                bad,
                service_name="dev_trino",
                service_def=SERVICE_DEF,
            )


if __name__ == "__main__":
    unittest.main()

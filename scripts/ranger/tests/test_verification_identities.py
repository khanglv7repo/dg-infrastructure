from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml


RANGER_DIR = Path(__file__).resolve().parents[1]
if str(RANGER_DIR) not in sys.path:
    sys.path.insert(0, str(RANGER_DIR))

BOOTSTRAP_PATH = RANGER_DIR / "bootstrap.yaml"

POLICY_USER = "governance-policy-verifier-bot"
CONTROL_USER = "governance-verifier-bot"


class VerificationIdentityContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = yaml.safe_load(BOOTSTRAP_PATH.read_text(encoding="utf-8"))

    def test_both_verification_principals_are_bootstrapped(self) -> None:
        names = {
            str(item.get("name"))
            for item in self.config["technical_users"]
        }
        self.assertIn(POLICY_USER, names)
        self.assertIn(CONTROL_USER, names)

    def test_both_can_execute_and_self_identify_in_trino(self) -> None:
        execute_users: set[str] = set()
        self_identity: dict[str, set[str]] = {}

        for grant in self.config["system_grants"]:
            semantic = str((grant.get("resource") or {}).get("semantic") or "")
            users = {str(value) for value in grant.get("users", [])}
            values = {
                str(value)
                for value in (grant.get("resource") or {}).get("values", [])
            }
            accesses = {str(value) for value in grant.get("accesses", [])}

            if semantic == "query_id" and "execute" in accesses:
                execute_users |= users
            if semantic == "trino_user" and "impersonate" in accesses:
                for user in users:
                    self_identity.setdefault(user, set()).update(values)

        for user in (POLICY_USER, CONTROL_USER):
            self.assertIn(user, execute_users)
            self.assertIn(user, self_identity)
            self.assertIn(user, self_identity[user])

    def test_only_control_identity_has_broad_baseline_data_read(self) -> None:
        data_users = {
            str(user)
            for grant in self.config["technical_data_grants"]
            for user in grant.get("users", [])
        }

        self.assertIn(CONTROL_USER, data_users)
        self.assertNotIn(POLICY_USER, data_users)


if __name__ == "__main__":
    unittest.main()

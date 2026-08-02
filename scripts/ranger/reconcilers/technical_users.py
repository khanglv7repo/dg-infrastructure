from __future__ import annotations

from typing import Any

from ranger_client import RangerClient


USER_DEFAULTS = {
    "status": 1,
    "userSource": 1,  # Ranger external principal
    "isVisible": 1,
    "userRoleList": ["ROLE_USER"],
}


def _desired_external_user(config: dict[str, Any]) -> dict[str, Any]:
    name = str(config.get("name") or "").strip()
    if not name:
        raise RuntimeError("Ranger technical user is missing name")

    roles = config.get("userRoleList", USER_DEFAULTS["userRoleList"])
    if not isinstance(roles, list) or not roles:
        raise RuntimeError(
            f"Ranger technical user {name!r} requires userRoleList"
        )

    return {
        "name": name,
        "firstName": str(config.get("firstName") or name),
        "lastName": str(config.get("lastName") or ""),
        "description": str(config.get("description") or ""),
        "status": int(config.get("status", USER_DEFAULTS["status"])),
        "userSource": int(
            config.get("userSource", USER_DEFAULTS["userSource"])
        ),
        "isVisible": int(
            config.get("isVisible", USER_DEFAULTS["isVisible"])
        ),
        "userRoleList": [str(role) for role in roles],
    }


def reconcile_technical_user(
    client: RangerClient,
    config: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Ensure a Ranger policy principal exists.

    Existing users are intentionally not mutated. They might be owned by
    Ranger UserSync/LDAP/AD in a production-like environment. Local bootstrap
    creates only a missing external principal and never creates a password.
    """
    desired = _desired_external_user(config)
    current = client.find_user(str(desired["name"]))
    if current is not None:
        return "unchanged", current

    created = client.create_external_user(desired)
    return "created", created


def reconcile_technical_users(
    client: RangerClient,
    configs: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    return [
        reconcile_technical_user(client, config)
        for config in configs
    ]

from __future__ import annotations

from typing import Any

from ranger_client import RangerClient


def _sorted_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(str(item) for item in value)


def canonical_resources(value: object) -> dict[str, Any]:
    """Normalize a Ranger resource map for deterministic comparisons."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, resource in value.items():
        if not isinstance(resource, dict):
            continue
        result[str(key)] = {
            "values": _sorted_strings(resource.get("values")),
            "isExcludes": bool(resource.get("isExcludes", False)),
            "isRecursive": bool(resource.get("isRecursive", False)),
        }
    return result


def _allowed_accesses(item: dict[str, Any]) -> set[str]:
    accesses = item.get("accesses")
    if not isinstance(accesses, list):
        return set()
    return {
        str(access.get("type"))
        for access in accesses
        if isinstance(access, dict)
        and access.get("type")
        and bool(access.get("isAllowed", False))
    }


def _principal_has_accesses(
    items: object,
    *,
    principal_type: str,
    principal: str,
    accesses: set[str],
) -> bool:
    if not isinstance(items, list):
        return False
    field = "users" if principal_type == "user" else "groups"
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_principals = item.get(field, [])
        if not isinstance(raw_principals, list):
            continue
        principals = {str(value) for value in raw_principals}
        if principal in principals and accesses <= _allowed_accesses(item):
            return True
    return False


def grant_is_satisfied(
    policy: dict[str, Any],
    *,
    users: list[str],
    groups: list[str],
    accesses: list[str],
) -> bool:
    items = policy.get("policyItems")
    wanted_accesses = set(accesses)
    return all(
        _principal_has_accesses(
            items,
            principal_type="user",
            principal=user,
            accesses=wanted_accesses,
        )
        for user in users
    ) and all(
        _principal_has_accesses(
            items,
            principal_type="group",
            principal=group,
            accesses=wanted_accesses,
        )
        for group in groups
    )


def validate_principals_exist(
    client: RangerClient,
    *,
    grant_label: str,
    users: list[str],
    groups: list[str],
) -> None:
    for user in users:
        if client.find_user(user) is None:
            raise RuntimeError(
                f"{grant_label} references missing Ranger user {user!r}. "
                "Add a technical user to bootstrap.yaml or provision the "
                "principal through Ranger UserSync/IAM."
            )

    for group in groups:
        if client.find_group(group) is None:
            raise RuntimeError(
                f"{grant_label} references missing Ranger group {group!r}. "
                "Add the group to bootstrap.yaml or provision it through "
                "Ranger UserSync/IAM."
            )


def grant_policy_item(
    *,
    users: list[str],
    groups: list[str],
    accesses: list[str],
) -> dict[str, Any]:
    return {
        "users": users,
        "groups": groups,
        "roles": [],
        "conditions": [],
        "delegateAdmin": False,
        "accesses": [
            {"type": access, "isAllowed": True} for access in accesses
        ],
    }


def find_exact_resource_policy(
    policies: list[dict[str, Any]],
    resources: dict[str, Any],
) -> dict[str, Any] | None:
    """Find the single policy with the same exact resource signature."""
    wanted = canonical_resources(resources)
    matches = [
        policy
        for policy in policies
        if canonical_resources(policy.get("resources")) == wanted
    ]
    if len(matches) > 1:
        names = [str(policy.get("name")) for policy in matches]
        raise RuntimeError(
            "Ranger returned multiple policies for the same exact resource: "
            f"{names}"
        )
    return matches[0] if matches else None


def reconcile_policy_grant(
    client: RangerClient,
    *,
    service_name: str,
    fallback_policy_name: str,
    description: str,
    resources: dict[str, Any],
    users: list[str],
    groups: list[str],
    accesses: list[str],
    grant_label: str,
) -> tuple[str, dict[str, Any]]:
    """Ensure a grant while preserving any policy that already owns resource.

    Ranger rejects a second policy for some semantically identical resources.
    Therefore this reconciles by resource signature first, then merges a policy
    item when an existing policy already owns the exact resource.
    """
    validate_principals_exist(
        client,
        grant_label=grant_label,
        users=users,
        groups=groups,
    )

    policies = client.list_policies(service_name)
    existing = find_exact_resource_policy(policies, resources)

    if existing is not None:
        if grant_is_satisfied(
            existing,
            users=users,
            groups=groups,
            accesses=accesses,
        ):
            return "unchanged", existing

        current_items = existing.get("policyItems")
        items = list(current_items) if isinstance(current_items, list) else []
        items.append(
            grant_policy_item(
                users=users,
                groups=groups,
                accesses=accesses,
            )
        )
        payload = {**existing, "policyItems": items}
        return "updated", client.update_policy(
            str(existing["service"]),
            str(existing["name"]),
            payload,
        )

    payload = {
        "service": service_name,
        "name": fallback_policy_name,
        "description": description,
        "isEnabled": True,
        "isAuditEnabled": True,
        "resources": resources,
        "policyItems": [
            grant_policy_item(
                users=users,
                groups=groups,
                accesses=accesses,
            )
        ],
    }
    return "created", client.create_policy(payload)

from __future__ import annotations

from typing import Any

from ranger_client import RangerClient
from service_def import resolve_access_name, resolve_resource_name


def _sorted_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(str(item) for item in value)


def _canonical_resources(value: object) -> dict[str, Any]:
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


def _grant_is_satisfied(
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


def _build_grant(
    config: dict[str, Any],
    *,
    service_def: dict[str, Any],
) -> tuple[dict[str, Any], list[str], list[str], list[str]]:
    resource = config.get("resource")
    if not isinstance(resource, dict):
        raise RuntimeError(f"System grant {config.get('name')!r} has no resource")

    semantic = str(resource.get("semantic") or "").strip()
    aliases = resource.get("aliases")
    if not semantic or not isinstance(aliases, list):
        raise RuntimeError(
            f"System grant {config.get('name')!r} has invalid resource config"
        )

    resource_name = resolve_resource_name(
        service_def,
        semantic=semantic,
        aliases=[str(alias) for alias in aliases],
    )

    raw_accesses = config.get("accesses")
    if not isinstance(raw_accesses, list) or not raw_accesses:
        raise RuntimeError(f"System grant {config.get('name')!r} has no accesses")
    accesses = [
        resolve_access_name(service_def, str(access)) for access in raw_accesses
    ]

    values = resource.get("values")
    if not isinstance(values, list) or not values:
        raise RuntimeError(f"System grant {config.get('name')!r} has no values")

    raw_users = config.get("users", [])
    raw_groups = config.get("groups", [])
    if not isinstance(raw_users, list) or not isinstance(raw_groups, list):
        raise RuntimeError(f"System grant {config.get('name')!r} principals invalid")
    users = [str(user) for user in raw_users]
    groups = [str(group) for group in raw_groups]
    if not users and not groups:
        raise RuntimeError(f"System grant {config.get('name')!r} has no principals")

    resources = {
        resource_name: {
            "values": [str(value) for value in values],
            "isExcludes": False,
            "isRecursive": False,
        }
    }
    return resources, users, groups, accesses


def _validate_principals_exist(
    client: RangerClient,
    *,
    grant_name: str,
    users: list[str],
    groups: list[str],
) -> None:
    for user in users:
        if client.find_user(user) is None:
            raise RuntimeError(
                f"System grant {grant_name!r} references missing Ranger user "
                f"{user!r}. Add a local technical user to bootstrap.yaml or "
                "provision the principal through Ranger UserSync/IAM."
            )

    for group in groups:
        if client.find_group(group) is None:
            raise RuntimeError(
                f"System grant {grant_name!r} references missing Ranger group "
                f"{group!r}. Add the group to bootstrap.yaml or provision it "
                "through Ranger UserSync/IAM."
            )


def _grant_policy_item(
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


def _find_exact_resource_policy(
    policies: list[dict[str, Any]],
    resources: dict[str, Any],
) -> dict[str, Any] | None:
    """Find a policy with the same resource signature.

    We intentionally do not reuse a broader wildcard policy for a narrower
    grant, because doing so could accidentally widen a permission such as
    impersonation.
    """
    wanted = _canonical_resources(resources)
    matches = [
        policy
        for policy in policies
        if _canonical_resources(policy.get("resources")) == wanted
    ]
    if len(matches) > 1:
        names = [str(policy.get("name")) for policy in matches]
        raise RuntimeError(
            "Ranger returned multiple policies for the same exact resource: "
            f"{names}"
        )
    return matches[0] if matches else None


def _update_existing_policy_with_grant(
    client: RangerClient,
    policy: dict[str, Any],
    *,
    users: list[str],
    groups: list[str],
    accesses: list[str],
) -> tuple[str, dict[str, Any]]:
    if _grant_is_satisfied(
        policy,
        users=users,
        groups=groups,
        accesses=accesses,
    ):
        return "unchanged", policy

    current_items = policy.get("policyItems")
    items = list(current_items) if isinstance(current_items, list) else []
    items.append(
        _grant_policy_item(users=users, groups=groups, accesses=accesses)
    )

    payload = {**policy, "policyItems": items}
    return "updated", client.update_policy(
        str(policy["service"]),
        str(policy["name"]),
        payload,
    )


def _create_fallback_policy(
    client: RangerClient,
    config: dict[str, Any],
    *,
    service_name: str,
    resources: dict[str, Any],
    users: list[str],
    groups: list[str],
    accesses: list[str],
) -> tuple[str, dict[str, Any]]:
    name = str(config.get("name") or "").strip()
    if not name:
        raise RuntimeError("System grant requires a fallback policy name")

    payload = {
        "service": service_name,
        "name": name,
        "description": str(config.get("description") or ""),
        "isEnabled": True,
        "isAuditEnabled": True,
        "resources": resources,
        "policyItems": [
            _grant_policy_item(users=users, groups=groups, accesses=accesses)
        ],
    }
    return "created", client.create_policy(payload)


def reconcile_system_grant(
    client: RangerClient,
    config: dict[str, Any],
    *,
    service_name: str,
    service_def: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Ensure one baseline Trino grant without taking policy-name ownership."""
    grant_name = str(config.get("name") or "").strip()
    resources, users, groups, accesses = _build_grant(
        config,
        service_def=service_def,
    )

    # Produce an actionable local error before Ranger rejects the policy body.
    _validate_principals_exist(
        client,
        grant_name=grant_name,
        users=users,
        groups=groups,
    )

    policies = client.list_policies(service_name)
    existing = _find_exact_resource_policy(policies, resources)

    if existing is not None:
        return _update_existing_policy_with_grant(
            client,
            existing,
            users=users,
            groups=groups,
            accesses=accesses,
        )

    return _create_fallback_policy(
        client,
        config,
        service_name=service_name,
        resources=resources,
        users=users,
        groups=groups,
        accesses=accesses,
    )


def reconcile_system_grants(
    client: RangerClient,
    configs: list[dict[str, Any]],
    *,
    service_name: str,
    service_def: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    return [
        reconcile_system_grant(
            client,
            config,
            service_name=service_name,
            service_def=service_def,
        )
        for config in configs
    ]

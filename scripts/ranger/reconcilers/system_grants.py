from __future__ import annotations

from typing import Any

from ranger_client import RangerClient
from reconcilers.policy_grants import reconcile_policy_grant
from service_def import resolve_access_name, resolve_resource_name


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


def reconcile_system_grant(
    client: RangerClient,
    config: dict[str, Any],
    *,
    service_name: str,
    service_def: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Ensure one baseline Trino grant without taking policy-name ownership."""
    grant_name = str(config.get("name") or "").strip()
    if not grant_name:
        raise RuntimeError("System grant requires name")

    resources, users, groups, accesses = _build_grant(
        config,
        service_def=service_def,
    )
    return reconcile_policy_grant(
        client,
        service_name=service_name,
        fallback_policy_name=grant_name,
        description=str(config.get("description") or ""),
        resources=resources,
        users=users,
        groups=groups,
        accesses=accesses,
        grant_label=f"System grant {grant_name!r}",
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

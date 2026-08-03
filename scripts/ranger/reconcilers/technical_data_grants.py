from __future__ import annotations

from typing import Any

from ranger_client import RangerClient
from reconcilers.policy_grants import reconcile_policy_grant
from service_def import (
    ServiceDefinitionError,
    resolve_access_name,
    resolve_resource_item,
)


# Logical resource path expected by the Trino Ranger service definition. The
# live service definition is still authoritative: names and hierarchy are
# resolved/validated at runtime before any policy is written.
RESOURCE_PATH = ("catalog", "schema", "table", "column")
RESOURCE_ALIASES = {
    "catalog": ("trino catalog",),
    "schema": ("trino schema",),
    "table": ("trino table",),
    "column": ("trino column",),
}


def _as_values(value: object, *, field: str, grant_name: str) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = [str(item) for item in value]
    else:
        raise RuntimeError(
            f"Technical data grant {grant_name!r} resource {field!r} must "
            "be a string or list"
        )

    values = [item.strip() for item in values if item.strip()]
    if not values:
        raise RuntimeError(
            f"Technical data grant {grant_name!r} resource {field!r} is empty"
        )
    return values


def _resolve_path(
    service_def: dict[str, Any],
    configured_resources: dict[str, Any],
    *,
    grant_name: str,
) -> list[tuple[str, str, list[str]]]:
    """Resolve and validate the configured catalog->column hierarchy."""
    unknown = sorted(set(configured_resources) - set(RESOURCE_PATH))
    if unknown:
        raise RuntimeError(
            f"Technical data grant {grant_name!r} has unknown resources: "
            f"{unknown}"
        )

    configured = [key for key in RESOURCE_PATH if key in configured_resources]
    if not configured or configured[0] != "catalog":
        raise RuntimeError(
            f"Technical data grant {grant_name!r} must start with catalog"
        )

    expected_prefix = list(RESOURCE_PATH[: len(configured)])
    if configured != expected_prefix:
        raise RuntimeError(
            f"Technical data grant {grant_name!r} resources must form a "
            f"contiguous hierarchy; got={configured} expected={expected_prefix}"
        )

    resolved: list[tuple[str, str, list[str]]] = []
    previous_actual_name = ""

    for semantic in configured:
        item = resolve_resource_item(
            service_def,
            semantic=semantic,
            aliases=RESOURCE_ALIASES.get(semantic, ()),
        )
        actual_name = str(item.get("name") or "").strip()
        if not actual_name:
            raise ServiceDefinitionError(
                f"Resolved Trino resource {semantic!r} has no name"
            )

        actual_parent = str(item.get("parent") or "").strip()
        if previous_actual_name and actual_parent != previous_actual_name:
            raise ServiceDefinitionError(
                f"Unexpected Trino resource hierarchy for {semantic!r}: "
                f"parent={actual_parent!r}, expected={previous_actual_name!r}"
            )
        if not previous_actual_name and actual_parent:
            raise ServiceDefinitionError(
                f"Unexpected root resource {semantic!r}: "
                f"parent={actual_parent!r}"
            )

        if not bool(item.get("isValidLeaf", False)):
            raise ServiceDefinitionError(
                f"Trino resource {actual_name!r} is not a valid policy leaf"
            )

        resolved.append(
            (
                semantic,
                actual_name,
                _as_values(
                    configured_resources[semantic],
                    field=semantic,
                    grant_name=grant_name,
                ),
            )
        )
        previous_actual_name = actual_name

    return resolved


def _principals(config: dict[str, Any], grant_name: str) -> tuple[list[str], list[str]]:
    raw_users = config.get("users", [])
    raw_groups = config.get("groups", [])
    if not isinstance(raw_users, list) or not isinstance(raw_groups, list):
        raise RuntimeError(
            f"Technical data grant {grant_name!r} users/groups must be lists"
        )

    users = [str(item) for item in raw_users]
    groups = [str(item) for item in raw_groups]
    if not users and not groups:
        raise RuntimeError(
            f"Technical data grant {grant_name!r} requires a user or group"
        )
    return users, groups


def _accesses(config: dict[str, Any], service_def: dict[str, Any], grant_name: str) -> list[str]:
    raw_accesses = config.get("accesses")
    if not isinstance(raw_accesses, list) or not raw_accesses:
        raise RuntimeError(
            f"Technical data grant {grant_name!r} requires accesses"
        )
    return [
        resolve_access_name(service_def, str(access)) for access in raw_accesses
    ]


def _resource_map(
    path: list[tuple[str, str, list[str]]],
    depth: int,
) -> dict[str, Any]:
    return {
        actual_name: {
            "values": values,
            "isExcludes": False,
            "isRecursive": False,
        }
        for _, actual_name, values in path[:depth]
    }


def reconcile_technical_data_grant(
    client: RangerClient,
    config: dict[str, Any],
    *,
    service_name: str,
    service_def: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Ensure read grants at every Trino hierarchy depth.

    Trino 482 checks catalog, schema, table and column resources separately.
    A deep column policy is not sufficient for direct catalog/schema checks.
    Therefore one logical technical-data grant is expanded into a policy/grant
    at every configured valid leaf depth.
    """
    grant_name = str(config.get("name") or "").strip()
    if not grant_name:
        raise RuntimeError("Technical data grant requires name")

    raw_resources = config.get("resources")
    if not isinstance(raw_resources, dict):
        raise RuntimeError(
            f"Technical data grant {grant_name!r} requires resources object"
        )

    path = _resolve_path(
        service_def,
        raw_resources,
        grant_name=grant_name,
    )
    users, groups = _principals(config, grant_name)
    accesses = _accesses(config, service_def, grant_name)
    description = str(config.get("description") or "")

    results: list[tuple[str, dict[str, Any]]] = []
    for depth, (semantic, _, _) in enumerate(path, start=1):
        resources = _resource_map(path, depth)
        fallback_name = f"{grant_name}-{semantic}"
        results.append(
            reconcile_policy_grant(
                client,
                service_name=service_name,
                fallback_policy_name=fallback_name,
                description=(
                    f"{description} [technical data scope: {semantic}]".strip()
                ),
                resources=resources,
                users=users,
                groups=groups,
                accesses=accesses,
                grant_label=(
                    f"Technical data grant {grant_name!r}/{semantic}"
                ),
            )
        )
    return results


def reconcile_technical_data_grants(
    client: RangerClient,
    configs: list[dict[str, Any]],
    *,
    service_name: str,
    service_def: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    results: list[tuple[str, dict[str, Any]]] = []
    for config in configs:
        results.extend(
            reconcile_technical_data_grant(
                client,
                config,
                service_name=service_name,
                service_def=service_def,
            )
        )
    return results

from __future__ import annotations

import re
from typing import Any, Iterable


class ServiceDefinitionError(RuntimeError):
    pass


def _normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _candidate_names(item: dict[str, Any]) -> set[str]:
    values = {
        item.get("name"),
        item.get("label"),
        item.get("rbKeyLabel"),
    }
    return {_normalize(value) for value in values if value}


def _resolve_named_item(
    items: object,
    aliases: Iterable[str],
    *,
    kind: str,
) -> dict[str, Any]:
    if not isinstance(items, list):
        raise ServiceDefinitionError(f"Service definition has no {kind} list")

    wanted = {_normalize(alias) for alias in aliases if alias}
    if not wanted:
        raise ServiceDefinitionError(f"No aliases configured for {kind}")

    matches = [
        item
        for item in items
        if isinstance(item, dict) and _candidate_names(item) & wanted
    ]

    if len(matches) == 1:
        return matches[0]
    if not matches:
        available = [
            str(item.get("name"))
            for item in items
            if isinstance(item, dict) and item.get("name")
        ]
        raise ServiceDefinitionError(
            f"Could not resolve {kind} aliases {sorted(wanted)}; "
            f"available={available}"
        )
    raise ServiceDefinitionError(
        f"Ambiguous {kind} aliases {sorted(wanted)}; "
        f"matches={[item.get('name') for item in matches]}"
    )


def resolve_resource_name(
    service_def: dict[str, Any],
    *,
    semantic: str,
    aliases: Iterable[str],
) -> str:
    item = _resolve_named_item(
        service_def.get("resources"),
        [semantic, *aliases],
        kind=f"resource {semantic!r}",
    )
    name = item.get("name")
    if not name:
        raise ServiceDefinitionError("Resolved resource has no name")
    return str(name)


def resolve_access_name(
    service_def: dict[str, Any],
    access: str,
) -> str:
    item = _resolve_named_item(
        service_def.get("accessTypes"),
        [access],
        kind=f"access {access!r}",
    )
    name = item.get("name")
    if not name:
        raise ServiceDefinitionError("Resolved access has no name")
    return str(name)

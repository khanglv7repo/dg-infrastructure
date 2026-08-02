from __future__ import annotations

from typing import Any

from ranger_client import RangerClient


GROUP_DEFAULTS = {
    "groupType": 1,
    "groupSource": 0,
    "isVisible": 1,
}


def _desired(config: dict[str, Any]) -> dict[str, Any]:
    name = str(config.get("name") or "").strip()
    if not name:
        raise RuntimeError("Ranger group is missing name")
    return {
        "name": name,
        "description": str(config.get("description") or ""),
        "groupType": int(config.get("groupType", GROUP_DEFAULTS["groupType"])),
        "groupSource": int(
            config.get("groupSource", GROUP_DEFAULTS["groupSource"])
        ),
        "isVisible": int(config.get("isVisible", GROUP_DEFAULTS["isVisible"])),
    }


def _matches(current: dict[str, Any], desired: dict[str, Any]) -> bool:
    return all(current.get(key) == value for key, value in desired.items())


def reconcile_group(
    client: RangerClient,
    config: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    desired = _desired(config)
    current = client.find_group(str(desired["name"]))

    if current is None:
        return "created", client.create_group(desired)

    if _matches(current, desired):
        return "unchanged", current

    payload = {**current, **desired}
    return "updated", client.update_group(payload)


def reconcile_groups(
    client: RangerClient,
    configs: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    return [reconcile_group(client, config) for config in configs]

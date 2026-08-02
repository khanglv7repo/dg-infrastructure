from __future__ import annotations

from typing import Any

from ranger_client import RangerClient


MANAGED_FIELDS = (
    "name",
    "type",
    "displayName",
    "description",
    "isEnabled",
)


def _is_blank_secret(key: str, value: object) -> bool:
    key_lower = key.lower()
    looks_secret = "password" in key_lower or "secret" in key_lower
    return looks_secret and (value is None or str(value) == "")


def _managed_configs(value: object) -> dict[str, Any]:
    """Return config values bootstrap should actively reconcile.

    Ranger commonly masks stored passwords on reads. A blank password in local
    bootstrap config means "do not take ownership of this secret", not "erase
    the current value". Ignoring blank secrets also prevents an update loop on
    every bootstrap run.
    """
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if not _is_blank_secret(str(key), item)
    }


def _configs_match(current: object, desired: object) -> bool:
    desired_dict = _managed_configs(desired)
    current_dict = current if isinstance(current, dict) else {}
    return all(current_dict.get(key) == value for key, value in desired_dict.items())


def _matches(current: dict[str, Any], desired: dict[str, Any]) -> bool:
    for field in MANAGED_FIELDS:
        if field in desired and current.get(field) != desired.get(field):
            return False
    return _configs_match(current.get("configs"), desired.get("configs"))


def reconcile_service(
    client: RangerClient,
    desired: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    name = str(desired.get("name") or "").strip()
    if not name:
        raise RuntimeError("Ranger service is missing name")

    current = client.get_service(name)
    if current is None:
        return "created", client.create_service(desired)

    if _matches(current, desired):
        return "unchanged", current

    current_configs = current.get("configs")
    merged_configs = (
        dict(current_configs) if isinstance(current_configs, dict) else {}
    )
    merged_configs.update(_managed_configs(desired.get("configs")))

    # Preserve fields owned by other reconcilers (notably tagService) by
    # starting from current state and overlaying only desired service fields.
    payload = {
        **current,
        **desired,
        "configs": merged_configs,
    }
    return "updated", client.update_service(name, payload)

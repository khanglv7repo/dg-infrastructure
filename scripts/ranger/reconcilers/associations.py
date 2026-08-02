from __future__ import annotations

from typing import Any

from ranger_client import RangerClient


def reconcile_tag_service_association(
    client: RangerClient,
    *,
    resource_service_name: str,
    tag_service_name: str,
) -> tuple[str, dict[str, Any]]:
    current = client.get_service(resource_service_name)
    if current is None:
        raise RuntimeError(
            f"Resource service {resource_service_name!r} does not exist"
        )

    if current.get("tagService") == tag_service_name:
        return "unchanged", current

    payload = {**current, "tagService": tag_service_name}
    updated = client.update_service(resource_service_name, payload)

    if updated.get("tagService") != tag_service_name:
        fetched = client.get_service(resource_service_name)
        if fetched is None or fetched.get("tagService") != tag_service_name:
            raise RuntimeError(
                "Ranger resource/tag association did not converge: "
                f"{resource_service_name} -> {tag_service_name}"
            )
        updated = fetched

    return "updated", updated

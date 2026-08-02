from __future__ import annotations

import os
import sys
from collections import Counter
from typing import Any, Iterable

from loguru import logger

from config import (
    ENV_PATH,
    load_bootstrap_config,
    load_environment,
    resolved_resource_service,
    resolved_tag_service,
)
from ranger_client import RangerClient, normalize_base_url
from reconcilers.associations import reconcile_tag_service_association
from reconcilers.groups import reconcile_groups
from reconcilers.services import reconcile_service
from reconcilers.system_grants import reconcile_system_grants
from reconcilers.technical_users import reconcile_technical_users


Result = tuple[str, dict[str, Any]]


def configure_logging() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=os.getenv("LOG_LEVEL", "INFO"),
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>ranger-bootstrap</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )


def _runtime() -> tuple[str, str, str, float]:
    base_url = normalize_base_url(
        os.getenv("RANGER_BASE_URL", "http://localhost:6080")
    )
    username = (
        os.getenv("RANGER_BOOTSTRAP_USER")
        or os.getenv("RANGER_SERVICE_ACCOUNT")
        or "admin"
    )
    password = (
        os.getenv("RANGER_BOOTSTRAP_PASSWORD")
        or os.getenv("RANGER_SERVICE_SECRET")
        or ""
    )
    timeout = float(os.getenv("RANGER_TIMEOUT_SECONDS", "30"))
    if not password:
        raise RuntimeError("Ranger bootstrap password is empty")
    return base_url, username, password, timeout


def _dict_list(value: object, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RuntimeError(f"{name} must be a list")
    if not all(isinstance(item, dict) for item in value):
        raise RuntimeError(f"Every {name} entry must be an object")
    return value


def _log_named_results(label: str, results: Iterable[Result]) -> list[Result]:
    materialized = list(results)
    for action, value in materialized:
        logger.success(
            "{} ready | name={} | action={}",
            label,
            value.get("name"),
            action,
        )
    return materialized


def _summary(results: Iterable[Result]) -> str:
    counts = Counter(action for action, _ in results)
    return " | ".join(
        f"{action}={counts.get(action, 0)}"
        for action in ("created", "updated", "unchanged")
    )


def main() -> None:
    load_environment()
    configure_logging()

    config = load_bootstrap_config()
    resource_service = resolved_resource_service(config)
    tag_service = resolved_tag_service(config)
    base_url, username, password, timeout = _runtime()

    resource_name = str(resource_service["name"])
    resource_type = str(resource_service["type"])
    tag_name = str(tag_service["name"])

    logger.info("Ranger bootstrap started")
    logger.info(
        "Environment | env_file={} | ranger_url={} | user={}",
        ENV_PATH,
        base_url,
        username,
    )
    logger.info(
        "Desired topology | resource_service={} | tag_service={}",
        resource_name,
        tag_name,
    )

    all_results: list[Result] = []

    with RangerClient(
        base_url=base_url,
        username=username,
        password=password,
        timeout_seconds=timeout,
    ) as client:
        # Fail fast. System grant resource/access names are resolved from the
        # live service definition instead of hard-coded plugin field names.
        trino_service_def = client.get_service_def(resource_type)
        client.get_service_def("tag")
        logger.success("Service definitions available | {}, tag", resource_type)

        group_results = _log_named_results(
            "Group",
            reconcile_groups(
                client,
                _dict_list(config["groups"], "groups"),
            ),
        )
        all_results.extend(group_results)

        # Local-dev technical principals only. This is deliberately not an
        # OpenMetadata user sync and does not create Ranger login passwords.
        user_results = _log_named_results(
            "Technical user",
            reconcile_technical_users(
                client,
                _dict_list(config["technical_users"], "technical_users"),
            ),
        )
        all_results.extend(user_results)

        tag_action, tag_current = reconcile_service(client, tag_service)
        tag_result = (tag_action, tag_current)
        all_results.append(tag_result)
        logger.success(
            "Tag service ready | name={} | action={}",
            tag_current.get("name", tag_name),
            tag_action,
        )

        resource_action, resource_current = reconcile_service(
            client,
            resource_service,
        )
        resource_result = (resource_action, resource_current)
        all_results.append(resource_result)
        logger.success(
            "Resource service ready | name={} | action={}",
            resource_current.get("name", resource_name),
            resource_action,
        )

        association_action, associated = reconcile_tag_service_association(
            client,
            resource_service_name=resource_name,
            tag_service_name=tag_name,
        )
        association_result = (association_action, associated)
        all_results.append(association_result)
        logger.success(
            "Association ready | {} -> {} | action={}",
            associated.get("name", resource_name),
            associated.get("tagService", tag_name),
            association_action,
        )

        grant_results = reconcile_system_grants(
            client,
            _dict_list(config["system_grants"], "system_grants"),
            service_name=resource_name,
            service_def=trino_service_def,
        )
        for action, policy in grant_results:
            logger.success(
                "System grant ready | policy={} | action={}",
                policy.get("name"),
                action,
            )
        all_results.extend(grant_results)

    logger.success(
        "Ranger bootstrap completed successfully | {}",
        _summary(all_results),
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("Ranger bootstrap interrupted")
        raise SystemExit(130)
    except Exception:
        logger.exception("Ranger bootstrap failed")
        raise SystemExit(1)

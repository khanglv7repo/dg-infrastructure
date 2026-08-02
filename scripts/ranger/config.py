from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
ENV_PATH = REPO_ROOT / ".env"
BOOTSTRAP_CONFIG_PATH = SCRIPT_DIR / "bootstrap.yaml"
BOOTSTRAP_SCHEMA_VERSION = 4


class BootstrapConfigError(RuntimeError):
    """Raised when bootstrap configuration is missing or inconsistent."""


def load_environment() -> None:
    """Load local-dev .env without modifying or overriding process values."""
    load_dotenv(ENV_PATH, override=False)


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise BootstrapConfigError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}

    if not isinstance(value, dict):
        raise BootstrapConfigError(f"Expected a YAML object in {path}")
    return value


def _require_non_empty_list(
    config: dict[str, Any],
    key: str,
) -> list[dict[str, Any]]:
    value = config.get(key)
    if not isinstance(value, list) or not value:
        raise BootstrapConfigError(
            f"bootstrap.yaml requires a non-empty {key} list"
        )
    if not all(isinstance(item, dict) for item in value):
        raise BootstrapConfigError(f"Every {key} entry must be an object")
    return value


def _validate_named_entries(entries: list[dict[str, Any]], key: str) -> None:
    seen: set[str] = set()
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name:
            raise BootstrapConfigError(f"Every {key} entry requires name")
        if name in seen:
            raise BootstrapConfigError(f"Duplicate {key} name: {name}")
        seen.add(name)


def _require_service(
    config: dict[str, Any],
    key: str,
    *,
    expected_type: str,
) -> dict[str, Any]:
    service = config.get(key)
    if not isinstance(service, dict):
        raise BootstrapConfigError(f"bootstrap.yaml requires {key}")

    name = str(service.get("name") or "").strip()
    service_type = str(service.get("type") or "").strip()
    if not name:
        raise BootstrapConfigError(f"{key}.name is required")
    if service_type != expected_type:
        raise BootstrapConfigError(
            f"{key}.type must be {expected_type!r}; got {service_type!r}"
        )

    configs = service.get("configs", {})
    if not isinstance(configs, dict):
        raise BootstrapConfigError(f"{key}.configs must be an object")
    return service


def load_bootstrap_config() -> dict[str, Any]:
    config = load_yaml(BOOTSTRAP_CONFIG_PATH)

    version = config.get("version")
    if version != BOOTSTRAP_SCHEMA_VERSION:
        raise BootstrapConfigError(
            "bootstrap.yaml version must be "
            f"{BOOTSTRAP_SCHEMA_VERSION}; got {version!r}"
        )

    groups = _require_non_empty_list(config, "groups")
    _validate_named_entries(groups, "groups")

    technical_users = _require_non_empty_list(config, "technical_users")
    _validate_named_entries(technical_users, "technical_users")

    _require_service(config, "resource_service", expected_type="trino")
    _require_service(config, "tag_service", expected_type="tag")

    grants = _require_non_empty_list(config, "system_grants")
    _validate_named_entries(grants, "system_grants")

    for grant in grants:
        users = grant.get("users", [])
        groups_for_grant = grant.get("groups", [])
        if not isinstance(users, list) or not isinstance(groups_for_grant, list):
            raise BootstrapConfigError(
                f"system_grants[{grant['name']!r}] users/groups must be lists"
            )
        if not users and not groups_for_grant:
            raise BootstrapConfigError(
                f"system_grants[{grant['name']!r}] requires a user or group"
            )

    return config


def resolved_resource_service(config: dict[str, Any]) -> dict[str, Any]:
    """Resolve local environment overrides for the Trino Ranger service."""
    desired = dict(config["resource_service"])
    desired["configs"] = dict(desired.get("configs") or {})
    desired["name"] = (
        os.getenv("RANGER_RESOURCE_SERVICE_NAME")
        or os.getenv("TRINO_SERVICE_NAME")
        or str(desired["name"])
    )
    return desired


def resolved_tag_service(config: dict[str, Any]) -> dict[str, Any]:
    desired = dict(config["tag_service"])
    desired["configs"] = dict(desired.get("configs") or {})
    desired["name"] = os.getenv(
        "RANGER_TAG_SERVICE_NAME",
        str(desired["name"]),
    )
    return desired

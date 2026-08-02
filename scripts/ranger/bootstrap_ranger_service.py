from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml
from dotenv import load_dotenv
from loguru import logger


SCRIPT_DIR = Path(__file__).resolve().parent
ENV_PATH = SCRIPT_DIR.parent.parent / ".env"
CONFIG_PATH = SCRIPT_DIR / "ranger_service.yaml"

API_PREFIX = "/service/public/v2/api"

load_dotenv(ENV_PATH, override=False)


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


def normalize_ranger_base_url(value: str) -> str:
    value = value.rstrip("/")

    if value.endswith(API_PREFIX):
        return value[: -len(API_PREFIX)]

    return value


RANGER_BASE_URL = normalize_ranger_base_url(
    os.getenv(
        "RANGER_BASE_URL",
        "http://localhost:6080",
    )
)

RANGER_USERNAME = (
    os.getenv("RANGER_BOOTSTRAP_USER")
    or os.getenv("RANGER_SERVICE_ACCOUNT")
    or "admin"
)

RANGER_PASSWORD = (
    os.getenv("RANGER_BOOTSTRAP_PASSWORD")
    or os.getenv("RANGER_SERVICE_SECRET")
    or ""
)

RANGER_TIMEOUT_SECONDS = float(
    os.getenv(
        "RANGER_TIMEOUT_SECONDS",
        "30",
    )
)


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise RuntimeError(
            f"Ranger service config not found: {CONFIG_PATH}"
        )

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}

    service = payload.get("service")

    if not isinstance(service, dict):
        raise RuntimeError(
            f"Missing 'service' section in {CONFIG_PATH}"
        )

    if not service.get("name"):
        raise RuntimeError(
            "Missing service.name in ranger_service.yaml"
        )

    if not service.get("type"):
        raise RuntimeError(
            "Missing service.type in ranger_service.yaml"
        )

    return service


def build_service_payload(
    config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "name": config["name"],
        "type": config["type"],
        "displayName": config.get(
            "displayName",
            config["name"],
        ),
        "description": config.get(
            "description",
            "",
        ),
        "isEnabled": bool(
            config.get("isEnabled", True)
        ),
        "configs": config.get(
            "configs",
            {},
        ),
    }


def request_or_raise(
    response: httpx.Response,
    *,
    operation: str,
) -> httpx.Response:
    if response.is_success:
        return response

    logger.error(
        "Ranger request failed | operation={} | status={} | url={}",
        operation,
        response.status_code,
        response.request.url,
    )

    body = response.text.strip()

    if body:
        logger.error(
            "Ranger response | body={}",
            body,
        )

    response.raise_for_status()
    return response


def get_service(
    client: httpx.Client,
    service_name: str,
) -> dict[str, Any] | None:
    logger.info(
        "Checking Ranger service | name={}",
        service_name,
    )

    response = client.get(
        f"{API_PREFIX}/service/name/{service_name}"
    )

    if response.status_code == 404:
        logger.info(
            "Ranger service not found | name={}",
            service_name,
        )
        return None

    request_or_raise(
        response,
        operation=f"get service '{service_name}'",
    )

    return response.json()


def create_service(
    client: httpx.Client,
    payload: dict[str, Any],
) -> dict[str, Any]:
    logger.info(
        "Creating Ranger service | name={} | type={}",
        payload["name"],
        payload["type"],
    )

    response = client.post(
        f"{API_PREFIX}/service",
        json=payload,
    )

    request_or_raise(
        response,
        operation=f"create service '{payload['name']}'",
    )

    return response.json()


def update_service(
    client: httpx.Client,
    service_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    logger.info(
        "Updating Ranger service | id={} | name={}",
        service_id,
        payload["name"],
    )

    response = client.put(
        f"{API_PREFIX}/service/{service_id}",
        json=payload,
    )

    request_or_raise(
        response,
        operation=f"update service '{payload['name']}'",
    )

    return response.json()


def main() -> None:
    configure_logging()

    logger.info("Ranger bootstrap started")

    config = load_config()
    payload = build_service_payload(config)

    service_name = str(payload["name"])

    logger.info(
        "Environment | env_file={} | ranger_url={} | user={}",
        ENV_PATH,
        RANGER_BASE_URL,
        RANGER_USERNAME,
    )

    logger.info(
        "Desired Ranger service | name={} | type={}",
        service_name,
        payload["type"],
    )

    if not RANGER_PASSWORD:
        raise RuntimeError(
            "Ranger password is empty"
        )

    with httpx.Client(
        base_url=RANGER_BASE_URL,
        auth=(
            RANGER_USERNAME,
            RANGER_PASSWORD,
        ),
        timeout=RANGER_TIMEOUT_SECONDS,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    ) as client:
        existing = get_service(
            client,
            service_name,
        )

        if existing is None:
            created = create_service(
                client,
                payload,
            )

            logger.success(
                "Ranger service created | id={} | name={}",
                created.get("id"),
                created.get("name", service_name),
            )

            logger.success(
                "Ranger bootstrap completed | action=create"
            )

            return

        service_id = existing.get("id")

        if service_id is None:
            raise RuntimeError(
                f"Existing Ranger service '{service_name}' "
                "does not contain an id"
            )

        desired = {
            **existing,
            **payload,
            "id": service_id,
        }

        updated = update_service(
            client,
            int(service_id),
            desired,
        )

        logger.success(
            "Ranger service updated | id={} | name={}",
            updated.get("id", service_id),
            updated.get("name", service_name),
        )

        logger.success(
            "Ranger bootstrap completed | action=update"
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning(
            "Ranger bootstrap interrupted"
        )
        raise SystemExit(130)
    except Exception:
        logger.exception(
            "Ranger bootstrap failed"
        )
        raise SystemExit(1)
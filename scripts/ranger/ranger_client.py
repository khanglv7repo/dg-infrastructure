from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


PUBLIC_API_PREFIX = "/service/public/v2/api"
XUSERS_PREFIX = "/service/xusers"


class RangerAPIError(RuntimeError):
    """Raised when Ranger REST API returns an unexpected response."""


def normalize_base_url(value: str) -> str:
    value = value.rstrip("/")
    for suffix in (PUBLIC_API_PREFIX, "/service/tags"):
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value


class RangerClient:
    """Thin Ranger REST adapter.

    This class knows HTTP endpoints and response shapes only. Desired-state
    decisions belong in reconcilers.
    """

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=normalize_base_url(base_url),
            auth=(username, password),
            timeout=timeout_seconds,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    def __enter__(self) -> RangerClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise RangerAPIError(
                f"Ranger returned non-JSON response from {response.request.url}: "
                f"{response.text[:1000]}"
            ) from exc

    @staticmethod
    def _raise(response: httpx.Response, operation: str) -> None:
        if response.is_success:
            return
        body = response.text.strip()
        detail = f" | body={body[:2000]}" if body else ""
        raise RangerAPIError(
            f"Ranger request failed: {operation} | "
            f"HTTP {response.status_code} | {response.request.url}{detail}"
        )

    # ------------------------------------------------------------------
    # Service definitions
    # ------------------------------------------------------------------
    def get_service_def(self, service_type: str) -> dict[str, Any]:
        encoded = quote(service_type, safe="")
        response = self._client.get(
            f"{PUBLIC_API_PREFIX}/servicedef/name/{encoded}"
        )
        self._raise(response, f"get service definition {service_type!r}")
        value = self._json(response)
        if not isinstance(value, dict):
            raise RangerAPIError(
                f"Unexpected service-definition response for {service_type!r}"
            )
        return value

    # ------------------------------------------------------------------
    # Services
    # ------------------------------------------------------------------
    def get_service(self, name: str) -> dict[str, Any] | None:
        encoded = quote(name, safe="")
        response = self._client.get(
            f"{PUBLIC_API_PREFIX}/service/name/{encoded}"
        )
        if response.status_code == 404:
            return None
        self._raise(response, f"get service {name!r}")
        value = self._json(response)
        return value if isinstance(value, dict) else None

    def create_service(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(
            f"{PUBLIC_API_PREFIX}/service",
            json=payload,
        )
        self._raise(response, f"create service {payload['name']!r}")
        value = self._json(response)
        if isinstance(value, dict):
            return value
        fetched = self.get_service(str(payload["name"]))
        if fetched is None:
            raise RangerAPIError("Service created but could not be read back")
        return fetched

    def update_service(
        self,
        name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        encoded = quote(name, safe="")
        response = self._client.put(
            f"{PUBLIC_API_PREFIX}/service/name/{encoded}",
            json=payload,
        )
        self._raise(response, f"update service {name!r}")
        value = self._json(response)
        if isinstance(value, dict):
            return value
        fetched = self.get_service(name)
        if fetched is None:
            raise RangerAPIError("Service updated but could not be read back")
        return fetched

    # ------------------------------------------------------------------
    # Groups
    # ------------------------------------------------------------------
    def find_group(self, name: str) -> dict[str, Any] | None:
        response = self._client.get(
            f"{XUSERS_PREFIX}/groups",
            params={"name": name, "pageSize": 1000},
        )
        self._raise(response, f"find group {name!r}")
        value = self._json(response)
        if not isinstance(value, dict):
            return None
        groups = value.get("vXGroups", [])
        if not isinstance(groups, list):
            return None
        for group in groups:
            if isinstance(group, dict) and group.get("name") == name:
                return group
        return None

    def create_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(
            f"{XUSERS_PREFIX}/groups",
            json=payload,
        )
        self._raise(response, f"create group {payload['name']!r}")
        value = self._json(response)
        if isinstance(value, dict):
            return value
        fetched = self.find_group(str(payload["name"]))
        if fetched is None:
            raise RangerAPIError("Group created but could not be read back")
        return fetched

    def update_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.put(
            f"{XUSERS_PREFIX}/groups",
            json=payload,
        )
        self._raise(response, f"update group {payload['name']!r}")
        value = self._json(response)
        if isinstance(value, dict):
            return value
        fetched = self.find_group(str(payload["name"]))
        if fetched is None:
            raise RangerAPIError("Group updated but could not be read back")
        return fetched

    # ------------------------------------------------------------------
    # Users / policy principals
    # ------------------------------------------------------------------
    def find_user(self, name: str) -> dict[str, Any] | None:
        """Find an existing Ranger principal without assuming its source.

        Using the list endpoint keeps this compatible with users provisioned by
        local bootstrap, LDAP/AD UserSync, or another external identity source.
        """
        response = self._client.get(
            f"{XUSERS_PREFIX}/users",
            params={"pageSize": 1000},
        )
        self._raise(response, f"find user {name!r}")
        value = self._json(response)
        if not isinstance(value, dict):
            return None
        users = value.get("vXUsers", [])
        if not isinstance(users, list):
            return None
        for user in users:
            if isinstance(user, dict) and user.get("name") == name:
                return user
        return None

    def create_external_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a Ranger external user principal, not a login credential."""
        response = self._client.post(
            f"{XUSERS_PREFIX}/users/external",
            json=payload,
        )
        self._raise(response, f"create external user {payload['name']!r}")
        value = self._json(response)
        if isinstance(value, dict):
            return value
        fetched = self.find_user(str(payload["name"]))
        if fetched is None:
            raise RangerAPIError(
                "External user created but could not be read back"
            )
        return fetched

    # ------------------------------------------------------------------
    # Policies
    # ------------------------------------------------------------------
    def list_policies(self, service: str) -> list[dict[str, Any]]:
        service_encoded = quote(service, safe="")
        response = self._client.get(
            f"{PUBLIC_API_PREFIX}/service/{service_encoded}/policy"
        )
        self._raise(response, f"list policies for service {service!r}")
        value = self._json(response)
        if not isinstance(value, list):
            raise RangerAPIError(
                f"Unexpected policy-list response for service {service!r}"
            )
        return [item for item in value if isinstance(item, dict)]

    def get_policy(self, service: str, name: str) -> dict[str, Any] | None:
        service_encoded = quote(service, safe="")
        name_encoded = quote(name, safe="")
        response = self._client.get(
            f"{PUBLIC_API_PREFIX}/service/{service_encoded}/policy/{name_encoded}"
        )
        if response.status_code == 404:
            return None
        self._raise(response, f"get policy {service!r}/{name!r}")
        value = self._json(response)
        return value if isinstance(value, dict) else None

    def create_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(
            f"{PUBLIC_API_PREFIX}/policy",
            json=payload,
        )
        self._raise(response, f"create policy {payload['name']!r}")
        value = self._json(response)
        if isinstance(value, dict):
            return value
        fetched = self.get_policy(str(payload["service"]), str(payload["name"]))
        if fetched is None:
            raise RangerAPIError("Policy created but could not be read back")
        return fetched

    def update_policy(
        self,
        service: str,
        name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        service_encoded = quote(service, safe="")
        name_encoded = quote(name, safe="")
        response = self._client.put(
            f"{PUBLIC_API_PREFIX}/service/{service_encoded}/policy/{name_encoded}",
            json=payload,
        )
        self._raise(response, f"update policy {service!r}/{name!r}")
        value = self._json(response)
        if isinstance(value, dict):
            return value
        fetched = self.get_policy(service, name)
        if fetched is None:
            raise RangerAPIError("Policy updated but could not be read back")
        return fetched

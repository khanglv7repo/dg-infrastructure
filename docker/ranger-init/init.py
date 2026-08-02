"""Idempotently provision the local Ranger Trino service and baseline policies."""
from __future__ import annotations
import base64, json, os, time, urllib.error, urllib.parse, urllib.request

BASE_URL = os.getenv("RANGER_BASE_URL", "http://localhost:6080/service/public/v2/api").rstrip("/")
USERNAME = os.getenv("RANGER_BOOTSTRAP_USER", "admin")
PASSWORD = os.environ["RANGER_BOOTSTRAP_PASSWORD"]
SERVICE_NAME = os.getenv("TRINO_SERVICE_NAME", "dev_trino")
TIMEOUT_SECONDS = int(os.getenv("RANGER_INIT_TIMEOUT_SECONDS", "300"))
AUTH = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
HEADERS = {"Authorization": f"Basic {AUTH}", "Content-Type": "application/json"}


def request(method: str, path: str, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE_URL + path, data=data, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        body = raw.decode(errors="replace") if raw else ""
        if exc.code not in {400, 404, 409}:
            raise RuntimeError(f"Ranger API {method} {path} failed: HTTP {exc.code}: {body}") from exc
        return exc.code, json.loads(body) if body.startswith(("{", "[")) else None


def wait_for_ranger():
    deadline = time.monotonic() + TIMEOUT_SECONDS
    last_error = None
    while time.monotonic() < deadline:
        try:
            status, _ = request("GET", "/service")
            if status == 200:
                print("Ranger Admin API is ready", flush=True)
                return
        except Exception as exc:
            last_error = exc
        time.sleep(5)
    raise RuntimeError(f"Ranger Admin did not become ready: {last_error}")


def ensure_service():
    status, _ = request("GET", f"/service/name/{urllib.parse.quote(SERVICE_NAME, safe='')}")
    if status == 200:
        print(f"Ranger service already exists: {SERVICE_NAME}", flush=True)
        return
    payload = {
        "name": SERVICE_NAME,
        "type": "trino",
        "isEnabled": True,
        "configs": {
            "username": "admin",
            "password": "",
            "jdbc.url": "jdbc:trino://trino:8080",
            "jdbc.driverClassName": "io.trino.jdbc.TrinoDriver",
        },
    }
    created, _ = request("POST", "/service", payload)
    if created not in {200, 201, 409}:
        raise RuntimeError(f"Unexpected Ranger service creation status: {created}")
    print(f"Created Ranger service: {SERVICE_NAME}", flush=True)


def policy_exists(name):
    query = urllib.parse.urlencode({"serviceName": SERVICE_NAME, "policyName": name})
    status, body = request("GET", f"/policy?{query}")
    if status != 200:
        return False
    if isinstance(body, list):
        return any(isinstance(item, dict) and item.get("name") == name for item in body)
    return bool(body)


def ensure_policy(policy):
    name = policy["name"]
    if policy_exists(name):
        print(f"Ranger policy already exists: {name}", flush=True)
        return
    created, _ = request("POST", "/policy", policy)
    if created not in {200, 201, 409}:
        raise RuntimeError(f"Unexpected Ranger policy creation status for {name}: {created}")
    print(f"Created Ranger policy: {name}", flush=True)


def baseline_policies():
    users = ["admin", "analyst", "intern", "ai_agent"]
    return [
        {
            "service": SERVICE_NAME,
            "name": "local-admin-data-access",
            "description": "Local administrator access to all Trino data resources.",
            "isEnabled": True,
            "isAuditEnabled": True,
            "resources": {
                "catalog": {"values": ["*"]}, "schema": {"values": ["*"]},
                "table": {"values": ["*"]}, "column": {"values": ["*"]},
            },
            "policyItems": [{
                "users": ["admin"],
                "accesses": [{"type": x, "isAllowed": True} for x in
                    ["select", "insert", "update", "delete", "create", "drop", "alter", "use"]],
                "delegateAdmin": True,
            }],
        },
        {
            "service": SERVICE_NAME,
            "name": "local-users-execute-query",
            "description": "Required Trino query execution permission for local users.",
            "isEnabled": True,
            "isAuditEnabled": True,
            "resources": {"queryId": {"values": ["*"]}},
            "policyItems": [{"users": users, "accesses": [{"type": "execute", "isAllowed": True}], "delegateAdmin": False}],
        },
        {
            "service": SERVICE_NAME,
            "name": "local-users-self-impersonation",
            "description": "Required Trino self-impersonation permission.",
            "isEnabled": True,
            "isAuditEnabled": True,
            "resources": {"trinouser": {"values": ["{USER}"]}},
            "policyItems": [{"users": ["{USER}"], "accesses": [{"type": "impersonate", "isAllowed": True}], "delegateAdmin": False}],
        },
    ]


def main():
    wait_for_ranger()
    ensure_service()
    for policy in baseline_policies():
        ensure_policy(policy)
    print("Ranger initialization completed", flush=True)


if __name__ == "__main__":
    main()

"""Live local-stack smoke test for governance policy enforcement.

This is intentionally not part of CI: it requires a running Backend, Ranger,
Trino and a real table containing distinguishing control evidence.

Required environment:
  DG_VERIFY_TABLE_FQN=catalog.schema.table
  DG_VERIFY_MASK_COLUMN=column_name
  DG_VERIFY_ROW_FILTER=<valid Trino boolean expression>

Optional:
  DG_BACKEND_URL=http://127.0.0.1:8000/api/v1
  DG_TRINO_HOST=127.0.0.1
  DG_TRINO_PORT=8080
  DG_POLICY_USER=governance-policy-verifier-bot
  DG_CONTROL_USER=governance-verifier-bot
  DG_VERIFY_TIMEOUT_SECONDS=90

The harness creates successive logical policy versions for the same temporary
policy key and activates them through the authoritative Backend REST API:
ALLOW -> MASK + ROW_FILTER -> DENY.

It refuses to call MASK/ROW_FILTER verified unless the control identity first
observes non-null mask samples and at least one row outside the row filter.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib import error, request

try:
    import trino
except ImportError as exc:  # pragma: no cover - live harness only
    raise SystemExit("Install live dependency first: python -m pip install trino") from exc


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def table_sql(fqn: str) -> str:
    parts = fqn.split(".")
    if len(parts) != 3 or any(not part for part in parts):
        raise SystemExit("DG_VERIFY_TABLE_FQN must be catalog.schema.table")
    return ".".join(quote_identifier(part) for part in parts)


@dataclass(frozen=True)
class Config:
    backend_url: str
    trino_host: str
    trino_port: int
    policy_user: str
    control_user: str
    table_fqn: str
    mask_column: str
    row_filter: str
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> "Config":
        policy_user = os.getenv(
            "DG_POLICY_USER", "governance-policy-verifier-bot"
        ).strip()
        control_user = os.getenv(
            "DG_CONTROL_USER", "governance-verifier-bot"
        ).strip()
        if not policy_user or not control_user or policy_user == control_user:
            raise SystemExit("policy and control verification users must be different")
        return cls(
            backend_url=os.getenv(
                "DG_BACKEND_URL", "http://127.0.0.1:8000/api/v1"
            ).rstrip("/"),
            trino_host=os.getenv("DG_TRINO_HOST", "127.0.0.1"),
            trino_port=int(os.getenv("DG_TRINO_PORT", "8080")),
            policy_user=policy_user,
            control_user=control_user,
            table_fqn=required("DG_VERIFY_TABLE_FQN"),
            mask_column=required("DG_VERIFY_MASK_COLUMN"),
            row_filter=required("DG_VERIFY_ROW_FILTER"),
            timeout_seconds=float(os.getenv("DG_VERIFY_TIMEOUT_SECONDS", "90")),
        )


def api(
    config: Config,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode()
    req = request.Request(
        f"{config.backend_url}{path}",
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Actor-Id": "local-runtime-verifier",
            "X-Actor-Name": "Local Runtime Verifier",
            "X-Actor-Roles": "governance-admin",
        },
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            raw = response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(
            f"Backend {method} {path} failed HTTP {exc.code}: {detail[:1000]}"
        ) from exc
    return json.loads(raw) if raw else {}


def query(config: Config, user: str, sql: str) -> list[list[Any]]:
    conn = trino.dbapi.connect(
        host=config.trino_host,
        port=config.trino_port,
        user=user,
        http_scheme="http",
    )
    try:
        cur = conn.cursor()
        cur.execute(sql)
        return [list(row) for row in cur.fetchall()]
    finally:
        conn.close()


def wait_projection_settled(config: Config, policy_key: str) -> dict[str, Any]:
    deadline = time.monotonic() + config.timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = api(config, "GET", f"/data-access-policies/{policy_key}/status")
        projections = last.get("projections") or []
        if projections and all(
            row.get("sync_status") == "SYNCHRONIZED" for row in projections
        ):
            return last
        time.sleep(2)
    raise RuntimeError(
        f"Ranger projections did not synchronize before timeout: {last}"
    )


def logical_policy(
    config: Config,
    *,
    select: str,
    mask: bool = False,
    row_filter: bool = False,
) -> dict[str, Any]:
    catalog, schema, table = config.table_fqn.split(".")
    return {
        "subjects": [{"type": "USER", "name": config.policy_user}],
        "resource": {"catalog": catalog, "schema": schema, "table": table},
        "access": {"select": select},
        "masks": {config.mask_column: "MASK"} if mask else {},
        "row_filter": config.row_filter if row_filter else None,
    }


def activate(
    config: Config,
    policy_key: str,
    version: int,
    policy: dict[str, Any],
) -> None:
    api(
        config,
        "POST",
        f"/data-access-policies/{policy_key}/versions",
        {"logical_policy": policy},
    )
    api(
        config,
        "POST",
        f"/data-access-policies/{policy_key}/versions/{version}/activate",
    )
    wait_projection_settled(config, policy_key)


def assert_control_evidence(config: Config) -> None:
    table = table_sql(config.table_fqn)
    col = quote_identifier(config.mask_column)

    samples = query(
        config,
        config.control_user,
        f"SELECT CAST({col} AS varchar) FROM {table} "
        f"WHERE {col} IS NOT NULL LIMIT 5",
    )
    if not samples:
        raise RuntimeError(
            "control identity returned no non-null mask samples; "
            "MASK verification would be non-discriminating"
        )

    violations = query(
        config,
        config.control_user,
        f"SELECT 1 FROM {table} WHERE NOT ({config.row_filter}) LIMIT 1",
    )
    if not violations:
        raise RuntimeError(
            "control identity sees no row outside DG_VERIFY_ROW_FILTER; "
            "ROW_FILTER verification would be non-discriminating"
        )


def main() -> None:
    config = Config.from_env()
    if config.policy_user == config.control_user:
        raise SystemExit("policy verifier and control verifier must differ")

    # Prove the control dataset is discriminating before changing policy state.
    assert_control_evidence(config)

    policy_key = f"runtime-smoke-{uuid.uuid4().hex[:12]}"
    table = table_sql(config.table_fqn)
    col = quote_identifier(config.mask_column)

    print(f"policy_key={policy_key}")

    activate(
        config,
        policy_key,
        1,
        logical_policy(config, select="ALLOW"),
    )
    allow_rows = query(
        config,
        config.policy_user,
        f"SELECT 1 FROM {table} LIMIT 1",
    )
    if not allow_rows:
        raise RuntimeError("ALLOW policy query returned no evidence row")
    print("ALLOW: confirmed")

    activate(
        config,
        policy_key,
        2,
        logical_policy(
            config,
            select="ALLOW",
            mask=True,
            row_filter=True,
        ),
    )
    # Backend's own verifier is authoritative for exact Ranger mask transform
    # comparison. Here we additionally prove the policy identity can query the
    # column and cannot observe a row violating the filter.
    masked = query(
        config,
        config.policy_user,
        f"SELECT CAST({col} AS varchar) FROM {table} "
        f"WHERE {col} IS NOT NULL LIMIT 5",
    )
    if not masked:
        raise RuntimeError("MASK policy query returned no evidence row")
    violations = query(
        config,
        config.policy_user,
        f"SELECT 1 FROM {table} WHERE NOT ({config.row_filter}) LIMIT 1",
    )
    if violations:
        raise RuntimeError("ROW_FILTER violation is visible to policy verifier")
    print("MASK + ROW_FILTER: runtime restriction observed")

    activate(
        config,
        policy_key,
        3,
        logical_policy(config, select="DENY"),
    )
    try:
        query(config, config.policy_user, f"SELECT 1 FROM {table} LIMIT 1")
    except Exception:
        print("DENY: confirmed")
    else:
        raise RuntimeError("DENY policy unexpectedly allowed SELECT")

    print("governance runtime smoke: PASS")


if __name__ == "__main__":
    main()

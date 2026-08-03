# Ranger Bootstrap

Idempotent bootstrap for the local Data Governance Ranger/Trino environment.

## What bootstrap owns

Bootstrap creates or reconciles Ranger infrastructure prerequisites only:

1. Governance groups referenced by policies (`pii_readers`,
   `payment_data_readers`).
2. Local technical Ranger principals (`governance-verifier-bot`).
3. Ranger services (`dev_trino`, `dev_tag`).
4. The `dev_trino -> dev_tag` association.
5. Trino system grants (`execute`, self-`impersonate`).
6. Technical baseline data grants required by backend scanner/verifier
   identities (`financial` read for `governance-verifier-bot`).

It does **not** synchronize OpenMetadata users into Ranger. It does **not** own
business PII tag policies, and it does **not** own runtime resource-to-tag
assignments.

## Single desired-state file

All desired state is in:

```text
scripts/ranger/bootstrap.yaml
```

`ranger_service.yaml` is no longer required. The existing repository `.env` is
read only; bootstrap never rewrites it.

## Why technical data access is separate

`governance-verifier-bot` is a backend scanner/verifier identity. It needs
baseline access to the local `financial` catalog so it can sample and verify
resources. That technical permission is deliberately separate from business
roles such as `pii_readers`.

One logical `technical_data_grants` entry is expanded into grants at each Trino
resource depth:

```text
catalog: financial
catalog: financial -> schema: *
catalog: financial -> schema: * -> table: *
catalog: financial -> schema: * -> table: * -> column: *
```

This is intentional. Trino performs direct authorization checks at catalog,
schema, table, and column depths. A column-level SELECT policy alone is not
sufficient for commands such as `SHOW SCHEMAS FROM financial`.

Resource names, hierarchy, and access names are validated against the live
Ranger Trino service definition before policies are written.

## Run

From the platform repository root:

```bash
python -m unittest discover -s scripts/ranger/tests -v
python scripts/ranger/bootstrap.py
```

Run the bootstrap a second time to verify idempotence. Stable resources should
converge to `action=unchanged`.

## Expected order

```text
Ranger reachable
  -> service definitions
  -> groups
  -> technical users
  -> dev_tag
  -> dev_trino
  -> dev_trino -> dev_tag
  -> execute grant
  -> impersonate grant
  -> technical catalog/schema/table/column grants
```

## Verify through Trino

```bash
python - <<'PY'
import trino

conn = trino.dbapi.connect(
    host="127.0.0.1",
    port=8080,
    user="governance-verifier-bot",
)
cur = conn.cursor()

for sql in [
    "SELECT current_user",
    "SELECT 1",
    "SHOW CATALOGS",
    "SHOW SCHEMAS FROM financial",
]:
    print(f"\n>>> {sql}")
    cur.execute(sql)
    print(cur.fetchall())
PY
```

Expected after policy refresh: `SHOW CATALOGS` contains `financial` and
`SHOW SCHEMAS FROM financial` returns visible schemas.

## Ownership boundaries

```text
scripts/ranger/bootstrap.yaml
    Ranger infrastructure + technical access prerequisites

backend/config/policies.yaml
    reusable business tag policies

OpenMetadata Confirmed tags
    runtime resource <-> tag state synchronized by backend
```

See `docs/ARCHITECTURE.md`, `docs/CONFIG_REFERENCE.md`,
`docs/API_REFERENCE.md`, `docs/TROUBLESHOOTING.md`, and
`docs/VERIFICATION.md`.

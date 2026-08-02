# Ranger Bootstrap

This directory contains the idempotent bootstrap for the local Data Governance
Ranger/Trino environment.

## What bootstrap owns

Bootstrap creates or reconciles only Ranger infrastructure prerequisites:

1. Ranger groups used by governance policies (`pii_readers`,
   `payment_data_readers`).
2. Ranger technical principals required by Trino authorization
   (`governance-verifier-bot`).
3. The Trino resource service (`dev_trino`).
4. The tag service (`dev_tag`).
5. The `dev_trino -> dev_tag` association.
6. Baseline Trino system grants (`execute`, `impersonate`).

It does **not** synchronize OpenMetadata users into Ranger. It does **not** own
business PII tag policies, and it does **not** own runtime resource-to-tag
assignments.

## Single desired-state file

All Ranger bootstrap desired state is in:

```text
scripts/ranger/bootstrap.yaml
```

`ranger_service.yaml` is no longer required. This removes the cross-file
configuration dependency that previously caused `Config file not found` when a
patch or checkout did not contain that legacy file.

Environment variables may still override local service names:

- `RANGER_RESOURCE_SERVICE_NAME` or `TRINO_SERVICE_NAME`
- `RANGER_TAG_SERVICE_NAME`

The existing repository `.env` is read only; bootstrap never rewrites it.

## Run

From the platform repository root:

```bash
python scripts/ranger/bootstrap.py
```

Run tests first when changing bootstrap code:

```bash
python -m unittest discover -s scripts/ranger/tests -v
```

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
```

A second run should converge to `unchanged` for all stable resources.

## Important ownership boundaries

```text
scripts/ranger/bootstrap.yaml
    Ranger infrastructure prerequisites

backend/config/policies.yaml
    business tag policies (PII.Email -> pii_readers -> select)

OpenMetadata Confirmed tags
    runtime resource <-> tag state synchronized by backend
```

See `docs/ARCHITECTURE.md`, `docs/CONFIG_REFERENCE.md`,
`docs/API_REFERENCE.md`, and `docs/TROUBLESHOOTING.md` for details.

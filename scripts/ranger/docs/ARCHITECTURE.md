# Ranger Bootstrap Architecture

## Responsibility split

The local platform has three independent responsibility layers.

### 1. Infrastructure bootstrap

`platform/scripts/ranger/bootstrap.yaml` declares principals, Ranger services,
the resource/tag association, and baseline Trino system grants.

```text
groups
technical users
resource service (dev_trino)
tag service (dev_tag)
association (dev_trino -> dev_tag)
system grants (execute + impersonate)
```

Bootstrap is idempotent. It reads live Ranger state, creates missing objects,
updates managed fields where needed, and otherwise returns `unchanged`.

### 2. Backend business policy catalog

`backend/config/policies.yaml` owns reusable business rules such as:

```text
PII.Email -> pii_readers -> select
PII.PaymentCard -> payment_data_readers -> select
```

Those policies are reconciled into the Ranger tag service by the backend. They
are not part of infrastructure bootstrap.

### 3. Runtime classification state

OpenMetadata Confirmed tags describe which concrete resources currently carry
a classification. The backend synchronizes that state to Ranger resource/tag
mappings. Removing a Confirmed tag removes the mapping; it does not delete the
reusable tag policy.

## Identity model

`governance-verifier-bot` is a technical Trino/Ranger identity. Creating it in
Ranger is not an OpenMetadata user synchronization flow. In production, an
external identity source such as LDAP/AD/Keycloak with Ranger UserSync should
normally own users and groups.

## Why system grants are merged

Ranger service definitions can generate default policies such as
`all - queryid`. Ranger may reject another policy for the exact same resource.
The bootstrap therefore treats `execute` and `impersonate` as grants:

```text
find exact-resource policy
  -> if present: add missing principal/access
  -> if absent: create fallback policy
```

This avoids duplicate-resource policy errors and keeps the process idempotent.

## Why bootstrap.yaml is now the only config file

Older revisions split the Trino service into `ranger_service.yaml`. That made
bootstrap dependent on a second file being copied correctly. The current design
keeps both `resource_service` and `tag_service` in `bootstrap.yaml`, so a single
file describes the desired Ranger topology.

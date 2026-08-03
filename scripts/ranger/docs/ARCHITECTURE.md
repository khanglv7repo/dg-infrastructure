# Ranger Bootstrap Architecture

## Responsibility split

The platform has three independent layers.

### 1. Infrastructure bootstrap

`platform/scripts/ranger/bootstrap.yaml` declares:

```text
groups
technical users
resource service (dev_trino)
tag service (dev_tag)
association (dev_trino -> dev_tag)
system grants (execute + impersonate)
technical data grants (scanner/verifier baseline read)
```

Bootstrap is idempotent. It reads current Ranger state, creates missing state,
merges grants into existing exact-resource policies when necessary, and returns
`unchanged` when desired state is already satisfied.

### 2. Backend business policy catalog

`backend/config/policies.yaml` owns reusable business rules such as:

```text
PII.Email -> pii_readers -> select
PII.PaymentCard -> payment_data_readers -> select
```

Those policies are reconciled into the Ranger tag service by the backend. They
are not infrastructure bootstrap state.

### 3. Runtime classification state

OpenMetadata Confirmed tags describe which concrete resources currently carry
a classification. The backend synchronizes that state to Ranger resource/tag
mappings. Removing a Confirmed tag removes the mapping; it does not delete the
reusable tag policy.

## Identity model

`governance-verifier-bot` is a technical Trino/Ranger identity. Creating it in
Ranger is not an OpenMetadata user synchronization flow. In production, an
external identity source such as LDAP/AD/Keycloak plus Ranger UserSync should
normally own users and groups.

## System grants vs technical data grants

System grants allow a Trino request to reach data authorization:

```text
execute
self-impersonate
```

They do not make a catalog readable. The scanner/verifier therefore also needs
technical data access to the catalog it scans:

```text
governance-verifier-bot
  -> financial
     -> schema *
        -> table *
           -> column *
              -> select
```

This is technical infrastructure access. It is deliberately separate from
business membership such as `pii_readers`.

## Why one technical grant expands to four resource depths

Trino 482 performs authorization at multiple depths:

```text
catalog check  -> catalog resource
schema browse  -> catalog/schema resource
table browse   -> catalog/schema/table resource
column select  -> catalog/schema/table/column resource
```

A deep column policy does not satisfy every direct ancestor check. The
technical-data reconciler expands one logical scope into exact policies/grants
for every configured valid leaf depth.

## Why grants are merged by resource

Ranger may already own an exact resource policy, for example `all - queryid`.
Creating another policy for the exact same resource can be rejected. Common
grant reconciliation therefore follows:

```text
find exact-resource policy
  -> present: add missing principal/access
  -> absent: create fallback policy
```

This applies to both system grants and technical data grants.

## Live service definition is authoritative

Bootstrap does not blindly assume Ranger payload resource names. It loads the
live Trino service definition, resolves resource/access names, validates the
catalog -> schema -> table -> column hierarchy, and fails before policy writes
if the installed service definition is incompatible.

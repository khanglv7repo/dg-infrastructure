# Troubleshooting

## Config file not found: ranger_service.yaml

Older bootstrap revisions depended on a second service YAML. Schema version 5
stores `resource_service` directly in `bootstrap.yaml`; `ranger_service.yaml`
is not required.

## Another policy already exists for matching resource

Ranger already owns a policy for the exact resource, commonly a generated policy
such as `all - queryid`. Do not create a second exact-resource policy. Common
grant reconciliation now locates that policy and merges the missing grant.

## User name ... does not exist in ranger admin

A policy references a principal Ranger does not know. For local technical users,
add the identity under `technical_users`. This is not an OpenMetadata user sync.
In production, provision identities through the organization identity source and
Ranger UserSync.

## Group name ... does not exist in ranger admin

Add the required local group under `groups` or provision it using UserSync.

## Principal ... cannot become user ...

The request lacks Trino self-impersonation authorization. Confirm the technical
user exists and the `impersonate` system grant converged.

## SELECT 1 works but SHOW CATALOGS is empty

This means system authorization can execute a query, but the user has no visible
catalog resource. Confirm `technical_data_grants` is present and the generated
catalog/schema/table/column grants converged.

## Access Denied: Cannot access catalog financial

The user passed `execute` and `impersonate` but lacks direct catalog permission.
Schema version 5 solves this by expanding the logical `financial` technical read
grant to each Trino hierarchy depth. Run bootstrap and then wait for Trino's
Ranger `PolicyRefresher` to load the new policy version.

Verify:

```sql
SHOW CATALOGS;
SHOW SCHEMAS FROM financial;
```

## There are no tagged resources for service dev_trino

This is not a technical-data-grant failure. It means Ranger tag policy plumbing
is active but Flow B has not yet synchronized any Confirmed OpenMetadata tag to
a concrete Ranger resource/tag mapping.

## DBeaver connects but metadata tree is incomplete

First verify the same identity with Trino SQL (`SHOW CATALOGS`, `SHOW SCHEMAS`,
`SHOW TABLES`). Some JDBC clients also query Trino's `system` catalog for extra
metadata. Do not automatically grant the entire `system` catalog unless the
client actually requires it; add a narrowly reviewed local technical grant if
needed.

## Resource service shows updated on every run

Blank desired secret values are treated as unmanaged so Ranger's masked stored
password does not cause a false diff on every bootstrap run.

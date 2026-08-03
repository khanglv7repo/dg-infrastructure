# bootstrap.yaml Reference

Schema version: `5`.

## groups

Ranger groups referenced by business policies. These are authorization
principals, not OpenMetadata teams.

## technical_users

Small set of local technical identities that Ranger policies reference directly.
Bootstrap creates a missing principal through Ranger's external-user API and
does not create a login password. Existing users are not mutated because they
may be owned by LDAP/AD/UserSync.

## resource_service

Ranger service used by Trino. Default local name: `dev_trino`.

Environment overrides:

```text
RANGER_RESOURCE_SERVICE_NAME
TRINO_SERVICE_NAME
```

A blank `configs.password` means bootstrap does not take ownership of the stored
secret. This avoids repeated updates when Ranger masks password values on reads.

## tag_service

Ranger tag-policy service. Default local name: `dev_tag`.

Override:

```text
RANGER_TAG_SERVICE_NAME
```

## system_grants

Baseline Trino authorization required before resource/tag policy evaluation.
Each entry contains a fallback policy name, principals, one semantic resource,
values, and access types. Names are resolved against the live Trino service
definition.

Current local requirements:

```text
Query ID=* -> governance-verifier-bot -> execute
Trino User=governance-verifier-bot -> governance-verifier-bot -> impersonate
```

## technical_data_grants

Infrastructure data access for backend technical identities. It is not a PII
business policy.

Example:

```yaml
technical_data_grants:
  - name: dg-technical-governance-verifier-financial-read
    description: Allow the governance verifier to read the local financial catalog.
    users:
      - governance-verifier-bot
    resources:
      catalog: financial
      schema: "*"
      table: "*"
      column: "*"
    accesses:
      - select
```

Resource values may be a string or list. Configured resources must form a
contiguous path beginning at `catalog`:

```text
catalog
catalog -> schema
catalog -> schema -> table
catalog -> schema -> table -> column
```

The reconciler validates the path against the live Ranger service definition
and creates/merges a grant at every configured depth. The fallback policy names
are suffixed with the depth (`-catalog`, `-schema`, `-table`, `-column`).

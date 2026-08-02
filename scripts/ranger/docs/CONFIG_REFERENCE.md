# bootstrap.yaml Reference

Schema version: `4`.

## groups

Ranger groups referenced by business policies. These are authorization
principals, not OpenMetadata teams.

## technical_users

Small set of local technical identities that Ranger policies reference directly.
The bootstrap creates a missing principal through Ranger's external-user API and
does not create a login password. Existing users are not mutated because they
may be owned by LDAP/AD/UserSync.

## resource_service

The Ranger service used by Trino. Default local name: `dev_trino`.

Supported environment overrides:

```text
RANGER_RESOURCE_SERVICE_NAME
TRINO_SERVICE_NAME
```

A blank `configs.password` means bootstrap does not take ownership of the stored
secret. Ranger can mask passwords on reads, so ignoring a blank desired password
prevents a false update on every run.

## tag_service

The Ranger tag-policy service. Default local name: `dev_tag`.

Override:

```text
RANGER_TAG_SERVICE_NAME
```

## system_grants

Baseline Trino authorization grants that must pass before table/tag access can
be evaluated.

Each grant contains:

- a fallback policy `name`
- `users` and/or `groups`
- a semantic resource plus aliases
- resource values
- required access types

Resource/access names are resolved against the live Trino Ranger service
definition instead of being hard-coded.

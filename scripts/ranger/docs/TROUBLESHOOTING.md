# Troubleshooting

## Config file not found: ranger_service.yaml

This was a bootstrap packaging/design bug in older revisions. The current schema
(version 4) stores `resource_service` directly in `bootstrap.yaml` and does not
require `ranger_service.yaml`.

## Another policy already exists for matching resource

Ranger already owns a policy for the exact resource, commonly a generated policy
such as `all - queryid`. Do not create a second policy. The system-grant
reconciler now finds the exact-resource policy and merges the missing grant.

## User name ... does not exist in ranger admin

A policy references a principal Ranger does not know. For local technical users,
add the identity under `technical_users`. This is not an OpenMetadata user sync.
In production, provision the identity through the organization identity source
and Ranger UserSync.

## Group name ... does not exist in ranger admin

Add the required local group under `groups` or provision it using UserSync.

## Principal ... cannot become user ...

The request passed identity creation/authentication but lacks Trino Ranger
impersonation authorization. Confirm the technical user exists and the
`impersonate` system grant converged.

## Resource service shows updated on every run

Older revisions could compare an empty desired password against Ranger's masked
stored password. Version 4 treats blank secret config values as unmanaged, so a
stable service should converge to `unchanged`.

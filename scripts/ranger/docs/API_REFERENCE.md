# Ranger REST API Used by Bootstrap

The implementation targets the Ranger 2.8.0 REST API exposed by the local Ranger
Admin instance.

## Service definitions

```text
GET /service/public/v2/api/servicedef/name/{name}
```

Used to discover the actual Trino resource and access names before creating
system grants.

## Services

```text
GET  /service/public/v2/api/service/name/{name}
POST /service/public/v2/api/service
PUT  /service/public/v2/api/service/name/{name}
```

Used for `dev_trino`, `dev_tag`, and the `tagService` association field.

## Groups

```text
GET  /service/xusers/groups
POST /service/xusers/groups
PUT  /service/xusers/groups
```

## Technical users

```text
GET  /service/xusers/users
POST /service/xusers/users/external
```

The external-user endpoint registers a Ranger policy principal. It is not used
to synchronize OpenMetadata users or create a Trino login password.

## Policies

```text
GET  /service/public/v2/api/service/{service}/policy
GET  /service/public/v2/api/service/{service}/policy/{policy}
POST /service/public/v2/api/policy
PUT  /service/public/v2/api/service/{service}/policy/{policy}
```

The list endpoint is required so bootstrap can locate an existing policy with an
exact matching resource and merge a baseline grant into it.

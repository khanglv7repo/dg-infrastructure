# Legacy Platform Migration

Source: `/home/minh_chau/Documents/goto_ssi/old`.

## Retain and refactor

| Legacy capability | Current destination | Refactor rule |
|---|---|---|
| Docker OpenMetadata, PostgreSQL, OpenSearch, Ranger, and Trino lab | `platform/docker-compose.yml`, `platform/docker/` | Infrastructure only; no application business logic in Compose. |
| OpenMetadata metadata ingestion | `governance_app/docker/metadata-ingestion/` | Use `OM_INGESTION_BOT_TOKEN` only; no admin JWT/login fallback. |
| Ranger/Trino bootstrap configuration | `platform/ranger/`, `platform/trino/` | Preserve Docker bootstrap only; governance policy reconciliation remains owned by `governance_app`. |
| OpenMetadata migration wrapper | `platform/openmetadata/` | Retain the upstream migration startup wrapper. |

## Do not migrate into runtime

- `services/governance-automation-api`, Faker, DQ, tag-sync, and `openmetadata-ranger-policy-as-code`: legacy scripts only. They are outside this infrastructure migration and must not become a second application/runtime.
- OpenMetadata admin JWT/PAT, admin email/password, automatic admin login, `.env` files, generated reports, caches, and live data.

## Migration order

1. Move the reusable infrastructure files under `platform/` and provide a root compose entrypoint.
2. Keep the migrated Bot-only ingestion sidecar as the only ingestion runtime.
3. Validate Compose rendering without secrets, then run live checks only with the existing Bot/service credentials.

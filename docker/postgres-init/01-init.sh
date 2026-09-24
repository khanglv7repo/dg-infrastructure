#!/bin/sh
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<EOSQL
CREATE ROLE ${OPENMETADATA_DB_USER} LOGIN PASSWORD '${OPENMETADATA_DB_PASSWORD}';
CREATE DATABASE ${OPENMETADATA_DB} OWNER ${OPENMETADATA_DB_USER};
CREATE ROLE ${TRINO_DB_USER} LOGIN PASSWORD '${TRINO_DB_PASSWORD}';
CREATE DATABASE ${FINANCIAL_DB} OWNER ${POSTGRES_USER};
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$FINANCIAL_DB" <<EOSQL
CREATE SCHEMA IF NOT EXISTS raw AUTHORIZATION ${POSTGRES_USER};
CREATE SCHEMA IF NOT EXISTS analytics AUTHORIZATION ${POSTGRES_USER};
GRANT CONNECT ON DATABASE ${FINANCIAL_DB} TO ${TRINO_DB_USER};
GRANT USAGE ON SCHEMA raw, analytics TO ${TRINO_DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA raw GRANT SELECT ON TABLES TO ${TRINO_DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO ${TRINO_DB_USER};
EOSQL

# TASK-10: Backend/Agent database separation, per
# planning/03-CODE-EDIT-MANIFEST.md's "Initial databases" row and
# docs/DG_FINAL_SPEC.md section 12.1/section 10. This block only runs on a
# genuinely fresh Postgres volume (Postgres only executes
# docker-entrypoint-initdb.d scripts once, on first init of an empty data
# directory), but is still written idempotently so it is safe to re-run by
# hand against a non-empty cluster (e.g. this repo's own live dev DB already
# has a manually-created governance_db from before this variable existed --
# re-running must be a no-op there, never an error or a reassignment).
#
# PostgreSQL has neither `CREATE ROLE IF NOT EXISTS` nor
# `CREATE DATABASE IF NOT EXISTS` (verified live against this exact image,
# postgres:15.18 -- both raise a syntax error). CREATE DATABASE also cannot
# run inside a DO $$ ... $$ block (not allowed in a multi-statement
# transaction). The portable pattern is a shell-level existence check before
# each CREATE, one psql call per check.
create_role_if_missing() {
  role_name="$1"
  role_password="$2"
  exists=$(psql -tAc "SELECT 1 FROM pg_roles WHERE rolname = '${role_name}'" \
    --username "$POSTGRES_USER" --dbname postgres)
  if [ "$exists" != "1" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
      -c "CREATE ROLE ${role_name} LOGIN PASSWORD '${role_password}';"
  fi
}

create_database_if_missing() {
  db_name="$1"
  db_owner="$2"
  exists=$(psql -tAc "SELECT 1 FROM pg_database WHERE datname = '${db_name}'" \
    --username "$POSTGRES_USER" --dbname postgres)
  if [ "$exists" != "1" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
      -c "CREATE DATABASE ${db_name} OWNER ${db_owner};"
  fi
}

create_role_if_missing "${GOVERNANCE_DB_USER}" "${GOVERNANCE_DB_PASSWORD}"
create_database_if_missing "${GOVERNANCE_DB}" "${GOVERNANCE_DB_USER}"

create_role_if_missing "${AGENT_CHECKPOINT_DB_USER}" "${AGENT_CHECKPOINT_DB_PASSWORD}"
create_database_if_missing "${AGENT_CHECKPOINT_DB}" "${AGENT_CHECKPOINT_DB_USER}"

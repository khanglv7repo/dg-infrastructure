#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

set -a
source "$ROOT_DIR/.env"
set +a

export RANGER_URL="${RANGER_URL:-http://localhost:6080}"
export RANGER_USERNAME="${RANGER_BOOTSTRAP_USER:-admin}"
export RANGER_PASSWORD="${RANGER_BOOTSTRAP_PASSWORD:?RANGER_BOOTSTRAP_PASSWORD is required}"
export RANGER_SERVICE_NAME="${RANGER_SERVICE_NAME:-dev_trino}"

python3 "$ROOT_DIR/docker/ranger-init/init.py"
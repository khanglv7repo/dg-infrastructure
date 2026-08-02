#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$ROOT_DIR/data"

mkdir -p \
  "$DATA_DIR/postgres" \
  "$DATA_DIR/opensearch" \
  "$DATA_DIR/ranger-db" \
  "$DATA_DIR/ranger-solr"

chmod -R 0777 "$DATA_DIR"

echo "Prepared data directories:"
find "$DATA_DIR" -maxdepth 2 -type d -printf '%m %u:%g %p\n'
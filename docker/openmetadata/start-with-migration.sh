#!/usr/bin/env bash
set -Eeuo pipefail

cd /opt/openmetadata
./bootstrap/openmetadata-ops.sh migrate
exec /bin/bash /openmetadata-start.sh

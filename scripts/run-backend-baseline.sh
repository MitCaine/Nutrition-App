#!/usr/bin/env bash
# Run the parked backend's ordinary test baseline (no PostgreSQL/Docker required).
set -euo pipefail
cd "$(dirname "$0")/../apps/backend"
python -m ruff check .
python -m pytest -q -m "not postgres_concurrency and not phase5c_performance_t0 and \
not phase5c4_control_postgres and not phase5c4_minio and not phase5c4_docker_integration" "$@"

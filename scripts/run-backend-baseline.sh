#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_ROOT="$REPO_ROOT/apps/backend"

ORDINARY_BACKEND_MARKERS='not postgres_concurrency and not phase5c_performance_t0 and not phase5c4_control_postgres and not phase5c4_minio and not phase5c4_docker_integration'

if [[ "${1:-}" == "--print-marker-expression" ]]; then
    printf '%s\n' "$ORDINARY_BACKEND_MARKERS"
    exit 0
fi

if [[ -n "${NUTRITION_BACKEND_PYTHON:-}" ]]; then
    BACKEND_PYTHON="$NUTRITION_BACKEND_PYTHON"
elif [[ -x "$BACKEND_ROOT/.venv/bin/python" ]]; then
    BACKEND_PYTHON="$BACKEND_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    BACKEND_PYTHON="$(command -v python3)"
else
    echo "Unable to locate a Python interpreter for the backend baseline." >&2
    exit 1
fi

if [[ "$BACKEND_PYTHON" == */* ]]; then
    [[ -x "$BACKEND_PYTHON" ]] || {
        echo "Backend Python is not executable: $BACKEND_PYTHON" >&2
        exit 1
    }
else
    command -v "$BACKEND_PYTHON" >/dev/null 2>&1 || {
        echo "Backend Python is unavailable: $BACKEND_PYTHON" >&2
        exit 1
    }
fi

cd "$BACKEND_ROOT"

exec "$BACKEND_PYTHON" -m pytest \
    -m "$ORDINARY_BACKEND_MARKERS" \
    "$@"

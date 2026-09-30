#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_ROOT="$REPO_ROOT/apps/backend"

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

if [[ "${1:-}" == "--print-marker-expression" ]]; then
    exec "$BACKEND_PYTHON" -I "$REPO_ROOT/scripts/lib/backend_qualification.py" \
        baseline --print-marker-expression
fi

exec "$BACKEND_PYTHON" -I "$REPO_ROOT/scripts/lib/backend_qualification.py" \
    baseline --candidate-root "$REPO_ROOT" -- "$@"

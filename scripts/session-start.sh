#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/selected-python.sh"
nutrition_select_python

if [[ "${1:-}" != "--json" ]]; then
    "$NUTRITION_DEPS_PYTHON" "$ROOT/scripts/toolchain-report.py"
fi

exec "$ROOT/scripts/project-audit.sh" session "$@"

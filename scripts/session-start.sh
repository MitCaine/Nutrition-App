#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" != "--json" ]]; then
    python3 "$ROOT/scripts/toolchain-report.py"
fi

exec "$ROOT/scripts/project-audit.sh" session "$@"

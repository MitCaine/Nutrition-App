#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/selected-python.sh"
nutrition_select_python
# Keep JSON stdout machine-readable. Node is diagnostic, not a Python gate.
"$NUTRITION_DEPS_PYTHON" "$ROOT/scripts/toolchain-report.py" --check python >&2
exec "$NUTRITION_DEPS_PYTHON" "$ROOT/scripts/project-audit.py" "$@"

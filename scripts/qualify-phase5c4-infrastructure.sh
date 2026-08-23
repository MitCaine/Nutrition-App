#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${NUTRITION_PHASE5C4_QUALIFICATION_CONFIRM:-}" != \
  "phase5c4_infrastructure_destroy_disposable" ]]; then
  echo "Refusing destructive qualification without exact disposable confirmation." >&2
  echo "Set NUTRITION_PHASE5C4_QUALIFICATION_CONFIRM=phase5c4_infrastructure_destroy_disposable" >&2
  exit 2
fi

echo "Destructive scope: one generated nutrition-p5c4q-* Compose project only."
echo "Services: source/restored/control PostgreSQL 16, pgBackRest, MinIO, local route provider."
echo "All project containers, networks, and volumes will be removed on success or failure."

BACKEND_DIR="$ROOT/apps/backend"
PYTHON="$BACKEND_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "Backend Python environment is missing at apps/backend/.venv." >&2
  exit 1
fi

cd "$BACKEND_DIR"
exec "$PYTHON" -m scripts.qualify_phase5c4_infrastructure

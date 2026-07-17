#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/apps/backend"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: Docker is not installed or is not on PATH."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Error: Docker Desktop is not running."
  exit 1
fi

# Locate the repository's Compose file.
COMPOSE_FILE=""
for candidate in \
  "$ROOT_DIR/compose.yaml" \
  "$ROOT_DIR/compose.yml" \
  "$ROOT_DIR/docker-compose.yaml" \
  "$ROOT_DIR/docker-compose.yml"
do
  if [[ -f "$candidate" ]]; then
    COMPOSE_FILE="$candidate"
    break
  fi
done

if [[ -z "$COMPOSE_FILE" ]]; then
  echo "Error: No Docker Compose file found in:"
  echo "  $ROOT_DIR"
  exit 1
fi

COMPOSE=(docker compose -f "$COMPOSE_FILE")

# Detect the PostgreSQL service name.
POSTGRES_SERVICE=""
for candidate in postgres db database; do
  if "${COMPOSE[@]}" config --services | grep -qx "$candidate"; then
    POSTGRES_SERVICE="$candidate"
    break
  fi
done

if [[ -z "$POSTGRES_SERVICE" ]]; then
  echo "Error: Could not find a PostgreSQL Compose service."
  echo "Available services:"
  "${COMPOSE[@]}" config --services
  exit 1
fi

echo "Starting PostgreSQL service: $POSTGRES_SERVICE"
"${COMPOSE[@]}" up -d "$POSTGRES_SERVICE"

echo "Waiting for PostgreSQL..."
for attempt in {1..30}; do
  if "${COMPOSE[@]}" exec -T "$POSTGRES_SERVICE" \
    pg_isready -U nutrition_app -d nutrition_app >/dev/null 2>&1
  then
    echo "PostgreSQL is ready."
    break
  fi

  if [[ "$attempt" -eq 30 ]]; then
    echo "Error: PostgreSQL did not become ready."
    "${COMPOSE[@]}" logs "$POSTGRES_SERVICE"
    exit 1
  fi

  sleep 1
done

cd "$BACKEND_DIR"

if [[ ! -f ".env" ]]; then
  echo "Error: $BACKEND_DIR/.env does not exist."
  echo "Create it from .env.example and configure the runtime database URL."
  exit 1
fi

# Prefer the backend virtual environment when present.
if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

echo "Using Python: $("$PYTHON" --version)"

echo "Checking runtime configuration and database identity..."
"$PYTHON" - <<'PY'
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.core.database_identity import redacted_database_url

print(f"Deployment mode: {settings.deployment_mode.value}")
print(f"Process mode: {settings.process_mode.value}")
print(f"Database: {redacted_database_url(settings.database_url)}")
print(f"USDA key loaded: {bool(settings.usda_api_key)}")

if settings.process_mode.value != "runtime":
    raise SystemExit(
        "start-backend.sh only starts the runtime process. "
        f"Configured process mode is {settings.process_mode.value!r}."
    )

if not settings.usda_api_key:
    print("Warning: USDA search/import will be unavailable.")

engine = create_engine(settings.database_url)

with engine.connect() as connection:
    session_user, current_user = connection.execute(
        text("SELECT session_user, current_user")
    ).one()

print(f"Database session user: {session_user}")
print(f"Database current user: {current_user}")

if session_user != "nutrition_runtime":
    raise SystemExit(
        "Refusing to start FastAPI with a non-runtime database login. "
        f"Expected nutrition_runtime, received {session_user!r}. "
        "Apply migrations separately using nutrition_migrator."
    )

if current_user != "nutrition_runtime":
    raise SystemExit(
        "Refusing to start FastAPI with an unexpected effective database role. "
        f"Expected nutrition_runtime, received {current_user!r}."
    )
PY

echo "Alembic migrations are not run by this script."
echo "Apply migrations separately using the nutrition_migrator identity."

echo "Starting FastAPI at http://localhost:$PORT"
exec "$PYTHON" -m uvicorn app.main:app \
  --host "$HOST" \
  --port "$PORT"

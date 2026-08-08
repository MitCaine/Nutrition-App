#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/apps/backend"
POSTGRES_IMAGE="postgres:16@sha256:33f923b05f64ca54ac4401c01126a6b92afe839a0aa0a52bc5aeb5cc958e5f20"
OUTPUT_DIR=""
CONTAINER_NAME=""
CONTAINER_STARTED=false
MANUAL_TEST=false
KEEP_CONTAINER=false

usage() {
    echo "usage: $0 [--output-dir PATH] [--manual-test]" >&2
}

cleanup() {
    if [[ "$CONTAINER_STARTED" == true && "$KEEP_CONTAINER" != true && -n "$CONTAINER_NAME" ]]; then
        docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir)
            if [[ $# -lt 2 ]]; then
                usage
                exit 2
            fi
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --manual-test)
            MANUAL_TEST=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage
            exit 2
            ;;
    esac
done

if ! command -v docker >/dev/null 2>&1; then
    echo "Issue 17 Phase 5C workflow requires Docker." >&2
    exit 1
fi

PYTHON_BIN="${NUTRITION_ISSUE17_PYTHON:-$BACKEND/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Issue 17 Phase 5C workflow requires the backend Python environment." >&2
    exit 1
fi

if [[ -n "${NUTRITION_ISSUE17_RUN_ID:-}" ]]; then
    RUN_ID="$NUTRITION_ISSUE17_RUN_ID"
else
    RUN_ID="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_hex(6))')"
fi
if [[ ! "$RUN_ID" =~ ^[0-9a-f]{12}$ ]]; then
    echo "Issue 17 workflow run ID must be exactly 12 lowercase hexadecimal characters." >&2
    exit 1
fi

if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nutrition-issue17-phase5c.XXXXXX")"
else
    if [[ -L "$OUTPUT_DIR" ]]; then
        echo "Issue 17 output directory must not be a symbolic link." >&2
        exit 1
    fi
    mkdir -p "$OUTPUT_DIR"
    if [[ -n "$(find "$OUTPUT_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
        echo "Issue 17 output directory must be empty." >&2
        exit 1
    fi
    chmod 700 "$OUTPUT_DIR"
fi

CONTAINER_NAME="nutrition-issue17-phase5c-$RUN_ID"
SOURCE_DATABASE="nutrition_phase5c_bench_i17_source_$RUN_ID"
CLONE_DATABASE="nutrition_phase5c_bench_i17_clone_$RUN_ID"
POSTGRES_PASSWORD="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(32))')"
RUNTIME_PASSWORD="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(32))')"

docker run --detach --rm \
    --name "$CONTAINER_NAME" \
    --label nutrition.issue17.phase5c=true \
    --label "nutrition.issue17.run=$RUN_ID" \
    --env POSTGRES_DB=postgres \
    --env POSTGRES_USER=postgres \
    --env "POSTGRES_PASSWORD=$POSTGRES_PASSWORD" \
    --publish 127.0.0.1::5432 \
    "$POSTGRES_IMAGE" >/dev/null
CONTAINER_STARTED=true

attempt=0
while [[ $attempt -lt 60 ]]; do
    if docker exec "$CONTAINER_NAME" pg_isready -U postgres -d postgres >/dev/null 2>&1; then
        break
    fi
    attempt=$((attempt + 1))
    sleep 1
done
if [[ $attempt -ge 60 ]]; then
    echo "Disposable PostgreSQL did not become ready." >&2
    exit 1
fi

PORT_MAPPING="$(docker port "$CONTAINER_NAME" 5432/tcp)"
HOST_PORT="${PORT_MAPPING##*:}"
if [[ ! "$HOST_PORT" =~ ^[0-9]+$ ]]; then
    echo "Unable to resolve the disposable PostgreSQL loopback port." >&2
    exit 1
fi

export NUTRITION_ISSUE17_ADMIN_URL="postgresql+psycopg://postgres:$POSTGRES_PASSWORD@127.0.0.1:$HOST_PORT/postgres"
export NUTRITION_ISSUE17_RUNTIME_PASSWORD="$RUNTIME_PASSWORD"
export NUTRITION_DEPLOYMENT_MODE=test
export NUTRITION_DATABASE_URL="$NUTRITION_ISSUE17_ADMIN_URL"

cd "$BACKEND"
ORCHESTRATOR_ARGUMENTS=(
    --output-dir "$OUTPUT_DIR"
    --source-database "$SOURCE_DATABASE"
    --clone-database "$CLONE_DATABASE"
    --container-name "$CONTAINER_NAME"
)
if [[ "$MANUAL_TEST" == true ]]; then
    ORCHESTRATOR_ARGUMENTS+=(--manual-test)
fi
"$PYTHON_BIN" -m scripts.qualify_issue17_phase5c_clone \
    "${ORCHESTRATOR_ARGUMENTS[@]}"

echo "Issue 17 Phase 5C evidence: $OUTPUT_DIR"
if [[ "$MANUAL_TEST" == true ]]; then
    RUNTIME_URL="postgresql+psycopg://nutrition_runtime:$RUNTIME_PASSWORD@127.0.0.1:$HOST_PORT/$CLONE_DATABASE"
    echo "Manual-test PostgreSQL URL: $RUNTIME_URL"
    echo "Start the backend:"
    echo "  cd '$BACKEND'"
    echo "  NUTRITION_DEPLOYMENT_MODE=test NUTRITION_DATABASE_URL='$RUNTIME_URL' .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
    echo "Cleanup when manual testing is complete:"
    echo "  docker rm -f '$CONTAINER_NAME'"
    KEEP_CONTAINER=true
fi

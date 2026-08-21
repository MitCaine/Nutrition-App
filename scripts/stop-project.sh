#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.project-runtime"

source "$ROOT_DIR/scripts/lib/project-process.sh"

BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
EXPO_PID_FILE="$RUNTIME_DIR/expo.pid"
SIMULATOR_UDID_FILE="$RUNTIME_DIR/simulator-udid"
SIMULATOR_STARTED_FILE="$RUNTIME_DIR/simulator-started"

find_compose_file() {
  local candidate

  for candidate in \
    "$ROOT_DIR/compose.yaml" \
    "$ROOT_DIR/compose.yml" \
    "$ROOT_DIR/docker-compose.yaml" \
    "$ROOT_DIR/docker-compose.yml"
  do
    if [[ -f "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

echo "Stopping Nutrition App project services..."

project_process_stop_from_record \
  "$EXPO_PID_FILE" \
  expo \
  "Expo"

project_process_stop_from_record \
  "$BACKEND_PID_FILE" \
  backend \
  "backend"

if [[
  -f "$SIMULATOR_STARTED_FILE"
  && -f "$SIMULATOR_UDID_FILE"
]]
then
  simulator_udid="$(cat "$SIMULATOR_UDID_FILE")"

  if command -v xcrun >/dev/null 2>&1; then
    echo "Shutting down project simulator..."
    xcrun simctl shutdown "$simulator_udid" 2>/dev/null || true
  else
    echo "xcrun is unavailable; simulator could not be shut down."
  fi
else
  echo "Simulator was not started by this project; leaving it running."
fi

rm -f \
  "$SIMULATOR_STARTED_FILE" \
  "$SIMULATOR_UDID_FILE"

if compose_file="$(find_compose_file)"; then
  if command -v docker >/dev/null 2>&1 &&
     docker info >/dev/null 2>&1
  then
    echo "Stopping repository Docker Compose services..."
    docker compose -f "$compose_file" down
  else
    echo "Docker is unavailable; Compose services could not be stopped."
  fi
fi

rm -rf "$RUNTIME_DIR"

echo "Nutrition App project services stopped."

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

for simulator_record in "$SIMULATOR_STARTED_FILE" "$SIMULATOR_UDID_FILE"; do
  if [[ -L "$simulator_record" || ( -e "$simulator_record" && ! -f "$simulator_record" ) ]]; then
    echo "Incomplete cleanup: ambiguous simulator record; preserving simulator records." >&2
    exit 1
  fi
done

if [[ -f "$SIMULATOR_STARTED_FILE" ]]; then
  if [[ ! -s "$SIMULATOR_UDID_FILE" ]]; then
    echo "Incomplete cleanup: simulator identity is missing; preserving simulator records." >&2
    exit 1
  fi
  simulator_udid="$(cat "$SIMULATOR_UDID_FILE")"

  if command -v xcrun >/dev/null 2>&1; then
    echo "Shutting down project simulator..."
    if ! xcrun simctl shutdown "$simulator_udid"; then
      echo "Incomplete cleanup: simulator shutdown failed; preserving simulator records." >&2
      exit 1
    fi
  else
    echo "Incomplete cleanup: xcrun is unavailable; preserving simulator records." >&2
    exit 1
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
    if ! docker compose -f "$compose_file" down; then
      echo "Incomplete cleanup: Docker Compose shutdown failed; preserving runtime state." >&2
      exit 1
    fi
  else
    echo "Incomplete cleanup: Docker is unavailable; preserving runtime state for Compose cleanup." >&2
    exit 1
  fi
fi

rm -rf "$RUNTIME_DIR"

echo "Nutrition App project services stopped."

#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.project-runtime"
BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
EXPO_PID_FILE="$RUNTIME_DIR/expo.pid"
SIMULATOR_UDID_FILE="$RUNTIME_DIR/simulator-udid"
SIMULATOR_STARTED_FILE="$RUNTIME_DIR/simulator-started"

process_is_running() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null
}

child_pids() {
  local parent_pid="$1"
  ps -ax -o pid= -o ppid= |
    awk -v parent="$parent_pid" '$2 == parent { print $1 }'
}

stop_process_tree() {
  local pid="$1"
  local service_name="$2"

  if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
    echo "Ignoring invalid $service_name PID: $pid"
    return
  fi

  if ! process_is_running "$pid"; then
    echo "$service_name PID $pid is no longer running."
    return
  fi

  # Stop descendants first. Expo and Uvicorn may create child processes.
  local child
  while read -r child; do
    if [[ -n "$child" ]]; then
      stop_process_tree "$child" "$service_name child"
    fi
  done < <(child_pids "$pid")

  echo "Stopping $service_name PID $pid..."
  kill -TERM "$pid" 2>/dev/null || true

  for _ in {1..10}; do
    if ! process_is_running "$pid"; then
      return
    fi
    sleep 1
  done

  if process_is_running "$pid"; then
    echo "$service_name PID $pid did not stop gracefully; sending SIGKILL."
    kill -KILL "$pid" 2>/dev/null || true
  fi
}

stop_from_pid_file() {
  local pid_file="$1"
  local service_name="$2"

  if [[ ! -f "$pid_file" ]]; then
    echo "No recorded $service_name process found."
    return
  fi

  local pid
  pid="$(cat "$pid_file")"

  stop_process_tree "$pid" "$service_name"
  rm -f "$pid_file"
}

echo "Stopping Nutrition App project services..."

# Stop Expo first so it does not attempt to reconnect while the backend stops.
stop_from_pid_file "$EXPO_PID_FILE" "Expo"
stop_from_pid_file "$BACKEND_PID_FILE" "backend"

# Shut down the simulator only when start-project.sh booted it.
# A simulator that was already running before startup is left running.
if [[ -f "$SIMULATOR_STARTED_FILE" && -f "$SIMULATOR_UDID_FILE" ]]; then
  simulator_udid="$(cat "$SIMULATOR_UDID_FILE")"

  if command -v xcrun >/dev/null 2>&1; then
    echo "Shutting down project simulator..."
    xcrun simctl shutdown "$simulator_udid" 2>/dev/null || true
  fi
else
  echo "Simulator was not started by this project; leaving it running."
fi

rm -f "$SIMULATOR_STARTED_FILE" "$SIMULATOR_UDID_FILE"

# Locate the same default Compose file used by start-backend.sh.
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

if [[ -n "$COMPOSE_FILE" ]]; then
  if command -v docker >/dev/null 2>&1 &&
     docker info >/dev/null 2>&1
  then
    echo "Stopping repository Docker Compose services..."
    docker compose -f "$COMPOSE_FILE" down
  else
    echo "Docker is unavailable; Compose services could not be stopped."
  fi
fi

rm -rf "$RUNTIME_DIR"

echo "Nutrition App project services stopped."
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

  [[ "$pid" =~ ^[0-9]+$ ]] &&
    kill -0 "$pid" 2>/dev/null
}

get_child_pids() {
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

  local child_pid

  while read -r child_pid; do
    if [[ -n "$child_pid" ]]; then
      stop_process_tree "$child_pid" "$service_name child"
    fi
  done < <(get_child_pids "$pid")

  echo "Stopping $service_name PID $pid..."
  kill -TERM "$pid" 2>/dev/null || true

  for _ in {1..15}; do
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

# Stop the mobile process first so it does not keep reconnecting to Metro
# or the backend while the remaining services are shutting down.
stop_from_pid_file "$EXPO_PID_FILE" "Expo"
stop_from_pid_file "$BACKEND_PID_FILE" "backend"

if [[ -f "$SIMULATOR_STARTED_FILE" &&
      -f "$SIMULATOR_UDID_FILE" ]]
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
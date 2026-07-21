#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOBILE_DIR="$ROOT_DIR/apps/mobile"
RUNTIME_DIR="$ROOT_DIR/.project-runtime"

BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
EXPO_PID_FILE="$RUNTIME_DIR/expo.pid"
SIMULATOR_UDID_FILE="$RUNTIME_DIR/simulator-udid"
SIMULATOR_STARTED_FILE="$RUNTIME_DIR/simulator-started"

BACKEND_LOG="$RUNTIME_DIR/backend.log"
EXPO_LOG="$RUNTIME_DIR/expo.log"

SIMULATOR_NAME="${SIMULATOR_NAME:-iPhone 17 Pro Max}"
PORT="${PORT:-8000}"

mkdir -p "$RUNTIME_DIR"

process_is_running() {
  local pid="$1"

  [[ "$pid" =~ ^[0-9]+$ ]] &&
    kill -0 "$pid" 2>/dev/null
}

remove_stale_pid_file() {
  local pid_file="$1"
  local service_name="$2"

  if [[ ! -f "$pid_file" ]]; then
    return
  fi

  local pid
  pid="$(cat "$pid_file")"

  if process_is_running "$pid"; then
    echo "Error: $service_name is already running with PID $pid."
    echo "Run scripts/stop-project.sh first."
    exit 1
  fi

  rm -f "$pid_file"
}

find_simulator_udid() {
  xcrun simctl list devices available -j |
    python3 -c '
import json
import sys

target = sys.argv[1]
data = json.load(sys.stdin)

for runtime_devices in data.get("devices", {}).values():
    for device in runtime_devices:
        if (
            device.get("name") == target
            and device.get("isAvailable", False)
        ):
            print(device["udid"])
            raise SystemExit(0)

raise SystemExit(1)
' "$SIMULATOR_NAME"
}

get_simulator_state() {
  local simulator_udid="$1"

  xcrun simctl list devices -j |
    python3 -c '
import json
import sys

target = sys.argv[1]
data = json.load(sys.stdin)

for runtime_devices in data.get("devices", {}).values():
    for device in runtime_devices:
        if device.get("udid") == target:
            print(device.get("state", "Unknown"))
            raise SystemExit(0)

print("Unknown")
' "$simulator_udid"
}

wait_for_log_pattern() {
  local pid="$1"
  local log_file="$2"
  local pattern="$3"
  local timeout_seconds="$4"
  local service_name="$5"

  local elapsed=0

  while (( elapsed < timeout_seconds )); do
    if grep -Eq "$pattern" "$log_file" 2>/dev/null; then
      return 0
    fi

    if ! process_is_running "$pid"; then
      echo "Error: $service_name exited during startup."
      echo
      cat "$log_file"
      return 1
    fi

    sleep 1
    elapsed=$((elapsed + 1))
  done

  echo "Error: Timed out waiting for $service_name to become ready."
  echo
  tail -n 100 "$log_file" 2>/dev/null || true
  return 1
}

cleanup_failed_start() {
  echo
  echo "Startup failed. Cleaning up partially started services..."

  "$ROOT_DIR/scripts/stop-project.sh" || true
}

trap cleanup_failed_start ERR

remove_stale_pid_file "$BACKEND_PID_FILE" "Backend"
remove_stale_pid_file "$EXPO_PID_FILE" "Expo"

if [[ ! -x "$ROOT_DIR/scripts/start-backend.sh" ]]; then
  echo "Error: scripts/start-backend.sh is missing or not executable."
  exit 1
fi

if [[ ! -x "$ROOT_DIR/scripts/stop-project.sh" ]]; then
  echo "Error: scripts/stop-project.sh is missing or not executable."
  exit 1
fi

if [[ ! -d "$MOBILE_DIR" ]]; then
  echo "Error: Mobile directory not found:"
  echo "  $MOBILE_DIR"
  exit 1
fi

if ! command -v xcrun >/dev/null 2>&1; then
  echo "Error: xcrun is unavailable."
  echo "Install Xcode and its command-line tools."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Error: npm is not installed or is not on PATH."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is not installed or is not on PATH."
  exit 1
fi

echo "Locating simulator: $SIMULATOR_NAME"

if ! simulator_udid="$(find_simulator_udid)"; then
  echo "Error: An available '$SIMULATOR_NAME' simulator was not found."
  echo
  echo "Available iPhone simulators:"
  xcrun simctl list devices available |
    grep "iPhone" || true
  exit 1
fi

printf '%s\n' "$simulator_udid" >"$SIMULATOR_UDID_FILE"
rm -f "$SIMULATOR_STARTED_FILE"

simulator_state="$(get_simulator_state "$simulator_udid")"

if [[ "$simulator_state" == "Booted" ]]; then
  echo "$SIMULATOR_NAME is already booted."
else
  echo "Booting $SIMULATOR_NAME..."
  xcrun simctl boot "$simulator_udid"
  touch "$SIMULATOR_STARTED_FILE"
fi

echo "Waiting for the simulator to finish booting..."
xcrun simctl bootstatus "$simulator_udid" -b

echo "Opening Simulator..."
open -a Simulator --args -CurrentDeviceUDID "$simulator_udid"

echo "Starting backend..."

: >"$BACKEND_LOG"

nohup "$ROOT_DIR/scripts/start-backend.sh" \
  >"$BACKEND_LOG" 2>&1 &

backend_pid=$!
printf '%s\n' "$backend_pid" >"$BACKEND_PID_FILE"

wait_for_log_pattern \
  "$backend_pid" \
  "$BACKEND_LOG" \
  "Uvicorn running on|Application startup complete" \
  45 \
  "backend"

echo "Backend is ready with PID $backend_pid."

echo "Starting iOS development build..."

cd "$MOBILE_DIR"

: >"$EXPO_LOG"

nohup npx expo run:ios \
  --device "$SIMULATOR_NAME" \
  >"$EXPO_LOG" 2>&1 &

expo_pid=$!
printf '%s\n' "$expo_pid" >"$EXPO_PID_FILE"

wait_for_log_pattern \
  "$expo_pid" \
  "$EXPO_LOG" \
  "Bundling complete|Build Succeeded|Installing on|Opening on|Metro waiting on|Waiting on" \
  300 \
  "Expo iOS build"

trap - ERR

echo
echo "Nutrition App started."
echo
echo "Backend:"
echo "  URL: http://localhost:$PORT"
echo "  PID: $backend_pid"
echo "  Log: $BACKEND_LOG"
echo
echo "Mobile:"
echo "  Simulator: $SIMULATOR_NAME"
echo "  PID: $expo_pid"
echo "  Log: $EXPO_LOG"
echo
echo "Stop everything with:"
echo "  ./scripts/stop-project.sh"
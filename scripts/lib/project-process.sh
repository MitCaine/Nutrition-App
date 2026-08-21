#!/usr/bin/env bash

PROJECT_PROCESS_RECORD_FORMAT="nutrition-project-process-v1"
PROJECT_PROCESS_GRACE_SECONDS="${PROJECT_PROCESS_GRACE_SECONDS:-15}"

PROJECT_PROCESS_CAPTURE_PID=""
PROJECT_PROCESS_CAPTURE_START_IDENTITY=""
PROJECT_PROCESS_CAPTURE_COMMAND=""
PROJECT_PROCESS_CAPTURE_PPID=""
PROJECT_PROCESS_CAPTURE_STATE=""

PROJECT_PROCESS_RECORD_SERVICE=""
PROJECT_PROCESS_RECORD_PID=""
PROJECT_PROCESS_RECORD_START_IDENTITY=""
PROJECT_PROCESS_RECORD_CONTRACT=""
PROJECT_PROCESS_RECORD_COMMAND=""

PROJECT_PROCESS_STATUS_REASON=""

project_process_trim() {
  local value="${1-}"

  printf '%s\n' "$value" |
    sed \
      -e 's/^[[:space:]]*//' \
      -e 's/[[:space:]]*$//'
}

project_process_ps_field() {
  local pid="$1"
  local field="$2"
  local value

  if ! value="$(
    ps -p "$pid" -o "${field}=" 2>/dev/null
  )"
  then
    return 1
  fi

  project_process_trim "$value"
}

project_process_is_running() {
  local pid="$1"
  local process_state

  [[ "$pid" =~ ^[0-9]+$ ]] || return 1

  kill -0 "$pid" 2>/dev/null || return 1

  if ! process_state="$(
    project_process_ps_field "$pid" stat
  )"
  then
    return 1
  fi

  [[ -n "$process_state" ]] || return 1
  [[ "$process_state" != Z* ]]
}

project_process_capture_identity() {
  local pid="$1"
  local start_before
  local start_after
  local command_value
  local parent_value
  local state_value

  PROJECT_PROCESS_CAPTURE_PID=""
  PROJECT_PROCESS_CAPTURE_START_IDENTITY=""
  PROJECT_PROCESS_CAPTURE_COMMAND=""
  PROJECT_PROCESS_CAPTURE_PPID=""
  PROJECT_PROCESS_CAPTURE_STATE=""

  project_process_is_running "$pid" || return 1

  if ! start_before="$(
    project_process_ps_field "$pid" lstart
  )"
  then
    return 1
  fi

  if ! parent_value="$(
    project_process_ps_field "$pid" ppid
  )"
  then
    return 1
  fi

  if ! command_value="$(
    project_process_ps_field "$pid" command
  )"
  then
    return 1
  fi

  if ! state_value="$(
    project_process_ps_field "$pid" stat
  )"
  then
    return 1
  fi

  if ! start_after="$(
    project_process_ps_field "$pid" lstart
  )"
  then
    return 1
  fi

  project_process_is_running "$pid" || return 1

  [[ -n "$start_before" ]] || return 1
  [[ "$start_before" == "$start_after" ]] || return 1
  [[ "$parent_value" =~ ^[0-9]+$ ]] || return 1
  [[ -n "$command_value" ]] || return 1
  [[ -n "$state_value" ]] || return 1
  [[ "$state_value" != Z* ]] || return 1

  PROJECT_PROCESS_CAPTURE_PID="$pid"
  PROJECT_PROCESS_CAPTURE_START_IDENTITY="$start_before"
  PROJECT_PROCESS_CAPTURE_COMMAND="$command_value"
  PROJECT_PROCESS_CAPTURE_PPID="$parent_value"
  PROJECT_PROCESS_CAPTURE_STATE="$state_value"
}

project_process_start_identity() {
  local pid="$1"

  project_process_capture_identity "$pid" || return 1
  printf '%s\n' "$PROJECT_PROCESS_CAPTURE_START_IDENTITY"
}

project_process_command() {
  local pid="$1"

  project_process_capture_identity "$pid" || return 1
  printf '%s\n' "$PROJECT_PROCESS_CAPTURE_COMMAND"
}

project_process_contract_for_service() {
  local service="$1"

  case "$service" in
    backend)
      printf '%s\n' "backend-v1"
      ;;
    expo)
      printf '%s\n' "expo-ios-v1"
      ;;
    *)
      return 1
      ;;
  esac
}

project_process_command_matches_contract() {
  local contract="$1"
  local command_value="$2"

  case "$contract" in
    backend-v1)
      if [[ "$command_value" == *"start-backend.sh"* ]]; then
        return 0
      fi

      if [[
        "$command_value" == *"uvicorn"*
        && "$command_value" == *"app.main:app"*
      ]]
      then
        return 0
      fi

      return 1
      ;;

    expo-ios-v1)
      [[
        "$command_value" == *"expo"*
        && "$command_value" == *"run:ios"*
      ]]
      ;;

    *)
      return 1
      ;;
  esac
}

project_process_write_record() {
  local record_file="$1"
  local service="$2"
  local pid="$3"
  local contract
  local temporary_file

  if ! contract="$(
    project_process_contract_for_service "$service"
  )"
  then
    echo "Error: unsupported project process service: $service" >&2
    return 2
  fi

  if ! project_process_capture_identity "$pid"; then
    echo \
      "Error: unable to capture stable process identity for $service PID $pid." \
      >&2
    return 2
  fi

  if ! project_process_command_matches_contract \
      "$contract" \
      "$PROJECT_PROCESS_CAPTURE_COMMAND"
  then
    echo \
      "Error: $service PID $pid does not match command contract $contract." \
      >&2
    echo \
      "Observed command: $PROJECT_PROCESS_CAPTURE_COMMAND" \
      >&2
    return 2
  fi

  mkdir -p "$(dirname "$record_file")"

  temporary_file="${record_file}.tmp.$$"

  {
    printf 'format=%s\n' "$PROJECT_PROCESS_RECORD_FORMAT"
    printf 'service=%s\n' "$service"
    printf 'pid=%s\n' "$pid"
    printf 'start=%s\n' "$PROJECT_PROCESS_CAPTURE_START_IDENTITY"
    printf 'contract=%s\n' "$contract"
    printf 'command=%s\n' "$PROJECT_PROCESS_CAPTURE_COMMAND"
  } > "$temporary_file"

  mv "$temporary_file" "$record_file"
}

project_process_load_record() {
  local record_file="$1"
  local key
  local value
  local expected_contract

  local seen_format=0
  local seen_service=0
  local seen_pid=0
  local seen_start=0
  local seen_contract=0
  local seen_command=0

  PROJECT_PROCESS_RECORD_SERVICE=""
  PROJECT_PROCESS_RECORD_PID=""
  PROJECT_PROCESS_RECORD_START_IDENTITY=""
  PROJECT_PROCESS_RECORD_CONTRACT=""
  PROJECT_PROCESS_RECORD_COMMAND=""

  [[ -f "$record_file" ]] || return 1

  while IFS='=' read -r key value || [[ -n "$key$value" ]]; do
    case "$key" in
      format)
        (( seen_format == 0 )) || return 1
        seen_format=1
        [[ "$value" == "$PROJECT_PROCESS_RECORD_FORMAT" ]] || return 1
        ;;

      service)
        (( seen_service == 0 )) || return 1
        seen_service=1
        PROJECT_PROCESS_RECORD_SERVICE="$value"
        ;;

      pid)
        (( seen_pid == 0 )) || return 1
        seen_pid=1
        PROJECT_PROCESS_RECORD_PID="$value"
        ;;

      start)
        (( seen_start == 0 )) || return 1
        seen_start=1
        PROJECT_PROCESS_RECORD_START_IDENTITY="$value"
        ;;

      contract)
        (( seen_contract == 0 )) || return 1
        seen_contract=1
        PROJECT_PROCESS_RECORD_CONTRACT="$value"
        ;;

      command)
        (( seen_command == 0 )) || return 1
        seen_command=1
        PROJECT_PROCESS_RECORD_COMMAND="$value"
        ;;

      *)
        return 1
        ;;
    esac
  done < "$record_file"

  (( seen_format == 1 )) || return 1
  (( seen_service == 1 )) || return 1
  (( seen_pid == 1 )) || return 1
  (( seen_start == 1 )) || return 1
  (( seen_contract == 1 )) || return 1
  (( seen_command == 1 )) || return 1

  [[ "$PROJECT_PROCESS_RECORD_PID" =~ ^[0-9]+$ ]] || return 1
  [[ -n "$PROJECT_PROCESS_RECORD_START_IDENTITY" ]] || return 1
  [[ -n "$PROJECT_PROCESS_RECORD_COMMAND" ]] || return 1

  if ! expected_contract="$(
    project_process_contract_for_service \
      "$PROJECT_PROCESS_RECORD_SERVICE"
  )"
  then
    return 1
  fi

  [[ "$PROJECT_PROCESS_RECORD_CONTRACT" == "$expected_contract" ]] || return 1

  project_process_command_matches_contract \
    "$PROJECT_PROCESS_RECORD_CONTRACT" \
    "$PROJECT_PROCESS_RECORD_COMMAND"
}

project_process_record_status() {
  local record_file="$1"
  local expected_service="$2"

  PROJECT_PROCESS_STATUS_REASON=""

  if ! project_process_load_record "$record_file"; then
    PROJECT_PROCESS_STATUS_REASON=\
"record is malformed, legacy, or has an invalid command contract"
    return 2
  fi

  if [[ "$PROJECT_PROCESS_RECORD_SERVICE" != "$expected_service" ]]
  then
    PROJECT_PROCESS_STATUS_REASON=\
"record service does not match the requested service"
    return 2
  fi

  if ! project_process_is_running \
      "$PROJECT_PROCESS_RECORD_PID"
  then
    PROJECT_PROCESS_STATUS_REASON=\
"recorded process is no longer running"
    return 1
  fi

  if ! project_process_capture_identity \
      "$PROJECT_PROCESS_RECORD_PID"
  then
    PROJECT_PROCESS_STATUS_REASON=\
"recorded process exited during identity verification"
    return 1
  fi

  if [[ "$PROJECT_PROCESS_CAPTURE_START_IDENTITY" != "$PROJECT_PROCESS_RECORD_START_IDENTITY" ]]
  then
    PROJECT_PROCESS_STATUS_REASON=\
"live PID has a different process-start identity"
    return 2
  fi

  if ! project_process_command_matches_contract \
      "$PROJECT_PROCESS_RECORD_CONTRACT" \
      "$PROJECT_PROCESS_CAPTURE_COMMAND"
  then
    PROJECT_PROCESS_STATUS_REASON=\
"live PID does not match the recorded service command contract"
    return 2
  fi

  PROJECT_PROCESS_STATUS_REASON="owned"
  return 0
}

project_process_prepare_start_record() {
  local record_file="$1"
  local service="$2"
  local service_name="$3"
  local status_code

  if [[ ! -f "$record_file" ]]; then
    return 0
  fi

  if project_process_record_status \
      "$record_file" \
      "$service"
  then
    echo \
      "Error: $service_name is already running with PID $PROJECT_PROCESS_RECORD_PID."
    echo "Run scripts/stop-project.sh first."
    return 1
  else
    status_code=$?
  fi

  case "$status_code" in
    1)
      echo \
        "Removing stale $service_name process record: $PROJECT_PROCESS_STATUS_REASON."
      ;;
    2)
      echo \
        "Removing untrusted $service_name process record without signaling: $PROJECT_PROCESS_STATUS_REASON."
      ;;
    *)
      echo \
        "Error: unexpected $service_name process-record status: $status_code." \
        >&2
      return 1
      ;;
  esac

  rm -f "$record_file"
}

project_process_identity_matches() {
  local pid="$1"
  local expected_start="$2"
  local contract="${3-}"
  local expected_parent="${4-}"

  project_process_capture_identity "$pid" || return 1

  [[ "$PROJECT_PROCESS_CAPTURE_START_IDENTITY" == "$expected_start" ]] || return 1

  if [[ -n "$expected_parent" ]]; then
    [[ "$PROJECT_PROCESS_CAPTURE_PPID" == "$expected_parent" ]] || return 1
  fi

  if [[ -n "$contract" ]]; then
    project_process_command_matches_contract \
      "$contract" \
      "$PROJECT_PROCESS_CAPTURE_COMMAND" || return 1
  fi
}

project_process_child_pids() {
  local parent_pid="$1"

  ps -ax -o pid= -o ppid= |
    awk \
      -v parent="$parent_pid" \
      '$2 == parent { print $1 }'
}

project_process_signal_if_same_identity() {
  local pid="$1"
  local expected_start="$2"
  local signal_name="$3"
  local service_name="$4"
  local contract="${5-}"
  local expected_parent="${6-}"

  if ! project_process_identity_matches \
      "$pid" \
      "$expected_start" \
      "$contract" \
      "$expected_parent"
  then
    echo \
      "Refusing to signal $service_name PID $pid: process identity no longer matches."
    return 1
  fi

  kill "-$signal_name" "$pid" 2>/dev/null
}

project_process_force_kill_if_same_identity() {
  local pid="$1"
  local expected_start="$2"
  local service_name="$3"
  local contract="${4-}"
  local expected_parent="${5-}"

  if ! project_process_signal_if_same_identity \
      "$pid" \
      "$expected_start" \
      KILL \
      "$service_name" \
      "$contract" \
      "$expected_parent"
  then
    return 1
  fi
}

project_process_stop_identity_tree() {
  local pid="$1"
  local expected_start="$2"
  local service_name="$3"
  local contract="${4-}"
  local expected_parent="${5-}"

  local child_pid
  local child_start
  local child_parent
  local grace_seconds
  local elapsed

  if ! project_process_identity_matches \
      "$pid" \
      "$expected_start" \
      "$contract" \
      "$expected_parent"
  then
    echo \
      "Refusing to stop $service_name PID $pid: process identity does not match."
    return 0
  fi

  while read -r child_pid; do
    [[ -n "$child_pid" ]] || continue

    if ! project_process_identity_matches \
        "$pid" \
        "$expected_start" \
        "$contract" \
        "$expected_parent"
    then
      echo \
        "Stopping $service_name aborted: root identity changed during child discovery."
      return 0
    fi

    if ! project_process_capture_identity "$child_pid"; then
      continue
    fi

    child_parent="$PROJECT_PROCESS_CAPTURE_PPID"
    child_start="$PROJECT_PROCESS_CAPTURE_START_IDENTITY"

    [[ "$child_parent" == "$pid" ]] || continue

    project_process_stop_identity_tree \
      "$child_pid" \
      "$child_start" \
      "$service_name child" \
      "" \
      "$pid"
  done < <(
    project_process_child_pids "$pid"
  )

  if ! project_process_identity_matches \
      "$pid" \
      "$expected_start" \
      "$contract" \
      "$expected_parent"
  then
    echo \
      "$service_name PID $pid exited or changed identity before TERM; no signal sent."
    return 0
  fi

  echo "Stopping $service_name PID $pid..."

  if ! project_process_signal_if_same_identity \
      "$pid" \
      "$expected_start" \
      TERM \
      "$service_name" \
      "$contract" \
      "$expected_parent"
  then
    return 0
  fi

  grace_seconds="$PROJECT_PROCESS_GRACE_SECONDS"

  if [[ ! "$grace_seconds" =~ ^[0-9]+$ ]]; then
    grace_seconds=15
  fi

  elapsed=0

  while (( elapsed < grace_seconds )); do
    if ! project_process_is_running "$pid"; then
      return 0
    fi

    if ! project_process_identity_matches \
        "$pid" \
        "$expected_start" \
        "$contract" \
        "$expected_parent"
    then
      echo \
        "$service_name PID $pid changed identity after TERM; treating the original process as exited."
      return 0
    fi

    sleep 1
    elapsed=$((elapsed + 1))
  done

  if ! project_process_is_running "$pid"; then
    return 0
  fi

  echo \
    "$service_name PID $pid did not stop gracefully; validating identity before SIGKILL."

  if ! project_process_force_kill_if_same_identity \
      "$pid" \
      "$expected_start" \
      "$service_name" \
      "$contract" \
      "$expected_parent"
  then
    echo \
      "SIGKILL withheld for $service_name PID $pid because ownership could not be revalidated."
    return 0
  fi
}

project_process_stop_from_record() {
  local record_file="$1"
  local service="$2"
  local service_name="$3"

  local status_code
  local pid
  local start_identity
  local contract

  if [[ ! -f "$record_file" ]]; then
    echo "No recorded $service_name process found."
    return 0
  fi

  if project_process_record_status \
      "$record_file" \
      "$service"
  then
    pid="$PROJECT_PROCESS_RECORD_PID"
    start_identity="$PROJECT_PROCESS_RECORD_START_IDENTITY"
    contract="$PROJECT_PROCESS_RECORD_CONTRACT"

    project_process_stop_identity_tree \
      "$pid" \
      "$start_identity" \
      "$service_name" \
      "$contract"

    rm -f "$record_file"
    return 0
  else
    status_code=$?
  fi

  case "$status_code" in
    1)
      echo \
        "$service_name process record is stale: $PROJECT_PROCESS_STATUS_REASON."
      ;;
    2)
      echo \
        "Refusing to signal $service_name from untrusted process record: $PROJECT_PROCESS_STATUS_REASON."
      ;;
    *)
      echo \
        "Unexpected $service_name process-record status: $status_code." \
        >&2
      return 1
      ;;
  esac

  rm -f "$record_file"
}

#!/usr/bin/env bash

set -uo pipefail

evidence_dir=""
runner="local"
compilation_mode="clean"

while test "$#" -gt 0
do
  case "$1" in
    --evidence-dir)
      test "$#" -ge 2
      evidence_dir="$2"
      shift 2
      ;;
    --runner)
      test "$#" -ge 2
      runner="$2"
      shift 2
      ;;
    --compilation-mode)
      test "$#" -ge 2
      compilation_mode="$2"
      shift 2
      ;;
    *)
      echo "IOS_NATIVE_ARGUMENT_INVALID:$1" >&2
      exit 2
      ;;
esac
done

case "$compilation_mode" in
  clean)
    ;;
  incremental)
    echo "IOS_NATIVE_INCREMENTAL_COMPILATION_UNSUPPORTED:negative-evaluation" >&2
    exit 2
    ;;
  *)
    echo "IOS_NATIVE_COMPILATION_MODE_INVALID:$compilation_mode" >&2
    exit 2
    ;;
esac

if test -z "$evidence_dir"
then
  echo "IOS_NATIVE_EVIDENCE_DIR_REQUIRED" >&2
  exit 2
fi

if test "$(uname -s)" != "Darwin"
then
  echo "IOS_NATIVE_REQUIRES_MACOS" >&2
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
repo_root="$(cd "$repo_root" && pwd -P)"

if test -n "$(
  git -C "$repo_root" status \
    --porcelain=v1 \
    -uall
)"
then
  echo "IOS_NATIVE_SOURCE_WORKTREE_DIRTY" >&2
  exit 1
fi

mkdir -p "$evidence_dir"
evidence_dir="$(cd "$evidence_dir" && pwd -P)"

probe_root="$evidence_dir/Nutrition App Native"
derived_data="$evidence_dir/DerivedData"
harness_bin="$evidence_dir/harness-bin"
manifest="$evidence_dir/manifest.json"
timings_file="$evidence_dir/stages.jsonl"
prebuild_paths="$evidence_dir/prebuild-paths.env"
dependency_versions="$evidence_dir/dependency-versions.env"
build_invocation_file="$evidence_dir/build-invocation.json"
module_evidence="$evidence_dir/module-evidence.json"
candidate_build_evidence="$evidence_dir/candidate-build-evidence.json"
application_link_proof="$evidence_dir/application-link-proof.json"
native_lifecycle_dir="$evidence_dir/native-lifecycle"
native_lifecycle_helper="$repo_root/scripts/lib/native_process_lifecycle.py"
native_lifecycle_binding="$native_lifecycle_dir/invocation.json"
native_lifecycle_wrapper="$native_lifecycle_dir/ibtool"
native_output_cleanup="$repo_root/scripts/lib/task_output_cleanup.py"
native_output_owner="$native_lifecycle_dir/output-owner.json"
native_output_attempt=""
native_output_durable="$native_lifecycle_dir/retained-outputs"
native_output_quarantine="$native_lifecycle_dir/quarantine"
native_owner_hold_pid=""
native_owner_ready="$native_lifecycle_dir/output-owner-ready.json"
native_lifecycle_python=""
native_lifecycle_python_version=""
native_lifecycle_python_executable=""
native_lifecycle_ibtool=""
native_lifecycle_ibtoold=""
native_lifecycle_xcodebuild=""
native_lifecycle_developer_dir=""
native_lifecycle_xcode_spec_compiler=""
native_lifecycle_xcode_spec_storyboard=""
native_lifecycle_xcode_spec_linker=""
native_lifecycle_xcode_spec_postprocessor=""
cleanup_disposition="NOT_STARTED"
cleanup_reason=""
cleanup_retained_roots=""
cleanup_removed_roots=""
cleanup_quarantined_roots=""
required_proof_failure=0
application_build_outcome="$evidence_dir/application-build-outcome.json"
propagation_proof_outcome="$evidence_dir/propagation-proof-outcome.json"

export IOS_NATIVE_COMPILATION_MODE="$compilation_mode"

if test -e "$probe_root"
then
  echo "IOS_NATIVE_PROBE_ALREADY_EXISTS" >&2
  exit 1
fi
if test -e "$derived_data" || test -L "$derived_data" ||
  test -e "$harness_bin" || test -L "$harness_bin"
then
  echo "IOS_NATIVE_GENERATED_ROOT_ALREADY_EXISTS" >&2
  exit 1
fi

if ! start_epoch="$(date +%s)"
then
  echo "IOS_NATIVE_START_TIME_UNAVAILABLE" >&2
  exit 1
fi
worktree_created=0
cleanup_done=0
signal_status=0
qualifier_exit_status=0
evidence_retention_failure=0

if ! : > "$timings_file"
then
  echo "IOS_NATIVE_TIMING_FILE_INITIALIZATION_FAILED" >&2
  exit 1
fi

on_signal() {
  signal_status="$2"
  if test "$qualifier_exit_status" -eq 0
  then
    qualifier_exit_status="$2"
  fi
}

record_stage() {
  local name="$1"
  local elapsed="$2"
  local status="$3"
  local exit_code="$4"

  if ! printf \
      '{"stage":"%s","elapsed_seconds":%s,"status":"%s","exit_code":%s}\n' \
      "$name" \
      "$elapsed" \
      "$status" \
      "$exit_code" \
      >> "$timings_file"
  then
    evidence_retention_failure=1
    echo "IOS_NATIVE_TIMING_WRITE_FAILED:$name" >&2
    return 1
  fi
}

run_stage() {
  local name="$1"
  local function_name="$2"
  local run_when_signaled="${3:-0}"
  local stage_start
  local stage_end
  local elapsed
  local exit_code
  local status
  local timing_exit=0

  if ! stage_start="$(date +%s)"
  then
    stage_start=0
    timing_exit=1
    evidence_retention_failure=1
    echo "IOS_NATIVE_STAGE_START_TIME_FAILED:$name" >&2
  fi

  if test "$signal_status" -ne 0 &&
    test "$run_when_signaled" -ne 1
  then
    record_stage "$name" 0 "SKIPPED" null
    return "$signal_status"
  fi

  if test "$name" = cleanup
  then
    "$function_name"
    exit_code="$?"
  else
    (
      set -e
      "$function_name"
    )
    exit_code="$?"
  fi

  if test "$signal_status" -ne 0 &&
    test "$run_when_signaled" -ne 1
  then
    exit_code="$signal_status"
  fi

  if ! stage_end="$(date +%s)"
  then
    stage_end="$stage_start"
    timing_exit=1
    echo "IOS_NATIVE_STAGE_END_TIME_FAILED:$name" >&2
  fi
  elapsed="$((stage_end - stage_start))"

  if test "$timing_exit" -ne 0
  then
    evidence_retention_failure=1
    if test "$exit_code" -eq 0
    then
      exit_code=1
    fi
  fi

  if test "$name" = cleanup &&
    test "$cleanup_disposition" = INCOMPLETE
  then
    status="INCOMPLETE"
  elif test "$exit_code" -eq 0
  then
    status="PASS"
  elif test "$exit_code" -ge 128
  then
    status="SIGNAL"
  else
    status="FAILURE"
  fi

  if ! record_stage "$name" "$elapsed" "$status" "$exit_code"
  then
    if test "$exit_code" -eq 0
    then
      exit_code=1
    fi
  fi
  if test "$name" = cleanup &&
    test "$cleanup_disposition" = INCOMPLETE
  then
    if test "$required_proof_failure" -eq 0
    then
      return 0
    fi
    return 1
  fi
  return "$exit_code"
}

mark_cleanup_incomplete() {
  local reason="$1"
  cleanup_disposition="INCOMPLETE"
  if test -n "$cleanup_removed_roots"
  then
    cleanup_reason="completed recoverable quarantine moves: ${cleanup_quarantined_roots//$'\n'/, }; $reason"
  else
    cleanup_reason="$reason"
  fi
  cleanup_retained_roots=""
  for root in "$probe_root" "$derived_data" "$harness_bin"
  do
    if test -e "$root" || test -L "$root"
    then
      cleanup_retained_roots="${cleanup_retained_roots}${root}
"
    fi
  done
  echo "IOS_NATIVE_CLEANUP_INCOMPLETE:$reason" >&2
}

verify_native_proof_readback_before_operation() {
  local operation="$1"
  local proof_status=0
  local proof_stdout_path="$native_lifecycle_dir/cleanup-proof-verify-$operation.stdout.log"
  local proof_stderr_path="$native_lifecycle_dir/cleanup-proof-verify-$operation.stderr.log"
  "$native_lifecycle_python" "$native_output_cleanup" native-proof-verify \
    --owner-record "$native_output_owner" \
    --invocation-record "$native_lifecycle_binding" \
    --durable-evidence "$native_output_durable" \
    > "$proof_stdout_path" 2> "$proof_stderr_path"
  proof_status="$?"
  if test "$proof_status" -ne 0
  then
    local proof_detail
    proof_detail="$(tail -n 1 "$proof_stderr_path" 2>/dev/null || true)"
    required_proof_failure=1
    record_outcome \
      "$propagation_proof_outcome" \
      propagation_proof \
      FAILURE \
      "$proof_status" \
      "${proof_detail:-relocated compile/link proof readback failed}" || true
    if test "$qualifier_exit_status" -eq 0
    then
      qualifier_exit_status=1
    fi
    mark_cleanup_incomplete "required compile/link proof readback refused before $operation: ${proof_detail:-no adapter detail}"
    return 1
  fi
  return 0
}

verify_before_disposal() {
  local operation="$1"
  local verify_status=0
  local stdout_path="$native_lifecycle_dir/cleanup-verify-$operation.stdout.log"
  local stderr_path="$native_lifecycle_dir/cleanup-verify-$operation.stderr.log"

  if test -z "$native_lifecycle_binding" ||
    ! test -f "$native_lifecycle_binding"
  then
    mark_cleanup_incomplete "invocation binding unavailable before $operation"
    return 1
  fi

  if test "$operation" != output-owner-terminal
  then
    if ! verify_native_proof_readback_before_operation "$operation"
    then
      return 1
    fi
    if ! reconcile_native_worktree_phase
    then
      mark_cleanup_incomplete "native worktree phase reconciliation refused before $operation"
      return 1
    fi
  fi

  "$native_lifecycle_python" \
      "$native_lifecycle_helper" \
      verify \
      --invocation-record "$native_lifecycle_binding" \
      > "$stdout_path" \
      2> "$stderr_path"
  verify_status="$?"
  if test "$verify_status" -ne 0
  then
    local detail
    detail="$(tail -n 1 "$stderr_path" 2>/dev/null || true)"
    if test "$verify_status" -eq 2
    then
      required_proof_failure=1
      record_outcome \
        "$propagation_proof_outcome" \
        propagation_proof \
        FAILURE \
        "$verify_status" \
        "${detail:-required lifecycle evidence verification failed}" || true
      if test "$qualifier_exit_status" -eq 0
      then
        qualifier_exit_status=1
      fi
    fi
    mark_cleanup_incomplete "verification refused before $operation: ${detail:-no verifier detail}"
    return 1
  fi
  if test "$operation" != output-owner-terminal
  then
    if ! verify_native_proof_readback_before_operation "$operation"
    then
      return 1
    fi
  fi

  if test "$operation" != output-owner-terminal
  then
    local operations_stdout="$native_lifecycle_dir/cleanup-operations-verify-$operation.stdout.log"
    local operations_stderr="$native_lifecycle_dir/cleanup-operations-verify-$operation.stderr.log"
    local operations_status=0
    local -a operations_args
    operations_args=(
      "$native_output_cleanup" native-quarantine-verify
      --owner-record "$native_output_owner"
      --invocation-record "$native_lifecycle_binding"
      --durable-evidence "$native_output_durable"
    )
    case "$operation" in
      worktree-quarantine)
        operations_args+=(--allow-current-path "$probe_root")
        ;;
      derived-data-quarantine)
        operations_args+=(--allow-current-path "$derived_data")
        ;;
      harness-bin-quarantine)
        operations_args+=(--allow-current-path "$harness_bin")
        ;;
      cleanup-pass)
        operations_args+=(--require-complete)
        ;;
    esac
    "$native_lifecycle_python" "${operations_args[@]}" \
      > "$operations_stdout" 2> "$operations_stderr" || operations_status="$?"
    if test "$operations_status" -ne 0
    then
      local operations_detail
      operations_detail="$(tail -n 1 "$operations_stderr" 2>/dev/null || true)"
      mark_cleanup_incomplete \
        "prior native output operation readback failed before $operation: ${operations_detail:-no adapter detail}"
      return 1
    fi
  fi
}

reconcile_native_worktree_phase() {
  local status=0
  local stdout_path="$native_lifecycle_dir/worktree-phase-reconciliation.stdout.log"
  local stderr_path="$native_lifecycle_dir/worktree-phase-reconciliation.stderr.log"
  "$native_lifecycle_python" "$native_output_cleanup" native-worktree-phase-reconcile \
    --owner-record "$native_output_owner" \
    --invocation-record "$native_lifecycle_binding" \
    --durable-evidence "$native_output_durable" \
    >> "$stdout_path" 2>> "$stderr_path" || status="$?"
  if test "$status" -ne 0
  then
    return "$status"
  fi
  return 0
}

recover_native_worktree_quarantine() {
  if ! verify_native_proof_readback_before_operation worktree-quarantine
  then
    return 1
  fi
  if ! reconcile_native_worktree_phase
  then
    return 1
  fi
  # Recheck the installed producer and every native operation after the
  # adapter has restored the source-bound phase, before continuing cleanup.
  verify_before_disposal derived-data-quarantine
}

cleanup_stage() {
  cleanup_disposition="IN_PROGRESS"
  cleanup_reason=""
  cleanup_removed_roots=""
  cleanup_quarantined_roots=""

  if test -f "$native_output_owner"
  then
    if ! finish_native_output_owner
    then
      return 1
    fi
  elif test -e "$probe_root" || test -L "$probe_root" ||
    test -e "$derived_data" || test -L "$derived_data" ||
    test -e "$harness_bin" || test -L "$harness_bin"
  then
    mark_cleanup_incomplete "generated roots exist without Nutrition-owned creation receipts"
    return 1
  fi

  if test -e "$probe_root" || test -L "$probe_root"
  then
    local worktree_destination="$native_output_quarantine/Nutrition App Native"
    if ! verify_before_disposal worktree-quarantine
    then
      return 1
    fi
    if ! execute_verified_native_quarantine worktree "$probe_root" "$worktree_destination"
    then
      local detail
      local recovery_detail
      detail="$(tail -n 1 "$native_lifecycle_dir/quarantine-worktree.stderr.log" 2>/dev/null || true)"
      if ! recover_native_worktree_quarantine
      then
        recovery_detail="$(tail -n 1 "$native_lifecycle_dir/worktree-phase-reconciliation.stderr.log" 2>/dev/null || true)"
        mark_cleanup_incomplete "registered worktree quarantine failed; retained $probe_root: ${recovery_detail:-${detail:-no adapter detail}}"
        return 1
      fi
    fi
    cleanup_removed_roots="${cleanup_removed_roots}${probe_root}
"
    cleanup_quarantined_roots="${cleanup_quarantined_roots}${worktree_destination}
"
    local worktree_operation="$native_output_durable/worktree-quarantine-$(
      "$native_lifecycle_python" - "$native_output_owner" "$probe_root" <<'PY'
import json,sys
record=json.load(open(sys.argv[1], encoding="utf-8"))
receipt=next(item for item in record["owned_outputs"] if item["path"] == sys.argv[2])
print(receipt["node"][1])
PY
    ).json"
    local worktree_operation_binding
    worktree_operation_binding="$("$native_lifecycle_python" - "$worktree_operation" <<'PY'
import hashlib,json,sys
path=sys.argv[1]
print(json.dumps({"path":path,"sha256":hashlib.sha256(open(path,"rb").read()).hexdigest()},sort_keys=True))
PY
    )" || return 1
    local worktree_phase_details
    worktree_phase_details="$("$native_lifecycle_python" - "$probe_root" "$worktree_destination" "$worktree_operation_binding" <<'PY'
import json,sys
print(json.dumps({"root":sys.argv[1],"destination":sys.argv[2],"quarantine_operation":json.loads(sys.argv[3])},sort_keys=True))
PY
    )" || return 1
    if ! record_native_phase worktree-removed "$worktree_phase_details"
    then
      if ! recover_native_worktree_quarantine
      then
        local recovery_detail
        recovery_detail="$(tail -n 1 "$native_lifecycle_dir/worktree-phase-reconciliation.stderr.log" 2>/dev/null || true)"
        mark_cleanup_incomplete "worktree quarantine phase evidence failed after moving $probe_root: ${recovery_detail:-no adapter detail}"
        return 1
      fi
    fi
    worktree_created=0
  fi

  if test -e "$derived_data" || test -L "$derived_data"
  then
    local derived_destination="$native_output_quarantine/DerivedData"
    if ! verify_before_disposal derived-data-quarantine
    then
      return 1
    fi
    if ! execute_verified_native_quarantine derived-data "$derived_data" "$derived_destination"
    then
      local detail
      detail="$(tail -n 1 "$native_lifecycle_dir/quarantine-derived-data.stderr.log" 2>/dev/null || true)"
      mark_cleanup_incomplete "DerivedData quarantine failed; retained $derived_data: ${detail:-no adapter detail}"
      return 1
    fi
    cleanup_removed_roots="${cleanup_removed_roots}${derived_data}
"
    cleanup_quarantined_roots="${cleanup_quarantined_roots}${derived_destination}
"
    local derived_operation="$native_output_durable/output-quarantine-$(
      "$native_lifecycle_python" - "$native_output_owner" "$derived_data" <<'PY'
import json,sys
record=json.load(open(sys.argv[1], encoding="utf-8"))
receipt=next(item for item in record["owned_outputs"] if item["path"] == sys.argv[2])
print(receipt["node"][1])
PY
    ).json"
    local derived_operation_binding
    derived_operation_binding="$("$native_lifecycle_python" - "$derived_operation" <<'PY'
import hashlib,json,sys
path=sys.argv[1]
print(json.dumps({"path":path,"sha256":hashlib.sha256(open(path,"rb").read()).hexdigest()},sort_keys=True))
PY
    )" || return 1
    local derived_phase_details
    derived_phase_details="$("$native_lifecycle_python" - "$derived_data" "$derived_destination" "$derived_operation_binding" <<'PY'
import json,sys
print(json.dumps({"root":sys.argv[1],"destination":sys.argv[2],"quarantine_operation":json.loads(sys.argv[3])},sort_keys=True))
PY
    )" || return 1
    if ! record_native_phase derived-data-removed "$derived_phase_details"
    then
      mark_cleanup_incomplete "DerivedData quarantine phase evidence failed after moving $derived_data"
      return 1
    fi
  fi

  if test -e "$harness_bin" || test -L "$harness_bin"
  then
    local harness_destination="$native_output_quarantine/harness-bin"
    if ! verify_before_disposal harness-bin-quarantine
    then
      return 1
    fi
    if ! execute_verified_native_quarantine harness-bin "$harness_bin" "$harness_destination"
    then
      local detail
      detail="$(tail -n 1 "$native_lifecycle_dir/quarantine-harness-bin.stderr.log" 2>/dev/null || true)"
      mark_cleanup_incomplete "harness binary quarantine failed; retained $harness_bin: ${detail:-no adapter detail}"
      return 1
    fi
    cleanup_removed_roots="${cleanup_removed_roots}${harness_bin}
"
    cleanup_quarantined_roots="${cleanup_quarantined_roots}${harness_destination}
"
    local harness_operation="$native_output_durable/output-quarantine-$(
      "$native_lifecycle_python" - "$native_output_owner" "$harness_bin" <<'PY'
import json,sys
record=json.load(open(sys.argv[1], encoding="utf-8"))
receipt=next(item for item in record["owned_outputs"] if item["path"] == sys.argv[2])
print(receipt["node"][1])
PY
    ).json"
    local harness_operation_binding
    harness_operation_binding="$("$native_lifecycle_python" - "$harness_operation" <<'PY'
import hashlib,json,sys
path=sys.argv[1]
print(json.dumps({"path":path,"sha256":hashlib.sha256(open(path,"rb").read()).hexdigest()},sort_keys=True))
PY
    )" || return 1
    local harness_phase_details
    harness_phase_details="$("$native_lifecycle_python" - "$harness_bin" "$harness_destination" "$harness_operation_binding" <<'PY'
import json,sys
print(json.dumps({"root":sys.argv[1],"destination":sys.argv[2],"quarantine_operation":json.loads(sys.argv[3])},sort_keys=True))
PY
    )" || return 1
    if ! record_native_phase harness-bin-removed "$harness_phase_details"
    then
      mark_cleanup_incomplete "harness quarantine phase evidence failed after moving $harness_bin"
      return 1
    fi
  fi

  if test -e "$probe_root" || test -L "$probe_root"
  then
    printf '%s\n' "probe root remains after cleanup" \
      > "$evidence_dir/generated-cleanup-failure.txt"
    mark_cleanup_incomplete "probe root remains after cleanup: $probe_root"
    return 1
  fi

  if ! verify_before_disposal cleanup-pass
  then
    return 1
  fi

  cleanup_disposition="PASS"
  cleanup_reason="all generated outputs moved to verified recoverable quarantine after fresh source and invocation checks"
  cleanup_retained_roots=""
  return 0
}

record_outcome() {
  local path="$1"
  local name="$2"
  local status="$3"
  local exit_code="$4"
  local reason="$5"

  "$native_lifecycle_python" - "$path" "$name" "$status" "$exit_code" "$reason" <<'PY'
import json
import sys
from pathlib import Path

path, name, status, exit_code, reason = sys.argv[1:]
try:
    parsed_exit = int(exit_code)
except ValueError:
    parsed_exit = None
Path(path).write_text(
    json.dumps(
        {"name": name, "status": status, "exit_code": parsed_exit, "reason": reason},
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)
PY
  local record_status="$?"
  if test "$record_status" -ne 0
  then
    evidence_retention_failure=1
    echo "IOS_NATIVE_OUTCOME_RECORD_FAILED:$name" >&2
    return 1
  fi
}

write_manifest() {
  local final_exit="$1"
  local total_end
  local total_elapsed

  if ! total_end="$(date +%s)"
  then
    total_end="$start_epoch"
    evidence_retention_failure=1
    if test "$qualifier_exit_status" -eq 0
    then
      qualifier_exit_status=1
    fi
    final_exit="$qualifier_exit_status"
    echo "IOS_NATIVE_TOTAL_TIME_FAILED" >&2
  fi
  total_elapsed="$((total_end - start_epoch))"

  IOS_NATIVE_FINAL_EXIT="$final_exit" \
  IOS_NATIVE_SIGNAL_STATUS="$signal_status" \
  IOS_NATIVE_EVIDENCE_RETENTION_FAILURE="$evidence_retention_failure" \
  IOS_NATIVE_TOTAL_ELAPSED="$total_elapsed" \
  IOS_NATIVE_TIMING_BOUNDARY="toolchain preflight through cleanup completion" \
  IOS_NATIVE_COMPILATION_MODE="$compilation_mode" \
  IOS_NATIVE_BUILD_INVOCATION_FILE="$build_invocation_file" \
  IOS_NATIVE_MODULE_EVIDENCE_FILE="$module_evidence" \
  IOS_NATIVE_CANDIDATE_BUILD_EVIDENCE_FILE="$candidate_build_evidence" \
  IOS_NATIVE_APPLICATION_LINK_PROOF_FILE="$application_link_proof" \
  IOS_NATIVE_APPLICATION_BUILD_OUTCOME_FILE="$application_build_outcome" \
  IOS_NATIVE_PROPAGATION_PROOF_OUTCOME_FILE="$propagation_proof_outcome" \
  IOS_NATIVE_LIFECYCLE_DIR="$native_lifecycle_dir" \
  IOS_NATIVE_LIFECYCLE_BINDING="$native_lifecycle_binding" \
  IOS_NATIVE_OUTPUT_OWNER_FILE="$native_output_owner" \
  IOS_NATIVE_OUTPUT_EVIDENCE_DIR="$native_output_durable" \
  IOS_NATIVE_OUTPUT_QUARANTINE_ROOT="$native_output_quarantine" \
  IOS_NATIVE_CLEANUP_DISPOSITION="$cleanup_disposition" \
  IOS_NATIVE_CLEANUP_REASON="$cleanup_reason" \
  IOS_NATIVE_CLEANUP_RETAINED_ROOTS="$cleanup_retained_roots" \
  IOS_NATIVE_CLEANUP_QUARANTINED_ROOTS="$cleanup_quarantined_roots" \
  "$native_lifecycle_python" - "$timings_file" "$manifest" <<'PY'
import json
import os
import shlex
import sys
from pathlib import Path


timings_path = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])

expected_stages = [
    "npm_install",
    "prebuild_plugins",
    "autolinking",
    "pods",
    "xcode_build",
    "swift_harnesses",
    "cleanup",
]

observed = []
if timings_path.exists():
    for line in timings_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            observed.append(json.loads(line))

by_name = {entry["stage"]: entry for entry in observed}
stages = []
for name in expected_stages:
    stages.append(
        by_name.get(
            name,
            {
                "stage": name,
                "elapsed_seconds": None,
                "status": "SKIPPED",
                "exit_code": None,
            },
        )
    )

final_exit = int(os.environ["IOS_NATIVE_FINAL_EXIT"])
signal_status = int(os.environ.get("IOS_NATIVE_SIGNAL_STATUS", "0"))
if final_exit == 0:
    result = "PASS"
    failure_kind = None
elif signal_status or final_exit >= 128:
    result = "SIGNAL"
    failure_kind = "signal"
else:
    result = "PARTIAL_FAILURE"
    failure_kind = "failure"


def text(name):
    value = os.environ.get(name)
    return value if value else None


def document(name, default=None):
    path = text(name)
    if not path:
        return default
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def outcome(name, display_name):
    value = document(name)
    if not isinstance(value, dict):
        return {
            "name": display_name,
            "status": "SKIPPED",
            "exit_code": None,
            "reason": "not attempted",
        }
    return value


def cache_entry(prefix, path, source):
    outcome = text(f"{prefix}_CACHE_OUTCOME")
    cache_hit = text(f"{prefix}_CACHE_HIT")
    explicit_status = text(f"{prefix}_CACHE_STATUS")
    if explicit_status in {"hit", "miss", "unavailable"}:
        status = explicit_status
    elif outcome is None or outcome != "success":
        status = "unavailable"
    elif cache_hit == "true":
        status = "hit"
    else:
        status = "miss"

    return {
        "path": path,
        "path_source": source,
        "key": text(f"{prefix}_CACHE_KEY"),
        "restored_key": text(f"{prefix}_CACHE_RESTORED_KEY"),
        "status": status,
        "restore_outcome": outcome,
        "restore_cache_hit": cache_hit,
        "save_outcome": text(f"{prefix}_CACHE_SAVE_OUTCOME") or "not_attempted",
    }


stage_status = {entry["stage"]: entry["status"] for entry in stages}
application_build = outcome("IOS_NATIVE_APPLICATION_BUILD_OUTCOME_FILE", "application_build")
propagation_proof = outcome("IOS_NATIVE_PROPAGATION_PROOF_OUTCOME_FILE", "propagation_proof")
compilation = {
    "mode": text("IOS_NATIVE_COMPILATION_MODE") or "clean",
}
build_invocation = document("IOS_NATIVE_BUILD_INVOCATION_FILE")
build_command = None
if build_invocation:
    build_command = (
        " ".join(
            name + "=" + shlex.quote(value)
            for name, value in build_invocation["environment"].items()
        )
        + " "
        + shlex.join(
            [build_invocation["executable"], *build_invocation["argv"]]
        )
    )
module_document = document("IOS_NATIVE_MODULE_EVIDENCE_FILE", {})
candidate_build_document = document(
    "IOS_NATIVE_CANDIDATE_BUILD_EVIDENCE_FILE",
    {},
)
application_link_document = document(
    "IOS_NATIVE_APPLICATION_LINK_PROOF_FILE",
    {},
)


def file_digest(path):
    item = Path(path)
    if not item.is_file():
        return None
    digest = __import__("hashlib").sha256()
    with item.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def lifecycle_proof(path):
    item = Path(path)
    if not item.exists():
        return {"path": str(item), "sha256": None, "content": None, "status": "MISSING"}
    try:
        raw = item.read_bytes()
    except OSError as error:
        return {"path": str(item), "sha256": None, "content": None, "status": f"UNREADABLE:{error}"}
    try:
        content = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        content = raw.decode("utf-8", "replace")
        status = "INVALID_JSON"
    else:
        status = content.get("status", "UNKNOWN") if isinstance(content, dict) else "INVALID_DOCUMENT"
    return {
        "path": str(item),
        "sha256": __import__("hashlib").sha256(raw).hexdigest(),
        "content": content,
        "status": status,
    }


def lifecycle_inventory():
    root_value = text("IOS_NATIVE_LIFECYCLE_DIR")
    if not root_value:
        return {"invocation_binding": None, "capability_proof": None, "full_build_proof": None, "records": [], "phases": []}
    root = Path(root_value)
    if not root.is_dir():
        return {"invocation_binding": None, "capability_proof": None, "full_build_proof": None, "records": [], "phases": []}
    records_dir = root / "records"
    phases_dir = root / "phases"
    output_owner_path = Path(text("IOS_NATIVE_OUTPUT_OWNER_FILE") or "")
    output_evidence = Path(text("IOS_NATIVE_OUTPUT_EVIDENCE_DIR") or "")
    output_operations = []
    if output_evidence.is_dir():
        for path in sorted(output_evidence.glob("*.json")):
            try:
                content = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                content = None
            output_operations.append({"path": str(path), "sha256": file_digest(path),
                                      "status": content.get("status") if isinstance(content, dict) else "UNREADABLE"})
    return {
        "invocation_binding": document("IOS_NATIVE_LIFECYCLE_BINDING"),
        "capability_proof": lifecycle_proof(root / "capability-proof.json"),
        "full_build_proof": lifecycle_proof(root / "full-build-proof.json"),
        "records": [
            {"path": str(path), "sha256": file_digest(path)}
            for path in sorted(records_dir.glob("*.json"))
            if path.is_file()
        ] if records_dir.is_dir() else [],
        "phases": [
            {"path": str(path), "sha256": file_digest(path)}
            for path in sorted(phases_dir.glob("*.json"))
            if path.is_file()
        ] if phases_dir.is_dir() else [],
        "nutrition_output_lifecycle": {
            "owner": {"path": str(output_owner_path), "sha256": file_digest(output_owner_path),
                      "content": document("IOS_NATIVE_OUTPUT_OWNER_FILE")},
            "evidence_root": str(output_evidence),
            "quarantine_root": text("IOS_NATIVE_OUTPUT_QUARANTINE_ROOT"),
            "operations": output_operations,
        },
        "coverage_limit": "known process identities and the admitted IBC_EXEC producer only; no universal descendant tracking; IBPostprocessor literal ibtool is not covered by IBC_EXEC",
    }


cleanup_roots = [
    value
    for value in (text("IOS_NATIVE_CLEANUP_RETAINED_ROOTS") or "").splitlines()
    if value
]
quarantined_roots = [
    value
    for value in (text("IOS_NATIVE_CLEANUP_QUARANTINED_ROOTS") or "").splitlines()
    if value
]
cleanup = {
    "status": text("IOS_NATIVE_CLEANUP_DISPOSITION") or "NOT_STARTED",
    "reason": text("IOS_NATIVE_CLEANUP_REASON"),
    "retained_roots": cleanup_roots,
    "quarantined_roots": quarantined_roots,
}
manifest = {
    "schema_version": 1,
    "profile": "ios-native",
    "commit": text("IOS_NATIVE_COMMIT"),
    "result": result,
    "failure_kind": failure_kind,
    "evidence_retention_failure": text("IOS_NATIVE_EVIDENCE_RETENTION_FAILURE") == "1",
    "exit_code": final_exit,
    "runner": text("IOS_NATIVE_RUNNER"),
    "macos": text("IOS_NATIVE_MACOS"),
    "architecture": text("IOS_NATIVE_ARCHITECTURE"),
    "xcode": text("IOS_NATIVE_XCODE"),
    "xcode_build": text("IOS_NATIVE_XCODE_BUILD"),
    "iphonesimulator_sdk": text("IOS_NATIVE_IPHONESIMULATOR_SDK"),
    "swift": text("IOS_NATIVE_SWIFT"),
    "ruby": text("IOS_NATIVE_RUBY"),
    "ruby_binary": text("IOS_NATIVE_RUBY_BINARY"),
    "node": text("IOS_NATIVE_NODE"),
    "node_binary": text("IOS_NATIVE_NODE_BINARY"),
    "npm": text("IOS_NATIVE_NPM"),
    "expo": text("IOS_NATIVE_EXPO"),
    "react_native": text("IOS_NATIVE_REACT_NATIVE"),
    "cocoapods": text("IOS_NATIVE_COCOAPODS"),
    "generated_scheme": (build_invocation or {}).get("scheme"),
    "generated_build_command": build_command,
    "generated_build_argv": (build_invocation or {}).get("argv"),
    "generated_build_executable": (build_invocation or {}).get("executable"),
    "generated_build_environment": (build_invocation or {}).get("environment"),
    "generated_workspace": (build_invocation or {}).get("workspace"),
    "derived_data_path": (build_invocation or {}).get("derived_data_path"),
    "build_invocation": build_invocation,
    "prebuild": stage_status["prebuild_plugins"],
    "config_plugins": stage_status["prebuild_plugins"],
    "autolinking": stage_status["autolinking"],
    "pods": stage_status["pods"],
    "simulator_build": application_build["status"],
    "application_build": application_build,
    "propagation_proof": propagation_proof,
    "nutrition_ocr": {
        "autolinking": stage_status["autolinking"],
        "pod": stage_status["pods"],
        "application_compilation": application_build["status"],
    },
    "swift_harnesses": {
        "geometry": stage_status["swift_harnesses"],
        "image_quality": stage_status["swift_harnesses"],
        "vision_runtime": stage_status["swift_harnesses"],
    },
    "space_path_regression": stage_status["prebuild_plugins"],
    "generated_cleanup": cleanup["status"],
    "cleanup_disposition": cleanup,
    "native_process_lifecycle": lifecycle_inventory(),
    "native_process_lifecycle_control": "IBC_EXEC wrapper sets IBToolNeverDeque=1 for admitted calls",
    "compilation": compilation,
    "module_evidence": module_document,
    "candidate_build_evidence": candidate_build_document,
    "application_link_proof": application_link_document,
    "stages": stages,
    "total": {
        "elapsed_seconds": int(os.environ["IOS_NATIVE_TOTAL_ELAPSED"]),
        "status": result,
        "boundary": os.environ["IOS_NATIVE_TIMING_BOUNDARY"],
    },
    "elapsed_seconds": int(os.environ["IOS_NATIVE_TOTAL_ELAPSED"]),
    "cache": {
        "npm": cache_entry(
            "IOS_NATIVE_NPM",
            text("IOS_NATIVE_NPM_CACHE_PATH"),
            text("IOS_NATIVE_NPM_CACHE_PATH_SOURCE"),
        ),
        "cocoapods": cache_entry(
            "IOS_NATIVE_COCOAPODS",
            text("IOS_NATIVE_COCOAPODS_CACHE_PATH"),
            text("IOS_NATIVE_COCOAPODS_CACHE_PATH_SOURCE"),
        ),
        "cached_contents": [
            "npm download cache",
            "CocoaPods download cache",
        ],
        "excluded_contents": [
            "node_modules",
            "ios",
            "Pods",
            "DerivedData",
            "compiled products",
            "harness binaries",
            "worktree",
        ],
        "key_identity_inputs": {
            "npm": [
                ".nvmrc",
                "apps/mobile/package.json",
                "apps/mobile/package-lock.json",
                "macOS",
                "architecture",
                "Node",
                "npm",
            ],
            "cocoapods": [
                ".nvmrc",
                "apps/mobile/package.json",
                "apps/mobile/package-lock.json",
                "apps/mobile/app.json",
                "apps/mobile/app.config.js",
                "apps/mobile/config/runtimeConfig.js",
                "apps/mobile/plugins/**",
                "apps/mobile/modules/**/expo-module.config.json",
                "apps/mobile/modules/**/ios/**",
                "macOS",
                "architecture",
                "Node",
                "npm",
                "Ruby",
                "CocoaPods",
                "Xcode",
                "iPhone Simulator SDK",
            ],
        },
    },
}

manifest_path.write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
}

on_exit() {
  local observed_exit="${1:-0}"
  local cleanup_exit=0

  trap - EXIT INT TERM

  if test "$qualifier_exit_status" -eq 0
  then
    qualifier_exit_status="$observed_exit"
  fi

  if test "$cleanup_done" -eq 0
  then
    run_stage cleanup cleanup_stage 1
    cleanup_exit="$?"
    cleanup_done=1
  fi

  if test -n "$(
    git -C "$repo_root" status \
      --porcelain=v1 \
      -uall
  )"
  then
    printf '%s\n' "repository source mutated during qualification" \
      > "$evidence_dir/source-mutation.txt"
    if test "$qualifier_exit_status" -eq 0
    then
      qualifier_exit_status=1
    fi
  fi

  if test "$evidence_retention_failure" -ne 0 &&
    test "$qualifier_exit_status" -eq 0
  then
    qualifier_exit_status=1
  fi

  if test -f "$native_lifecycle_binding"
  then
    if ! record_native_phase qualifier-finished "{\"cleanup_disposition\":\"$cleanup_disposition\"}"
    then
      evidence_retention_failure=1
      echo "IOS_NATIVE_QUALIFIER_TERMINAL_RECORD_FAILED" >&2
      if test "$qualifier_exit_status" -eq 0
      then
        qualifier_exit_status=1
      fi
    fi
  fi

  write_manifest "$qualifier_exit_status"
  manifest_exit="$?"
  if test "$manifest_exit" -ne 0
  then
    evidence_retention_failure=1
    echo "IOS_NATIVE_MANIFEST_WRITE_FAILED" >&2
    if test "$qualifier_exit_status" -eq 0
    then
      qualifier_exit_status=1
    fi
  fi

  if test -f "$manifest"
  then
    cat "$manifest"
    manifest_read_exit="$?"
    if test "$manifest_read_exit" -ne 0
    then
      evidence_retention_failure=1
      echo "IOS_NATIVE_MANIFEST_READ_FAILED" >&2
      if test "$qualifier_exit_status" -eq 0
      then
        qualifier_exit_status=1
      fi
    fi
  else
    evidence_retention_failure=1
    echo "IOS_NATIVE_MANIFEST_RETENTION_FAILED" >&2
    if test "$qualifier_exit_status" -eq 0
    then
      qualifier_exit_status=1
    fi
  fi

  if test "$qualifier_exit_status" -eq 0
  then
    echo "IOS_NATIVE_QUALIFICATION=PASS"
  else
    echo "IOS_NATIVE_QUALIFICATION=FAILURE" >&2
  fi
  echo "IOS_NATIVE_CLEANUP=$cleanup_disposition"

  exit "$qualifier_exit_status"
}

select_native_python() {
  local required_version
  local interpreter_candidate
  local selection_source
  local interpreter_info
  local actual_version
  local actual_executable

  if ! required_version="$(cat "$repo_root/.python-version")" ||
    test -z "$required_version"
  then
    echo "IOS_NATIVE_PYTHON_VERSION_FILE_UNAVAILABLE:$repo_root/.python-version" >&2
    return 2
  fi
  case "$required_version" in
    *[!0-9.]*|*.*.*|.*|*.)
      echo "IOS_NATIVE_PYTHON_VERSION_FILE_INVALID:$required_version" >&2
      return 2
      ;;
  esac
  case "$required_version" in
    [0-9]*.[0-9]*)
      ;;
    *)
      echo "IOS_NATIVE_PYTHON_VERSION_FILE_INVALID:$required_version" >&2
      return 2
      ;;
  esac

  if test "${NUTRITION_CONTROLLER_PYTHON+x}" = x
  then
    if test -z "$NUTRITION_CONTROLLER_PYTHON"
    then
      echo "IOS_NATIVE_PYTHON_EXPLICIT_PATH_EMPTY" >&2
      return 2
    fi
    interpreter_candidate="$NUTRITION_CONTROLLER_PYTHON"
    selection_source="explicit"
    case "$interpreter_candidate" in
      /*)
        ;;
      *)
        echo "IOS_NATIVE_PYTHON_EXPLICIT_PATH_NOT_ABSOLUTE:$interpreter_candidate" >&2
        return 2
        ;;
    esac
  else
    local interpreter_command="python${required_version}"
    if ! interpreter_candidate="$(command -v "$interpreter_command")" ||
      test -z "$interpreter_candidate"
    then
      echo "IOS_NATIVE_PYTHON_VERSIONED_COMMAND_UNAVAILABLE:$interpreter_command" >&2
      return 2
    fi
    selection_source="versioned-command"
  fi

  if ! test -f "$interpreter_candidate" ||
    ! test -x "$interpreter_candidate"
  then
    echo "IOS_NATIVE_PYTHON_BINARY_UNAVAILABLE:$interpreter_candidate" >&2
    return 2
  fi

  if ! interpreter_info="$(
    "$interpreter_candidate" -I -B -c \
      'import os,sys; print("%s.%s\t%s" % (sys.version_info.major, sys.version_info.minor, os.path.realpath(sys.executable)))'
  )" ||
    test -z "$interpreter_info"
  then
    echo "IOS_NATIVE_PYTHON_VERSION_PROBE_FAILED:$interpreter_candidate" >&2
    return 2
  fi
  case "$interpreter_info" in
    *$'\n'*|*$'\r'*)
      echo "IOS_NATIVE_PYTHON_VERSION_PROBE_INVALID:$interpreter_candidate" >&2
      return 2
      ;;
  esac
  IFS=$'\t' read -r actual_version actual_executable <<< "$interpreter_info"
  case "$actual_version" in
    [0-9]*.[0-9]*)
      ;;
    *)
      echo "IOS_NATIVE_PYTHON_VERSION_PROBE_INVALID:$interpreter_candidate" >&2
      return 2
      ;;
  esac
  case "$actual_executable" in
    /*)
      ;;
    *)
      echo "IOS_NATIVE_PYTHON_EXECUTABLE_PATH_INVALID:$interpreter_candidate" >&2
      return 2
      ;;
  esac
  if ! test -x "$actual_executable"
  then
    echo "IOS_NATIVE_PYTHON_EXECUTABLE_UNAVAILABLE:$actual_executable" >&2
    return 2
  fi
  if test "$actual_version" != "$required_version"
  then
    echo "IOS_NATIVE_PYTHON_VERSION_MISMATCH:$actual_version:required=$required_version" >&2
    return 2
  fi

  native_lifecycle_python="$interpreter_candidate"
  native_lifecycle_python_version="$actual_version"
  native_lifecycle_python_executable="$actual_executable"
  export NUTRITION_CONTROLLER_PYTHON="$native_lifecycle_python"
  export IOS_NATIVE_PYTHON_REQUIRED_VERSION="$required_version"
  export IOS_NATIVE_PYTHON_VERSION="$native_lifecycle_python_version"
  export IOS_NATIVE_PYTHON_CONFIGURED_PATH="$native_lifecycle_python"
  export IOS_NATIVE_PYTHON_EXECUTABLE="$native_lifecycle_python_executable"
  export IOS_NATIVE_PYTHON_SELECTION_SOURCE="$selection_source"

  "$native_lifecycle_python" -I -B - \
    "$evidence_dir/python-runtime.json" \
    "$repo_root/.python-version" \
    "$required_version" \
    "$actual_version" \
    "$native_lifecycle_python" \
    "$native_lifecycle_python_executable" \
    "$selection_source" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

record, version_file, required, actual, configured, executable, source = sys.argv[1:]
Path(record).write_text(
    json.dumps({
        "required_version": required,
        "actual_version": actual,
        "configured_interpreter": configured,
        "runtime_executable": executable,
        "selection_source": source,
        "version_file": version_file,
        "version_file_sha256": hashlib.sha256(Path(version_file).read_bytes()).hexdigest(),
    }, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY
  local record_status="$?"
  if test "$record_status" -ne 0
  then
    native_lifecycle_python=""
    echo "IOS_NATIVE_PYTHON_SELECTION_EVIDENCE_FAILED" >&2
    return 2
  fi
}

capture_toolchain() {
  local tool
  local xcode_info
  local swift_info
  for tool in node npm pod xcrun xcode-select ruby
  do
    if ! command -v "$tool" >/dev/null 2>&1
    then
      echo "IOS_NATIVE_TOOL_MISSING:$tool" >&2
      return 1
    fi
  done

  if ! node_binary="$(command -v node)" ||
    test -z "$node_binary"
  then
    echo "IOS_NATIVE_NODE_BINARY_UNAVAILABLE" >&2
    return 1
  fi

  if ! ruby_binary="$(command -v ruby)" ||
    test -z "$ruby_binary"
  then
    echo "IOS_NATIVE_RUBY_BINARY_UNAVAILABLE" >&2
    return 1
  fi

  if test -z "$native_lifecycle_python" ||
    ! test -x "$native_lifecycle_python"
  then
    echo "IOS_NATIVE_PYTHON_BINARY_UNAVAILABLE" >&2
    return 1
  fi

  if ! native_lifecycle_developer_dir="${DEVELOPER_DIR:-$(xcode-select -p)}" ||
    test -z "$native_lifecycle_developer_dir"
  then
    echo "IOS_NATIVE_DEVELOPER_DIRECTORY_UNAVAILABLE" >&2
    return 1
  fi
  if ! native_lifecycle_developer_dir="$(cd "$native_lifecycle_developer_dir" && pwd -P)"
  then
    echo "IOS_NATIVE_DEVELOPER_DIRECTORY_INVALID" >&2
    return 1
  fi
  export DEVELOPER_DIR="$native_lifecycle_developer_dir"

  if ! xcodebuild_binary="$(xcrun --find xcodebuild)" ||
    test -z "$xcodebuild_binary"
  then
    echo "IOS_NATIVE_XCODEBUILD_BINARY_UNAVAILABLE" >&2
    return 1
  fi
  if ! native_lifecycle_ibtool="$(xcrun --find ibtool)" ||
    test -z "$native_lifecycle_ibtool"
  then
    echo "IOS_NATIVE_IBTOOL_BINARY_UNAVAILABLE" >&2
    return 1
  fi
  if ! native_lifecycle_ibtool="$("$native_lifecycle_python" -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$native_lifecycle_ibtool")"
  then
    echo "IOS_NATIVE_IBTOOL_PATH_RESOLUTION_FAILED" >&2
    return 1
  fi
  native_lifecycle_ibtoold="$(dirname "$native_lifecycle_ibtool")/ibtoold"
  if ! test -x "$native_lifecycle_ibtoold"
  then
    echo "IOS_NATIVE_IBTOOLD_BINARY_UNAVAILABLE:$native_lifecycle_ibtoold" >&2
    return 1
  fi
  if ! native_lifecycle_ibtoold="$("$native_lifecycle_python" -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$native_lifecycle_ibtoold")"
  then
    echo "IOS_NATIVE_IBTOOLD_PATH_RESOLUTION_FAILED" >&2
    return 1
  fi
  native_lifecycle_xcodebuild="$("$native_lifecycle_python" -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$xcodebuild_binary")"
  xcodebuild_binary="$native_lifecycle_xcodebuild"

  local spec_root
  spec_root="$(dirname "$native_lifecycle_developer_dir")/SharedFrameworks/SwiftBuild.framework/Versions/A/PlugIns/SWBBuildService.bundle/Contents/PlugIns/SWBApplePlatformPlugin.bundle/Contents/Frameworks/SWBApplePlatform.framework/Versions/A/Resources"
  native_lifecycle_xcode_spec_compiler="$spec_root/IBCompiler.xcspec"
  native_lifecycle_xcode_spec_storyboard="$spec_root/IBStoryboardCompiler.xcspec"
  native_lifecycle_xcode_spec_linker="$spec_root/IBStoryboardLinker.xcspec"
  native_lifecycle_xcode_spec_postprocessor="$spec_root/IBPostprocessor.xcspec"
  for spec in \
    "$native_lifecycle_xcode_spec_compiler" \
    "$native_lifecycle_xcode_spec_storyboard" \
    "$native_lifecycle_xcode_spec_linker" \
    "$native_lifecycle_xcode_spec_postprocessor"
  do
    if ! test -f "$spec"
    then
      echo "IOS_NATIVE_TOOLCHAIN_SPEC_UNAVAILABLE:$spec" >&2
      return 1
    fi
  done

  if ! xcode_info="$("$xcodebuild_binary" -version)" ||
    test -z "$xcode_info"
  then
    echo "IOS_NATIVE_XCODE_VERSION_UNAVAILABLE" >&2
    return 1
  fi

  if ! node_version="$(node --version)" ||
    test -z "$node_version"
  then
    echo "IOS_NATIVE_NODE_VERSION_UNAVAILABLE" >&2
    return 1
  fi

  if ! npm_version="$(npm --version)" ||
    test -z "$npm_version"
  then
    echo "IOS_NATIVE_NPM_VERSION_UNAVAILABLE" >&2
    return 1
  fi

  if ! ruby_version="$(ruby --version)" ||
    test -z "$ruby_version"
  then
    echo "IOS_NATIVE_RUBY_VERSION_UNAVAILABLE" >&2
    return 1
  fi

  if ! macos_version="$(sw_vers -productVersion)" ||
    test -z "$macos_version"
  then
    echo "IOS_NATIVE_MACOS_VERSION_UNAVAILABLE" >&2
    return 1
  fi

  if ! architecture="$(uname -m)" ||
    test -z "$architecture"
  then
    echo "IOS_NATIVE_ARCHITECTURE_UNAVAILABLE" >&2
    return 1
  fi

  xcode_version="$(printf '%s\n' "$xcode_info" | awk 'NR == 1 {print $2}')"
  xcode_build="$(printf '%s\n' "$xcode_info" | awk 'NR == 2 {print $3}')"

  if ! swift_info="$(xcrun swiftc --version)" ||
    test -z "$swift_info"
  then
    echo "IOS_NATIVE_SWIFT_VERSION_UNAVAILABLE" >&2
    return 1
  fi
  swift_version="$(printf '%s\n' "$swift_info" | sed -n '1p')"

  if ! cocoapods_version="$(pod --version)" ||
    test -z "$cocoapods_version"
  then
    echo "IOS_NATIVE_COCOAPODS_VERSION_UNAVAILABLE" >&2
    return 1
  fi

  if ! iphonesimulator_sdk="$(xcrun --sdk iphonesimulator --show-sdk-version)" ||
    test -z "$iphonesimulator_sdk"
  then
    echo "IOS_NATIVE_IPHONESIMULATOR_SDK_UNAVAILABLE" >&2
    return 1
  fi

  if test -z "$xcode_version" || test -z "$xcode_build"
  then
    echo "IOS_NATIVE_XCODE_VERSION_UNAVAILABLE" >&2
    return 1
  fi

  xcode_major="${xcode_version%%.*}"
  xcode_tail="${xcode_version#*.}"
  xcode_minor="${xcode_tail%%.*}"

  case "$xcode_major" in
    ''|*[!0-9]*)
      echo "IOS_NATIVE_XCODE_VERSION_INVALID:$xcode_version" >&2
      return 1
      ;;
  esac

  if test "$xcode_major" -lt 26 ||
    (test "$xcode_major" -eq 26 && test "$xcode_minor" -lt 4)
  then
    echo "IOS_NATIVE_XCODE_TOO_OLD:$xcode_version" >&2
    return 1
  fi

  npm_cache_path="${npm_config_cache:-${NPM_CONFIG_CACHE:-}}"
  npm_cache_path_source="npm_config_cache"
  if test -z "${npm_config_cache:-}" && test -n "${NPM_CONFIG_CACHE:-}"
  then
    npm_cache_path_source="NPM_CONFIG_CACHE"
  fi
  if test -z "$npm_cache_path"
  then
    if ! npm_cache_path="$(npm config get cache)" ||
      test -z "$npm_cache_path"
    then
      echo "IOS_NATIVE_NPM_CACHE_UNAVAILABLE" >&2
      return 1
    fi
    npm_cache_path_source="npm config get cache"
  fi

  cocoapods_cache_path="${CP_CACHE_DIR:-${HOME}/Library/Caches/CocoaPods}"
  if test -n "${CP_CACHE_DIR:-}"
  then
    cocoapods_cache_path_source="CP_CACHE_DIR"
  else
    cocoapods_cache_path_source="CocoaPods Config DEFAULTS cache_root"
  fi

  if ! "$native_lifecycle_python" \
    "$repo_root/scripts/toolchain-report.py" \
    --check node \
    > "$evidence_dir/node-toolchain.log"
  then
    echo "IOS_NATIVE_NODE_TOOLCHAIN_CHECK_FAILED" >&2
    return 1
  fi

  if ! pod env > "$evidence_dir/cocoapods-env.log" 2>&1
  then
    echo "IOS_NATIVE_COCOAPODS_ENV_FAILED" >&2
    return 1
  fi

  export IOS_NATIVE_NODE_BINARY="$node_binary"
  export IOS_NATIVE_RUBY_BINARY="$ruby_binary"
  export IOS_NATIVE_XCODEBUILD_BINARY="$xcodebuild_binary"
  export IOS_NATIVE_NODE="$node_version"
  export IOS_NATIVE_NPM="$npm_version"
  export IOS_NATIVE_RUBY="$ruby_version"
  export IOS_NATIVE_MACOS="$macos_version"
  export IOS_NATIVE_ARCHITECTURE="$architecture"
  export IOS_NATIVE_XCODE="$xcode_version"
  export IOS_NATIVE_XCODE_BUILD="$xcode_build"
  export IOS_NATIVE_SWIFT="$swift_version"
  export IOS_NATIVE_COCOAPODS="$cocoapods_version"
  export IOS_NATIVE_IPHONESIMULATOR_SDK="$iphonesimulator_sdk"
  export IOS_NATIVE_NPM_CACHE_PATH="$npm_cache_path"
  export IOS_NATIVE_NPM_CACHE_PATH_SOURCE="$npm_cache_path_source"
  export IOS_NATIVE_COCOAPODS_CACHE_PATH="$cocoapods_cache_path"
  export IOS_NATIVE_COCOAPODS_CACHE_PATH_SOURCE="$cocoapods_cache_path_source"
}

setup_native_lifecycle() {
  local setup_log="$evidence_dir/native-lifecycle-setup.log"
  if ! IOS_NATIVE_QUALIFIER_PID="$$" \
    IOS_NATIVE_SPEC_COMPILER="$native_lifecycle_xcode_spec_compiler" \
    IOS_NATIVE_SPEC_STORYBOARD_COMPILER="$native_lifecycle_xcode_spec_storyboard" \
    IOS_NATIVE_SPEC_LINKER="$native_lifecycle_xcode_spec_linker" \
    IOS_NATIVE_SPEC_POSTPROCESSOR="$native_lifecycle_xcode_spec_postprocessor" \
    "$native_lifecycle_python" - \
      "$evidence_dir" \
      "$repo_root" \
      "$probe_root" \
      "$derived_data" \
      "$harness_bin" \
      "$native_lifecycle_ibtool" \
      "$native_lifecycle_ibtoold" \
      "$native_lifecycle_xcodebuild" \
      "$native_lifecycle_developer_dir" \
      "$xcode_version" \
      "$xcode_build" \
      "$native_lifecycle_helper" \
      "$repo_root/scripts/ios-native-qualification.sh" \
      "$native_lifecycle_binding" \
      "$native_lifecycle_wrapper" \
      "$native_lifecycle_python" \
      > "$setup_log" 2>&1 <<'PY'
import os
import sys
from pathlib import Path

helper = Path(sys.argv[12]).resolve(strict=True)
sys.path.insert(0, str(helper.parent))
import native_process_lifecycle as lifecycle

evidence, source, worktree, derived, harness, ibtool, ibtoold, xcodebuild, developer, version, build, _, qualifier_script, binding, wrapper, python = sys.argv[1:]
invocation_dir, created_binding, created_wrapper = lifecycle.create_invocation(
    evidence_dir=evidence,
    source_root=source,
    qualifier_pid=int(os.environ["IOS_NATIVE_QUALIFIER_PID"]),
    worktree_root=worktree,
    derived_data_root=derived,
    harness_root=harness,
    ibtool_path=ibtool,
    ibtoold_path=ibtoold,
    xcodebuild_path=xcodebuild,
    developer_dir=developer,
    xcode_version=version,
    xcode_build=build,
    spec_paths={
        "compiler": os.environ["IOS_NATIVE_SPEC_COMPILER"],
        "storyboard_compiler": os.environ["IOS_NATIVE_SPEC_STORYBOARD_COMPILER"],
        "linker": os.environ["IOS_NATIVE_SPEC_LINKER"],
        "postprocessor": os.environ["IOS_NATIVE_SPEC_POSTPROCESSOR"],
    },
    helper_path=helper,
    qualifier_script_path=qualifier_script,
)
if created_binding != Path(binding) or created_wrapper != Path(wrapper):
    raise SystemExit("NATIVE_LIFECYCLE_PATH_BINDING_MISMATCH")
lifecycle.write_wrapper(created_binding, created_wrapper, python)
PY
  then
    echo "IOS_NATIVE_LIFECYCLE_SETUP_FAILED" >&2
    return 1
  fi
}

record_native_phase() {
  local phase="$1"
  local details_json="${2:-}"
  if test -z "$details_json"
  then
    details_json="{}"
  fi
  "$native_lifecycle_python" - \
    "$native_lifecycle_helper" \
    "$native_lifecycle_binding" \
    "$phase" \
    "$details_json" <<'PY'
import json
import sys
from pathlib import Path

helper = Path(sys.argv[1]).resolve(strict=True)
sys.path.insert(0, str(helper.parent))
import native_process_lifecycle as lifecycle

details = json.loads(sys.argv[4])
lifecycle.record_phase(sys.argv[2], sys.argv[3], **details)
PY
}

initialize_native_output_owner() {
  native_output_attempt="native-${commit:0:12}-$$-${start_epoch}"
  if ! mkdir -m 700 "$native_output_durable"
  then
    echo "IOS_NATIVE_OUTPUT_EVIDENCE_ROOT_CREATE_FAILED" >&2
    return 1
  fi
  if ! "$native_lifecycle_python" "$native_output_cleanup" create-owned \
      --owner-record "$native_output_owner" \
      --path "$derived_data" \
      --task "$native_output_attempt" \
      --attempt "$native_output_attempt" \
      --definition "$native_lifecycle_binding" \
      > "$native_lifecycle_dir/derived-data-owner.json"
  then
    echo "IOS_NATIVE_DERIVED_DATA_OWNERSHIP_FAILED" >&2
    return 1
  fi
  if ! "$native_lifecycle_python" "$native_output_cleanup" create-owned \
      --owner-record "$native_output_owner" \
      --path "$harness_bin" \
      --task "$native_output_attempt" \
      --attempt "$native_output_attempt" \
      --definition "$native_lifecycle_binding" \
      > "$native_lifecycle_dir/harness-bin-owner.json"
  then
    echo "IOS_NATIVE_HARNESS_OWNERSHIP_FAILED" >&2
    return 1
  fi
  return 0
}

start_native_output_owner() {
  "$native_lifecycle_python" "$native_output_cleanup" owner-hold \
    --owner-record "$native_output_owner" \
    --ready-file "$native_owner_ready" \
    > "$native_lifecycle_dir/output-owner-hold.log" 2>&1 &
  native_owner_hold_pid="$!"
  local wait_index=0
  while test "$wait_index" -lt 250 && ! test -f "$native_owner_ready" &&
    kill -0 "$native_owner_hold_pid" 2>/dev/null
  do
    sleep 0.02
    wait_index=$((wait_index + 1))
  done
  if ! test -f "$native_owner_ready"
  then
    echo "IOS_NATIVE_OUTPUT_OWNER_LOCK_FAILED" >&2
    return 1
  fi
  return 0
}

stop_native_output_owner() {
  if test -n "$native_owner_hold_pid"
  then
    kill -TERM "$native_owner_hold_pid" 2>/dev/null || true
    wait "$native_owner_hold_pid" 2>/dev/null || true
    native_owner_hold_pid=""
  fi
}

finish_native_output_owner() {
  local phase_details
  local hold_pid="$native_owner_hold_pid"
  phase_details="$("$native_lifecycle_python" - "$native_output_attempt" "$qualifier_exit_status" "$signal_status" <<'PY'
import json
import sys
print(json.dumps({"owner_attempt": sys.argv[1], "producer_exit_code": int(sys.argv[2]),
                  "signal_status": int(sys.argv[3])}, sort_keys=True))
PY
)" || return 1
  if ! record_native_phase producer-finished "$phase_details"
  then
    mark_cleanup_incomplete "native producer terminal phase could not be retained"
    return 1
  fi
  stop_native_output_owner
  if ! verify_before_disposal output-owner-terminal
  then
    return 1
  fi
  local finish_status=0
  if test -n "$hold_pid"
  then
    "$native_lifecycle_python" "$native_output_cleanup" finish-native-owner \
      --owner-record "$native_output_owner" \
      --invocation-record "$native_lifecycle_binding" \
      --hold-pid "$hold_pid" \
      > "$native_lifecycle_dir/output-owner-terminal.json" || finish_status=$?
  else
    "$native_lifecycle_python" "$native_output_cleanup" finish-native-owner \
      --owner-record "$native_output_owner" \
      --invocation-record "$native_lifecycle_binding" \
      > "$native_lifecycle_dir/output-owner-terminal.json" || finish_status=$?
  fi
  if test "$finish_status" -ne 0
  then
    mark_cleanup_incomplete "native producer ownership terminal observation failed"
    return 1
  fi
  if ! "$native_lifecycle_python" "$native_output_cleanup" native-quarantine-parent-create \
      --owner-record "$native_output_owner" \
      --path "$native_output_quarantine" \
      --same-device-as "$derived_data" \
      --durable-evidence "$native_output_durable" \
      --invocation-record "$native_lifecycle_binding" \
      > "$native_lifecycle_dir/quarantine-parent.json"
  then
    mark_cleanup_incomplete "native quarantine parent could not be bound to the output owner"
    return 1
  fi
  return 0
}

execute_verified_native_quarantine() {
  local kind="$1"
  local output_path="$2"
  local destination="$3"
  local stdout_path="$native_lifecycle_dir/quarantine-$kind.stdout.log"
  local stderr_path="$native_lifecycle_dir/quarantine-$kind.stderr.log"
  local quarantine_status=0
  if "$native_lifecycle_python" - \
    "$native_lifecycle_helper" \
    "$native_lifecycle_binding" \
    "$native_output_owner" \
    "$native_output_durable" \
    "$native_output_quarantine" \
    "$output_path" \
    "$destination" \
    "$native_output_attempt" \
    "$repo_root" \
    "$kind" \
    > "$stdout_path" 2> "$stderr_path" <<'PY'
import json
import sys
from pathlib import Path

helper_path, binding_path, owner_path, durable, quarantine_parent, output_path, destination, attempt, repository, kind = sys.argv[1:]
helper_path = Path(helper_path).resolve(strict=True)
sys.path.insert(0, str(helper_path.parent))
import native_process_lifecycle as verifier
if Path(verifier.__file__).resolve(strict=True) != helper_path:
    raise SystemExit("NATIVE_HELPER_IMPORT_PATH_MISMATCH")
script_root = Path(repository).resolve(strict=True) / "scripts"
sys.path.insert(0, str(script_root))
from lib import task_output_cleanup as cleanup

def verify_native_proofs():
    try:
        cleanup.verify_native_proof_readback(
            Path(owner_path), invocation_record=Path(binding_path), durable_evidence=Path(durable),
        )
    except cleanup.OutputError as error:
        print(f"NATIVE_PROOF_READBACK_REQUIRED_FAILURE:{error}", file=sys.stderr)
        raise SystemExit(2) from error

def verify_producer_before_move():
    def verify_prior_operations():
        try:
            cleanup.verify_native_quarantine_operations(
                Path(owner_path), invocation_record=Path(binding_path),
                durable_evidence=Path(durable), allow_current_path=Path(output_path),
            )
        except cleanup.OutputError as error:
            print(f"NATIVE_PRIOR_OUTPUT_READBACK_REQUIRED_FAILURE:{error}", file=sys.stderr)
            raise SystemExit(1) from error

    verify_native_proofs()
    status = verifier.verify_command(binding_path, [])
    if status:
        raise SystemExit(status)
    verify_native_proofs()
    verify_prior_operations()

verify_producer_before_move()

with cleanup.owner_lock(Path(owner_path), blocking=False):
    if kind == "worktree":
        result = cleanup.execute_registered_worktree_quarantine(
            Path(owner_path), output_path=Path(output_path), repository=Path(repository),
            quarantine_parent=Path(quarantine_parent), destination=Path(destination),
            durable_evidence=Path(durable), task=attempt, attempt=attempt, owner_lock_held=True,
            before_move=verify_producer_before_move,
        )
    elif kind in {"derived-data", "harness-bin"}:
        result = cleanup.execute_native_quarantine(
            Path(owner_path), output_path=Path(output_path), destination=Path(destination),
            durable_evidence=Path(durable), task=attempt, attempt=attempt, owner_lock_held=True,
            before_move=verify_producer_before_move,
        )
    else:
        raise SystemExit("NATIVE_QUARANTINE_KIND_INVALID")
print(json.dumps(result, sort_keys=True))
PY
  then
    quarantine_status=0
  else
    quarantine_status="$?"
  fi
  if test "$quarantine_status" -eq 2
  then
    local detail
    detail="$(tail -n 1 "$stderr_path" 2>/dev/null || true)"
    required_proof_failure=1
    record_outcome \
      "$propagation_proof_outcome" \
      propagation_proof \
      FAILURE \
      "$quarantine_status" \
      "${detail:-required lifecycle evidence verification failed immediately before quarantine}" || true
    if test "$qualifier_exit_status" -eq 0
    then
      qualifier_exit_status=1
    fi
  fi
  return "$quarantine_status"
}

ibtool_capability_stage() {
  local -a storyboards
  local storyboard
  storyboards=()
  while IFS= read -r -d '' storyboard
  do
    storyboards+=("$storyboard")
  done < <(
    find "$mobile/ios" \
      -type f \
      -name 'SplashScreen.storyboard' \
      -print0
  )
  if test "${#storyboards[@]}" -ne 1
  then
    echo "IOS_NATIVE_SPLASH_STORYBOARD_AMBIGUOUS:${#storyboards[@]}" >&2
    return 1
  fi
  if ! record_native_phase capability-required "{\"storyboard\":$(
    "$native_lifecycle_python" -c 'import json,sys; print(json.dumps(sys.argv[1]))' "${storyboards[0]}"
  )}"
  then
    echo "IOS_NATIVE_CAPABILITY_PHASE_RECORD_FAILED" >&2
    return 1
  fi
  if ! "$native_lifecycle_python" \
    "$native_lifecycle_helper" \
    capability \
    --binding "$native_lifecycle_binding" \
    --storyboard "${storyboards[0]}" \
    --output-dir "$native_lifecycle_dir/capability"
  then
    echo "IOS_NATIVE_IBTOOL_CAPABILITY_FAILED" >&2
    return 1
  fi
}

npm_install_stage() {
  test ! -e "$mobile/ios"

  (
    cd "$mobile"
    npm ci --audit=false
  ) > "$evidence_dir/npm-ci.log" 2>&1
}

prebuild_plugins_stage() {
  local expo_version
  local react_native_version
  local project
  local producer_exit_code

  expo_version="$(
    cd "$mobile"
    node -p 'require("./node_modules/expo/package.json").version'
  )"
  react_native_version="$(
    cd "$mobile"
    node -p 'require("./node_modules/react-native/package.json").version'
  )"
  printf 'expo=%s\nreact_native=%s\n' \
    "$expo_version" \
    "$react_native_version" \
    > "$dependency_versions"

  "$native_lifecycle_python" "$native_output_cleanup" begin-native-generated-output \
    --owner-record "$native_output_owner" \
    --invocation-record "$native_lifecycle_binding" \
    > "$native_lifecycle_dir/expo-output-intent.json"

  if (
    cd "$mobile"

    EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY=remote \
    EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE=test \
    EXPO_PUBLIC_NUTRITION_API_URL=http://127.0.0.1:8000 \
      npm exec -- \
      expo prebuild \
      --clean \
      --platform ios \
      --no-install
  ) > "$evidence_dir/prebuild.log" 2>&1
  then
    producer_exit_code=0
  else
    producer_exit_code="$?"
  fi

  "$native_lifecycle_python" "$native_output_cleanup" finish-native-generated-output \
    --owner-record "$native_output_owner" \
    --invocation-record "$native_lifecycle_binding" \
    --producer-exit-code "$producer_exit_code" \
    > "$native_lifecycle_dir/expo-output-observed.json"

  if test "$producer_exit_code" -ne 0
  then
    return "$producer_exit_code"
  fi

  test -d "$mobile/ios"
  test -f "$mobile/ios/Podfile"

  project="$(
    find "$mobile/ios" \
      -maxdepth 1 \
      -name '*.xcodeproj' \
      -print |
      sed -n '1p'
  )"

  test -n "$project"
  test -f "$project/project.pbxproj"

  grep -Fq \
    "Expo Constants generates a CocoaPods script phase through" \
    "$mobile/ios/Podfile"

  grep -Fq \
    "Nutrition App iOS path portability: React Native Info.plist discovery" \
    "$mobile/ios/Podfile"

  grep -Fq \
    "Nutrition App iOS path portability: CocoaPods XCFramework diagnostics" \
    "$mobile/ios/Podfile"

  grep -Fq \
    "Find.find(project_folder_path)" \
    "$mobile/ios/Podfile"

  grep -Fq \
    "::NewArchitectureHelper.define_singleton_method" \
    "$mobile/ios/Podfile"

  grep -Fq \
    'basename "$basepath"' \
    "$mobile/ios/Podfile"

  grep -Fq \
    'REACT_NATIVE_XCODE_SCRIPT=' \
    "$project/project.pbxproj"

  unsafe_bundle_count="$(
    grep -Fc \
      '"$NODE_BINARY" --print' \
      "$project/project.pbxproj" \
      || true
  )"

  test "$unsafe_bundle_count" -eq 0

  printf 'PROJECT=%s\n' "$project" > "$prebuild_paths"

}

autolinking_stage() {
  (
    cd "$mobile"

    ./node_modules/.bin/expo-modules-autolinking \
      resolve \
      --platform apple \
      --json
  ) \
    > "$evidence_dir/autolinking.json" \
    2> "$evidence_dir/autolinking.stderr"

  node - "$evidence_dir/autolinking.json" <<'NODE'
const fs = require("fs");

const path = process.argv[2];
const document = JSON.parse(
  fs.readFileSync(path, "utf8")
);

const matches = (document.modules || []).filter(
  (entry) => {
    const pods = (entry.pods || []).map(
      (pod) => pod.podName
    );

    const swiftModules =
      entry.swiftModuleNames || [];

    const classes = (entry.modules || []).map(
      (module) => module.class
    );

    return (
      entry.packageName === "nutrition-ocr" &&
      pods.includes("NutritionOcr") &&
      swiftModules.includes("NutritionOcr") &&
      classes.includes("NutritionOcrModule")
    );
  }
);

if (matches.length !== 1) {
  throw new Error(
    "NutritionOcr autolinking mismatch: " + matches.length
  );
}
NODE
}

pods_stage() {
  local workspace
  local project
  local scheme

  project="$(sed -n 's/^PROJECT=//p' "$prebuild_paths")"

  (
    cd "$mobile/ios"
    pod install
  ) > "$evidence_dir/pod-install.log" 2>&1

  if grep -Fq \
    "find: " \
    "$evidence_dir/pod-install.log"
  then
    echo "IOS_NATIVE_UNSAFE_FIND_OUTPUT" >&2
    return 1
  fi

  test -f "$mobile/ios/Podfile.lock"

  grep -Fq \
    "NutritionOcr" \
    "$mobile/ios/Podfile.lock"

  grep -Fq \
    "ExpoModulesCore" \
    "$mobile/ios/Podfile.lock"

  workspace="$(
    find "$mobile/ios" \
      -maxdepth 1 \
      -name '*.xcworkspace' \
      -print |
      sed -n '1p'
  )"

  test -n "$workspace"

  scheme="$(basename "$project" .xcodeproj)"
  printf 'WORKSPACE=%s\nSCHEME=%s\n' \
    "$workspace" \
    "$scheme" \
    >> "$prebuild_paths"
}

capture_build_invocation() {
  local executable="$1"
  local workspace="$2"
  local scheme="$3"
  local build_command
  shift 3

  if ! build_command="$(
    IOS_NATIVE_BUILD_INVOCATION_FILE="$build_invocation_file" \
    IOS_NATIVE_BUILD_WORKSPACE="$workspace" \
    IOS_NATIVE_BUILD_DERIVED_DATA="$derived_data" \
    IOS_NATIVE_BUILD_NODE_BINARY="$node_binary" \
    IOS_NATIVE_IBTOOL_WRAPPER="$native_lifecycle_wrapper" \
    "$native_lifecycle_python" - "$executable" "$workspace" "$scheme" "$derived_data" "$node_binary" "$@" <<'PY'
import json
import os
import shlex
import sys
from pathlib import Path


executable, workspace, scheme, derived_data, node_binary = sys.argv[1:6]
argv = sys.argv[6:]


def option_value(option):
    matches = [
        argv[index + 1]
        for index, value in enumerate(argv[:-1])
        if value == option
    ]
    if len(matches) != 1:
        raise SystemExit(f"IOS_NATIVE_BUILD_OPTION_INVALID:{option}")
    return matches[0]


def assignment_value(name):
    prefix = f"{name}="
    matches = [value[len(prefix):] for value in argv if value.startswith(prefix)]
    if len(matches) != 1:
        raise SystemExit(f"IOS_NATIVE_BUILD_SETTING_INVALID:{name}")
    return matches[0]


document = {
    "schema_version": 1,
    "executable": executable,
    "argv": argv,
    "environment": {
        "NODE_BINARY": node_binary,
        "NODE_ENV": "development",
        "EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY": "remote",
        "EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE": "test",
        "EXPO_PUBLIC_NUTRITION_API_URL": "http://127.0.0.1:8000",
    },
    "workspace": workspace,
    "scheme": scheme,
    "derived_data_path": derived_data,
    "configuration": option_value("-configuration"),
    "sdk": option_value("-sdk"),
    "destination": option_value("-destination"),
    "signing": {
        "CODE_SIGNING_ALLOWED": assignment_value("CODE_SIGNING_ALLOWED"),
        "CODE_SIGNING_REQUIRED": assignment_value("CODE_SIGNING_REQUIRED"),
    },
    "debug": {
        "ENABLE_DEBUG_DYLIB": assignment_value("ENABLE_DEBUG_DYLIB"),
    },
    "link_map": {
        "LD_GENERATE_MAP_FILE": assignment_value("LD_GENERATE_MAP_FILE"),
    },
    "interface_builder": {
        "IBC_EXEC": assignment_value("IBC_EXEC"),
    },
}
if option_value("-workspace") != workspace:
    raise SystemExit("IOS_NATIVE_BUILD_WORKSPACE_MISMATCH")
if option_value("-scheme") != scheme:
    raise SystemExit("IOS_NATIVE_BUILD_SCHEME_MISMATCH")
if option_value("-derivedDataPath") != derived_data:
    raise SystemExit("IOS_NATIVE_BUILD_DERIVED_DATA_MISMATCH")
if document["signing"] != {
    "CODE_SIGNING_ALLOWED": "NO",
    "CODE_SIGNING_REQUIRED": "NO",
}:
    raise SystemExit("IOS_NATIVE_BUILD_SIGNING_OPTIONS_INVALID")
if document["debug"]["ENABLE_DEBUG_DYLIB"] != "NO":
    raise SystemExit("IOS_NATIVE_BUILD_DEBUG_DYLIB_MUST_BE_DISABLED")
if document["link_map"]["LD_GENERATE_MAP_FILE"] != "YES":
    raise SystemExit("IOS_NATIVE_BUILD_LINK_MAP_MUST_BE_ENABLED")
if document["interface_builder"]["IBC_EXEC"] != os.environ.get("IOS_NATIVE_IBTOOL_WRAPPER"):
    raise SystemExit("IOS_NATIVE_BUILD_IBC_EXEC_SETTING_INVALID")
if not argv or argv[-1] != "build":
    raise SystemExit("IOS_NATIVE_BUILD_ACTION_INVALID")

Path(os.environ["IOS_NATIVE_BUILD_INVOCATION_FILE"]).write_text(
    json.dumps(document, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(
    "NODE_BINARY="
    + shlex.quote(node_binary)
    + " "
    + shlex.join([executable, *argv])
)
PY
  )"
  then
    echo "IOS_NATIVE_BUILD_INVOCATION_CAPTURE_FAILED" >&2
    return 1
  fi

  IOS_NATIVE_BUILD_COMMAND="$build_command"
  IOS_NATIVE_BUILD_WORKSPACE="$workspace"
  IOS_NATIVE_BUILD_DERIVED_DATA="$derived_data"
  IOS_NATIVE_SCHEME="$scheme"
  export IOS_NATIVE_BUILD_COMMAND
  export IOS_NATIVE_BUILD_WORKSPACE
  export IOS_NATIVE_BUILD_DERIVED_DATA
  export IOS_NATIVE_BUILD_INVOCATION_FILE="$build_invocation_file"
  export IOS_NATIVE_SCHEME
}

capture_candidate_build_evidence() {
  local target_support="$mobile/ios/Pods/Target Support Files/NutritionOcr"
  local app_support="$mobile/ios/Pods/Target Support Files/Pods-$scheme"
  local pod_project="$mobile/ios/Pods/Pods.xcodeproj/project.pbxproj"
  local products_root="$derived_data/Build/Products/Debug-iphonesimulator"
  local intermediates_root="$derived_data/Build/Intermediates.noindex"
  local provider_file
  local app_product
  local candidate_link_map
  local scheme_without_spaces
  local -a candidate_link_maps
  candidate_link_maps=()

  scheme_without_spaces="${scheme// /}"
  provider_file=""
  if test -d "$mobile/ios"
  then
    provider_file="$(
      find "$mobile/ios" \
        -type f \
        -name 'ExpoModulesProvider.swift' \
        -print |
        sed -n '1p'
    )"
  fi
  app_product=""
  if test -d "$products_root"
  then
    app_product="$(
      find "$products_root" \
        -type f \
        -path "*${scheme_without_spaces}.app/${scheme_without_spaces}" \
        -print |
        sed -n '1p'
    )"
  fi
  if test -d "$intermediates_root"
  then
    while IFS= read -r -d '' candidate_link_map
    do
      candidate_link_maps+=("$candidate_link_map")
    done < <(
      find "$intermediates_root" \
        -type f \
        -path "*${scheme_without_spaces}.build*" \
        -name '*LinkMap*.txt' \
        -print0
    )
  fi

  if ! "$native_lifecycle_python" - \
    "$evidence_dir" \
    "$app_product" \
    "$provider_file" \
    "$pod_project" \
    "$target_support" \
    "$app_support" \
    "${candidate_link_maps[@]-}" <<'PY'
import hashlib
import json
import shutil
import sys
from pathlib import Path


evidence_root = Path(sys.argv[1])
app_product, provider_file, pod_project, target_support, app_support = sys.argv[2:7]
link_map_sources = sorted(Path(value) for value in sys.argv[7:])
scheme_without_spaces = Path(app_product).name if app_product else ""
candidate_root = evidence_root / "candidate-native-evidence"
maps_root = candidate_root / "link-maps"
products_root = candidate_root / "linked-products"
app_root = candidate_root / "final-application"
source_root = evidence_root / "nutrition-ocr-source-evidence"
maps_root.mkdir(parents=True, exist_ok=True)
products_root.mkdir(parents=True, exist_ok=True)
app_root.mkdir(parents=True, exist_ok=True)
source_root.mkdir(parents=True, exist_ok=True)
errors = []
expected_app = Path(app_product).resolve() if app_product else None
intermediates_root = None
if app_product:
    derived_root = Path(app_product).parents[4]
    intermediates_root = (derived_root / "Build" / "Intermediates.noindex").resolve()
expected_normal_root = (
    intermediates_root
    / f"{scheme_without_spaces}.build"
    / "Debug-iphonesimulator"
    / f"{scheme_without_spaces}.build"
    / "Objects-normal"
    if intermediates_root
    else None
)


def digest(path):
    item = Path(path)
    checksum = hashlib.sha256()
    with item.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return {
        "path": str(item),
        "size_bytes": item.stat().st_size,
        "sha256": checksum.hexdigest(),
    }


def retain_file(source, destination):
    if not source:
        return None
    source_path = Path(source)
    if not source_path.is_file():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source_path, destination)
    except OSError as error:
        errors.append(f"copy failed for {source_path}: {error}")
        return None
    return {
        "source_path": str(source_path),
        "source_realpath": str(source_path.resolve()),
        "retained_path": str(destination),
        "retained": digest(destination),
    }


def retain_tree(source, destination):
    if not source or not Path(source).is_dir():
        return None
    try:
        shutil.copytree(source, destination, dirs_exist_ok=True)
    except OSError as error:
        errors.append(f"tree copy failed for {source}: {error}")
        return None
    entries = []
    for item in sorted(Path(destination).rglob("*")):
        if item.is_file():
            entries.append({
                "path": item.relative_to(destination).as_posix(),
                "sha256": digest(item)["sha256"],
            })
    canonical = json.dumps(
        entries,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "source_path": str(Path(source)),
        "retained_path": str(destination),
        "files": entries,
        "sha256": hashlib.sha256(canonical).hexdigest(),
    }


provider = retain_file(
    provider_file,
    evidence_root / "nutrition-ocr-provider-registration.swift",
)
pod_project_copy = retain_file(
    pod_project,
    source_root / "Pods.xcodeproj-project.pbxproj",
)
target_support_copy = retain_tree(
    target_support,
    source_root / "NutritionOcr-target-support",
)
app_support_copy = retain_tree(
    app_support,
    source_root / "Pods-target-support",
)
autolinking_copy = retain_file(
    evidence_root / "autolinking.json",
    source_root / "autolinking.json",
)
final_application = retain_file(
    app_product,
    app_root / "NutritionApp",
)
link_maps = []
for index, source in enumerate(link_map_sources, start=1):
    retained_map = retain_file(
        str(source),
        maps_root / f"{index:03d}-{source.name}",
    )
    if retained_map is None:
        continue
    lines = Path(retained_map["retained_path"]).read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()
    path_line = next(
        (line for line in lines if line.startswith("# Path:")),
        None,
    )
    linked_product = path_line.partition(":")[2].strip() if path_line else ""
    product_candidate = "foreign_product"
    product_architecture = None
    retained_product = None
    if linked_product and expected_app and Path(linked_product).resolve() == expected_app:
        product_candidate = "direct_final_application"
        retained_product = retain_file(
            linked_product,
            products_root / f"{index:03d}-{Path(linked_product).name}",
        )
    elif linked_product and expected_normal_root:
        try:
            relative = Path(linked_product).resolve().relative_to(
                expected_normal_root.resolve()
            )
        except ValueError:
            relative = None
        if (
            relative
            and len(relative.parts) == 3
            and relative.parts[1] == "Binary"
            and relative.parts[2] == scheme_without_spaces
        ):
            product_candidate = "thin_app_target_output"
            product_architecture = relative.parts[0]
            retained_product = retain_file(
                linked_product,
                products_root / f"{index:03d}-{Path(linked_product).name}",
            )
    link_maps.append({
        "index": index,
        "source_path": str(source),
        "retained_map": retained_map,
        "path_line": path_line,
        "linked_product_source_path": linked_product or None,
        "linked_product_candidate": product_candidate,
        "linked_product_architecture": product_architecture,
        "retained_linked_product": retained_product,
    })

document = {
    "schema_version": 1,
    "status": "PARTIAL" if errors else "CAPTURED",
    "final_application": final_application,
    "provider_registration_file": provider,
    "generated_source_evidence": {
        "pod_project": pod_project_copy,
        "nutrition_ocr_target_support": target_support_copy,
        "application_target_support": app_support_copy,
        "autolinking": autolinking_copy,
    },
    "candidate_link_maps": link_maps,
    "errors": errors,
}
(evidence_root / "candidate-build-evidence.json").write_text(
    json.dumps(document, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
if errors:
    raise SystemExit("IOS_NATIVE_CANDIDATE_EVIDENCE_RETENTION_FAILED")
PY
  then
    evidence_retention_failure=1
    echo "IOS_NATIVE_CANDIDATE_EVIDENCE_RETENTION_FAILED" >&2
    return 1
  fi
}

module_evidence_stage() {
  local pod_project="$mobile/ios/Pods/Pods.xcodeproj/project.pbxproj"
  local target_support="$mobile/ios/Pods/Target Support Files/NutritionOcr"
  local app_support="$mobile/ios/Pods/Target Support Files/Pods-$scheme"
  local provider_file
  local source_evidence_dir="$evidence_dir/nutrition-ocr-source-evidence"
  local products_root="$derived_data/Build/Products/Debug-iphonesimulator"
  local intermediates_root="$derived_data/Build/Intermediates.noindex"
  local module_archive
  local module_swiftmodule
  local module_object
  local app_link_map
  local app_product
  local scheme_without_spaces

  scheme_without_spaces="${scheme// /}"
  test -f "$pod_project"
  test -d "$target_support"
  test -d "$app_support"

  for source in NutritionOcrModule.swift NutritionOcrGeometry.swift NutritionImageQuality.swift
  do
    if ! grep -R -Fq "$source" "$pod_project" "$target_support"
    then
      echo "IOS_NATIVE_MODULE_SOURCE_MEMBERSHIP_MISSING:$source" >&2
      return 1
    fi
  done

  provider_file="$(
    find "$mobile/ios" \
      -type f \
      -name 'ExpoModulesProvider.swift' \
      -print |
      sed -n '1p'
  )"
  if test -z "$provider_file" ||
    ! "$native_lifecycle_python" - "$provider_file" <<'PY'
import re
import sys
from pathlib import Path


source = Path(sys.argv[1]).read_text(encoding="utf-8")
provider_class = re.search(
    r"\bclass\s+ExpoModulesProvider(?=\s|:|\{)",
    source,
)
module_import = re.search(
    r"^[ \t]*(?:internal[ \t]+)?import[ \t]+NutritionOcr(?:[ \t]|$)",
    source,
    re.MULTILINE,
)
module_method = re.search(
    r"\bgetModuleClasses\s*\([^)]*\)[^{]*\{(?P<body>.*?)(?:\n[ \t]*\})",
    source,
    re.DOTALL,
)
module_tuple = module_method and re.search(
    r"\(\s*module\s*:\s*NutritionOcrModule\.self\s*,\s*name\s*:\s*nil\s*\)",
    module_method.group("body"),
    re.DOTALL,
)
if not (provider_class and module_import and module_tuple):
    raise SystemExit(1)
PY
  then
    echo "IOS_NATIVE_MODULE_PROVIDER_REGISTRATION_MISSING" >&2
    return 1
  fi

  module_archive="$(
    find "$products_root/NutritionOcr" \
      -type f \
      -name 'libNutritionOcr.a' \
      -print |
      sed -n '1p'
  )"
  module_swiftmodule="$(
    find "$products_root" \
      -type f \
      -path '*NutritionOcr*.swiftmodule*' \
      -print |
      sed -n '1p'
  )"
  module_object="$(
    find "$intermediates_root" \
      -type f \
      -path '*NutritionOcr.build*' \
      \( -name '*NutritionOcr*.o' -o -name 'NutritionOcr.LinkFileList' \) \
      -print |
      sed -n '1p'
  )"
  app_product="$(
    find "$products_root" \
      -type f \
      -path "*${scheme_without_spaces}.app/${scheme_without_spaces}" \
      -print |
      sed -n '1p'
  )"

  test -n "$module_archive"
  test -n "$module_swiftmodule"
  test -n "$module_object"
  test -n "$app_product"

  if ! app_link_map="$("$native_lifecycle_python" - \
    "$candidate_build_evidence" \
    "$app_product" \
    "$intermediates_root" \
    "$scheme_without_spaces" \
    "$evidence_dir/application-link-proof" <<'PY'
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


inventory_path = Path(sys.argv[1])
expected_app = Path(sys.argv[2]).resolve()
intermediates_root = Path(sys.argv[3]).resolve()
scheme = sys.argv[4]
proof_root = Path(sys.argv[5])
proof_root.mkdir(parents=True, exist_ok=True)
document = json.loads(inventory_path.read_text(encoding="utf-8"))
normal_root = (
    intermediates_root
    / f"{scheme}.build"
    / "Debug-iphonesimulator"
    / f"{scheme}.build"
    / "Objects-normal"
).resolve()
final_record = document.get("final_application")
final_binary = (
    Path(final_record["retained_path"])
    if final_record and final_record.get("retained_path")
    else None
)
errors = []
proof_maps = []
accepted_maps = []
architectures = []
lipo_binary = None
lipo_lookup_result = None
lipo_arch_result = None


def file_sha(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def object_lines(lines):
    try:
        start = lines.index("# Object files:") + 1
    except ValueError:
        return []
    result = []
    for line in lines[start:]:
        if line.startswith("# "):
            break
        result.append(line)
    return result


if not final_record or not final_binary or not final_binary.is_file():
    errors.append("IOS_NATIVE_APPLICATION_LINK_FINAL_APP_BINARY_MISSING")
elif os.path.realpath(final_record["source_path"]) != str(expected_app):
    errors.append("IOS_NATIVE_APPLICATION_LINK_FINAL_APP_PATH_MISMATCH")
elif file_sha(final_binary) != final_record["retained"]["sha256"]:
    errors.append("IOS_NATIVE_APPLICATION_LINK_FINAL_APP_DIGEST_MISMATCH")

for candidate in document.get("candidate_link_maps", []):
    retained_map = candidate.get("retained_map") or {}
    map_path = Path(retained_map["retained_path"])
    entry = {
        "source_path": candidate.get("source_path"),
        "retained_map": retained_map,
        "path_line": candidate.get("path_line"),
        "retained_product_candidate": candidate.get("linked_product_candidate"),
        "classification": "unclassified",
        "status": "FAILURE",
        "object_table_entry_count": None,
        "nutrition_ocr_objects": [],
    }
    proof_maps.append(entry)
    if not map_path.is_file():
        errors.append("IOS_NATIVE_APPLICATION_LINK_RETAINED_MAP_MISSING")
        entry["reason"] = "retained link map is missing"
        continue
    if file_sha(map_path) != retained_map.get("retained", {}).get("sha256"):
        errors.append("IOS_NATIVE_APPLICATION_LINK_RETAINED_MAP_DIGEST_MISMATCH")
        entry["reason"] = "retained link map digest changed"
        continue

    lines = map_path.read_text(encoding="utf-8", errors="replace").splitlines()
    object_table = object_lines(lines)
    entry["object_table_entry_count"] = len(object_table)
    entry["nutrition_ocr_objects"] = [
        line
        for line in object_table
        if "NutritionOcr" in line
        and re.search(r"(?:\.o(?:$|[)\] \t])|\.a(?:\[|\())", line)
    ]
    path_line = next(
        (line for line in lines if line.startswith("# Path:")),
        None,
    )
    entry["path_line"] = path_line
    if path_line is None:
        entry["reason"] = "link map has no # Path entry"
        entry["status"] = "IGNORED_NO_PRODUCT_PATH"
        continue
    linked_product = Path(path_line.partition(":")[2].strip()).resolve()
    entry["linked_product_source_path"] = str(linked_product)
    linked_record = candidate.get("retained_linked_product")
    linked_binary = (
        Path(linked_record["retained_path"])
        if linked_record and linked_record.get("retained_path")
        else None
    )
    if linked_binary and linked_binary.is_file():
        entry["linked_product"] = {
            "source_path": linked_record["source_realpath"],
            "retained_path": str(linked_binary),
            "sha256": file_sha(linked_binary),
        }

    if linked_product == expected_app:
        entry["classification"] = "direct_final_application"
        if candidate.get("linked_product_candidate") != "direct_final_application":
            entry["reason"] = "captured product was not classified as the final app executable"
            errors.append("IOS_NATIVE_APPLICATION_LINK_PRODUCT_CAPTURE_MISMATCH")
            continue
        if (
            not linked_binary
            or not linked_binary.is_file()
            or not final_binary
            or not final_binary.is_file()
        ):
            entry["reason"] = "direct final application binary was not retained"
            errors.append("IOS_NATIVE_APPLICATION_LINK_FINAL_APP_BINARY_MISSING")
            continue
        if file_sha(linked_binary) != file_sha(final_binary):
            entry["reason"] = "link-map target differs from retained final application"
            errors.append("IOS_NATIVE_APPLICATION_LINK_FINAL_APP_DIGEST_MISMATCH")
            continue
        entry["status"] = "PASS"
    else:
        try:
            relative = linked_product.relative_to(normal_root)
        except ValueError:
            entry["classification"] = "foreign_product"
            entry["status"] = "IGNORED_FOREIGN_PRODUCT"
            entry["reason"] = "link-map product is outside the app target architecture output"
            continue
        if (
            len(relative.parts) != 3
            or relative.parts[1] != "Binary"
            or relative.parts[2] != scheme
        ):
            entry["classification"] = "unrecognized_target_output"
            entry["reason"] = "link-map product does not match Objects-normal/<arch>/Binary/<app>"
            errors.append("IOS_NATIVE_APPLICATION_LINK_MAP_PRODUCT_TOPOLOGY_INVALID")
            continue
        architecture = relative.parts[0]
        entry["classification"] = "thin_application_architecture"
        entry["architecture"] = architecture
        if (
            candidate.get("linked_product_candidate") != "thin_app_target_output"
            or candidate.get("linked_product_architecture") != architecture
        ):
            entry["reason"] = "captured product does not match the authenticated thin target path"
            errors.append("IOS_NATIVE_APPLICATION_LINK_PRODUCT_CAPTURE_MISMATCH")
            continue
        if not lipo_binary:
            try:
                lipo_lookup_result = subprocess.run(
                    ["xcrun", "-f", "lipo"],
                    capture_output=True,
                    text=True,
                )
                if lipo_lookup_result.returncode == 0:
                    lipo_binary = lipo_lookup_result.stdout.strip()
                if not lipo_binary:
                    raise RuntimeError("xcrun returned an empty lipo path")
            except (OSError, RuntimeError) as error:
                entry["reason"] = f"lipo is unavailable: {error}"
                errors.append(
                    f"IOS_NATIVE_APPLICATION_LINK_LIPO_UNAVAILABLE:{error}"
                )
                continue
            if lipo_lookup_result.returncode != 0:
                entry["reason"] = "xcrun could not locate lipo"
                errors.append("IOS_NATIVE_APPLICATION_LINK_LIPO_UNAVAILABLE")
                continue
        if lipo_arch_result is None and final_binary and final_binary.is_file():
            lipo_arch_result = subprocess.run(
                [lipo_binary, "-archs", str(final_binary)],
                capture_output=True,
                text=True,
            )
            if lipo_arch_result.returncode == 0:
                architectures = lipo_arch_result.stdout.strip().split()
            else:
                errors.append("IOS_NATIVE_APPLICATION_LINK_LIPO_ARCHS_FAILED")
        if architecture not in architectures:
            entry["reason"] = "thin architecture is absent from the final application"
            errors.append(
                f"IOS_NATIVE_APPLICATION_LINK_MAP_ARCHITECTURE_NOT_IN_FINAL_APP:{architecture}"
            )
            continue
        if not linked_binary or not linked_binary.is_file():
            entry["reason"] = "thin linker output was not retained"
            errors.append("IOS_NATIVE_APPLICATION_LINK_MAP_THIN_PRODUCT_MISSING")
            continue

        extracted_slice = proof_root / "slices" / (
            f"{candidate['index']:03d}-{architecture}-{scheme}"
        )
        extracted_slice.parent.mkdir(parents=True, exist_ok=True)
        extract_command = [
            lipo_binary,
            "-thin",
            architecture,
            str(final_binary),
            "-output",
            str(extracted_slice),
        ]
        extracted = subprocess.run(
            extract_command,
            capture_output=True,
            text=True,
        )
        entry["slice_extraction"] = {
            "command": extract_command,
            "exit_code": extracted.returncode,
            "stdout": extracted.stdout,
            "stderr": extracted.stderr,
        }
        if extracted.returncode != 0 or not extracted_slice.is_file():
            entry["reason"] = "lipo could not extract the final application architecture"
            errors.append(
                f"IOS_NATIVE_APPLICATION_LINK_MAP_THIN_SLICE_EXTRACTION_FAILED:{architecture}"
            )
            continue
        entry["slice_extraction"]["retained_slice"] = str(extracted_slice)
        entry["slice_extraction"]["sha256"] = file_sha(extracted_slice)
        entry["linked_product"]["sha256"] = file_sha(linked_binary)
        compare_command = ["cmp", "-s", str(linked_binary), str(extracted_slice)]
        comparison = subprocess.run(
            compare_command,
            capture_output=True,
            text=True,
        )
        entry["slice_comparison"] = {
            "command": compare_command,
            "exit_code": comparison.returncode,
            "stdout": comparison.stdout,
            "stderr": comparison.stderr,
            "byte_identical": comparison.returncode == 0,
        }
        if comparison.returncode != 0:
            entry["reason"] = "thin linker output differs from the final app architecture slice"
            errors.append(
                f"IOS_NATIVE_APPLICATION_LINK_MAP_THIN_SLICE_MISMATCH:{architecture}"
            )
            continue
        entry["status"] = "PASS"

    if entry["status"] == "PASS":
        if not entry["nutrition_ocr_objects"]:
            entry["status"] = "FAILURE"
            entry["reason"] = "final-app link map has no NutritionOcr object or archive member"
            errors.append("IOS_NATIVE_APPLICATION_LINK_MISSING_NUTRITION_OCR")
        else:
            accepted_maps.append(str(map_path))

if not accepted_maps and not errors:
    errors.append("IOS_NATIVE_APPLICATION_LINK_MAP_NOT_FINAL_APP")
elif not any(
    entry["status"] == "PASS" and entry["nutrition_ocr_objects"]
    for entry in proof_maps
):
    if "IOS_NATIVE_APPLICATION_LINK_MISSING_NUTRITION_OCR" not in errors:
        errors.append("IOS_NATIVE_APPLICATION_LINK_MISSING_NUTRITION_OCR")

proof = {
    "schema_version": 1,
    "status": "PASS" if not errors else "FAILURE",
    "final_application": final_record,
    "expected_final_application_path": str(expected_app),
    "expected_architecture_output_root": str(normal_root),
    "lipo": {
        "executable": lipo_binary,
        "lookup_command": ["xcrun", "-f", "lipo"] if lipo_lookup_result else None,
        "lookup_exit_code": (
            lipo_lookup_result.returncode if lipo_lookup_result else None
        ),
        "lookup_stdout": lipo_lookup_result.stdout if lipo_lookup_result else None,
        "lookup_stderr": lipo_lookup_result.stderr if lipo_lookup_result else None,
        "archs_command": (
            [lipo_binary, "-archs", str(final_binary)]
            if lipo_binary and final_binary
            else None
        ),
        "archs_exit_code": lipo_arch_result.returncode if lipo_arch_result else None,
        "archs_stdout": lipo_arch_result.stdout if lipo_arch_result else None,
        "archs_stderr": lipo_arch_result.stderr if lipo_arch_result else None,
        "architectures": architectures,
    },
    "candidate_maps": proof_maps,
    "accepted_link_maps": accepted_maps,
    "errors": errors,
}
proof_path = proof_root.parent / "application-link-proof.json"
proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
if errors:
    raise SystemExit(errors[0])
print(accepted_maps[0])
PY
  )"
  then
    return 1
  fi
  {
    grep -R -h -F \
      -e NutritionOcrModule.swift \
      -e NutritionOcrGeometry.swift \
      -e NutritionImageQuality.swift \
      "$pod_project" "$target_support"
    grep -R -h -F NutritionOcr "$app_support"
  } > "$evidence_dir/nutrition-ocr-source-membership.txt"
  {
    grep -F NutritionOcr "$app_link_map"
  } > "$evidence_dir/nutrition-ocr-link-evidence.txt"

  cp "$provider_file" \
    "$evidence_dir/nutrition-ocr-provider-registration.swift"
  cp "$app_link_map" \
    "$evidence_dir/nutrition-ocr-link-map.txt"

  MODULE_EVIDENCE_OUTPUT="$module_evidence" \
  MODULE_EVIDENCE_COMMIT="$commit" \
  MODULE_EVIDENCE_AUTOLINKING="$evidence_dir/autolinking.json" \
  MODULE_EVIDENCE_POD_PROJECT="$pod_project" \
  MODULE_EVIDENCE_TARGET_SUPPORT="$target_support" \
  MODULE_EVIDENCE_APP_SUPPORT="$app_support" \
  MODULE_EVIDENCE_PROVIDER="$provider_file" \
  MODULE_EVIDENCE_RETAINED_SOURCE="$source_evidence_dir" \
  MODULE_EVIDENCE_RETAINED_PROVIDER="$evidence_dir/nutrition-ocr-provider-registration.swift" \
  MODULE_EVIDENCE_RETAINED_LINK_MAP="$evidence_dir/nutrition-ocr-link-map.txt" \
  MODULE_EVIDENCE_RETAINED_LINK_EVIDENCE="$evidence_dir/nutrition-ocr-link-evidence.txt" \
  MODULE_EVIDENCE_CANDIDATE_BUILD="$candidate_build_evidence" \
  MODULE_EVIDENCE_APPLICATION_LINK_PROOF="$application_link_proof" \
  MODULE_EVIDENCE_ARCHIVE="$module_archive" \
  MODULE_EVIDENCE_SWIFTMODULE="$module_swiftmodule" \
  MODULE_EVIDENCE_OBJECT="$module_object" \
  MODULE_EVIDENCE_LINK_MAP="$app_link_map" \
  MODULE_EVIDENCE_APP_PRODUCT="$app_product" \
  "$native_lifecycle_python" - <<'PY'
import hashlib
import json
import os
from pathlib import Path


def digest(path):
    item = Path(path)
    sha = hashlib.sha256()
    with item.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return {
        "path": str(item),
        "size_bytes": item.stat().st_size,
        "sha256": sha.hexdigest(),
    }


def digest_tree(path):
    root = Path(path)
    entries = []
    for item in sorted(root.rglob("*")):
        if item.is_file():
            entries.append({
                "path": item.relative_to(root).as_posix(),
                "sha256": digest(item)["sha256"],
            })
    canonical = json.dumps(
        entries,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "path": str(root),
        "files": entries,
        "sha256": hashlib.sha256(canonical).hexdigest(),
    }


evidence_root = Path(os.environ["MODULE_EVIDENCE_OUTPUT"]).parent
document = {
    "schema_version": 1,
    "status": "PASS",
    "candidate_sha": os.environ["MODULE_EVIDENCE_COMMIT"],
    "provider_registration": {
        "autolinking_json": digest(os.environ["MODULE_EVIDENCE_AUTOLINKING"]),
        "pod_project": digest(os.environ["MODULE_EVIDENCE_POD_PROJECT"]),
        "target_support": digest_tree(os.environ["MODULE_EVIDENCE_TARGET_SUPPORT"]),
        "app_support": digest_tree(os.environ["MODULE_EVIDENCE_APP_SUPPORT"]),
        "generated_provider": digest(os.environ["MODULE_EVIDENCE_PROVIDER"]),
        "provider_class": "ExpoModulesProvider",
        "provider_import": "NutritionOcr",
        "module_class": "NutritionOcrModule",
        "module_tuple": "(module: NutritionOcrModule.self, name: nil)",
    },
    "source_membership": [
        "NutritionOcrModule.swift",
        "NutritionOcrGeometry.swift",
        "NutritionImageQuality.swift",
    ],
    "built_outputs": {
        name: digest(os.environ[key])
        for name, key in (
            ("archive", "MODULE_EVIDENCE_ARCHIVE"),
            ("swiftmodule", "MODULE_EVIDENCE_SWIFTMODULE"),
            ("object_or_link_file_list", "MODULE_EVIDENCE_OBJECT"),
            ("application_link_map", "MODULE_EVIDENCE_LINK_MAP"),
            ("application_product", "MODULE_EVIDENCE_APP_PRODUCT"),
        )
    },
    "application_link_proof": digest(
        os.environ["MODULE_EVIDENCE_APPLICATION_LINK_PROOF"]
    ),
    "evidence_files": [
        {
            "path": "candidate-build-evidence.json",
            "digest": digest(os.environ["MODULE_EVIDENCE_CANDIDATE_BUILD"]),
        },
        {
            "path": "application-link-proof.json",
            "digest": digest(os.environ["MODULE_EVIDENCE_APPLICATION_LINK_PROOF"]),
        },
        {
            "path": "nutrition-ocr-source-membership.txt",
            "sha256": digest(evidence_root / "nutrition-ocr-source-membership.txt")["sha256"],
        },
        {
            "path": "nutrition-ocr-source-evidence",
            "digest": digest_tree(os.environ["MODULE_EVIDENCE_RETAINED_SOURCE"]),
        },
        {
            "path": "nutrition-ocr-provider-registration.swift",
            "digest": digest(os.environ["MODULE_EVIDENCE_RETAINED_PROVIDER"]),
        },
        {
            "path": "nutrition-ocr-link-map.txt",
            "digest": digest(os.environ["MODULE_EVIDENCE_RETAINED_LINK_MAP"]),
        },
        {
            "path": "nutrition-ocr-link-evidence.txt",
            "digest": digest(os.environ["MODULE_EVIDENCE_RETAINED_LINK_EVIDENCE"]),
        },
    ],
}
Path(os.environ["MODULE_EVIDENCE_OUTPUT"]).write_text(
    json.dumps(document, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
}

xcode_build_stage() {
  local workspace
  local scheme
  local project
  local xcodebuild_exit
  local app_binary
  local app_bundle
  local -a build_args

  project="$(sed -n 's/^PROJECT=//p' "$prebuild_paths")"
  workspace="$(sed -n 's/^WORKSPACE=//p' "$prebuild_paths")"
  scheme="$(sed -n 's/^SCHEME=//p' "$prebuild_paths")"
  build_args=(
    -verbose
    -workspace "$workspace"
    -scheme "$scheme"
    -configuration Debug
    -sdk iphonesimulator
    -destination "generic/platform=iOS Simulator"
    -derivedDataPath "$derived_data"
    CODE_SIGNING_ALLOWED=NO
    CODE_SIGNING_REQUIRED=NO
    ENABLE_DEBUG_DYLIB=NO
    LD_GENERATE_MAP_FILE=YES
    "IBC_EXEC=$native_lifecycle_wrapper"
    build
  )

  if ! capture_build_invocation \
    "$xcodebuild_binary" \
    "$workspace" \
    "$scheme" \
    "${build_args[@]}"
  then
    return 1
  fi

  "$xcodebuild_binary" \
    -workspace "$workspace" \
    -list \
    -json \
    > "$evidence_dir/xcode-list.json" \
    2> "$evidence_dir/xcode-list.stderr"

  node - "$evidence_dir/xcode-list.json" "$scheme" <<'NODE'
const fs = require("fs");

const document = JSON.parse(
  fs.readFileSync(
    process.argv[2],
    "utf8"
  )
);

const scheme = process.argv[3];
const schemes =
  document.workspace?.schemes || [];

if (!schemes.includes(scheme)) {
  throw new Error(
    "Generated scheme missing: " + scheme
  );
}
NODE

  if ! ibtool_capability_stage
  then
    return 1
  fi

  if ! record_native_phase xcode-build-started "{\"build_invocation\":$(
    "$native_lifecycle_python" -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$build_invocation_file"
  )}"
  then
    echo "IOS_NATIVE_XCODE_BUILD_PHASE_RECORD_FAILED" >&2
    return 1
  fi

  xcodebuild_exit=0
  NODE_BINARY="$node_binary" \
  NODE_ENV=development \
  EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY=remote \
  EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE=test \
  EXPO_PUBLIC_NUTRITION_API_URL=http://127.0.0.1:8000 \
    "$xcodebuild_binary" \
      "${build_args[@]}" \
      > "$evidence_dir/xcodebuild.log" \
      2>&1 || xcodebuild_exit="$?"

  if ! record_native_phase xcode-build-finished "{\"build_invocation\":$(
    "$native_lifecycle_python" -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$build_invocation_file"
  ),\"xcodebuild_exit\":$xcodebuild_exit}"
  then
    echo "IOS_NATIVE_XCODE_BUILD_FINISH_PHASE_RECORD_FAILED" >&2
    return 1
  fi

  if test "$xcodebuild_exit" -eq 0 && grep -Fq "BUILD SUCCEEDED" "$evidence_dir/xcodebuild.log"
  then
    if ! record_outcome "$application_build_outcome" application_build PASS 0 "xcodebuild exited 0 and emitted BUILD SUCCEEDED"
    then
      return 1
    fi
  elif test "$xcodebuild_exit" -ne 0
  then
    record_outcome "$application_build_outcome" application_build FAILURE "$xcodebuild_exit" "xcodebuild exited nonzero" || true
  else
    record_outcome "$application_build_outcome" application_build FAILURE 1 "xcodebuild success marker missing" || true
  fi

  if ! capture_candidate_build_evidence
  then
    return 1
  fi

  if test "$xcodebuild_exit" -ne 0
  then
    return "$xcodebuild_exit"
  fi

  if ! grep -Fq \
    "BUILD SUCCEEDED" \
    "$evidence_dir/xcodebuild.log"
  then
    echo "IOS_NATIVE_XCODE_BUILD_SUCCEEDED_MARKER_MISSING" >&2
    return 1
  fi

  app_binary="$(
    find "$derived_data/Build/Products/Debug-iphonesimulator" \
      -type f \
      -path "*${scheme// /}.app/${scheme// /}" \
      -print |
      sed -n '1p'
  )"
  if test -z "$app_binary"
  then
    record_outcome "$application_build_outcome" application_build FAILURE 1 "application product binary missing" || true
    echo "IOS_NATIVE_APP_PRODUCT_BINARY_MISSING" >&2
    return 1
  fi
  app_bundle="$(dirname "$app_binary")"
  if ! "$native_lifecycle_python" - \
    "$native_lifecycle_helper" \
    "$native_lifecycle_binding" \
    "$build_invocation_file" \
    "$evidence_dir/xcodebuild.log" \
    "$app_bundle" <<'PY'
import sys
from pathlib import Path

helper = Path(sys.argv[1]).resolve(strict=True)
sys.path.insert(0, str(helper.parent))
import native_process_lifecycle as lifecycle

lifecycle.write_full_build_proof(
    sys.argv[2],
    build_invocation_path=sys.argv[3],
    build_log_path=sys.argv[4],
    app_product_path=sys.argv[5],
)
PY
  then
    record_outcome "$propagation_proof_outcome" propagation_proof FAILURE 1 "required full-build IBC_EXEC proof failed" || true
    echo "IOS_NATIVE_FULL_BUILD_IBC_EXEC_PROOF_FAILED" >&2
    return 1
  fi

  if ! record_outcome "$propagation_proof_outcome" propagation_proof PASS 0 "required full-build IBC_EXEC proof passed"
  then
    return 1
  fi

  module_evidence_stage

}

swift_harnesses_stage() {
  local ios_source="$mobile/modules/nutrition-ocr/ios"
  local ios_tests="$mobile/modules/nutrition-ocr/ios-tests"

  mkdir -p "$harness_bin"

  xcrun swiftc \
    "$ios_source/NutritionOcrGeometry.swift" \
    "$ios_tests/NutritionOcrGeometryTests.swift" \
    -framework ImageIO \
    -o "$harness_bin/geometry" \
    > "$evidence_dir/geometry-compile.log" \
    2>&1

  "$harness_bin/geometry" \
    > "$evidence_dir/geometry-run.log" \
    2>&1

  grep -Fq \
    "NutritionOcrGeometryTests passed" \
    "$evidence_dir/geometry-run.log"

  xcrun swiftc \
    "$ios_source/NutritionImageQuality.swift" \
    "$ios_tests/NutritionImageQualityTests.swift" \
    -framework CoreGraphics \
    -framework ImageIO \
    -framework Vision \
    -o "$harness_bin/image-quality" \
    > "$evidence_dir/image-quality-compile.log" \
    2>&1

  "$harness_bin/image-quality" \
    > "$evidence_dir/image-quality-run.log" \
    2>&1

  grep -Fq \
    "NutritionImageQualityTests passed" \
    "$evidence_dir/image-quality-run.log"

  xcrun swiftc \
    "$ios_source/NutritionOcrGeometry.swift" \
    "$ios_tests/NutritionOcrVisionRuntimeTests.swift" \
    -framework AppKit \
    -framework CoreImage \
    -framework ImageIO \
    -framework UniformTypeIdentifiers \
    -framework Vision \
    -o "$harness_bin/vision-runtime" \
    > "$evidence_dir/vision-runtime-compile.log" \
    2>&1

  "$harness_bin/vision-runtime" \
    > "$evidence_dir/vision-runtime-run.log" \
    2>&1

  grep -Fq \
    "NutritionOcrVisionRuntimeTests passed" \
    "$evidence_dir/vision-runtime-run.log"
}

mobile="$probe_root/apps/mobile"

if ! select_native_python
then
  qualifier_exit_status=2
  exit 2
fi

trap 'on_signal INT 130' INT
trap 'on_signal TERM 143' TERM
trap 'on_exit $?' EXIT

capture_toolchain
stage_exit="$?"
if test "$stage_exit" -ne 0
then
  if test "$signal_status" -ne 0
  then
    qualifier_exit_status="$signal_status"
  else
    qualifier_exit_status="$stage_exit"
  fi
  exit "$qualifier_exit_status"
fi

commit="$(git -C "$repo_root" rev-parse HEAD)"
export IOS_NATIVE_COMMIT="$commit"
export IOS_NATIVE_RUNNER="$runner"
export IOS_NATIVE_QUALIFIER_PID="$$"

if ! setup_native_lifecycle
then
  qualifier_exit_status=1
  exit 1
fi

if ! initialize_native_output_owner
then
  qualifier_exit_status=1
  exit 1
fi

worktree_create_intent="$("$native_lifecycle_python" "$native_output_cleanup" begin-worktree \
  --owner-record "$native_output_owner" \
  --path "$probe_root" \
  --task "$native_output_attempt" \
  --attempt "$native_output_attempt" \
  --definition "$native_lifecycle_binding")"
stage_exit="$?"
if test "$stage_exit" -ne 0
then
  qualifier_exit_status="$stage_exit"
  exit "$qualifier_exit_status"
fi
worktree_create_nonce="$("$native_lifecycle_python" -c 'import json,sys; print(json.load(sys.stdin)["nonce"])' <<< "$worktree_create_intent")"
if test -z "$worktree_create_nonce"
then
  echo "IOS_NATIVE_WORKTREE_CREATION_INTENT_INVALID" >&2
  qualifier_exit_status=1
  exit 1
fi

git -C "$repo_root" worktree add \
  --detach \
  "$probe_root" \
  "$commit" \
  > "$evidence_dir/worktree.log" \
  2>&1
stage_exit="$?"
if test "$stage_exit" -ne 0
then
  if test -e "$probe_root" || test -L "$probe_root"
  then
    worktree_created=1
  else
    "$native_lifecycle_python" "$native_output_cleanup" cancel-worktree \
      --owner-record "$native_output_owner" \
      --path "$probe_root" \
      --nonce "$worktree_create_nonce" \
      --repository "$repo_root" \
      > "$native_lifecycle_dir/worktree-create-cancel.json" 2> "$native_lifecycle_dir/worktree-create-cancel.stderr.log" || true
  fi
  if test "$signal_status" -ne 0
  then
    qualifier_exit_status="$signal_status"
  else
    qualifier_exit_status="$stage_exit"
  fi
  exit "$qualifier_exit_status"
fi
worktree_created=1
if ! "$native_lifecycle_python" "$native_output_cleanup" finish-worktree \
    --owner-record "$native_output_owner" \
    --path "$probe_root" \
    --nonce "$worktree_create_nonce" \
    --repository "$repo_root" \
    --expected-head "$commit" \
    > "$native_lifecycle_dir/worktree-owner.json"
then
  echo "IOS_NATIVE_WORKTREE_RECEIPT_PERSISTENCE_FAILED" >&2
  qualifier_exit_status=1
  exit 1
fi
if ! start_native_output_owner
then
  qualifier_exit_status=1
  exit 1
fi

case "$probe_root" in
  *" "*)
    ;;
  *)
    echo "IOS_NATIVE_SPACE_PATH_NOT_ACTIVE" >&2
    qualifier_exit_status=1
    exit 1
    ;;
esac

run_stage npm_install npm_install_stage
stage_exit="$?"
if test "$stage_exit" -ne 0
then
  qualifier_exit_status="$stage_exit"
  exit "$qualifier_exit_status"
fi
export IOS_NATIVE_EXPO="$(
  cd "$mobile"
  node -p 'require("./node_modules/expo/package.json").version'
)"
export IOS_NATIVE_REACT_NATIVE="$(
  cd "$mobile"
  node -p 'require("./node_modules/react-native/package.json").version'
)"

run_stage prebuild_plugins prebuild_plugins_stage
stage_exit="$?"
if test "$stage_exit" -ne 0
then
  qualifier_exit_status="$stage_exit"
  exit "$qualifier_exit_status"
fi

run_stage autolinking autolinking_stage
stage_exit="$?"
if test "$stage_exit" -ne 0
then
  qualifier_exit_status="$stage_exit"
  exit "$qualifier_exit_status"
fi

run_stage pods pods_stage
stage_exit="$?"
if test "$stage_exit" -ne 0
then
  qualifier_exit_status="$stage_exit"
  exit "$qualifier_exit_status"
fi

run_stage xcode_build xcode_build_stage
stage_exit="$?"
if test "$stage_exit" -ne 0
then
  qualifier_exit_status="$stage_exit"
  exit "$qualifier_exit_status"
fi

run_stage swift_harnesses swift_harnesses_stage
stage_exit="$?"
if test "$stage_exit" -ne 0
then
  qualifier_exit_status="$stage_exit"
  exit "$qualifier_exit_status"
fi

tracked_status="$(
  git -C "$probe_root" status \
    --porcelain=v1 \
    -uno
)"

if test -n "$tracked_status"
then
  printf '%s\n' "$tracked_status" \
    > "$evidence_dir/generated-tracked-status.txt"
  echo "IOS_NATIVE_GENERATED_TRACKED_MUTATION" >&2
  qualifier_exit_status=1
  exit 1
fi

export IOS_NATIVE_EXPO="$(sed -n 's/^expo=//p' "$dependency_versions")"
export IOS_NATIVE_REACT_NATIVE="$(sed -n 's/^react_native=//p' "$dependency_versions")"

exit 0

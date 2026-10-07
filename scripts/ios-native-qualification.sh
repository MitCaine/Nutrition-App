#!/usr/bin/env bash

set -uo pipefail

evidence_dir=""
runner="local"
compilation_mode="clean"
compilation_cache_dir=""

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
    --compilation-cache-dir)
      test "$#" -ge 2
      compilation_cache_dir="$2"
      shift 2
      ;;
    *)
      echo "IOS_NATIVE_ARGUMENT_INVALID:$1" >&2
      exit 2
      ;;
esac
done

case "$compilation_mode" in
  clean|incremental)
    ;;
  *)
    echo "IOS_NATIVE_COMPILATION_MODE_INVALID:$compilation_mode" >&2
    exit 2
    ;;
esac

if test "$compilation_mode" = "incremental" && test -z "$compilation_cache_dir"
then
  echo "IOS_NATIVE_COMPILATION_CACHE_DIR_REQUIRED" >&2
  exit 2
fi

if test "$compilation_mode" = "clean" && test -n "$compilation_cache_dir"
then
  echo "IOS_NATIVE_COMPILATION_CACHE_REQUIRES_INCREMENTAL" >&2
  exit 2
fi

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

if test "$compilation_mode" = "incremental"
then
  case "$compilation_cache_dir" in
    /*) cache_dir_input="$compilation_cache_dir" ;;
    *) cache_dir_input="$(pwd -P)/$compilation_cache_dir" ;;
  esac
  case "$cache_dir_input" in
    "$repo_root"|"$repo_root"/*)
      echo "IOS_NATIVE_COMPILATION_CACHE_MUST_BE_EXTERNAL" >&2
      exit 2
      ;;
  esac
fi

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

if test "$compilation_mode" = "incremental"
then
  mkdir -p "$compilation_cache_dir"
  compilation_cache_dir="$(cd "$compilation_cache_dir" && pwd -P)"
  case "$compilation_cache_dir" in
    "$repo_root"|"$repo_root"/*)
      echo "IOS_NATIVE_COMPILATION_CACHE_MUST_BE_EXTERNAL" >&2
      exit 2
      ;;
  esac
fi

if test "$compilation_mode" = "incremental"
then
  probe_root="$compilation_cache_dir/Nutrition App Native"
  derived_data="$compilation_cache_dir/DerivedData"
  compilation_state="$compilation_cache_dir/compilation-state.json"
else
  probe_root="$evidence_dir/Nutrition App Native"
  derived_data="$evidence_dir/DerivedData"
  compilation_state=""
fi
harness_bin="$evidence_dir/harness-bin"
manifest="$evidence_dir/manifest.json"
timings_file="$evidence_dir/stages.jsonl"
prebuild_paths="$evidence_dir/prebuild-paths.env"
dependency_versions="$evidence_dir/dependency-versions.env"
compilation_identity="$evidence_dir/compilation-identity.json"
compilation_restore="$evidence_dir/compilation-restore.json"
compilation_save="$evidence_dir/compilation-save.json"
compilation_discard="$evidence_dir/compilation-discard.json"
module_evidence="$evidence_dir/module-evidence.json"
incremental_build_started_marker="$evidence_dir/incremental-build-started"
incremental_cache_committed_marker="$evidence_dir/incremental-cache-committed"
incremental_cache_discard_attempted_marker="$evidence_dir/incremental-cache-discard-attempted"
incremental_helper="$repo_root/scripts/lib/ios_native_incremental.py"

export IOS_NATIVE_COMPILATION_MODE="$compilation_mode"
export IOS_NATIVE_COMPILATION_CACHE_DIR="$compilation_cache_dir"

if test -e "$probe_root"
then
  echo "IOS_NATIVE_PROBE_ALREADY_EXISTS" >&2
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

  (
    set -e
    "$function_name"
  )
  exit_code="$?"

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

  if test "$exit_code" -eq 0
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
  return "$exit_code"
}

cleanup_stage() {
  local cleanup_exit=0

  if test "$worktree_created" -eq 1 &&
    git -C "$repo_root" worktree list --porcelain |
      grep -Fqx "worktree $probe_root"
  then
    if ! git -C "$repo_root" worktree remove \
      --force \
      "$probe_root" \
      > /dev/null \
      2> "$evidence_dir/worktree-cleanup.stderr"
    then
      cleanup_exit=1
    fi
  fi

  if test "$worktree_created" -eq 1
  then
    if ! git -C "$repo_root" worktree prune \
      > /dev/null \
      2> "$evidence_dir/worktree-prune.stderr"
    then
      cleanup_exit=1
    fi
  fi

  if test "$compilation_mode" = "clean"
  then
    if ! rm -rf "$derived_data"
    then
      cleanup_exit=1
    fi
  elif test "$qualifier_exit_status" -ne 0 &&
    test -e "$incremental_build_started_marker" &&
    test ! -e "$incremental_cache_committed_marker"
  then
    if ! discard_incremental_cache
    then
      cleanup_exit=1
    fi
  fi

  if ! rm -rf "$harness_bin"
  then
    cleanup_exit=1
  fi

  if test -e "$probe_root"
  then
    printf '%s\n' "probe root remains after cleanup" \
      > "$evidence_dir/generated-cleanup-failure.txt"
    cleanup_exit=1
  fi

  return "$cleanup_exit"
}

discard_incremental_cache() {
  if test "$compilation_mode" != "incremental" ||
    test ! -e "$incremental_build_started_marker" ||
    test -e "$incremental_cache_discard_attempted_marker"
  then
    return 0
  fi

  if ! : > "$incremental_cache_discard_attempted_marker"
  then
    echo "IOS_NATIVE_INCREMENTAL_DISCARD_MARKER_FAILED" >&2
    return 1
  fi
  if ! python3 \
    "$incremental_helper" \
    discard \
    --state "$compilation_state" \
    --derived-data "$derived_data" \
    --output "$compilation_discard" \
    > "$evidence_dir/compilation-discard.log" \
    2>&1
  then
    echo "IOS_NATIVE_INCREMENTAL_DISCARD_FAILED" >&2
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
  IOS_NATIVE_COMPILATION_CACHE_DIR="$compilation_cache_dir" \
  IOS_NATIVE_COMPILATION_STATE="$compilation_state" \
  IOS_NATIVE_COMPILATION_IDENTITY_FILE="$compilation_identity" \
  IOS_NATIVE_COMPILATION_RESTORE_FILE="$compilation_restore" \
  IOS_NATIVE_COMPILATION_SAVE_FILE="$compilation_save" \
  IOS_NATIVE_COMPILATION_DISCARD_FILE="$compilation_discard" \
  IOS_NATIVE_MODULE_EVIDENCE_FILE="$module_evidence" \
  python3 - "$timings_file" "$manifest" <<'PY'
import json
import os
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
compilation = {
    "mode": text("IOS_NATIVE_COMPILATION_MODE") or "clean",
    "cache_dir": text("IOS_NATIVE_COMPILATION_CACHE_DIR"),
    "state_file": text("IOS_NATIVE_COMPILATION_STATE"),
    "identity_file": text("IOS_NATIVE_COMPILATION_IDENTITY_FILE"),
    "restore": document("IOS_NATIVE_COMPILATION_RESTORE_FILE"),
    "save": document("IOS_NATIVE_COMPILATION_SAVE_FILE"),
    "discard": document("IOS_NATIVE_COMPILATION_DISCARD_FILE"),
}
module_document = document("IOS_NATIVE_MODULE_EVIDENCE_FILE", {})
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
    "generated_scheme": text("IOS_NATIVE_SCHEME"),
    "generated_build_command": text("IOS_NATIVE_BUILD_COMMAND"),
    "prebuild": stage_status["prebuild_plugins"],
    "config_plugins": stage_status["prebuild_plugins"],
    "autolinking": stage_status["autolinking"],
    "pods": stage_status["pods"],
    "simulator_build": stage_status["xcode_build"],
    "nutrition_ocr": {
        "autolinking": stage_status["autolinking"],
        "pod": stage_status["pods"],
        "application_compilation": stage_status["xcode_build"],
    },
    "swift_harnesses": {
        "geometry": stage_status["swift_harnesses"],
        "image_quality": stage_status["swift_harnesses"],
        "vision_runtime": stage_status["swift_harnesses"],
    },
    "space_path_regression": stage_status["prebuild_plugins"],
    "generated_cleanup": stage_status["cleanup"],
    "compilation": compilation,
    "module_evidence": module_document,
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

  if test "$qualifier_exit_status" -eq 0 &&
    test "$cleanup_exit" -ne 0
  then
    qualifier_exit_status="$cleanup_exit"
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

  if test "$compilation_mode" = "incremental"
  then
    if test "$qualifier_exit_status" -eq 0 &&
      test "$cleanup_exit" -eq 0 &&
      test "$evidence_retention_failure" -eq 0 &&
      test -e "$incremental_build_started_marker"
    then
      if ! record_incremental_cache
      then
        qualifier_exit_status=1
      elif ! : > "$incremental_cache_committed_marker"
      then
        echo "IOS_NATIVE_INCREMENTAL_COMMIT_MARKER_FAILED" >&2
        qualifier_exit_status=1
      fi
    fi

    if test "$qualifier_exit_status" -ne 0
    then
      if ! discard_incremental_cache
      then
        evidence_retention_failure=1
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

  if test "$compilation_mode" = "incremental" &&
    test "$qualifier_exit_status" -ne 0
  then
    if ! discard_incremental_cache
    then
      evidence_retention_failure=1
    fi
  fi

  if test "$qualifier_exit_status" -eq 0
  then
    echo "IOS_NATIVE_QUALIFICATION=PASS"
  else
    echo "IOS_NATIVE_QUALIFICATION=FAILURE" >&2
  fi

  exit "$qualifier_exit_status"
}

trap 'on_signal INT 130' INT
trap 'on_signal TERM 143' TERM
trap 'on_exit $?' EXIT

capture_toolchain() {
  local tool
  local xcode_info
  local swift_info
  for tool in node npm python3 pod xcodebuild xcrun ruby
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

  if ! xcode_info="$(xcodebuild -version)" ||
    test -z "$xcode_info"
  then
    echo "IOS_NATIVE_XCODE_VERSION_UNAVAILABLE" >&2
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

  if ! python3 \
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

  (
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

write_clean_compilation_operations() {
  python3 - \
    "$compilation_restore" \
    "$compilation_save" <<'PY'
import json
import sys
from pathlib import Path

document = {
    "operation": "disabled",
    "status": "disabled",
    "reason": "clean compilation mode does not restore or save DerivedData",
}
for argument in sys.argv[1:]:
    Path(argument).write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
PY
}

prepare_incremental_cache() {
  local workspace="$1"
  local scheme="$2"
  local build_command
  local prepare_start
  local prepare_end
  local prepare_elapsed

  build_command="xcodebuild -workspace $workspace -scheme $scheme -configuration Debug -sdk iphonesimulator -destination generic/platform=iOS Simulator -derivedDataPath $derived_data CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO LD_GENERATE_MAP_FILE=YES build"
  if ! prepare_start="$(date +%s)"
  then
    echo "IOS_NATIVE_INCREMENTAL_CACHE_TIMER_UNAVAILABLE" >&2
    return 1
  fi

  python3 \
    "$incremental_helper" \
    identity \
    --repo-root "$repo_root" \
    --mobile "$mobile" \
    --project-root "$probe_root" \
    --derived-data "$derived_data" \
    --candidate "$commit" \
    --build-command "$build_command" \
    --toolchain "macos=$macos_version" \
    --toolchain "architecture=$architecture" \
    --toolchain "xcode=$xcode_version" \
    --toolchain "xcode_build=$xcode_build" \
    --toolchain "iphonesimulator_sdk=$iphonesimulator_sdk" \
    --toolchain "swift=$swift_version" \
    --toolchain "node=$node_version" \
    --toolchain "npm=$npm_version" \
    --toolchain "ruby=$ruby_version" \
    --toolchain "cocoapods=$cocoapods_version" \
    --output "$compilation_identity" \
    > "$evidence_dir/compilation-identity.log" \
    2>&1

  python3 \
    "$incremental_helper" \
    prepare \
    --identity "$compilation_identity" \
    --state "$compilation_state" \
    --derived-data "$derived_data" \
    --output "$compilation_restore" \
    > "$evidence_dir/compilation-restore.log" \
    2>&1

  if ! prepare_end="$(date +%s)"
  then
    echo "IOS_NATIVE_INCREMENTAL_CACHE_TIMER_UNAVAILABLE" >&2
    return 1
  fi
  prepare_elapsed="$((prepare_end - prepare_start))"
  python3 - "$compilation_restore" "$prepare_elapsed" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
document = json.loads(path.read_text(encoding="utf-8"))
document["elapsed_seconds"] = int(sys.argv[2])
path.write_text(
    json.dumps(document, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

  cat "$compilation_restore"
}

record_incremental_cache() {
  local save_start
  local save_end
  local save_elapsed

  if ! save_start="$(date +%s)"
  then
    echo "IOS_NATIVE_INCREMENTAL_CACHE_TIMER_UNAVAILABLE" >&2
    return 1
  fi
  python3 \
    "$incremental_helper" \
    commit \
    --identity "$compilation_identity" \
    --state "$compilation_state" \
    --derived-data "$derived_data" \
    --output "$compilation_save" \
    > "$evidence_dir/compilation-save.log" \
    2>&1
  if ! save_end="$(date +%s)"
  then
    echo "IOS_NATIVE_INCREMENTAL_CACHE_TIMER_UNAVAILABLE" >&2
    return 1
  fi
  save_elapsed="$((save_end - save_start))"
  python3 - "$compilation_save" "$save_elapsed" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
document = json.loads(path.read_text(encoding="utf-8"))
document["elapsed_seconds"] = int(sys.argv[2])
path.write_text(
    json.dumps(document, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
  cat "$compilation_save"
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
    ! grep -Eq \
      'class[[:space:]]+ExpoModulesProvider([[:space:]:{]|$)' \
      "$provider_file" ||
    ! grep -Eq \
      '^[[:space:]]*import[[:space:]]+NutritionOcr([[:space:]]|$)' \
      "$provider_file" ||
    ! grep -Eq 'NutritionOcrModule([.]self)?' "$provider_file"
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
  app_link_map="$(
    find "$intermediates_root" \
      -type f \
      -path "*${scheme_without_spaces}.build*" \
      -name '*LinkMap*.txt' \
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
  test -n "$app_link_map"
  test -n "$app_product"

  if ! grep -Fq "NutritionOcr" "$app_link_map" ||
    ! grep -Fq "libNutritionOcr" "$app_link_map"
  then
    echo "IOS_NATIVE_APPLICATION_LINK_MISSING_NUTRITION_OCR" >&2
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

  mkdir -p "$source_evidence_dir"
  cp "$pod_project" \
    "$source_evidence_dir/Pods.xcodeproj-project.pbxproj"
  cp -R "$target_support" \
    "$source_evidence_dir/NutritionOcr-target-support"
  cp -R "$app_support" \
    "$source_evidence_dir/Pods-target-support"
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
  MODULE_EVIDENCE_ARCHIVE="$module_archive" \
  MODULE_EVIDENCE_SWIFTMODULE="$module_swiftmodule" \
  MODULE_EVIDENCE_OBJECT="$module_object" \
  MODULE_EVIDENCE_LINK_MAP="$app_link_map" \
  MODULE_EVIDENCE_APP_PRODUCT="$app_product" \
  python3 - <<'PY'
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
    "evidence_files": [
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

  project="$(sed -n 's/^PROJECT=//p' "$prebuild_paths")"
  workspace="$(sed -n 's/^WORKSPACE=//p' "$prebuild_paths")"
  scheme="$(sed -n 's/^SCHEME=//p' "$prebuild_paths")"

  if test "$compilation_mode" = "incremental"
  then
    prepare_incremental_cache "$workspace" "$scheme"
  else
    write_clean_compilation_operations
  fi

  xcodebuild \
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

  : > "$incremental_build_started_marker"
  NODE_BINARY="$node_binary" \
    xcodebuild \
      -workspace "$workspace" \
      -scheme "$scheme" \
      -configuration Debug \
      -sdk iphonesimulator \
      -destination \
      "generic/platform=iOS Simulator" \
      -derivedDataPath \
      "$derived_data" \
      CODE_SIGNING_ALLOWED=NO \
      CODE_SIGNING_REQUIRED=NO \
      LD_GENERATE_MAP_FILE=YES \
      build \
      > "$evidence_dir/xcodebuild.log" \
      2>&1

  grep -Fq \
    "BUILD SUCCEEDED" \
    "$evidence_dir/xcodebuild.log"

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

git -C "$repo_root" worktree add \
  --detach \
  "$probe_root" \
  "$commit" \
  > "$evidence_dir/worktree.log" \
  2>&1
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
worktree_created=1

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

scheme="$(sed -n 's/^SCHEME=//p' "$prebuild_paths")"
export IOS_NATIVE_EXPO="$(sed -n 's/^expo=//p' "$dependency_versions")"
export IOS_NATIVE_REACT_NATIVE="$(sed -n 's/^react_native=//p' "$dependency_versions")"
export IOS_NATIVE_SCHEME="$scheme"
export IOS_NATIVE_BUILD_COMMAND="xcodebuild -workspace ios/${scheme}.xcworkspace -scheme ${scheme} -configuration Debug -sdk iphonesimulator -destination generic/platform=iOS Simulator CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO LD_GENERATE_MAP_FILE=YES build"

exit 0

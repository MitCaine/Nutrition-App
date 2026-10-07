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
build_invocation_file="$evidence_dir/build-invocation.json"
module_evidence="$evidence_dir/module-evidence.json"
candidate_build_evidence="$evidence_dir/candidate-build-evidence.json"
application_link_proof="$evidence_dir/application-link-proof.json"
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
  IOS_NATIVE_BUILD_INVOCATION_FILE="$build_invocation_file" \
  IOS_NATIVE_MODULE_EVIDENCE_FILE="$module_evidence" \
  IOS_NATIVE_CANDIDATE_BUILD_EVIDENCE_FILE="$candidate_build_evidence" \
  IOS_NATIVE_APPLICATION_LINK_PROOF_FILE="$application_link_proof" \
  python3 - "$timings_file" "$manifest" <<'PY'
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
build_invocation = document("IOS_NATIVE_BUILD_INVOCATION_FILE")
build_command = None
if build_invocation:
    build_command = (
        "NODE_BINARY="
        + shlex.quote(build_invocation["environment"]["NODE_BINARY"])
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

  if ! xcodebuild_binary="$(command -v xcodebuild)" ||
    test -z "$xcodebuild_binary"
  then
    echo "IOS_NATIVE_XCODEBUILD_BINARY_UNAVAILABLE" >&2
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

  if ! xcode_info="$("$xcodebuild_binary" -version)" ||
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
    python3 - "$executable" "$workspace" "$scheme" "$derived_data" "$node_binary" "$@" <<'PY'
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
    "environment": {"NODE_BINARY": node_binary},
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

prepare_incremental_cache() {
  local workspace="$1"
  local scheme="$2"
  local prepare_start
  local prepare_end
  local prepare_elapsed

  if ! prepare_start="$(date +%s)"
  then
    echo "IOS_NATIVE_INCREMENTAL_CACHE_TIMER_UNAVAILABLE" >&2
    return 1
  fi

  if ! python3 \
    "$incremental_helper" \
    identity \
    --repo-root "$repo_root" \
    --mobile "$mobile" \
    --project-root "$probe_root" \
    --derived-data "$derived_data" \
    --candidate "$commit" \
    --build-invocation "$build_invocation_file" \
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
  then
    echo "IOS_NATIVE_INCREMENTAL_IDENTITY_FAILED" >&2
    return 1
  fi

  if ! python3 \
    "$incremental_helper" \
    prepare \
    --identity "$compilation_identity" \
    --state "$compilation_state" \
    --derived-data "$derived_data" \
    --output "$compilation_restore" \
    > "$evidence_dir/compilation-restore.log" \
    2>&1
  then
    echo "IOS_NATIVE_INCREMENTAL_PREPARE_FAILED" >&2
    return 1
  fi

  if ! prepare_end="$(date +%s)"
  then
    echo "IOS_NATIVE_INCREMENTAL_CACHE_TIMER_UNAVAILABLE" >&2
    return 1
  fi
  prepare_elapsed="$((prepare_end - prepare_start))"
  if ! python3 - "$compilation_restore" "$prepare_elapsed" <<'PY'
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
  then
    echo "IOS_NATIVE_INCREMENTAL_RESTORE_TIMING_WRITE_FAILED" >&2
    return 1
  fi

  if ! cat "$compilation_restore"
  then
    echo "IOS_NATIVE_INCREMENTAL_RESTORE_READ_FAILED" >&2
    return 1
  fi
}

validate_incremental_save() {
  local require_elapsed="$1"

  python3 - \
    "$compilation_identity" \
    "$compilation_restore" \
    "$compilation_save" \
    "$compilation_state" \
    "$derived_data" \
    "$commit" \
    "$require_elapsed" <<'PY'
import json
import sys
from pathlib import Path


identity_path, restore_path, save_path, state_path, derived_data, candidate, require_elapsed = sys.argv[1:]
identity = json.loads(Path(identity_path).read_text(encoding="utf-8"))
restore = json.loads(Path(restore_path).read_text(encoding="utf-8"))
save = json.loads(Path(save_path).read_text(encoding="utf-8"))
state = json.loads(Path(state_path).read_text(encoding="utf-8"))
identity_sha = identity.get("identity_sha256")
expected_derived_data = str(Path(derived_data).resolve())

if identity.get("candidate_sha") != candidate or not identity_sha:
    raise SystemExit("IOS_NATIVE_INCREMENTAL_CURRENT_IDENTITY_INVALID")
if restore.get("operation") != "restore" or restore.get("status") not in {"hit", "miss"}:
    raise SystemExit("IOS_NATIVE_INCREMENTAL_CURRENT_RESTORE_STATUS_INVALID")
if restore.get("identity_sha256") != identity_sha:
    raise SystemExit("IOS_NATIVE_INCREMENTAL_CURRENT_RESTORE_IDENTITY_MISMATCH")
if str(Path(restore.get("derived_data", "")).resolve()) != expected_derived_data:
    raise SystemExit("IOS_NATIVE_INCREMENTAL_CURRENT_RESTORE_PATH_MISMATCH")
if save.get("operation") != "save" or save.get("status") != "saved":
    raise SystemExit("IOS_NATIVE_INCREMENTAL_SAVE_STATUS_INVALID")
if save.get("identity_sha256") != identity_sha:
    raise SystemExit("IOS_NATIVE_INCREMENTAL_SAVE_IDENTITY_MISMATCH")
if str(Path(save.get("derived_data", "")).resolve()) != expected_derived_data:
    raise SystemExit("IOS_NATIVE_INCREMENTAL_SAVE_PATH_MISMATCH")
if state.get("identity_sha256") != identity_sha:
    raise SystemExit("IOS_NATIVE_INCREMENTAL_STATE_IDENTITY_MISMATCH")
if str(Path(state.get("derived_data", "")).resolve()) != expected_derived_data:
    raise SystemExit("IOS_NATIVE_INCREMENTAL_STATE_PATH_MISMATCH")
if state.get("cache_contents") != ["DerivedData only"]:
    raise SystemExit("IOS_NATIVE_INCREMENTAL_STATE_CONTENTS_INVALID")
if require_elapsed == "1" and not isinstance(save.get("elapsed_seconds"), int):
    raise SystemExit("IOS_NATIVE_INCREMENTAL_SAVE_TIMING_MISSING")
PY
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
  if ! python3 \
    "$incremental_helper" \
    commit \
    --identity "$compilation_identity" \
    --state "$compilation_state" \
    --derived-data "$derived_data" \
    --candidate "$commit" \
    --restore "$compilation_restore" \
    --stages "$timings_file" \
    --module-evidence "$module_evidence" \
    --output "$compilation_save" \
    > "$evidence_dir/compilation-save.log" \
    2>&1
  then
    echo "IOS_NATIVE_INCREMENTAL_CACHE_COMMIT_FAILED" >&2
    return 1
  fi
  if ! validate_incremental_save 0
  then
    echo "IOS_NATIVE_INCREMENTAL_CACHE_SAVE_VALIDATION_FAILED" >&2
    return 1
  fi
  if ! save_end="$(date +%s)"
  then
    echo "IOS_NATIVE_INCREMENTAL_CACHE_TIMER_UNAVAILABLE" >&2
    return 1
  fi
  save_elapsed="$((save_end - save_start))"
  if ! python3 - "$compilation_save" "$save_elapsed" <<'PY'
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
  then
    echo "IOS_NATIVE_INCREMENTAL_SAVE_TIMING_WRITE_FAILED" >&2
    return 1
  fi
  if ! validate_incremental_save 1
  then
    echo "IOS_NATIVE_INCREMENTAL_FINAL_SAVE_VALIDATION_FAILED" >&2
    return 1
  fi
  if ! cat "$compilation_save"
  then
    echo "IOS_NATIVE_INCREMENTAL_SAVE_READ_FAILED" >&2
    return 1
  fi
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

  if ! python3 - \
    "$evidence_dir" \
    "$app_product" \
    "$provider_file" \
    "$pod_project" \
    "$target_support" \
    "$app_support" \
    "${candidate_link_maps[@]}" <<'PY'
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
    ! python3 - "$provider_file" <<'PY'
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

  if ! app_link_map="$(python3 - \
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
  local -a build_args

  project="$(sed -n 's/^PROJECT=//p' "$prebuild_paths")"
  workspace="$(sed -n 's/^WORKSPACE=//p' "$prebuild_paths")"
  scheme="$(sed -n 's/^SCHEME=//p' "$prebuild_paths")"
  build_args=(
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

  if test "$compilation_mode" = "incremental"
  then
    prepare_incremental_cache "$workspace" "$scheme"
  else
    write_clean_compilation_operations
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

  : > "$incremental_build_started_marker"
  xcodebuild_exit=0
  NODE_BINARY="$node_binary" \
    "$xcodebuild_binary" \
      "${build_args[@]}" \
      > "$evidence_dir/xcodebuild.log" \
      2>&1 || xcodebuild_exit="$?"

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

export IOS_NATIVE_EXPO="$(sed -n 's/^expo=//p' "$dependency_versions")"
export IOS_NATIVE_REACT_NATIVE="$(sed -n 's/^react_native=//p' "$dependency_versions")"

exit 0

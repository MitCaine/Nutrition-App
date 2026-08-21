#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "$0")/lib/common.sh"

usage() {
    cat <<'USAGE'
Usage: ./scripts/run-review.sh [options]

Options:
  --profile NAME   baseline (default), backend, mobile, repository, cross-cutting
  --label TEXT     Short task/review identifier used in output names
  --no-package     Skip the project snapshot; still create an evidence bundle
  -h, --help       Show this help

The baseline profile runs ordinary backend, mobile, documentation, shell,
Git-whitespace, and repository closeout checks.

PostgreSQL, MinIO, performance, Docker infrastructure, and native iOS
qualification remain explicit opt-in work.
USAGE
}

PROFILE="baseline"
LABEL="review"
INCLUDE_PROJECT=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            [[ $# -ge 2 ]] || die "--profile requires a value."
            PROFILE="$2"
            shift 2
            ;;
        --label)
            [[ $# -ge 2 ]] || die "--label requires a value."
            LABEL="$2"
            shift 2
            ;;
        --no-package)
            INCLUDE_PROJECT=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "Unknown argument: $1"
            ;;
    esac
done

RUN_BACKEND=0
RUN_MOBILE=0
RUN_REPOSITORY=1
RUN_COMPOSE=0

case "$PROFILE" in
    baseline)
        RUN_BACKEND=1
        RUN_MOBILE=1
        ;;
    backend)
        RUN_BACKEND=1
        ;;
    mobile)
        RUN_MOBILE=1
        ;;
    repository)
        ;;
    cross-cutting)
        RUN_BACKEND=1
        RUN_MOBILE=1
        RUN_COMPOSE=1
        ;;
    *)
        die "Unsupported profile '$PROFILE'."
        ;;
esac

banner "Nutrition App Review Runner"
repo_cd

require_command git
require_command python3
require_command zip
require_command unzip
require_command tee
require_command grep
require_command awk

if [[ $RUN_MOBILE -eq 1 ]]; then
    require_command npm
fi

if [[ $RUN_COMPOSE -eq 1 ]]; then
    require_command docker
fi

BACKEND_PYTHON="$REPO_ROOT/apps/backend/.venv/bin/python"

if [[ $RUN_BACKEND -eq 1 && ! -x "$BACKEND_PYTHON" ]]; then
    die "Backend virtual environment not found at apps/backend/.venv."
fi

if [[ $RUN_REPOSITORY -eq 1 ]]; then
    [[ -f "$REPO_ROOT/scripts/validate-docs.py" ]] || \
        die "Missing scripts/validate-docs.py."

    [[ -x "$REPO_ROOT/scripts/session-end.sh" ]] || \
        die "Missing or non-executable scripts/session-end.sh."
fi

if [[ $INCLUDE_PROJECT -eq 1 && ! -x "$REPO_ROOT/scripts/zip-project.sh" ]]; then
    die "Missing or non-executable scripts/zip-project.sh."
fi

SAFE_LABEL="$(
    printf '%s' "$LABEL" \
        | tr '[:upper:]' '[:lower:]' \
        | tr ' ' '-' \
        | tr -cd 'a-z0-9._-'
)"

[[ -n "$SAFE_LABEL" ]] || SAFE_LABEL="review"

STAMP="$(date +"%Y%m%d-%H%M%S")"
RUN_ID="${STAMP}-${SAFE_LABEL}"

# Keep generated evidence outside the repository so review execution does not
# dirty the working tree or enter the project source archive.
OUTPUT_ROOT="${NUTRITION_REVIEW_OUTPUT_DIR:-$REPO_ROOT/../nutrition-app-review-output}"
RUN_DIR="$OUTPUT_ROOT/runs/$RUN_ID"
LOG_DIR="$RUN_DIR/logs"
FAILURE_DIR="$RUN_DIR/failures"
WARNING_DIR="$RUN_DIR/warnings"

RESULTS_TSV="$RUN_DIR/results.tsv"
RESULTS_JSON="$RUN_DIR/results.json"
SUMMARY_MD="$RUN_DIR/summary.md"
ENVIRONMENT_TXT="$RUN_DIR/environment.txt"
GIT_STATUS_TXT="$RUN_DIR/git-status.txt"
GIT_DIFF_PATCH="$RUN_DIR/git-diff.patch"
GIT_STATUS_AFTER_TXT="$RUN_DIR/git-status-after.txt"
GIT_DIFF_AFTER_PATCH="$RUN_DIR/git-diff-after.patch"
REPO_FINGERPRINT_BEFORE_TXT="$RUN_DIR/repository-fingerprint-before.txt"
REPO_FINGERPRINT_AFTER_TXT="$RUN_DIR/repository-fingerprint-after.txt"
LAUNCHER_PATH="$REPO_ROOT/Run Nutrition Review.command"

SOURCE_ZIP="$RUN_DIR/project-review.zip"
FINAL_ZIP="$OUTPUT_ROOT/nutrition-app-${SAFE_LABEL}-${STAMP}.zip"
BUNDLE_STAGE="$(make_temp_dir)"

ensure_directory "$LOG_DIR"
ensure_directory "$FAILURE_DIR"
ensure_directory "$WARNING_DIR"
ensure_directory "$OUTPUT_ROOT"

: > "$RESULTS_TSV"

cleanup() {
    rm -rf "$BUNDLE_STAGE"
}
trap cleanup EXIT

repository_fingerprint() {
    python3 - "$REPO_ROOT" <<'PY'
from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
digest = hashlib.sha256()


def git_bytes(*args: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(root), *args],
        stderr=subprocess.STDOUT,
    )


for label, args in (
    ("head", ("rev-parse", "HEAD")),
    ("branch", ("rev-parse", "--abbrev-ref", "HEAD")),
    ("index", ("write-tree",)),
    (
        "status",
        (
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ),
    ),
):
    digest.update(label.encode("utf-8") + b"\0")
    digest.update(git_bytes(*args))
    digest.update(b"\0")

paths = {
    raw
    for raw in git_bytes(
        "ls-files",
        "-c",
        "-o",
        "--exclude-standard",
        "-z",
    ).split(b"\0")
    if raw
}

for raw_path in sorted(paths):
    relative = os.fsdecode(raw_path)
    path = root / relative

    digest.update(b"path\0" + raw_path + b"\0")

    try:
        metadata = path.lstat()
    except FileNotFoundError:
        digest.update(b"missing\0")
        continue

    digest.update(
        f"{stat.S_IFMT(metadata.st_mode):o}:"
        f"{metadata.st_mode & 0o7777:o}:"
        f"{metadata.st_size}".encode("ascii")
        + b"\0"
    )

    if path.is_symlink():
        digest.update(b"symlink\0")
        digest.update(os.fsencode(os.readlink(path)))
    elif path.is_file():
        digest.update(b"file\0")

        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    elif path.is_dir():
        digest.update(b"directory\0")
    else:
        digest.update(b"other\0")

    digest.update(b"\0")

print(digest.hexdigest())
PY
}

STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
BASE_COMMIT="$(git rev-parse HEAD)"
BRANCH="$(git branch --show-current)"
[[ -n "$BRANCH" ]] || BRANCH="(detached HEAD)"

git status --short > "$GIT_STATUS_TXT"
git diff --binary HEAD > "$GIT_DIFF_PATCH"

REPO_FINGERPRINT_BEFORE="$(repository_fingerprint)"
printf '%s\n' "$REPO_FINGERPRINT_BEFORE" \
    > "$REPO_FINGERPRINT_BEFORE_TXT"

WORKTREE_DIRTY=false
[[ -s "$GIT_STATUS_TXT" ]] && WORKTREE_DIRTY=true

{
    echo "Run ID: $RUN_ID"
    echo "Started (UTC): $STARTED_AT"
    echo "Repository: $REPO_ROOT"
    echo "Profile: $PROFILE"
    echo "Label: $LABEL"
    echo "Commit: $BASE_COMMIT"
    echo "Branch: $BRANCH"
    echo "Working tree dirty: $WORKTREE_DIRTY"
    echo "Controller: ${NUTRITION_REVIEW_CONTROLLER:-not-recorded}"
    echo "Executor: ${NUTRITION_REVIEW_EXECUTOR:-not-recorded}"
    echo "Verified model: ${NUTRITION_REVIEW_MODEL:-not-recorded}"
    echo "Task capsule: ${NUTRITION_REVIEW_TASK_CAPSULE:-not-recorded}"
    echo "Specification: ${NUTRITION_REVIEW_SPECIFICATION:-not-recorded}"
    echo
    echo "System"
    echo "------"
    uname -a

    if command -v sw_vers >/dev/null 2>&1; then
        sw_vers
    fi

    echo
    echo "Tool versions"
    echo "-------------"
    git --version
    python3 --version 2>&1

    if [[ -x "$BACKEND_PYTHON" ]]; then
        "$BACKEND_PYTHON" --version 2>&1
    fi

    if command -v node >/dev/null 2>&1; then
        node --version
    fi

    if command -v npm >/dev/null 2>&1; then
        npm --version
    fi

    if command -v docker >/dev/null 2>&1; then
        docker --version
        docker compose version 2>/dev/null || true
    fi
} > "$ENVIRONMENT_TXT"

TOTAL=0
FAILED=0
CRITICAL_FAILED=0
ADVISORY_FAILED=0
WARNING_TOTAL=0

run_step() {
    local slug="$1"
    local display_name="$2"
    local severity="$3"
    local command_text="$4"
    shift 4

    local log_file="$LOG_DIR/${slug}.txt"
    local warning_file="$WARNING_DIR/${slug}.txt"
    local warning_ref=""
    local warning_count=0
    local start_epoch
    local end_epoch
    local duration
    local rc
    local severity_label
    local status

    case "$severity" in
        critical)
            severity_label="CRITICAL"
            ;;
        advisory)
            severity_label="ADVISORY"
            ;;
        *)
            die "Invalid severity '$severity' for '$display_name'."
            ;;
    esac

    TOTAL=$((TOTAL + 1))
    section "$display_name"

    {
        echo "Check: $display_name"
        echo "Severity: $severity"
        echo "Command: $command_text"
        echo "Started: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
        echo
    } > "$log_file"

    start_epoch="$(date +%s)"

    set +e
    "$@" 2>&1 | tee -a "$log_file"
    rc=${PIPESTATUS[0]}
    set -e

    end_epoch="$(date +%s)"
    duration=$((end_epoch - start_epoch))

    if [[ $rc -eq 0 ]]; then
        status="passed"
        success "$display_name passed (${duration}s)"
    else
        status="failed"
        FAILED=$((FAILED + 1))
        cp "$log_file" "$FAILURE_DIR/${slug}.txt"

        if [[ "$severity" == "critical" ]]; then
            CRITICAL_FAILED=$((CRITICAL_FAILED + 1))
        else
            ADVISORY_FAILED=$((ADVISORY_FAILED + 1))
        fi

        error "$severity_label failure: $display_name exited $rc (${duration}s)"
    fi

    {
        echo
        echo "Result: $status"
        echo "Exit code: $rc"
        echo "Duration seconds: $duration"
        echo "Finished: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    } >> "$log_file"

    # Surface explicit repository warnings and deprecation warnings without
    # treating ordinary informational output as a warning.
    LC_ALL=C grep -E \
        '(^|[[:space:]])WARN(ING)?([[:space:]:]|$)|DeprecationWarning' \
        "$log_file" \
        | awk '!seen[$0]++' \
        > "$warning_file" || true

    if [[ -s "$warning_file" ]]; then
        warning_count="$(
            wc -l < "$warning_file" | tr -d '[:space:]'
        )"
        warning_ref="warnings/${slug}.txt"
        WARNING_TOTAL=$((WARNING_TOTAL + warning_count))
        warn "$display_name produced $warning_count warning line(s)."
    else
        rm -f "$warning_file"
    fi

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$slug" \
        "$display_name" \
        "$severity" \
        "$status" \
        "$rc" \
        "$duration" \
        "$command_text" \
        "logs/${slug}.txt" \
        "$warning_count" \
        "$warning_ref" \
        >> "$RESULTS_TSV"
}

backend_ruff() {
    cd "$REPO_ROOT/apps/backend"
    "$BACKEND_PYTHON" -m ruff check .
}

backend_compileall() {
    cd "$REPO_ROOT/apps/backend"
    "$BACKEND_PYTHON" -m compileall -q app tests scripts
}

backend_pytest() {
    NUTRITION_BACKEND_PYTHON="$BACKEND_PYTHON" \
        "$REPO_ROOT/scripts/run-backend-baseline.sh"
}

mobile_typecheck() {
    cd "$REPO_ROOT/apps/mobile"
    npm run typecheck
}

mobile_config_validate() {
    cd "$REPO_ROOT/apps/mobile"

    EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY=remote \
    EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE=development \
    EXPO_PUBLIC_NUTRITION_API_URL=http://localhost:8000/api/v1 \
        npm run config:validate
}

mobile_jest() {
    cd "$REPO_ROOT/apps/mobile"
    CI=1 npm test -- --runInBand
}

documentation_validate() {
    cd "$REPO_ROOT"
    python3 scripts/validate-docs.py
}

shell_syntax_validate() {
    cd "$REPO_ROOT"

    local found=0
    local script

    while IFS= read -r -d '' script; do
        found=1
        bash -n "$script"
    done < <(find scripts -type f -name '*.sh' -print0)

    [[ $found -eq 1 ]]
}

git_diff_validate() {
    cd "$REPO_ROOT"
    git diff --check
}

launcher_validate() {
    [[ -f "$LAUNCHER_PATH" ]] || {
        echo "Missing Finder launcher: $LAUNCHER_PATH" >&2
        return 1
    }

    [[ -x "$LAUNCHER_PATH" ]] || {
        echo "Finder launcher is not executable: $LAUNCHER_PATH" >&2
        return 1
    }

    bash -n "$LAUNCHER_PATH"
}

repository_drift_validate() {
    local after

    git status --short > "$GIT_STATUS_AFTER_TXT"
    git diff --binary HEAD > "$GIT_DIFF_AFTER_PATCH"

    after="$(repository_fingerprint)"
    printf '%s\n' "$after" > "$REPO_FINGERPRINT_AFTER_TXT"

    if [[ "$after" == "$REPO_FINGERPRINT_BEFORE" ]]; then
        echo "Repository fingerprint remained stable: $after"
        return 0
    fi

    echo "Repository changed after review verification began." >&2
    echo "Before: $REPO_FINGERPRINT_BEFORE" >&2
    echo "After:  $after" >&2
    echo \
        "Source packaging will be blocked to avoid pairing test evidence with a different tree." \
        >&2

    return 1
}

compose_validate() {
    cd "$REPO_ROOT"
    docker compose -f docker-compose.yml config -q
}

session_end_validate() {
    cd "$REPO_ROOT"

    if [[ -x "$BACKEND_PYTHON" ]]; then
        PATH="$(dirname "$BACKEND_PYTHON"):$PATH" \
            ./scripts/session-end.sh
        return
    fi

    ./scripts/session-end.sh
}

project_package() {
    local before_package
    local after_package

    cd "$REPO_ROOT"

    before_package="$(repository_fingerprint)"

    if [[ "$before_package" != "$REPO_FINGERPRINT_BEFORE" ]]; then
        echo \
            "Refusing to package: repository state no longer matches the tested state." \
            >&2
        return 1
    fi

    NUTRITION_ARCHIVE_OUTPUT="$SOURCE_ZIP" \
        ./scripts/zip-project.sh

    after_package="$(repository_fingerprint)"

    if [[ "$after_package" != "$REPO_FINGERPRINT_BEFORE" ]]; then
        rm -f "$SOURCE_ZIP"

        echo \
            "Refusing package: repository changed during source packaging." \
            >&2
        return 1
    fi
}

if [[ $RUN_BACKEND -eq 1 ]]; then
    run_step \
        "backend-ruff" \
        "Backend Ruff" \
        "critical" \
        "cd apps/backend && .venv/bin/python -m ruff check ." \
        backend_ruff

    run_step \
        "backend-compileall" \
        "Backend Compileall" \
        "critical" \
        "cd apps/backend && .venv/bin/python -m compileall -q app tests scripts" \
        backend_compileall

    run_step \
        "backend-pytest" \
        "Backend Pytest" \
        "critical" \
        "./scripts/run-backend-baseline.sh" \
        backend_pytest
fi

if [[ $RUN_MOBILE -eq 1 ]]; then
    run_step \
        "mobile-typecheck" \
        "Mobile TypeScript" \
        "critical" \
        "cd apps/mobile && npm run typecheck" \
        mobile_typecheck

    run_step \
        "mobile-config" \
        "Mobile Expo Configuration" \
        "critical" \
        "cd apps/mobile && npm run config:validate" \
        mobile_config_validate

    run_step \
        "mobile-jest" \
        "Mobile Jest" \
        "critical" \
        "cd apps/mobile && CI=1 npm test -- --runInBand" \
        mobile_jest
fi

if [[ $RUN_REPOSITORY -eq 1 ]]; then
    run_step \
        "documentation" \
        "Documentation Validation" \
        "advisory" \
        "python3 scripts/validate-docs.py" \
        documentation_validate

    run_step \
        "shell-syntax" \
        "Shell Syntax" \
        "advisory" \
        "bash -n all shell scripts under scripts/" \
        shell_syntax_validate

    run_step \
        "git-diff-check" \
        "Git Diff Check" \
        "critical" \
        "git diff --check" \
        git_diff_validate

    run_step \
        "finder-launcher" \
        "Finder Launcher" \
        "critical" \
        "test executable and bash -n 'Run Nutrition Review.command'" \
        launcher_validate
fi

if [[ $RUN_COMPOSE -eq 1 ]]; then
    run_step \
        "compose-config" \
        "Docker Compose Configuration" \
        "critical" \
        "docker compose -f docker-compose.yml config -q" \
        compose_validate
fi

if [[ $RUN_REPOSITORY -eq 1 ]]; then
    run_step \
        "session-end" \
        "Repository Session End" \
        "critical" \
        "./scripts/session-end.sh" \
        session_end_validate

    run_step \
        "repository-drift" \
        "Repository Drift Check" \
        "critical" \
        "compare complete tracked and untracked repository fingerprints" \
        repository_drift_validate
fi

if [[ $INCLUDE_PROJECT -eq 1 ]]; then
    run_step \
        "project-package" \
        "Project Review Package" \
        "critical" \
        "NUTRITION_ARCHIVE_OUTPUT=<run-dir>/project-review.zip ./scripts/zip-project.sh" \
        project_package
fi

FINISHED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

python3 - \
    "$RESULTS_TSV" \
    "$RESULTS_JSON" \
    "$SUMMARY_MD" \
    "$RUN_ID" \
    "$LABEL" \
    "$PROFILE" \
    "$STARTED_AT" \
    "$FINISHED_AT" \
    "$REPO_ROOT" \
    "$BASE_COMMIT" \
    "$BRANCH" \
    "$WORKTREE_DIRTY" \
    "$FINAL_ZIP" \
    "$SOURCE_ZIP" \
    "${NUTRITION_REVIEW_CONTROLLER:-not-recorded}" \
    "${NUTRITION_REVIEW_EXECUTOR:-not-recorded}" \
    "${NUTRITION_REVIEW_MODEL:-not-recorded}" \
    "${NUTRITION_REVIEW_TASK_CAPSULE:-not-recorded}" \
    "${NUTRITION_REVIEW_SPECIFICATION:-not-recorded}" <<'PY'
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

(
    tsv_path,
    json_path,
    summary_path,
    run_id,
    label,
    profile,
    started_at,
    finished_at,
    repository,
    commit,
    branch,
    dirty,
    final_zip,
    source_zip,
    controller,
    executor,
    model,
    task_capsule,
    specification,
) = sys.argv[1:]

checks = []

with Path(tsv_path).open(encoding="utf-8", newline="") as handle:
    for row in csv.reader(handle, delimiter="\t"):
        if not row:
            continue

        (
            slug,
            name,
            severity,
            status,
            exit_code,
            duration,
            command,
            log,
            warning_count,
            warning_log,
        ) = row

        checks.append(
            {
                "id": slug,
                "name": name,
                "severity": severity,
                "status": status,
                "exit_code": int(exit_code),
                "duration_seconds": int(duration),
                "command": command,
                "log": log,
                "warning_count": int(warning_count),
                "warning_log": warning_log or None,
            }
        )

critical_failures = [
    check
    for check in checks
    if check["status"] == "failed" and check["severity"] == "critical"
]

advisory_failures = [
    check
    for check in checks
    if check["status"] == "failed" and check["severity"] == "advisory"
]

warning_checks = [
    check
    for check in checks
    if check["warning_count"] > 0
]

warning_total = sum(check["warning_count"] for check in warning_checks)
passed = sum(check["status"] == "passed" for check in checks)
failed = len(critical_failures) + len(advisory_failures)

result = {
    "schema_version": 2,
    "run_id": run_id,
    "label": label,
    "profile": profile,
    "started_at": started_at,
    "finished_at": finished_at,
    "repository_state": {
        "path": repository,
        "base_commit": commit,
        "branch": branch,
        "working_tree_dirty": dirty == "true",
    },
    "artifacts": {
        "review_bundle_path": final_zip,
        "review_bundle_name": Path(final_zip).name,
        "project_snapshot_included": Path(source_zip).is_file(),
    },
    "execution": {
        "controller": controller,
        "executor": executor,
        "verified_model": model,
        "task_capsule": task_capsule,
        "specification": specification,
    },
    "summary": {
        "total": len(checks),
        "passed": passed,
        "failed": failed,
        "critical_failures": len(critical_failures),
        "advisory_failures": len(advisory_failures),
        "warning_lines": warning_total,
        "status": "passed" if failed == 0 else "failed",
    },
    "checks": checks,
    "warnings": [
        {
            "check": check["name"],
            "count": check["warning_count"],
            "log": check["warning_log"],
        }
        for check in warning_checks
    ],
    "opt_in_qualification_not_run": [
        "PostgreSQL concurrency and migration qualification",
        "Control-database and Phase 5C4 infrastructure qualification",
        "MinIO integration qualification",
        "Performance qualification",
        "Native iOS OCR qualification",
    ],
}

Path(json_path).write_text(
    json.dumps(result, indent=2) + "\n",
    encoding="utf-8",
)

lines = [
    "# Nutrition App Review Evidence",
    "",
    f"- Run: `{run_id}`",
    f"- Label: {label}",
    f"- Profile: `{profile}`",
    f"- Commit: `{commit}`",
    f"- Branch: `{branch}`",
    f"- Working tree dirty: {dirty}",
    f"- Final bundle: `{Path(final_zip).name}`",
    f"- Project snapshot included: {'yes' if Path(source_zip).is_file() else 'no'}",
    f"- Started: {started_at}",
    f"- Finished: {finished_at}",
    f"- Result: **{'PASS' if failed == 0 else 'FAIL'}**",
    f"- Critical failures: {len(critical_failures)}",
    f"- Advisory failures: {len(advisory_failures)}",
    f"- Warning lines: {warning_total}",
    "",
    "## Checks",
    "",
    "| Check | Severity | Status | Exit | Seconds | Log |",
    "| --- | --- | --- | ---: | ---: | --- |",
]

for check in checks:
    lines.append(
        f"| {check['name']} | {check['severity'].upper()} | "
        f"{check['status'].upper()} | {check['exit_code']} | "
        f"{check['duration_seconds']} | `{check['log']}` |"
    )

lines.extend(["", "## Critical Failures", ""])

if critical_failures:
    for check in critical_failures:
        lines.append(
            f"- **{check['name']}**: `failures/{check['id']}.txt`"
        )
else:
    lines.append("None.")

lines.extend(["", "## Advisory Failures", ""])

if advisory_failures:
    for check in advisory_failures:
        lines.append(
            f"- **{check['name']}**: `failures/{check['id']}.txt`"
        )
else:
    lines.append("None.")

lines.extend(["", "## Warnings", ""])

if warning_checks:
    for check in warning_checks:
        lines.append(
            f"- **{check['name']}**: {check['warning_count']} line(s), "
            f"`{check['warning_log']}`"
        )
else:
    lines.append("None.")

lines.extend(
    [
        "",
        "## Explicitly Not Run",
        "",
        "The ordinary review runner does not claim qualification for:",
        "",
        "- PostgreSQL concurrency, migration, or role behavior",
        "- Control-database and Phase 5C4 infrastructure behavior",
        "- MinIO integration or persistence",
        "- Performance thresholds",
        "- Native iOS OCR behavior",
        "",
        "Run issue-specific opt-in qualification separately when the changed "
        "contract requires it.",
        "",
        "Advisory failures remain review failures; severity classification "
        "exists to improve triage, not to suppress failed checks.",
        "",
    ]
)

Path(summary_path).write_text(
    "\n".join(lines),
    encoding="utf-8",
)
PY

section "Creating final review bundle"

ensure_directory "$BUNDLE_STAGE/evidence"

cp \
    "$SUMMARY_MD" \
    "$RESULTS_JSON" \
    "$ENVIRONMENT_TXT" \
    "$GIT_STATUS_TXT" \
    "$GIT_DIFF_PATCH" \
    "$GIT_STATUS_AFTER_TXT" \
    "$GIT_DIFF_AFTER_PATCH" \
    "$REPO_FINGERPRINT_BEFORE_TXT" \
    "$REPO_FINGERPRINT_AFTER_TXT" \
    "$BUNDLE_STAGE/evidence/"

cp -R "$LOG_DIR" "$BUNDLE_STAGE/evidence/logs"
cp -R "$FAILURE_DIR" "$BUNDLE_STAGE/evidence/failures"
cp -R "$WARNING_DIR" "$BUNDLE_STAGE/evidence/warnings"

if [[ -f "$SOURCE_ZIP" ]]; then
    ensure_directory "$BUNDLE_STAGE/project"
    unzip -qq "$SOURCE_ZIP" -d "$BUNDLE_STAGE/project"
fi

if [[ -f "$LAUNCHER_PATH" ]]; then
    cp \
        "$LAUNCHER_PATH" \
        "$BUNDLE_STAGE/Run Nutrition Review.command"

    chmod +x "$BUNDLE_STAGE/Run Nutrition Review.command"
fi

cat > "$BUNDLE_STAGE/README.md" <<README
# Nutrition App Review Bundle

This bundle contains:

- \`Run Nutrition Review.command\`: the Finder-compatible one-click launcher;
- \`project/\`: the source snapshot and review manifest produced by
  \`scripts/zip-project.sh\` when repository state remained stable;
- \`evidence/summary.md\`: the human-readable verification summary;
- \`evidence/results.json\`: machine-readable verification results;
- \`evidence/environment.txt\`: the reproducibility environment;
- \`evidence/git-status.txt\` and \`git-diff.patch\`: initial repository state;
- \`evidence/git-status-after.txt\` and \`git-diff-after.patch\`: state after checks;
- \`evidence/repository-fingerprint-before.txt\` and
  \`repository-fingerprint-after.txt\`: full tracked/untracked drift evidence;
- \`evidence/logs/\`: complete output from every executed check;
- \`evidence/failures/\`: copies of failed-check logs;
- \`evidence/warnings/\`: extracted warning and deprecation lines.

Issue-specific opt-in qualification is not implied unless separately supplied.
README

rm -f "$FINAL_ZIP"

(
    cd "$BUNDLE_STAGE"
    zip -qry "$FINAL_ZIP" .
)

unzip -tqq "$FINAL_ZIP"

section "Review result"

info "Checks run: $TOTAL"
info "Checks failed: $FAILED"
info "Critical failures: $CRITICAL_FAILED"
info "Advisory failures: $ADVISORY_FAILED"
info "Warning lines: $WARNING_TOTAL"

if [[ $FAILED -gt 0 ]]; then
    echo
    error "Failure logs:"

    for failure_file in "$FAILURE_DIR"/*.txt; do
        [[ -e "$failure_file" ]] || continue
        echo "  $failure_file"
    done
fi

if [[ $WARNING_TOTAL -gt 0 ]]; then
    echo
    warn "Warning logs:"

    for warning_file in "$WARNING_DIR"/*.txt; do
        [[ -e "$warning_file" ]] || continue
        echo "  $warning_file"
    done
fi

echo
info "Evidence directory:"
echo "  $RUN_DIR"

info "Uploadable review bundle:"
echo "  $FINAL_ZIP"

if [[ $FAILED -eq 0 ]]; then
    success "Review verification and packaging completed successfully."

    if [[ "${NUTRITION_REVIEW_REVEAL:-0}" == "1" ]] && \
       command -v open >/dev/null 2>&1; then
        open -R "$FINAL_ZIP" || \
            warn "Could not reveal the final ZIP in Finder."
    fi

    exit 0
fi

error "Review bundle created with $FAILED failed check(s)."
exit 1

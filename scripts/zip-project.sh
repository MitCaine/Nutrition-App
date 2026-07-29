#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_NAME="nutrition-app-review"
TIMESTAMP="$(date +"%Y%m%d-%H%M%S")"
DEFAULT_OUTPUT="$PROJECT_DIR/../${PROJECT_NAME}-${TIMESTAMP}.zip"
REQUESTED_OUTPUT="${NUTRITION_ARCHIVE_OUTPUT:-$DEFAULT_OUTPUT}"

if [[ "$REQUESTED_OUTPUT" = /* ]]; then
  OUTPUT="$REQUESTED_OUTPUT"
else
  OUTPUT="$PROJECT_DIR/$REQUESTED_OUTPUT"
fi

TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nutrition-app-review.XXXXXX")"
MANIFEST="$TEMP_DIR/REVIEW_MANIFEST.txt"
ARCHIVE_LIST="$TEMP_DIR/archive-contents.txt"

cleanup() {
  rm -rf "$TEMP_DIR"
}

trap cleanup EXIT

INCLUDE_PATHS=(
  README.md
  CONTRIBUTING.md
  .gitignore
  .env.example
  .python-version
  .nvmrc
  .github

  docker-compose.yml
  docker-compose.phase5c4.yml
  docker-compose.phase5c4-qualification.yml
  docker

  docs
  scripts
  packages/shared-contracts

  apps/backend/app
  apps/backend/tests
  apps/backend/scripts
  apps/backend/pyproject.toml
  apps/backend/requirements-dev.lock
  apps/backend/alembic.ini
  apps/backend/alembic-control.ini
  apps/backend/.env.example
  apps/backend/evidence

  apps/mobile/App.js
  apps/mobile/src
  apps/mobile/modules
  apps/mobile/__tests__
  apps/mobile/config
  apps/mobile/plugins
  apps/mobile/package.json
  apps/mobile/package-lock.json
  apps/mobile/tsconfig.json
  apps/mobile/app.json
  apps/mobile/app.config.js
  apps/mobile/babel.config.js
  apps/mobile/jest.setup.ts
  apps/mobile/.env.example
)

EXISTING_PATHS=()
MISSING_PATHS=()

for path in "${INCLUDE_PATHS[@]}"; do
  if [[ -e "$PROJECT_DIR/$path" ]]; then
    EXISTING_PATHS+=("$path")
  else
    MISSING_PATHS+=("$path")
  fi
done

if [[ ${#EXISTING_PATHS[@]} -eq 0 ]]; then
  echo "No review-package inputs were found." >&2
  exit 1
fi

if ! command -v zip >/dev/null 2>&1; then
  echo "Required command not found: zip" >&2
  exit 1
fi

if ! command -v unzip >/dev/null 2>&1; then
  echo "Required command not found: unzip" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"
rm -f "$OUTPUT"

echo "Creating review manifest..."

{
  echo "Nutrition App Review Package"
  echo "============================"
  echo
  echo "Created: $(date)"
  echo "Archive: $(basename "$OUTPUT")"
  echo

  echo "Git Information"
  echo "---------------"

  if git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    BRANCH="$(git -C "$PROJECT_DIR" branch --show-current)"

    echo "Branch: ${BRANCH:-\(detached HEAD\)}"
    echo "Commit: $(git -C "$PROJECT_DIR" rev-parse HEAD)"
    echo

    echo "Working Tree Status"
    echo "-------------------"

    if [[ -n "$(git -C "$PROJECT_DIR" status --short)" ]]; then
      git -C "$PROJECT_DIR" status --short
    else
      echo "Clean"
    fi

    echo
    echo "Recent Commits"
    echo "--------------"
    git -C "$PROJECT_DIR" log --oneline -10
  else
    echo "Repository metadata unavailable."
  fi

  echo
  echo "Included Paths"
  echo "--------------"
  printf '%s\n' "${EXISTING_PATHS[@]}"
  echo

  if [[ ${#MISSING_PATHS[@]} -gt 0 ]]; then
    echo "Configured Paths Not Present"
    echo "----------------------------"
    printf '%s\n' "${MISSING_PATHS[@]}"
    echo
  fi

  echo "Exclusions"
  echo "----------"
  echo "Git metadata, secrets, private keys, dependency trees, virtual environments,"
  echo "runtime state, generated qualification evidence, caches, generated native/build"
  echo "output, coverage, logs, archives, database data, and OS/IDE metadata."
} > "$MANIFEST"

echo "Creating $(basename "$OUTPUT")..."

cd "$PROJECT_DIR"

zip -rq "$OUTPUT" "${EXISTING_PATHS[@]}" \
  -x \
  "*.zip" \
  "*.log" \
  "*.pyc" \
  "*.DS_Store" \
  "*/.DS_Store" \
  ".git/*" \
  "*/.git/*" \
  ".env" \
  "*/.env" \
  ".env.local" \
  "*/.env.local" \
  ".env.production" \
  "*/.env.production" \
  ".env.development" \
  "*/.env.development" \
  ".env.test" \
  "*/.env.test" \
  "*.key" \
  "*.p12" \
  "*.pfx" \
  "*.jks" \
  "*.keystore" \
  ".project-runtime/*" \
  "*/.project-runtime/*" \
  ".idea/*" \
  "*/.idea/*" \
  ".vscode/*" \
  "*/.vscode/*" \
  ".venv/*" \
  "*/.venv/*" \
  "venv/*" \
  "*/venv/*" \
  "node_modules/*" \
  "*/node_modules/*" \
  "target/*" \
  "*/target/*" \
  "build/*" \
  "*/build/*" \
  "dist/*" \
  "*/dist/*" \
  "coverage/*" \
  "*/coverage/*" \
  ".next/*" \
  "*/.next/*" \
  ".expo/*" \
  "*/.expo/*" \
  ".gradle/*" \
  "*/.gradle/*" \
  ".cache/*" \
  "*/.cache/*" \
  ".pytest_cache/*" \
  "*/.pytest_cache/*" \
  ".ruff_cache/*" \
  "*/.ruff_cache/*" \
  "__pycache__/*" \
  "*/__pycache__/*" \
  "*.egg-info/*" \
  "*/.egg-info/*" \
  "apps/mobile/ios/*" \
  "apps/mobile/android/*" \
  "docker/*/secrets/*" \
  "docker/*/*/secrets/*" \
  "docker/*/runtime/*" \
  "docker/*/*/runtime/*" \
  "docker/*/data/*" \
  "docker/*/*/data/*" \
  "docker/*/volumes/*" \
  "docker/*/*/volumes/*"

(
  cd "$TEMP_DIR"
  zip -q "$OUTPUT" REVIEW_MANIFEST.txt
)

unzip -Z1 "$OUTPUT" > "$ARCHIVE_LIST"

archive_contains_file() {
  local path="$1"
  grep -Fxq "$path" "$ARCHIVE_LIST"
}

archive_contains_prefix() {
  local path="$1"
  grep -Fq "${path%/}/" "$ARCHIVE_LIST"
}

echo "Validating archive contents..."

for path in "${EXISTING_PATHS[@]}"; do
  if [[ -f "$PROJECT_DIR/$path" ]]; then
    if ! archive_contains_file "$path"; then
      echo "Archive validation failed: missing file '$path'." >&2
      exit 1
    fi
  elif [[ -d "$PROJECT_DIR/$path" ]]; then
    if ! archive_contains_prefix "$path"; then
      echo "Archive validation failed: missing directory contents for '$path'." >&2
      exit 1
    fi
  fi
done

REQUIRED_QUALIFICATION_PATHS=(
  docker-compose.phase5c4-qualification.yml
  apps/backend/app/operators/phase5c4_infrastructure_qualification.py
  apps/backend/scripts/qualify_phase5c4_infrastructure.py
  scripts/qualify-phase5c4-infrastructure.sh
)

for path in "${REQUIRED_QUALIFICATION_PATHS[@]}"; do
  if [[ -e "$PROJECT_DIR/$path" ]] && ! archive_contains_file "$path"; then
    echo "Archive validation failed: missing qualification file '$path'." >&2
    exit 1
  fi
done

if [[ -d "$PROJECT_DIR/docker/phase5c4" ]] &&
   ! archive_contains_prefix "docker/phase5c4"; then
  echo "Archive validation failed: missing docker/phase5c4 contents." >&2
  exit 1
fi

FORBIDDEN_PATTERNS=(
  ".git/"
  ".project-runtime/"
  "node_modules/"
  ".venv/"
  "__pycache__/"
  ".pytest_cache/"
  ".ruff_cache/"
  "apps/mobile/ios/"
  "apps/mobile/android/"
)

for pattern in "${FORBIDDEN_PATTERNS[@]}"; do
  if grep -Fq "$pattern" "$ARCHIVE_LIST"; then
    echo "Archive validation failed: forbidden path present: '$pattern'." >&2
    exit 1
  fi
done

if grep -Eiq '(^|/)\.env($|\.)' "$ARCHIVE_LIST"; then
  while IFS= read -r archived_path; do
    case "$archived_path" in
      ".env.example" | */".env.example")
        ;;
      *)
        echo "Archive validation failed: environment file present: '$archived_path'." >&2
        exit 1
        ;;
    esac
  done < <(grep -Ei '(^|/)\.env($|\.)' "$ARCHIVE_LIST")
fi

if grep -Eiq '\.(key|p12|pfx|jks|keystore)$' "$ARCHIVE_LIST"; then
  echo "Archive validation failed: private-key or keystore material is present." >&2
  grep -Ei '\.(key|p12|pfx|jks|keystore)$' "$ARCHIVE_LIST" >&2
  exit 1
fi

if ! archive_contains_file "REVIEW_MANIFEST.txt"; then
  echo "Archive validation failed: REVIEW_MANIFEST.txt is missing." >&2
  exit 1
fi

echo
echo "Review package created successfully"
echo "Archive: $OUTPUT"

if command -v du >/dev/null 2>&1; then
  echo "Size:    $(du -h "$OUTPUT" | awk '{print $1}')"
fi

echo "Manifest: REVIEW_MANIFEST.txt"
echo
echo "Qualification assets included:"

for path in "${REQUIRED_QUALIFICATION_PATHS[@]}"; do
  if archive_contains_file "$path"; then
    echo "  - $path"
  fi
done

if archive_contains_prefix "docker/phase5c4"; then
  echo "  - docker/phase5c4/"
fi
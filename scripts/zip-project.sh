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

cleanup() {
  rm -rf "$TEMP_DIR"
}

trap cleanup EXIT

INCLUDE_PATHS=(
  README.md
  .gitignore
  .env.example
  docker-compose.yml
  docker-compose.phase5c4.yml
  docs
  scripts
  packages/shared-contracts
  apps/backend/app
  apps/backend/tests
  apps/backend/scripts
  apps/backend/pyproject.toml
  apps/backend/alembic.ini
  apps/backend/alembic-control.ini
  apps/backend/.env.example
  apps/backend/phase5c-performance-t0.json
  apps/backend/phase5c-performance-t0-optimized.json
  apps/backend/phase5c-performance-t0-requalified.json
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
  echo "Git metadata, secrets, dependency trees, virtual environments, caches,"
  echo "generated native/build output, coverage, logs, archives, and OS/IDE metadata."
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
  ".idea/*" \
  "*/.idea/*" \
  ".vscode/*" \
  "*/.vscode/*" \
  ".venv/*" \
  "*/.venv/*" \
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
  "apps/mobile/android/*"

(
  cd "$TEMP_DIR"
  zip -q "$OUTPUT" REVIEW_MANIFEST.txt
)

echo
echo "Review package created successfully"
echo "Archive: $OUTPUT"

if command -v du >/dev/null 2>&1; then
  echo "Size:    $(du -h "$OUTPUT" | awk '{print $1}')"
fi

echo "Manifest: REVIEW_MANIFEST.txt"

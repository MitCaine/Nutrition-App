#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
OUTPUT="${NUTRITION_ARCHIVE_OUTPUT:-$PROJECT_DIR/../${PROJECT_NAME}.zip}"
MANIFEST="$PROJECT_DIR/REVIEW_MANIFEST.txt"

cleanup() {
  rm -f "$MANIFEST"
}

trap cleanup EXIT

cd "$PROJECT_DIR"

rm -f "$OUTPUT"
rm -f "$MANIFEST"

echo "Creating review manifest..."

{
  echo "Nutrition App Review Package"
  echo "============================"
  echo
  echo "Created: $(date)"
  echo "Project: $PROJECT_NAME"
  echo "Archive: $(basename "$OUTPUT")"
  echo

  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Git Information"
    echo "---------------"
    echo "Branch: $(git branch --show-current)"
    echo "Commit: $(git rev-parse HEAD)"
    echo

    echo "Working Tree Status"
    echo "-------------------"
    if [[ -n "$(git status --short)" ]]; then
      git status --short
    else
      echo "Clean"
    fi
    echo

    echo "Recent Commits"
    echo "--------------"
    git log --oneline -10
    echo
  else
    echo "Git Information"
    echo "---------------"
    echo "Repository metadata unavailable."
    echo
  fi

  echo "Archive Scope"
  echo "-------------"
  echo "Includes repository source, tests, documentation, migrations,"
  echo "configuration files, scripts, and reviewed environment templates."
  echo
  echo "Excludes Git metadata, virtual environments, dependency trees,"
  echo "caches, generated native projects, local environment files,"
  echo "compiled Python files, package metadata, and macOS metadata."
  echo

  echo "Reviewed Environment Templates"
  echo "------------------------------"
  for example in \
    .env.example \
    apps/backend/.env.example \
    apps/mobile/.env.example
  do
    if [[ -f "$example" ]]; then
      echo "Included: $example"
    else
      echo "Missing:  $example"
    fi
  done
} > "$MANIFEST"

echo "Creating archive..."

zip -r "$OUTPUT" . \
  -x ".git/*" \
  -x "*/.git/*" \
  -x ".venv/*" \
  -x "*/.venv/*" \
  -x "node_modules/*" \
  -x "*/node_modules/*" \
  -x ".ruff_cache/*" \
  -x "*/.ruff_cache/*" \
  -x ".pytest_cache/*" \
  -x "*/.pytest_cache/*" \
  -x "__pycache__/*" \
  -x "*/__pycache__/*" \
  -x ".pycache/*" \
  -x "*/.pycache/*" \
  -x ".expo/*" \
  -x "*/.expo/*" \
  -x "apps/mobile/ios/*" \
  -x "apps/mobile/android/*" \
  -x ".env" \
  -x "*/.env" \
  -x ".env.*" \
  -x "*/.env.*" \
  -x "*.pyc" \
  -x ".DS_Store" \
  -x "*/.DS_Store" \
  -x "*.egg-info/*" \
  -x "*/.egg-info/*" \
  -x "*.zip"

# The broad secret-file exclusions above intentionally match .env.example.
# Re-add only the reviewed, non-secret templates by exact path.
for example in \
  .env.example \
  apps/backend/.env.example \
  apps/mobile/.env.example
do
  if [[ -f "$example" ]]; then
    zip -q "$OUTPUT" "$example"
  fi
done

echo
echo "Created: $OUTPUT"

if command -v du >/dev/null 2>&1; then
  echo "Size:    $(du -h "$OUTPUT" | awk '{print $1}')"
fi

echo
echo "Manifest included as REVIEW_MANIFEST.txt"
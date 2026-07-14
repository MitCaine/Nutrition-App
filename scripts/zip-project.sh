#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
OUTPUT="${NUTRITION_ARCHIVE_OUTPUT:-$PROJECT_DIR/../${PROJECT_NAME}.zip}"

rm -f "$OUTPUT"

cd "$PROJECT_DIR"

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
  -x "*/.egg-info/*"

# The broad secret-file exclusions above intentionally match .env.example too.
# Re-add only the three reviewed, non-secret templates by exact path.
for example in .env.example apps/backend/.env.example apps/mobile/.env.example; do
  if [[ -f "$example" ]]; then
    zip -q "$OUTPUT" "$example"
  fi
done

echo
echo "Created: $OUTPUT"

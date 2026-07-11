#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
OUTPUT="$PROJECT_DIR/../${PROJECT_NAME}.zip"

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

echo
echo "Created: $OUTPUT"
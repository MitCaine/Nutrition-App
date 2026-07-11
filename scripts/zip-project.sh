#!/bin/bash

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
OUTPUT="$PROJECT_DIR/../${PROJECT_NAME}.zip"

rm -f "$OUTPUT"

cd "$PROJECT_DIR" || exit 1

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
  -x "*.pyc" \
  -x ".DS_Store" \
  -x "*/.DS_Store"

echo
echo "Created: $OUTPUT"
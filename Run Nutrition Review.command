#!/usr/bin/env bash
set -u

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT" || exit 1

BRANCH="$(git branch --show-current 2>/dev/null || true)"
LABEL="${BRANCH:-review}"

echo
echo "Starting Nutrition App review workflow..."
echo

NUTRITION_REVIEW_REVEAL=1 \
"$REPO_ROOT/scripts/run-review.sh" \
    --profile baseline \
    --label "$LABEL"

STATUS=$?

echo
echo "========================================================================"

if [[ $STATUS -eq 0 ]]; then
    echo "Review completed successfully."
    echo "The uploadable ZIP has been revealed in Finder."
else
    echo "Review completed with failures."
    echo "Exit code: $STATUS"
fi

echo "========================================================================"
echo

read -r -p "Press Return to close this window..."

exit "$STATUS"

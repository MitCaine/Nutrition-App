#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The trusted qualification workflow is loaded from main, so it cannot pass the
# explicit portable flag until this change has landed there. Restrict the
# transition to these exact repository-owned Linux CI workflows; local calls
# and controller validation keep their strict default.
if [[ $# -eq 0 \
    && "${GITHUB_ACTIONS:-}" == true \
    && "${GITHUB_REPOSITORY:-}" == MitCaine/Nutrition-App \
    && "${GITHUB_WORKSPACE:-}" == "$ROOT" \
    && "${RUNNER_OS:-}" == Linux ]]; then
    case "${GITHUB_WORKFLOW_REF:-}" in
        MitCaine/Nutrition-App/.github/workflows/ci.yml@*|MitCaine/Nutrition-App/.github/workflows/trusted-qualification-execute.yml@*)
            set -- --portable-recovery
            ;;
    esac
fi
exec "$ROOT/scripts/project-audit.sh" pre-commit "$@"

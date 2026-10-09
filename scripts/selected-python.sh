#!/usr/bin/env bash
# Shared interpreter binding for session and audit wrappers; no installations.
nutrition_select_python() {
    NUTRITION_DEPS_PYTHON="${NUTRITION_DEPS_PYTHON:-python3}"
    if ! command -v "$NUTRITION_DEPS_PYTHON" >/dev/null 2>&1; then
        printf 'ERROR SELECTED_PYTHON_UNAVAILABLE: %s\n' "$NUTRITION_DEPS_PYTHON" >&2
        return 1
    fi
    export NUTRITION_DEPS_PYTHON
}

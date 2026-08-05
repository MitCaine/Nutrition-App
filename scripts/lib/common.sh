#!/usr/bin/env bash

# ==============================================================================
# Nutrition App Developer Toolkit
# Shared shell helpers
#
# Every script should source this file:
#
#   source "$(dirname "$0")/lib/common.sh"
#
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# Repository discovery
# ------------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)" || {
    echo "ERROR: Unable to locate Git repository."
    exit 1
}

# ------------------------------------------------------------------------------
# Colors
# ------------------------------------------------------------------------------

if [[ -t 1 ]]; then
    RED=$'\033[31m'
    GREEN=$'\033[32m'
    YELLOW=$'\033[33m'
    BLUE=$'\033[34m'
    BOLD=$'\033[1m'
    RESET=$'\033[0m'
else
    RED=""
    GREEN=""
    YELLOW=""
    BLUE=""
    BOLD=""
    RESET=""
fi

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------

banner() {
    printf "\n%s" "$BOLD"
    printf '%*s\n' 72 '' | tr ' ' '='
    printf "%s\n" "$*"
    printf '%*s\n' 72 '' | tr ' ' '='
    printf "%s" "$RESET"
}

section() {
    printf "\n%s== %s ==%s\n" "$BOLD" "$*" "$RESET"
}

info() {
    printf "%s[INFO]%s %s\n" "$BLUE" "$RESET" "$*"
}

success() {
    printf "%s[SUCCESS]%s %s\n" "$GREEN" "$RESET" "$*"
}

warn() {
    printf "%s[WARNING]%s %s\n" "$YELLOW" "$RESET" "$*"
}

error() {
    printf "%s[ERROR]%s %s\n" "$RED" "$RESET" "$*" >&2
}

die() {
    error "$*"
    exit 1
}

# ------------------------------------------------------------------------------
# Command helpers
# ------------------------------------------------------------------------------

require_command() {
    command -v "$1" >/dev/null 2>&1 || \
        die "Required command not found: $1"
}

run() {
    "$@"
}

log_run() {
    info "$*"
    "$@"
}

# ------------------------------------------------------------------------------
# Repository helpers
# ------------------------------------------------------------------------------

ensure_repo_root() {
    [[ -d "$REPO_ROOT/.git" ]] || \
        die "Repository root not found."
}

repo_cd() {
    cd "$REPO_ROOT"
}

git_clean_check() {
    if [[ -n "$(git status --porcelain)" ]]; then
        warn "Repository contains uncommitted changes."
        return 1
    fi

    success "Repository is clean."
}

# ------------------------------------------------------------------------------
# Filesystem helpers
# ------------------------------------------------------------------------------

ensure_directory() {
    mkdir -p "$1"
}

remove_if_exists() {
    [[ -e "$1" ]] && rm -rf "$1"
}

timestamp() {
    date +"%Y-%m-%d_%H-%M-%S"
}

make_temp_dir() {
    mktemp -d "${TMPDIR:-/tmp}/nutrition-review.XXXXXX"
}

# ------------------------------------------------------------------------------
# User interaction
# ------------------------------------------------------------------------------

confirm() {
    local prompt="${1:-Continue?}"

    read -r -p "$prompt [y/N]: " response

    case "$response" in
        y|Y|yes|YES)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# ------------------------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------------------------

cleanup() {
    :
}

trap cleanup EXIT

# ------------------------------------------------------------------------------
# Validate environment immediately after sourcing
# ------------------------------------------------------------------------------

ensure_repo_root
require_command git


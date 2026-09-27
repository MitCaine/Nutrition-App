# Select and refresh only the toolchain lines declared by this repository.
nutrition_app_toolchain() {
  local root="$NUTRITION_APP_ROOT"
  local node_line="$(< "$root/.nvmrc")"
  local python_line="$(< "$root/.python-version")"
  local node_formula='' node_prefix='' python_prefix='' candidate='' latest='' remaining=''

  if command -v brew >/dev/null 2>&1; then
    if [[ "${NUTRITION_START_WORK_SKIP_TOOL_UPDATES:-}" != 1 ]]; then
      if ! brew update --quiet; then
        print -u2 'Homebrew index refresh failed; checking installed tool versions.'
      fi
    fi
    candidate="$(brew --prefix "node@$node_line" 2>/dev/null)"
    if [[ -n "$candidate" && -x "$candidate/bin/node" ]]; then
      node_formula="node@$node_line"
      node_prefix="$candidate"
    else
      candidate="$(brew --prefix node 2>/dev/null)"
      if [[ -n "$candidate" && -x "$candidate/bin/node" &&
            "$("$candidate/bin/node" -p 'process.versions.node.split(".")[0]')" == "$node_line" ]]; then
        node_formula=node
        node_prefix="$candidate"
      fi
    fi
    python_prefix="$(brew --prefix "python@$python_line" 2>/dev/null)"

    if [[ "${NUTRITION_START_WORK_SKIP_TOOL_UPDATES:-}" != 1 ]]; then
      if [[ -n "$node_formula" ]]; then
        latest="$(brew info --json=v2 "$node_formula" 2>/dev/null | python3 -c \
          'import json,sys; print(json.load(sys.stdin)["formulae"][0]["versions"]["stable"])' 2>/dev/null)"
        if [[ "$latest" == "$node_line".* ]]; then
          if [[ -n "$(brew outdated --quiet "$node_formula" 2>/dev/null)" ]]; then
            print "Updating $node_formula within Node $node_line..."
            brew upgrade "$node_formula" || return 1
          fi
        else
          print "Node formula latest is ${latest:-unavailable}; keeping repository line $node_line."
        fi
      fi
      if [[ -n "$python_prefix" && -x "$python_prefix/bin/python$python_line" &&
            -n "$(brew outdated --quiet "python@$python_line" 2>/dev/null)" ]]; then
        print "Updating Python $python_line within its release line..."
        brew upgrade "python@$python_line" || return 1
      fi
      for candidate in "$node_formula" "python@$python_line"; do
        [[ -n "$candidate" ]] || continue
        remaining="$(brew outdated --quiet "$candidate" 2>/dev/null)" || {
          print -u2 "Could not verify Homebrew updates for $candidate."
          return 1
        }
        if [[ -n "$remaining" ]]; then
          print -u2 "$candidate still has an available update after Homebrew upgrade."
          return 1
        fi
      done
    fi
  fi

  if [[ -n "$node_prefix" ]]; then
    export PATH="$node_prefix/bin:$PATH"
  fi
  if [[ -n "$python_prefix" && -x "$python_prefix/bin/python$python_line" ]]; then
    export PATH="$python_prefix/bin:$PATH"
  fi
  if ! command -v node >/dev/null 2>&1 ||
      [[ "$(node -p 'process.versions.node.split(".")[0]')" != "$node_line" ]]; then
    print -u2 "Node $node_line is required. Install it or select it on PATH."
    return 2
  fi
  if ! command -v "python$python_line" >/dev/null 2>&1; then
    print -u2 "Python $python_line is required. Install it or select it on PATH."
    return 2
  fi
  export NUTRITION_DEPS_PYTHON="$(command -v "python$python_line")"
  if [[ "$("$NUTRITION_DEPS_PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" != "$python_line" ]]; then
    print -u2 "Selected Python does not match repository line $python_line."
    return 2
  fi
  print "Using $(node --version) and $("$NUTRITION_DEPS_PYTHON" --version)."
}

nutrition_app_toolchain
_nutrition_toolchain_status=$?
unfunction nutrition_app_toolchain
return $_nutrition_toolchain_status

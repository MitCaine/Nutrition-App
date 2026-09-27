#!/usr/bin/env zsh
# Source this file in a VS Code or Codex integrated zsh terminal. A child process
# cannot change the PATH of the terminal that launched it.
if [[ "${ZSH_EVAL_CONTEXT:-}" != *:file ]]; then
  print -u2 'Run: source ./scripts/start-work.zsh'
  exit 2
fi

typeset -g NUTRITION_APP_ROOT="${${(%):-%x}:A:h:h}"
source "$NUTRITION_APP_ROOT/scripts/dependency-modules/toolchain.zsh" || return $?
source "$NUTRITION_APP_ROOT/scripts/dependency-modules/dependencies.zsh" || return $?
print 'Nutrition App tool paths and dependency check are ready in this terminal.'

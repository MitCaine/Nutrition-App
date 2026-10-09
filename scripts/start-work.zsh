#!/usr/bin/env zsh
# Source this file in a VS Code or Codex integrated zsh terminal. A child process
# cannot change the PATH of the terminal that launched it.
if [[ "${ZSH_EVAL_CONTEXT:-}" != *:file ]]; then
  print -u2 'Run: source ./scripts/start-work.zsh'
  exit 2
fi

typeset -g NUTRITION_APP_ROOT="${${(%):-%x}:A:h:h}"
# Whole-project tool/dependency refresh requires an explicit scoped invocation.
# An ordinary source/document session must not enter either update module.
if (( $# == 0 )); then
  "$NUTRITION_APP_ROOT/scripts/session-start.sh"
  return $?
fi
if (( $# != 1 )) || [[ "$1" != --refresh-all ]]; then
  print -u2 'Use source ./scripts/start-work.zsh for a read-only session, or --refresh-all only for an authorized whole-project refresh. For scoped packages use scripts/update-dependencies backend|mobile PACKAGE [--apply].'
  return 2
fi
if source "$NUTRITION_APP_ROOT/scripts/dependency-modules/toolchain.zsh"; then
  _nutrition_start_toolchain_status=0
else
  _nutrition_start_toolchain_status=$?
fi
if source "$NUTRITION_APP_ROOT/scripts/dependency-modules/dependencies.zsh"; then
  _nutrition_start_dependencies_status=0
else
  _nutrition_start_dependencies_status=$?
fi
if "$NUTRITION_APP_ROOT/scripts/session-start.sh"; then
  _nutrition_start_session_status=0
else
  _nutrition_start_session_status=$?
fi
if (( _nutrition_start_toolchain_status || _nutrition_start_dependencies_status || _nutrition_start_session_status )); then
  print -u2 "Startup incomplete: toolchain status $_nutrition_start_toolchain_status; dependency status $_nutrition_start_dependencies_status; session report status $_nutrition_start_session_status. Successful updates remain applied; review the failures above and rerun."
  return 1
fi
print 'Nutrition App tool paths, dependency check, and session report are ready in this terminal.'

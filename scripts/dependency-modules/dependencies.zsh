# Resume only the updater's recorded output; unrelated changes fail closed.
nutrition_app_dependencies() {
  local root="$NUTRITION_APP_ROOT"
  if [[ "${NUTRITION_START_WORK_PREVIEW:-}" == 1 ]]; then
    print 'Preview mode: checking updates without applying them.'
    "$root/scripts/update-dependencies" all
  else
    "$root/scripts/update-dependencies" all --apply
  fi
}

nutrition_app_dependencies
_nutrition_dependencies_status=$?
unfunction nutrition_app_dependencies
return $_nutrition_dependencies_status

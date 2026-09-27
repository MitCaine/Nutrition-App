# One bulk resolver applies the backend and mobile lockfiles after both validate.
nutrition_app_dependencies() {
  local root="$NUTRITION_APP_ROOT"
  local changes=''
  if ! changes="$(git -C "$root" status --porcelain=v1 --untracked-files=all)"; then
    print -u2 'Could not verify checkout cleanliness; running read-only dependency checks.'
    "$root/scripts/update-dependencies" all
    return 2
  fi
  if [[ -n "$changes" || "${NUTRITION_START_WORK_PREVIEW:-}" == 1 ]]; then
    print 'Existing work or preview mode: checking updates without applying them.'
    "$root/scripts/update-dependencies" all
  else
    "$root/scripts/update-dependencies" all --apply
  fi
}

nutrition_app_dependencies
_nutrition_dependencies_status=$?
unfunction nutrition_app_dependencies
return $_nutrition_dependencies_status

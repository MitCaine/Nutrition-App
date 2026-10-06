#!/usr/bin/env bash

set -euo pipefail

cache_kind=""
repo_root=""

while test "$#" -gt 0
do
  case "$1" in
    --cache)
      test "$#" -ge 2
      cache_kind="$2"
      shift 2
      ;;
    --repo-root)
      test "$#" -ge 2
      repo_root="$2"
      shift 2
      ;;
    *)
      echo "IOS_NATIVE_CACHE_KEY_ARGUMENT_INVALID:$1" >&2
      exit 2
      ;;
  esac
done

case "$cache_kind" in
  npm|cocoapods)
    ;;
  *)
    echo "IOS_NATIVE_CACHE_KEY_CACHE_REQUIRED" >&2
    exit 2
    ;;
esac

if test -z "$repo_root"
then
  repo_root="$(git rev-parse --show-toplevel)"
fi

repo_root="$(cd "$repo_root" && pwd -P)"

required_tools=(git node npm shasum sw_vers uname)
if test "$cache_kind" = "cocoapods"
then
  required_tools+=(ruby pod xcodebuild xcrun)
fi

for tool in "${required_tools[@]}"
do
  if ! command -v "$tool" >/dev/null 2>&1
  then
    echo "IOS_NATIVE_CACHE_KEY_TOOL_MISSING:$tool" >&2
    exit 1
  fi
done

macos_version="$(sw_vers -productVersion)"
architecture="$(uname -m)"
node_version="$(node --version)"
npm_version="$(npm --version)"

if test "$cache_kind" = "cocoapods"
then
  ruby_version="$(ruby --version)"
  cocoapods_version="$(pod --version)"
  xcode_info="$(xcodebuild -version)"
  xcode_version="$(printf '%s\n' "$xcode_info" | awk 'NR == 1 {print $2}')"
  xcode_build="$(printf '%s\n' "$xcode_info" | awk 'NR == 2 {print $3}')"
  sdk_version="$(xcrun --sdk iphonesimulator --show-sdk-version)"
fi

input_paths=(
  ".nvmrc"
  "apps/mobile/package.json"
  "apps/mobile/package-lock.json"
)

if test "$cache_kind" = "cocoapods"
then
  input_paths+=(
    "apps/mobile/app.json"
    "apps/mobile/app.config.js"
    "apps/mobile/config/runtimeConfig.js"
  )
fi

if test "$cache_kind" = "cocoapods"
then
  while IFS= read -r path
  do
    input_paths+=("$path")
  done < <(
    git -C "$repo_root" ls-files -- \
      'apps/mobile/plugins/**' \
      'apps/mobile/modules/**/expo-module.config.json' \
      'apps/mobile/modules/**/ios/**'
  )
fi

input_fingerprint="$({
  for path in "${input_paths[@]}"
  do
    if test -f "$repo_root/$path"
    then
      printf '%s\t%s\n' \
        "$path" \
        "$(git -C "$repo_root" hash-object -- "$path")"
    else
      printf '%s\tMISSING\n' "$path"
    fi
  done
} | shasum -a 256 | awk '{print $1}')"

toolchain_fingerprint="$({
  printf 'macos=%s\n' "$macos_version"
  printf 'architecture=%s\n' "$architecture"
  printf 'node=%s\n' "$node_version"
  printf 'npm=%s\n' "$npm_version"
  if test "$cache_kind" = "cocoapods"
  then
    printf 'ruby=%s\n' "$ruby_version"
    printf 'cocoapods=%s\n' "$cocoapods_version"
    printf 'xcode=%s\n' "$xcode_version"
    printf 'xcode_build=%s\n' "$xcode_build"
    printf 'iphonesimulator_sdk=%s\n' "$sdk_version"
  fi
} | shasum -a 256 | awk '{print $1}')"

case "$cache_kind" in
  npm)
    printf 'nutrition-ios-npm-v1-%s-%s-%s-%s\n' \
      "$macos_version" \
      "$architecture" \
      "$toolchain_fingerprint" \
      "$input_fingerprint"
    ;;
  cocoapods)
    printf 'nutrition-ios-cocoapods-v1-%s-%s-%s-%s\n' \
      "$macos_version" \
      "$architecture" \
      "$toolchain_fingerprint" \
      "$input_fingerprint"
    ;;
esac

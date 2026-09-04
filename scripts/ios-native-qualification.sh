set -euo pipefail

evidence_dir=""
runner="local"

while test "$#" -gt 0
do
  case "$1" in
    --evidence-dir)
      test "$#" -ge 2
      evidence_dir="$2"
      shift 2
      ;;
    --runner)
      test "$#" -ge 2
      runner="$2"
      shift 2
      ;;
    *)
      echo "IOS_NATIVE_ARGUMENT_INVALID:$1" >&2
      exit 2
      ;;
  esac
done

if test -z "$evidence_dir"
then
  echo "IOS_NATIVE_EVIDENCE_DIR_REQUIRED" >&2
  exit 2
fi

if test "$(uname -s)" != "Darwin"
then
  echo "IOS_NATIVE_REQUIRES_MACOS" >&2
  exit 2
fi

repo_root="$(
  git rev-parse --show-toplevel
)"

if test -n "$(
  git -C "$repo_root" status \
    --porcelain=v1 \
    -uall
)"
then
  echo "IOS_NATIVE_SOURCE_WORKTREE_DIRTY" >&2
  exit 1
fi

commit="$(
  git -C "$repo_root" rev-parse HEAD
)"

mkdir -p "$evidence_dir"

probe_root="$evidence_dir/Nutrition App Native"
derived_data="$evidence_dir/DerivedData"
harness_bin="$evidence_dir/harness-bin"
manifest="$evidence_dir/manifest.json"

if test -e "$probe_root"
then
  echo "IOS_NATIVE_PROBE_ALREADY_EXISTS" >&2
  exit 1
fi

for tool in node npm python3 pod xcodebuild xcrun
do
  if ! command -v "$tool" >/dev/null 2>&1
  then
    echo "IOS_NATIVE_TOOL_MISSING:$tool" >&2
    exit 1
  fi
done

start_epoch="$(date +%s)"

node_binary="$(
  command -v node
)"
node_version="$(
  node --version
)"
npm_version="$(
  npm --version
)"
macos_version="$(
  sw_vers -productVersion
)"
architecture="$(
  uname -m
)"
xcode_version="$(
  xcodebuild -version |
    awk 'NR == 1 {print $2}'
)"
xcode_build="$(
  xcodebuild -version |
    awk 'NR == 2 {print $3}'
)"
swift_version="$(
  xcrun swiftc --version |
    sed -n '1p'
)"
cocoapods_version="$(
  pod --version
)"

xcode_major="${xcode_version%%.*}"
xcode_tail="${xcode_version#*.}"
xcode_minor="${xcode_tail%%.*}"

if test "$xcode_major" -lt 26
then
  echo "IOS_NATIVE_XCODE_TOO_OLD:$xcode_version" >&2
  exit 1
fi

if test "$xcode_major" -eq 26 &&
  test "$xcode_minor" -lt 4
then
  echo "IOS_NATIVE_XCODE_TOO_OLD:$xcode_version" >&2
  exit 1
fi

python3 \
  "$repo_root/scripts/toolchain-report.py" \
  --check node \
  > "$evidence_dir/node-toolchain.log"

cleanup() {
  if git -C "$repo_root" worktree list --porcelain |
    grep -Fqx "worktree $probe_root"
  then
    git -C "$repo_root" worktree remove \
      --force \
      "$probe_root" \
      >/dev/null 2>&1 \
      || true
  fi

  git -C "$repo_root" worktree prune \
    >/dev/null 2>&1 \
    || true

  rm -rf \
    "$derived_data" \
    "$harness_bin"
}

trap cleanup EXIT INT TERM

git -C "$repo_root" worktree add \
  --detach \
  "$probe_root" \
  "$commit" \
  > "$evidence_dir/worktree.log" \
  2>&1

case "$probe_root" in
  *" "*)
    ;;
  *)
    echo "IOS_NATIVE_SPACE_PATH_NOT_ACTIVE" >&2
    exit 1
    ;;
esac

mobile="$probe_root/apps/mobile"

test ! -e "$mobile/ios"

(
  cd "$mobile"
  npm ci --audit=false
) > "$evidence_dir/npm-ci.log" 2>&1

expo_version="$(
  cd "$mobile"
  node -p \
    'require("./node_modules/expo/package.json").version'
)"

react_native_version="$(
  cd "$mobile"
  node -p \
    'require("./node_modules/react-native/package.json").version'
)"

(
  cd "$mobile"

  EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY=remote \
  EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE=test \
  EXPO_PUBLIC_NUTRITION_API_URL=http://127.0.0.1:8000 \
    npm exec -- \
    expo prebuild \
    --clean \
    --platform ios \
    --no-install
) > "$evidence_dir/prebuild.log" 2>&1

test -d "$mobile/ios"
test -f "$mobile/ios/Podfile"

project="$(
  find "$mobile/ios" \
    -maxdepth 1 \
    -name '*.xcodeproj' \
    -print |
    sed -n '1p'
)"

test -n "$project"
test -f "$project/project.pbxproj"

grep -Fq \
  "Expo Constants generates a CocoaPods script phase through" \
  "$mobile/ios/Podfile"

grep -Fq \
  "Nutrition App iOS path portability: React Native Info.plist discovery" \
  "$mobile/ios/Podfile"

grep -Fq \
  "Nutrition App iOS path portability: CocoaPods XCFramework diagnostics" \
  "$mobile/ios/Podfile"

grep -Fq \
  "Find.find(project_folder_path)" \
  "$mobile/ios/Podfile"

grep -Fq \
  "::NewArchitectureHelper.define_singleton_method" \
  "$mobile/ios/Podfile"

grep -Fq \
  'basename "$basepath"' \
  "$mobile/ios/Podfile"

grep -Fq \
  'REACT_NATIVE_XCODE_SCRIPT=' \
  "$project/project.pbxproj"

unsafe_bundle_count="$(
  grep -Fc \
    '"$NODE_BINARY" --print' \
    "$project/project.pbxproj" \
    || true
)"

test "$unsafe_bundle_count" -eq 0

(
  cd "$mobile"

  ./node_modules/.bin/expo-modules-autolinking \
    resolve \
    --platform apple \
    --json
) \
  > "$evidence_dir/autolinking.json" \
  2> "$evidence_dir/autolinking.stderr"

node - "$evidence_dir/autolinking.json" <<'NODE'
const fs = require("fs");

const path = process.argv[2];
const document = JSON.parse(
  fs.readFileSync(path, "utf8")
);

const matches = (document.modules || []).filter(
  (entry) => {
    const pods = (entry.pods || []).map(
      (pod) => pod.podName
    );

    const swiftModules =
      entry.swiftModuleNames || [];

    const classes = (entry.modules || []).map(
      (module) => module.class
    );

    return (
      entry.packageName === "nutrition-ocr" &&
      pods.includes("NutritionOcr") &&
      swiftModules.includes("NutritionOcr") &&
      classes.includes("NutritionOcrModule")
    );
  }
);

if (matches.length !== 1) {
  throw new Error(
    `NutritionOcr autolinking mismatch: ${matches.length}`
  );
}
NODE

(
  cd "$mobile/ios"
pod install
) > "$evidence_dir/pod-install.log" 2>&1

if grep -Fq \
  "find: " \
  "$evidence_dir/pod-install.log"
then
  echo "IOS_NATIVE_UNSAFE_FIND_OUTPUT" >&2
  exit 1
fi

test -f "$mobile/ios/Podfile.lock"

grep -Fq \
  "NutritionOcr" \
  "$mobile/ios/Podfile.lock"

grep -Fq \
  "ExpoModulesCore" \
  "$mobile/ios/Podfile.lock"

workspace="$(
  find "$mobile/ios" \
    -maxdepth 1 \
    -name '*.xcworkspace' \
    -print |
    sed -n '1p'
)"

test -n "$workspace"

scheme="$(
  basename "$project" .xcodeproj
)"

xcodebuild \
  -workspace "$workspace" \
  -list \
  -json \
  > "$evidence_dir/xcode-list.json" \
  2> "$evidence_dir/xcode-list.stderr"

node - "$evidence_dir/xcode-list.json" "$scheme" <<'NODE'
const fs = require("fs");

const document = JSON.parse(
  fs.readFileSync(
    process.argv[2],
    "utf8"
  )
);

const scheme = process.argv[3];
const schemes =
  document.workspace?.schemes || [];

if (!schemes.includes(scheme)) {
  throw new Error(
    `Generated scheme missing: ${scheme}`
  );
}
NODE

NODE_BINARY="$node_binary" \
  xcodebuild \
    -workspace "$workspace" \
    -scheme "$scheme" \
    -configuration Debug \
    -sdk iphonesimulator \
    -destination \
    "generic/platform=iOS Simulator" \
    -derivedDataPath \
    "$derived_data" \
    CODE_SIGNING_ALLOWED=NO \
    CODE_SIGNING_REQUIRED=NO \
    build \
    > "$evidence_dir/xcodebuild.log" \
    2>&1

grep -Fq \
  "BUILD SUCCEEDED" \
  "$evidence_dir/xcodebuild.log"

grep -Fq \
  "NutritionOcrModule.swift" \
  "$evidence_dir/xcodebuild.log"

grep -Fq \
  "NutritionOcrGeometry.swift" \
  "$evidence_dir/xcodebuild.log"

grep -Fq \
  "NutritionImageQuality.swift" \
  "$evidence_dir/xcodebuild.log"

mkdir -p "$harness_bin"

ios_source="$mobile/modules/nutrition-ocr/ios"
ios_tests="$mobile/modules/nutrition-ocr/ios-tests"

xcrun swiftc \
  "$ios_source/NutritionOcrGeometry.swift" \
  "$ios_tests/NutritionOcrGeometryTests.swift" \
  -framework ImageIO \
  -o "$harness_bin/geometry" \
  > "$evidence_dir/geometry-compile.log" \
  2>&1

"$harness_bin/geometry" \
  > "$evidence_dir/geometry-run.log" \
  2>&1

grep -Fq \
  "NutritionOcrGeometryTests passed" \
  "$evidence_dir/geometry-run.log"

xcrun swiftc \
  "$ios_source/NutritionImageQuality.swift" \
  "$ios_tests/NutritionImageQualityTests.swift" \
  -framework CoreGraphics \
  -framework ImageIO \
  -framework Vision \
  -o "$harness_bin/image-quality" \
  > "$evidence_dir/image-quality-compile.log" \
  2>&1

"$harness_bin/image-quality" \
  > "$evidence_dir/image-quality-run.log" \
  2>&1

grep -Fq \
  "NutritionImageQualityTests passed" \
  "$evidence_dir/image-quality-run.log"

xcrun swiftc \
  "$ios_source/NutritionOcrGeometry.swift" \
  "$ios_tests/NutritionOcrVisionRuntimeTests.swift" \
  -framework AppKit \
  -framework CoreImage \
  -framework ImageIO \
  -framework UniformTypeIdentifiers \
  -framework Vision \
  -o "$harness_bin/vision-runtime" \
  > "$evidence_dir/vision-runtime-compile.log" \
  2>&1

"$harness_bin/vision-runtime" \
  > "$evidence_dir/vision-runtime-run.log" \
  2>&1

grep -Fq \
  "NutritionOcrVisionRuntimeTests passed" \
  "$evidence_dir/vision-runtime-run.log"

tracked_status="$(
  git -C "$probe_root" status \
    --porcelain=v1 \
    -uno
)"

if test -n "$tracked_status"
then
  printf '%s\n' "$tracked_status" \
    > "$evidence_dir/generated-tracked-status.txt"

  echo "IOS_NATIVE_GENERATED_TRACKED_MUTATION" >&2
  exit 1
fi

elapsed_seconds="$(
  echo "$(( $(date +%s) - start_epoch ))"
)"

build_command="xcodebuild -workspace ios/${scheme}.xcworkspace -scheme ${scheme} -configuration Debug -sdk iphonesimulator -destination generic/platform=iOS Simulator CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO build"

cleanup
trap - EXIT INT TERM

test ! -e "$probe_root"

if test -n "$(
  git -C "$repo_root" status \
    --porcelain=v1 \
    -uall
)"
then
  echo "IOS_NATIVE_SOURCE_MUTATED" >&2
  exit 1
fi

export IOS_NATIVE_COMMIT="$commit"
export IOS_NATIVE_RUNNER="$runner"
export IOS_NATIVE_MACOS="$macos_version"
export IOS_NATIVE_ARCHITECTURE="$architecture"
export IOS_NATIVE_XCODE="$xcode_version"
export IOS_NATIVE_XCODE_BUILD="$xcode_build"
export IOS_NATIVE_SWIFT="$swift_version"
export IOS_NATIVE_NODE="$node_version"
export IOS_NATIVE_NPM="$npm_version"
export IOS_NATIVE_EXPO="$expo_version"
export IOS_NATIVE_REACT_NATIVE="$react_native_version"
export IOS_NATIVE_COCOAPODS="$cocoapods_version"
export IOS_NATIVE_SCHEME="$scheme"
export IOS_NATIVE_BUILD_COMMAND="$build_command"
export IOS_NATIVE_ELAPSED="$elapsed_seconds"

node <<'NODE' > "$manifest"
const document = {
  schema_version: 1,
  profile: "ios-native",
  commit: process.env.IOS_NATIVE_COMMIT,
  result: "PASS",
  runner: process.env.IOS_NATIVE_RUNNER,
  macos: process.env.IOS_NATIVE_MACOS,
  architecture:
    process.env.IOS_NATIVE_ARCHITECTURE,
  xcode: process.env.IOS_NATIVE_XCODE,
  xcode_build:
    process.env.IOS_NATIVE_XCODE_BUILD,
  swift: process.env.IOS_NATIVE_SWIFT,
  node: process.env.IOS_NATIVE_NODE,
  npm: process.env.IOS_NATIVE_NPM,
  expo: process.env.IOS_NATIVE_EXPO,
  react_native:
    process.env.IOS_NATIVE_REACT_NATIVE,
  cocoapods:
    process.env.IOS_NATIVE_COCOAPODS,
  generated_scheme:
    process.env.IOS_NATIVE_SCHEME,
  generated_build_command:
    process.env.IOS_NATIVE_BUILD_COMMAND,
  prebuild: "PASS",
  config_plugins: "PASS",
  pods: "PASS",
  simulator_build: "PASS",
  nutrition_ocr: {
    autolinking: "PASS",
    pod: "PASS",
    application_compilation: "PASS",
  },
  swift_harnesses: {
    geometry: "PASS",
    image_quality: "PASS",
    vision_runtime: "PASS",
  },
  space_path_regression: "PASS",
  generated_cleanup: "PASS",
  elapsed_seconds: Number(
    process.env.IOS_NATIVE_ELAPSED
  ),
};

process.stdout.write(
  JSON.stringify(
    document,
    null,
    2
  ) + "\n"
);
NODE

cat "$manifest"

echo "IOS_NATIVE_QUALIFICATION=PASS"

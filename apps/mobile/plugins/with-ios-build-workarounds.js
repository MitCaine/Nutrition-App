const { withDangerousMod, withPodfile } = require("expo/config-plugins");
const fs = require("fs");
const path = require("path");

const expoConstantsPathWorkaround = `
    # Nutrition App iOS path portability: Expo Constants
    # Expo Constants generates a CocoaPods script phase through \`bash -c\`.
    # When the repository path contains spaces, the expanded script path is
    # reparsed as command text and split at the space. Execute the script
    # directly with bash instead.
    installer.pods_project.targets.each do |target|
      next unless target.name == 'EXConstants'

      target.shell_script_build_phases.each do |phase|
        next unless phase.name == '[CP-User] Generate app.config for prebuilt Constants.manifest'

        phase.shell_script = phase.shell_script.gsub(
          'bash -l -c "$PODS_TARGET_SRCROOT/../scripts/get-app-config-ios.sh"',
          'bash -l "$PODS_TARGET_SRCROOT/../scripts/get-app-config-ios.sh"',
        )
      end
    end
`;

const reactNativeInfoPlistPathWorkaround = `
    # Nutrition App iOS path portability: React Native Info.plist discovery
    # React Native shells out using an unescaped projectFolderPath.
    # Walk the tree through Ruby so a checkout path
    # containing spaces is passed as data rather than reparsed as shell input.
    require 'find'

    # CocoaPods evaluates Podfiles with Pod::Podfile in the lexical nesting.
    # Use the already-loaded top-level React Native helper explicitly; a bare
    # class NewArchitectureHelper here would define Pod::Podfile::NewArchitectureHelper
    # and leave react_native_post_install's helper unchanged.
    ::NewArchitectureHelper.define_singleton_method(:set_RCTNewArchEnabled_in_info_plist) do |installer, new_arch_enabled|
        project_paths = installer.aggregate_targets
          .map { |target| target.user_project }
          .uniq { |project| project.path }
          .map { |project| project.path }
        excluded_info_plist = [
          "/Pods",
          "Tests",
          "metainternal",
          ".bundle",
          "build/",
          "DerivedData/",
          ".xcframework",
          ".framework",
          "watchkitapp",
          "today-extention",
        ]

        project_paths.each do |project_path|
          project_folder_path = File.dirname(project_path)
          info_plist_files = []
          Find.find(project_folder_path) do |candidate|
            info_plist_files << candidate if File.file?(candidate) && File.basename(candidate) == "Info.plist"
          end

          info_plist_files.each do |info_plist_file|
            should_skip = excluded_info_plist.any? do |excluded|
              info_plist_file.include?(excluded)
            end
            next if should_skip

            begin
              info_plist = Xcodeproj::Plist.read_from_path(info_plist_file)
            rescue StandardError => e
              Pod::UI.warn("Failed to read Info.plist at #{info_plist_file}: #{e.message}")
              next
            end

            if info_plist["RCTNewArchEnabled"] && info_plist["RCTNewArchEnabled"] == new_arch_enabled
              next
            end

            info_plist["RCTNewArchEnabled"] = new_arch_enabled ? true : false
            Xcodeproj::Plist.write_to_path(info_plist, info_plist_file)
          end
        end
    end
`;

const expoPrecompiledXcframeworkPathWorkaround = `
    # Nutrition App iOS path portability: CocoaPods XCFramework diagnostics
    # CocoaPods leaves the basepath argument to basename unquoted in generated
    # XCFramework copy scripts. Quote that argument for every generated pod
    # phase so precompiled Expo modules remain safe in paths containing spaces.
    installer.pods_project.targets.each do |target|
      target.shell_script_build_phases.each do |phase|
        basepath_token = '\${' + 'basepath}'
        unsafe_basename = "basename #{basepath_token}"
        next unless phase.shell_script.to_s.include?(unsafe_basename)

        phase.shell_script = phase.shell_script.gsub(
          unsafe_basename,
          'basename "$basepath"',
        )
      end
    end
`;

const expoConstantsPathMarker =
  "Nutrition App iOS path portability: Expo Constants";
const reactNativeInfoPlistPathMarker =
  "Nutrition App iOS path portability: React Native Info.plist discovery";
const reactNativeInfoPlistImplementationMarker =
  "::NewArchitectureHelper.define_singleton_method";
const expoPrecompiledXcframeworkPathMarker =
  "Nutrition App iOS path portability: CocoaPods XCFramework diagnostics";
const legacyExpoConstantsPathMarker =
  "Expo Constants generates a CocoaPods script phase through";

const brokenBundleScriptPattern =
  /`\\"\$NODE_BINARY\\" --print \\"require\('path'\)\.dirname\(require\.resolve\('react-native\/package\.json'\)\) \+ '\/scripts\/react-native-xcode\.sh'\\"`\\n\\n/g;

function insertBeforeExactlyOnce(contents, anchor, block, description) {
  const occurrences = contents.split(anchor).length - 1;

  if (occurrences !== 1) {
    throw new Error(
      `Expected exactly one ${description}, found ${occurrences}.`,
    );
  }

  return contents.replace(anchor, `${block}\n${anchor}`);
}

function replaceMarkedBlockBeforeAnchor(
  contents,
  startMarker,
  endAnchor,
  replacement,
  description,
) {
  const startOccurrences = contents.split(startMarker).length - 1;
  if (startOccurrences !== 1) {
    throw new Error(
      `Expected exactly one ${description} start, found ${startOccurrences}.`,
    );
  }

  const start = contents.indexOf(startMarker);
  const end = contents.indexOf(endAnchor, start + startMarker.length);
  if (end === -1) {
    throw new Error(`Could not find the end of the ${description}.`);
  }

  return `${contents.slice(0, start)}${replacement}\n\n${contents.slice(end)}`;
}

function applyIosPodfileWorkarounds(contents) {
  const postInstallAnchor = "  post_install do |installer|\n";
  const reactNativePostInstallAnchor = "    react_native_post_install(\n";
  const postInstallOccurrences = contents.split(postInstallAnchor).length - 1;

  if (postInstallOccurrences !== 1) {
    throw new Error(
      `Expected exactly one Podfile post_install block, found ${postInstallOccurrences}.`,
    );
  }

  let updated = contents;

  if (
    !updated.includes(expoConstantsPathMarker) &&
    !updated.includes(legacyExpoConstantsPathMarker)
  ) {
    updated = updated.replace(
      postInstallAnchor,
      `${postInstallAnchor}${expoConstantsPathWorkaround}\n`,
    );
  }

  if (!updated.includes(reactNativeInfoPlistImplementationMarker)) {
    if (updated.includes(reactNativeInfoPlistPathMarker)) {
      const reactNativeBlockEnd = updated.includes(
        expoPrecompiledXcframeworkPathMarker,
      )
        ? `    # ${expoPrecompiledXcframeworkPathMarker}`
        : reactNativePostInstallAnchor;

      updated = replaceMarkedBlockBeforeAnchor(
        updated,
        `    # ${reactNativeInfoPlistPathMarker}`,
        reactNativeBlockEnd,
        reactNativeInfoPlistPathWorkaround,
        "React Native Info.plist workaround",
      );
    } else {
      updated = insertBeforeExactlyOnce(
        updated,
        reactNativePostInstallAnchor,
        reactNativeInfoPlistPathWorkaround,
        "react_native_post_install call",
      );
    }
  }

  if (!updated.includes(expoPrecompiledXcframeworkPathMarker)) {
    updated = insertBeforeExactlyOnce(
      updated,
      reactNativePostInstallAnchor,
      expoPrecompiledXcframeworkPathWorkaround,
      "react_native_post_install call",
    );
  }

  return updated;
}

function withIosPodfileBuildWorkaround(config) {
  return withPodfile(config, (podfileConfig) => {
    podfileConfig.modResults.contents = applyIosPodfileWorkarounds(
      podfileConfig.modResults.contents,
    );

    return podfileConfig;
  });
}

function withIosBundleScriptPathWorkaround(config) {
  return withDangerousMod(config, [
    "ios",
    (dangerousConfig) => {
      const iosRoot = dangerousConfig.modRequest.platformProjectRoot;
      const appName = dangerousConfig.modRequest.projectName;
      const projectFile = path.join(
        iosRoot,
        `${appName}.xcodeproj`,
        "project.pbxproj",
      );

      if (!fs.existsSync(projectFile)) {
        return dangerousConfig;
      }

      const contents = fs.readFileSync(projectFile, "utf8");

      if (contents.includes("REACT_NATIVE_XCODE_SCRIPT=")) {
        return dangerousConfig;
      }

      const matches = contents.match(brokenBundleScriptPattern) ?? [];

      if (matches.length !== 1) {
        throw new Error(
          `Expected exactly one unsafe React Native bundle script, found ${matches.length}.`,
        );
      }

      const fixed =
        'REACT_NATIVE_XCODE_SCRIPT=\\"$(\\"$NODE_BINARY\\" --print \\"require(\\\'path\\\').dirname(require.resolve(\\\'react-native/package.json\\\')) + \\\'/scripts/react-native-xcode.sh\\\'\\")\\"\\n/bin/sh \\"$REACT_NATIVE_XCODE_SCRIPT\\"\\n\\n';

      fs.writeFileSync(
        projectFile,
        contents.replace(brokenBundleScriptPattern, fixed),
      );

      return dangerousConfig;
    },
  ]);
}

module.exports = function withIosBuildWorkarounds(config) {
  config = withIosPodfileBuildWorkaround(config);
  config = withIosBundleScriptPathWorkaround(config);
  return config;
};

module.exports.applyIosPodfileWorkarounds = applyIosPodfileWorkarounds;

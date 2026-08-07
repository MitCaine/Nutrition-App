const { withDangerousMod, withPodfile } = require("expo/config-plugins");
const fs = require("fs");
const path = require("path");

const expoConstantsPathWorkaround = `
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

const brokenBundleScriptPattern =
  /`\\"\$NODE_BINARY\\" --print \\"require\('path'\)\.dirname\(require\.resolve\('react-native\/package\.json'\)\) \+ '\/scripts\/react-native-xcode\.sh'\\"`\\n\\n/g;

function withIosPodfileBuildWorkaround(config) {
  return withPodfile(config, (podfileConfig) => {
    const anchor = "  post_install do |installer|\n";
    const contents = podfileConfig.modResults.contents;
    const occurrences = contents.split(anchor).length - 1;

    if (occurrences !== 1) {
      throw new Error(
        `Expected exactly one Podfile post_install block, found ${occurrences}.`,
      );
    }

    if (contents.includes("Expo Constants generates a CocoaPods script phase through")) {
      return podfileConfig;
    }

    podfileConfig.modResults.contents = contents.replace(
      anchor,
      `${anchor}${expoConstantsPathWorkaround}\n`,
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

const { withDangerousMod, withPodfile } = require("expo/config-plugins");
const fs = require("fs");
const path = require("path");

const podfileBlock = `
    # Temporary workaround for the Xcode 26.4 / React Native bundled fmt incompatibility.
    # Remove this when React Native upgrades its fmt dependency or otherwise supports
    # Xcode 26.4 without fmt consteval compilation failures.
    installer.pods_project.targets.each do |target|
      next unless target.name == 'fmt'

      target.build_configurations.each do |config|
        config.build_settings['CLANG_CXX_LANGUAGE_STANDARD'] = 'c++17'
      end
    end

    # React Native 0.79's generated ReactCodegen script invokes absolute script
    # paths through with-environment.sh. That helper executes its first argument
    # unquoted, so checkouts in paths with spaces (for example "Nutrition App")
    # fail during Xcode builds. Keep this scoped to the ReactCodegen generated
    # script phase and remove it when React Native quotes that invocation.
    installer.pods_project.targets.each do |target|
      next unless target.name == 'ReactCodegen'

      target.shell_script_build_phases.each do |phase|
        next unless phase.name == '[CP-User] Generate Specs'

        broken_script = <<~'SCRIPT'
          SCRIPT_PHASES_SCRIPT="$RCT_SCRIPT_RN_DIR/scripts/react_native_pods_utils/script_phases.sh"
          WITH_ENVIRONMENT="$RCT_SCRIPT_RN_DIR/scripts/xcode/with-environment.sh"
          /bin/sh -c "$WITH_ENVIRONMENT $SCRIPT_PHASES_SCRIPT"
        SCRIPT

        fixed_script = <<~'SCRIPT'
          SCRIPT_PHASES_SCRIPT_DIR="$RCT_SCRIPT_RN_DIR/scripts/react_native_pods_utils"
          WITH_ENVIRONMENT="$RCT_SCRIPT_RN_DIR/scripts/xcode/with-environment.sh"
          (
            cd "$SCRIPT_PHASES_SCRIPT_DIR"
            /bin/sh "$WITH_ENVIRONMENT" ./script_phases.sh
          )
        SCRIPT

        phase.shell_script = phase.shell_script.gsub(broken_script, fixed_script)
      end
    end

    # Expo Constants generates a script phase using \`bash -c\` with an unquoted
    # absolute path. In checkouts with spaces, that fails before the app builds.
    # Keep this scoped to EXConstants and remove it when Expo quotes this phase.
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

function withIosPodfileBuildWorkarounds(config) {
  return withPodfile(config, (podfileConfig) => {
    if (podfileConfig.modResults.contents.includes("Xcode 26.4 / React Native bundled fmt incompatibility")) {
      return podfileConfig;
    }

    const anchor = "    # This is necessary for Xcode 14, because it signs resource bundles by default";
    if (!podfileConfig.modResults.contents.includes(anchor)) {
      throw new Error("Could not find Podfile post_install insertion point for iOS build workarounds.");
    }

    podfileConfig.modResults.contents = podfileConfig.modResults.contents.replace(anchor, `${podfileBlock}\n${anchor}`);
    return podfileConfig;
  });
}

function withIosBundleScriptPathWorkaround(config) {
  return withDangerousMod(config, [
    "ios",
    (dangerousConfig) => {
      const iosRoot = dangerousConfig.modRequest.platformProjectRoot;
      const appName = dangerousConfig.modRequest.projectName;
      const projectFile = path.join(iosRoot, `${appName}.xcodeproj`, "project.pbxproj");

      if (!fs.existsSync(projectFile)) {
        return dangerousConfig;
      }

      let contents = fs.readFileSync(projectFile, "utf8");
      if (contents.includes("REACT_NATIVE_XCODE_SCRIPT=")) {
        return dangerousConfig;
      }

      const fixed =
        'REACT_NATIVE_XCODE_SCRIPT=\\"$(\\"$NODE_BINARY\\" --print \\"require(\\\'path\\\').dirname(require.resolve(\\\'react-native/package.json\\\')) + \\\'/scripts/react-native-xcode.sh\\\'\\")\\"\\n/bin/sh \\"$REACT_NATIVE_XCODE_SCRIPT\\"\\n\\n';

      contents = contents.replace(brokenBundleScriptPattern, fixed);
      fs.writeFileSync(projectFile, contents);
      return dangerousConfig;
    },
  ]);
}

module.exports = function withIosBuildWorkarounds(config) {
  config = withIosPodfileBuildWorkarounds(config);
  config = withIosBundleScriptPathWorkaround(config);
  return config;
};

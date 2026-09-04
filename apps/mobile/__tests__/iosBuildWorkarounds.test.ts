const { readFileSync } = require("node:fs") as {
  readFileSync(path: string, encoding: "utf8"): string;
};
const path = require("node:path") as {
  join(...parts: string[]): string;
};
const { spawnSync } = require("node:child_process") as {
  spawnSync(
    command: string,
    args: string[],
    options: { input: string; encoding: "utf8" },
  ): { status: number | null; stdout: string; stderr: string };
};

const { applyIosPodfileWorkarounds } = require(
  "../plugins/with-ios-build-workarounds",
) as {
  applyIosPodfileWorkarounds(contents: string): string;
};

const BASE_PODFILE = [
  "target 'NutritionApp' do",
  "  post_install do |installer|",
  "    react_native_post_install(",
  "      installer,",
  "    )",
  "  end",
  "end",
  "",
].join("\n");

test("renders and executes whitespace-safe CocoaPods path workarounds", () => {
  const rendered = applyIosPodfileWorkarounds(BASE_PODFILE);
  const reactNativePostInstallSource = readFileSync(
    path.join(
      process.cwd(),
      "node_modules/react-native/scripts/react_native_pods.rb",
    ),
    "utf8",
  );
  const reactNativeInfoPlistSource = readFileSync(
    path.join(
      process.cwd(),
      "node_modules/react-native/scripts/cocoapods/new_architecture.rb",
    ),
    "utf8",
  );

  expect(reactNativePostInstallSource).toContain(
    "NewArchitectureHelper.set_RCTNewArchEnabled_in_info_plist(installer, NewArchitectureHelper.new_arch_enabled)",
  );
  expect(reactNativeInfoPlistSource).toContain(
    'infoPlistFiles = `find #{projectFolderPath} -name "Info.plist"`',
  );

  expect(rendered).toContain("Find.find(project_folder_path)");
  expect(rendered).not.toContain("infoPlistFiles = `find");
  expect(rendered).toContain(
    "::NewArchitectureHelper.define_singleton_method",
  );
  expect(rendered).not.toContain("\n    class NewArchitectureHelper\n");
  expect(rendered).toContain('basename "$basepath"');
  expect(rendered).not.toContain("basename ${basepath}");
  expect(rendered).toContain(
    'bash -l "$PODS_TARGET_SRCROOT/../scripts/get-app-config-ios.sh"',
  );

  const rubySyntax = spawnSync("ruby", ["-c", "-"], {
    input: rendered,
    encoding: "utf8",
  });

  expect(rubySyntax.status).toBe(0);
  expect(applyIosPodfileWorkarounds(rendered)).toBe(rendered);

  const reactNativeMarker =
    "    # Nutrition App iOS path portability: React Native Info.plist discovery";
  const xcframeworkMarker =
    "    # Nutrition App iOS path portability: CocoaPods XCFramework diagnostics";
  const reactNativeMarkerStart = rendered.indexOf(reactNativeMarker);
  const xcframeworkMarkerStart = rendered.indexOf(
    xcframeworkMarker,
    reactNativeMarkerStart,
  );
  const legacyRendered = [
    rendered.slice(0, reactNativeMarkerStart),
    [
      reactNativeMarker,
      "    class NewArchitectureHelper",
      "      def self.set_RCTNewArchEnabled_in_info_plist(installer, new_arch_enabled)",
      "      end",
      "    end",
      "",
    ].join("\n"),
    rendered.slice(xcframeworkMarkerStart),
  ].join("");
  const migrated = applyIosPodfileWorkarounds(legacyRendered);

  expect(migrated).toContain(
    "::NewArchitectureHelper.define_singleton_method",
  );
  expect(migrated).not.toContain("\n    class NewArchitectureHelper\n");
  expect(applyIosPodfileWorkarounds(migrated)).toBe(migrated);

  const workaroundStart = rendered.indexOf(reactNativeMarker);
  const workaroundEnd = rendered.indexOf(xcframeworkMarker, workaroundStart);
  const reactNativeWorkaround = rendered
    .slice(workaroundStart, workaroundEnd)
    .replace(/^    /gm, "");
  const rubyHarness = [
    "require 'fileutils'",
    "require 'tmpdir'",
    "",
    "class NewArchitectureHelper",
    "  def self.set_RCTNewArchEnabled_in_info_plist(installer, _new_arch_enabled)",
    "    `find #{installer.project_folder} -name \"Info.plist\"`",
    "    puts 'UPSTREAM_SHELL_FIND'",
    "  end",
    "end",
    "",
    "def react_native_post_install(installer, _react_native_path = nil)",
    "  NewArchitectureHelper.set_RCTNewArchEnabled_in_info_plist(installer, true)",
    "end",
    "",
    "module Pod",
    "  class Podfile",
    "    def self.evaluate(contents)",
    "      podfile = new",
    "      podfile.instance_eval { eval(contents, nil, 'Podfile') }",
    "      podfile",
    "    end",
    "",
    "    def post_install(&block)",
    "      @post_install_callback = block",
    "    end",
    "",
    "    def run_post_install(installer)",
    "      @post_install_callback.call(installer)",
    "    end",
    "  end",
    "end",
    "",
    "Installer = Struct.new(:project_folder, :project_path) do",
    "  def aggregate_targets",
    "    [Struct.new(:user_project).new(Struct.new(:path).new(project_path))]",
    "  end",
    "end",
    "",
    "project_root = Dir.mktmpdir('nutrition app')",
    "project_folder = File.join(project_root, 'Nutrition App')",
    "Dir.mkdir(project_folder)",
    "project_path = File.join(project_folder, 'NutritionApp.xcodeproj')",
    "begin",
    "  podfile = Pod::Podfile.evaluate(<<~'PODFILE')",
    "post_install do |installer|",
    reactNativeWorkaround,
    "  react_native_post_install(installer, nil)",
    "end",
    "PODFILE",
    "  podfile.run_post_install(Installer.new(project_folder, project_path))",
    "ensure",
    "  FileUtils.remove_entry(project_root)",
    "end",
  ].join("\n");
  const rubyPathExecution = spawnSync("ruby", ["-"], {
    input: rubyHarness,
    encoding: "utf8",
  });

  expect(rubyPathExecution.status).toBe(0);
  expect(rubyPathExecution.stdout).not.toContain("UPSTREAM_SHELL_FIND");
  expect(rubyPathExecution.stderr).not.toContain("find:");
});

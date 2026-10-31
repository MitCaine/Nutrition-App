/* Repository support boundary for the scoped Expo CLI Zod compatibility exception.
 * Exercise installed callers, not replicas. Revisit when Expo adds a Zod caller
 * or an optional MCP transport is introduced into the selected dependency graph.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");

const root = path.resolve(__dirname, "..");
const lock = require(path.join(root, "package-lock.json"));
const app = require(path.join(root, "package.json"));
const fromApp = createRequire(path.join(root, "package.json"));
const cliRoot = path.dirname(fromApp.resolve("@expo/cli/package.json"));
const fromCli = createRequire(path.join(cliRoot, "package.json"));
const version = fromApp("zod/package.json").version;
assert.equal(version, "4.6.7");
assert.equal(app.dependencies.zod, version);
assert.deepEqual(app.overrides["@expo/cli"], { zod: "$zod" });
assert.equal(fromCli.resolve("zod"), fromApp.resolve("zod"));
assert.equal(lock.packages["node_modules/postcss"].version, "8.5.30");
assert.deepEqual(Object.entries(lock.packages)
  .filter(([name]) => /(?:^|\/)node_modules\/zod$/.test(name))
  .map(([name, value]) => [name, value.version]), [["node_modules/zod", version]]);
assert.ok(!Object.keys(lock.packages).some((name) => name.endsWith("/expo-mcp")),
  "An optional MCP transport needs separate compatibility qualification");

const imports = [];
function inspect(directory) {
  for (const item of fs.readdirSync(directory, { withFileTypes: true })) {
    const filename = path.join(directory, item.name);
    if (item.isDirectory()) inspect(filename);
    else if (item.isFile() && item.name.endsWith(".js")) {
      const source = fs.readFileSync(filename, "utf8");
      const matches = [...source.matchAll(/require\(["'](zod(?:\/[^"']*)?)["']\)/g)];
      for (const match of matches) {
        assert.equal(match[1], "zod", "Legacy/subpath Zod engines need explicit review");
        imports.push(path.relative(cliRoot, filename).split(path.sep).join("/"));
      }
    }
  }
}
inspect(path.join(cliRoot, "build"));
assert.deepEqual(imports.sort(), [
  "build/src/start/server/DevToolsPlugin.schema.js",
  "build/src/start/server/createMCPDevToolsExtensionSchema.js",
]);

const { PluginSchema, DevToolsPluginOutputSchema } = fromCli("./build/src/start/server/DevToolsPlugin.schema.js");
const { createMCPDevToolsExtensionSchema } = fromCli("./build/src/start/server/createMCPDevToolsExtensionSchema.js");
const { DevToolsPlugin } = fromCli("./build/src/start/server/DevToolsPlugin.js");
const { addMcpCapabilities } = fromCli("./build/src/start/server/MCPDevToolsPluginCLIExtensions.js");
const plugin = {
  packageName: "nutrition-compatibility-fixture",
  packageRoot: root,
  cliExtensions: {
    description: "Contract fixture; no plugin commands are executed",
    entryPoint: "not-executed.cjs",
    commands: [
      { name: "inspect", title: "Inspect", environments: ["mcp"], parameters: [
        { name: "text", type: "text" },
        { name: "count", type: "number" },
        { name: "confirm", type: "confirm" },
      ] },
      { name: "local-only", title: "CLI only", environments: ["cli"] },
    ],
  },
};
const parsed = PluginSchema.parse(plugin);
assert.deepEqual(parsed, plugin);
assert.ok(Object.isFrozen(parsed.cliExtensions.commands[0].environments));
assert.ok(!PluginSchema.safeParse({ ...plugin, packageName: "" }).success);
assert.ok(!PluginSchema.safeParse({ ...plugin, cliExtensions: { ...plugin.cliExtensions, commands: [] } }).success);
assert.ok(!PluginSchema.safeParse({ ...plugin, cliExtensions: { ...plugin.cliExtensions,
  commands: [{ name: "bad", title: "Bad", environments: ["remote"] }] } }).success);
assert.equal(new DevToolsPlugin(plugin, root).packageName, plugin.packageName);
assert.throws(() => new DevToolsPlugin({ ...plugin, packageName: "" }, root), /Invalid plugin configuration/);
assert.throws(() => createMCPDevToolsExtensionSchema({ packageName: "empty" }), /no commands/);

const outputs = [
  { type: "text", text: "ok", level: "info" },
  { type: "image", url: "https://example.invalid/image.png", text: "image" },
  { type: "audio", url: "https://example.invalid/audio.wav" },
];
assert.deepEqual(DevToolsPluginOutputSchema.parse(outputs), outputs);
assert.ok(!DevToolsPluginOutputSchema.safeParse([{ type: "text", text: "bad", level: "fatal" }]).success);
assert.ok(!DevToolsPluginOutputSchema.safeParse([{ type: "image", url: "not a URL" }]).success);

(async () => {
  const registered = [];
  await addMcpCapabilities({ registerTool: (...args) => registered.push(args) }, {
    projectRoot: root,
    devtoolsPluginManager: { queryPluginsAsync: async () => [plugin] },
  });
  assert.equal(registered.length, 1);
  assert.equal(registered[0][0], plugin.packageName);
  const schema = registered[0][1].inputSchema.parameters;
  assert.deepEqual(schema.parse({ command: "inspect" }), { command: "inspect" });
  const valid = { command: "inspect", text: "item", count: 1, confirm: true };
  assert.deepEqual(schema.parse(valid), valid);
  for (const invalid of [{}, { command: "local-only" }, { command: "unknown" },
    { command: "inspect", count: "1" }, { command: "inspect", confirm: "true" },
    { command: "inspect", unexpected: true }]) {
    assert.ok(!schema.safeParse(invalid).success, JSON.stringify(invalid));
  }
  const json = fromApp("zod").toJSONSchema(schema);
  assert.equal(json.additionalProperties, false);
  assert.deepEqual(json.properties.command.enum, ["inspect"]);
  console.log("PASS: Zod4.6.7 only; PostCSS8.5.30; installed Expo schema/plugin/MCP-registration contracts");
  console.log("LIMIT: optional uninstalled MCP transport and command execution are not exercised");
})().catch((error) => { console.error(error); process.exitCode = 1; });

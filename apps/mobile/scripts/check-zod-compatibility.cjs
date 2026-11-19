/* Repository support boundary for the scoped Expo CLI Zod compatibility exception.
 * Exercise installed callers, not replicas. Since @expo/cli 57.0.34 the CLI declares no
 * Zod dependency: DevTools plugin schemas are JSON Schemas checked by @expo/schema-utils,
 * and Zod is only resolved at runtime from the optional expo-mcp package, then injected
 * into the MCP schema builders. Revisit when Expo adds a static Zod caller or an optional
 * MCP transport is introduced into the selected dependency graph.
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

const cliPackage = fromApp("@expo/cli/package.json");
assert.equal(cliPackage.dependencies?.zod, undefined, "Expo CLI Zod dependency needs explicit review");
assert.equal(cliPackage.peerDependenciesMeta?.["expo-mcp"]?.optional, true);
const schemaUtilsPackage = fromCli("@expo/schema-utils/package.json");
assert.ok(!Object.keys({ ...schemaUtilsPackage.dependencies, ...schemaUtilsPackage.peerDependencies }).includes("zod"),
  "@expo/schema-utils Zod dependency needs explicit review");

const callers = [];
function inspect(directory) {
  for (const item of fs.readdirSync(directory, { withFileTypes: true })) {
    const filename = path.join(directory, item.name);
    if (item.isDirectory()) inspect(filename);
    else if (item.isFile() && item.name.endsWith(".js")) {
      const source = fs.readFileSync(filename, "utf8");
      assert.ok(!/(?:require\(|import\(|from\s)["']zod(?:\/[^"']*)?["']/.test(source),
        "Static Zod engines need explicit review: " + filename);
      if (/['"]zod['"]/.test(source)) callers.push(path.relative(cliRoot, filename).split(path.sep).join("/"));
    }
  }
}
inspect(path.join(cliRoot, "build"));
assert.deepEqual(callers.sort(), ["build/src/start/server/mcp/MCP.js"]);
const mcpSource = fs.readFileSync(path.join(cliRoot, "build/src/start/server/mcp/MCP.js"), "utf8");
assert.match(mcpSource, /resolveFrom\)\(_nodepath\(\)\.default\.dirname\(mcpPackagePath\), 'zod'\)/,
  "Expo CLI must resolve Zod only through expo-mcp");

const { validate } = fromCli("@expo/schema-utils");
const { PluginSchema, DevToolsPluginOutputSchema } = fromCli("./build/src/start/server/devtools/DevToolsPlugin.schema.js");
const { createMCPDevToolsExtensionSchema } = fromCli("./build/src/start/server/mcp/createMCPDevToolsExtensionSchema.js");
const { DevToolsPlugin } = fromCli("./build/src/start/server/devtools/DevToolsPlugin.js");
const { addMcpCapabilities } = fromCli("./build/src/start/server/mcp/MCPDevToolsPluginCLIExtensions.js");
// MCP.js injects the `z` export of the Zod module it resolves (`const { z } = ...`).
const { z } = fromApp("zod");
assert.match(mcpSource, /const \{ z \} = await \(0, _requireutils\(\)\.loadModule\)\(zodPackagePath\)/);
const accepts = (schema, value) => { try { validate(schema, value); return true; } catch { return false; } };
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
assert.ok(accepts(PluginSchema, plugin));
assert.ok(!accepts(PluginSchema, { ...plugin, packageName: "" }));
assert.ok(!accepts(PluginSchema, { ...plugin, cliExtensions: { ...plugin.cliExtensions, commands: [] } }));
assert.ok(!accepts(PluginSchema, { ...plugin, cliExtensions: { ...plugin.cliExtensions,
  commands: [{ name: "bad", title: "Bad", environments: ["remote"] }] } }));
assert.equal(new DevToolsPlugin(plugin, root).packageName, plugin.packageName);
assert.throws(() => new DevToolsPlugin({ ...plugin, packageName: "" }, root), /Invalid plugin configuration/);
assert.throws(() => createMCPDevToolsExtensionSchema({ packageName: "empty" }, z), /no commands/);

const outputs = [
  { type: "text", text: "ok", level: "info" },
  { type: "image", url: "https://example.invalid/image.png", text: "image" },
  { type: "audio", url: "https://example.invalid/audio.wav" },
];
assert.ok(accepts(DevToolsPluginOutputSchema, outputs));
assert.ok(!accepts(DevToolsPluginOutputSchema, [{ type: "text", text: "bad", level: "fatal" }]));
assert.ok(!accepts(DevToolsPluginOutputSchema, [{ type: "image", url: "not a URL" }]));

(async () => {
  const registered = [];
  await addMcpCapabilities({ registerTool: (...args) => registered.push(args) }, {
    projectRoot: root,
    devtoolsPluginManager: { queryPluginsAsync: async () => [plugin] },
  }, z);
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
  const json = z.toJSONSchema(schema);
  assert.equal(json.additionalProperties, false);
  assert.deepEqual(json.properties.command.enum, ["inspect"]);
  console.log("PASS: Zod4.6.7 only; PostCSS8.5.30; installed Expo JSON-schema/plugin/injected-Zod MCP-registration contracts");
  console.log("LIMIT: optional uninstalled MCP transport and command execution are not exercised");
})().catch((error) => { console.error(error); process.exitCode = 1; });

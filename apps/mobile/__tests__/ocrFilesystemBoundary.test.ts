const { readFileSync } = require("node:fs") as { readFileSync(path: string, encoding: "utf8"): string };
const { join, dirname } = require("node:path") as { join(...paths: string[]): string; dirname(path: string): string };
const resolveModule = require as unknown as { resolve(name: string): string };

const mockNativeDelete = jest.fn();
// The React Native Jest preset excludes dependency TypeScript. Compile only these
// installed API resources with the already selected TypeScript compiler; substitute
// the native bridge, not deleteAsync or the public legacy exports.
const ts = require("typescript") as typeof import("typescript");
const packageRoot = dirname(resolveModule.resolve("expo-file-system/package.json"));
const installedModules: Record<string, { exports: Record<string, unknown> }> = {};
function installedApi(relative: string): Record<string, unknown> {
  if (installedModules[relative]) return installedModules[relative].exports;
  const module = { exports: {} as Record<string, unknown> };
  installedModules[relative] = module;
  const code = ts.transpileModule(readFileSync(join(packageRoot, relative), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const apiRequire = (name: string): unknown => {
    if (name === "./ExponentFileSystem") return { default: { deleteAsync: (...args: unknown[]) => mockNativeDelete(...args) }, __esModule: true };
    if (name === "./FileSystem") return installedApi("src/legacy/FileSystem.ts");
    if (name === "./FileSystem.types") return installedApi("src/legacy/FileSystem.types.ts");
    if (name === "expo-modules-core" || name === "react-native") return require(name);
    throw new Error(`Unexpected installed filesystem import: ${name}`);
  };
  new Function("module", "exports", "require", code)(module, module.exports, apiRequire);
  return module.exports;
}
const legacy = installedApi("src/legacy/index.ts") as unknown as typeof import("expo-file-system/legacy");
const rootWarnings = installedApi("src/legacyWarnings.ts") as unknown as {
  deleteAsync(uri: string, options: { idempotent: boolean }): Promise<void>;
};

beforeEach(() => mockNativeDelete.mockReset());

test("the installed supported legacy API reaches native deletion with idempotent options", async () => {
  mockNativeDelete.mockResolvedValue(undefined);
  await expect(legacy.deleteAsync("file:///camera-cache.jpg", { idempotent: true })).resolves.toBeUndefined();
  expect(mockNativeDelete).toHaveBeenCalledWith("file:///camera-cache.jpg", { idempotent: true });
});

test("native deletion failure is propagated by the real installed legacy API", async () => {
  const failure = new Error("native deletion failed");
  mockNativeDelete.mockRejectedValue(failure);
  await expect(legacy.deleteAsync("file:///camera-cache.jpg", { idempotent: true })).rejects.toBe(failure);
});

test("root deletion is a throwing stub and every OCR caller explicitly selects legacy", async () => {
  const warning = jest.spyOn(console, "warn").mockImplementation(() => undefined);
  try {
    await expect(rootWarnings.deleteAsync("file:///nonexistent.jpg", { idempotent: true })).rejects.toThrow("expo-file-system/legacy");
    expect(mockNativeDelete).not.toHaveBeenCalled();
    expect(readFileSync(join(packageRoot, "src/index.ts"), "utf8")).toContain("'./legacyWarnings'");
    for (const caller of ["components/NutritionCameraCapture.tsx", "screens/NutritionScanScreen.tsx", "diagnostics/OcrDiagnosticsScreen.tsx"]) {
      const source = readFileSync(join(packageRoot, "../../src/features/ocr", caller), "utf8");
      expect(source).toContain('import * as FileSystem from "expo-file-system/legacy";');
      expect(source).not.toContain('from "expo-file-system"');
    }
  } finally {
    warning.mockRestore();
  }
});

const { mkdtempSync, rmSync, readFileSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");
const resolveModule = require as unknown as { resolve(path: string): string };
const { spawnSync } = require("node:child_process");

// Portable desktop subprocess evidence; no Expo/device or rendered-query claim.
test("mixed-basis literal nutrition/history controls survive publication and reopen", () => {
  const directory = mkdtempSync(join(tmpdir(), "nutrition-acceptedNutritionMatrix-"));
  try {
    const child = spawnSync(process.execPath, [resolveModule.resolve("./fixtures/acceptedNutritionMatrix.cjs"), ...[directory]], {
      encoding: "utf8", timeout: 60000, maxBuffer: 8 * 1024 * 1024,
    });
    if (child.error || child.status !== 0) throw new Error(`${child.error ?? "fixture failed"}
${child.stdout}
${child.stderr}`);
    const results = JSON.parse(readFileSync(join(directory, "results.json"), "utf8"));
    expect(results.checks).toHaveLength(85);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}, 80000);

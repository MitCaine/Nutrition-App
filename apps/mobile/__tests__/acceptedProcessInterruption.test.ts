const { mkdtempSync, rmSync, readFileSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");
const resolveModule = require as unknown as { resolve(path: string): string };
const { spawnSync } = require("node:child_process");

// Portable desktop subprocess evidence; no Expo/device or rendered-query claim.
test("16 actual SIGKILL checkpoints recover in fresh verifier processes", () => {
  const directory = mkdtempSync(join(tmpdir(), "nutrition-acceptedProcessInterruption-"));
  try {
    const child = spawnSync(process.execPath, [resolveModule.resolve("./fixtures/acceptedProcessInterruption.cjs"), ...["run", directory]], {
      encoding: "utf8", timeout: 240000, maxBuffer: 8 * 1024 * 1024,
    });
    if (child.error || child.status !== 0) throw new Error(`${child.error ?? "fixture failed"}
${child.stdout}
${child.stderr}`);
    const results = JSON.parse(readFileSync(join(directory, "results.json"), "utf8"));
    expect(results).toHaveLength(16);
    expect(new Set(results.map((item: { verifierPid: number }) => item.verifierPid)).size).toBe(16);
    for (const item of results) {
      const killed = JSON.parse(readFileSync(join(directory, `${item.operation}-${item.boundary}`, "kill.json"), "utf8"));
      expect(killed.signal).toBe("SIGKILL");
      expect(killed.marker.pid).not.toBe(item.verifierPid);
      expect(item.checks.length).toBeGreaterThan(0);
    }
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}, 260000);

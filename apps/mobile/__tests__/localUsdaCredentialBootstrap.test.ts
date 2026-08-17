const mockOpenLocalRuntimeFoundation = jest.fn();
const mockGetStoredUsdaCredential = jest.fn();
const mockActivatePendingLocalRestore = jest.fn();

jest.mock("../src/runtime/local/localRuntimeFoundation", () => ({
  openLocalRuntimeFoundation: mockOpenLocalRuntimeFoundation,
}));

jest.mock("../src/runtime/local/usdaCredentialStore", () => ({
  getStoredUsdaCredential: mockGetStoredUsdaCredential,
}));

jest.mock("../src/storage/backup/localBackup", () => ({
  activatePendingLocalRestore: mockActivatePendingLocalRestore,
}));

import { bootstrapApplicationRuntime } from "../src/runtime/applicationRuntimeBootstrap";

function localRuntime() {
  const capability = {};
  return {
    authority: { kind: "local" as const, recoveryScope: "local:test" },
    calendar: capability,
    nutrients: capability,
    foods: capability,
    recipes: capability,
    dailyLogs: capability,
    targets: capability,
    ocr: capability,
    usda: capability,
    close: jest.fn(async () => undefined),
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockActivatePendingLocalRestore.mockResolvedValue(undefined);
});

test("default local bootstrap supplies the secure request-time USDA credential provider", async () => {
  const runtime = localRuntime();
  mockOpenLocalRuntimeFoundation.mockResolvedValue(runtime);

  const handle = await bootstrapApplicationRuntime({
    dataAuthority: "local",
    deploymentMode: "production",
  });

  expect(mockActivatePendingLocalRestore).toHaveBeenCalledTimes(1);
  expect(mockOpenLocalRuntimeFoundation).toHaveBeenCalledTimes(1);
  expect(mockOpenLocalRuntimeFoundation).toHaveBeenCalledWith({
    usda: { credentialProvider: mockGetStoredUsdaCredential },
  });
  expect(mockGetStoredUsdaCredential).not.toHaveBeenCalled();
  expect(handle.runtime).toBe(runtime);

  await handle.close();
  expect(runtime.close).toHaveBeenCalledTimes(1);
});

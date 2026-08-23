const mockGetItemAsync = jest.fn<Promise<string | null>, [string]>();
const mockSetItemAsync = jest.fn<Promise<void>, [string, string]>();
const mockDeleteItemAsync = jest.fn<Promise<void>, [string]>();

jest.mock("expo-secure-store", () => ({
  getItemAsync: mockGetItemAsync,
  setItemAsync: mockSetItemAsync,
  deleteItemAsync: mockDeleteItemAsync,
}), { virtual: true });

import {
  USDA_API_KEY_STORAGE_KEY,
  getStoredUsdaCredential,
  isUsdaCredentialConfigured,
  removeStoredUsdaCredential,
  setStoredUsdaCredential,
} from "../src/runtime/local/usdaCredentialStore";

beforeEach(() => {
  jest.clearAllMocks();
  mockGetItemAsync.mockResolvedValue(null);
  mockSetItemAsync.mockResolvedValue(undefined);
  mockDeleteItemAsync.mockResolvedValue(undefined);
});

test("reads and normalizes the stored personal USDA credential", async () => {
  mockGetItemAsync.mockResolvedValue("  personal-key  ");

  await expect(getStoredUsdaCredential()).resolves.toBe("personal-key");
  expect(mockGetItemAsync).toHaveBeenCalledWith(USDA_API_KEY_STORAGE_KEY);
  await expect(isUsdaCredentialConfigured()).resolves.toBe(true);
});

test("treats an absent or blank saved value as unconfigured", async () => {
  await expect(getStoredUsdaCredential()).resolves.toBeNull();
  await expect(isUsdaCredentialConfigured()).resolves.toBe(false);

  mockGetItemAsync.mockResolvedValue("   ");
  await expect(getStoredUsdaCredential()).resolves.toBeNull();
});

test("does not emit credential diagnostics during ordinary reads", async () => {
  const consoleLogSpy = jest.spyOn(console, "log").mockImplementation(() => undefined);

  try {
    mockGetItemAsync.mockResolvedValue("  personal-key  ");
    await expect(getStoredUsdaCredential()).resolves.toBe("personal-key");
    expect(consoleLogSpy).not.toHaveBeenCalled();

    mockGetItemAsync.mockResolvedValue("   ");
    await expect(getStoredUsdaCredential()).resolves.toBeNull();
    expect(consoleLogSpy).not.toHaveBeenCalled();
  } finally {
    consoleLogSpy.mockRestore();
  }
});

test("stores only a trimmed non-empty USDA credential", async () => {
  await setStoredUsdaCredential("  personal-key  ");

  expect(mockSetItemAsync).toHaveBeenCalledWith(USDA_API_KEY_STORAGE_KEY, "personal-key");
  await expect(setStoredUsdaCredential("   ")).rejects.toThrow("A USDA API key is required.");
  expect(mockSetItemAsync).toHaveBeenCalledTimes(1);
});

test("removes the USDA credential without reading or exposing it", async () => {
  await removeStoredUsdaCredential();

  expect(mockDeleteItemAsync).toHaveBeenCalledWith(USDA_API_KEY_STORAGE_KEY);
  expect(mockGetItemAsync).not.toHaveBeenCalled();
});

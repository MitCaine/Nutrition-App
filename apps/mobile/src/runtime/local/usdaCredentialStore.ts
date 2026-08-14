export const USDA_API_KEY_STORAGE_KEY = "nutrition-app.usda.api-key.v1";

type SecureStoreModule = Readonly<{
  getItemAsync(key: string): Promise<string | null>;
  setItemAsync(key: string, value: string): Promise<void>;
  deleteItemAsync(key: string): Promise<void>;
}>;

function secureStore(): SecureStoreModule {
  // Keep the native secret store behind the local-only path. Remote authority
  // must not evaluate or depend on this module's native implementation.
  return require("expo-secure-store") as SecureStoreModule;
}

export async function getStoredUsdaCredential(): Promise<string | null> {
  const value = await secureStore().getItemAsync(USDA_API_KEY_STORAGE_KEY);
  const normalized = value?.trim() ?? "";

  console.log(
      "[USDA credential diagnostic]",
      normalized.length > 0
          ? `configured, length=${normalized.length}`
          : "not configured",
  );

  return normalized.length > 0 ? normalized : null;
}

export async function isUsdaCredentialConfigured(): Promise<boolean> {
  return (await getStoredUsdaCredential()) !== null;
}

export async function setStoredUsdaCredential(value: string): Promise<void> {
  const normalized = value.trim();
  if (normalized.length === 0) {
    throw new Error("A USDA API key is required.");
  }
  await secureStore().setItemAsync(USDA_API_KEY_STORAGE_KEY, normalized);
}

export async function removeStoredUsdaCredential(): Promise<void> {
  await secureStore().deleteItemAsync(USDA_API_KEY_STORAGE_KEY);
}

import {
  loadThemePreference,
  parseThemePreference,
  resolveColorScheme,
  saveThemePreference,
  THEME_PREFERENCE_STORAGE_KEY,
  type PreferenceStorage,
} from "../src/app/theme/themePreference";

function memoryStorage(initial: string | null = null): PreferenceStorage & { value: string | null } {
  return {
    value: initial,
    async getItem() { return this.value; },
    async setItem(_key, value) { this.value = value; },
  };
}

test("theme preference defaults invalid and missing values to System", () => {
  expect(parseThemePreference(null)).toBe("system");
  expect(parseThemePreference("sepia")).toBe("system");
});

test("System follows the current appearance while explicit choices override it", () => {
  expect(resolveColorScheme("system", "light")).toBe("light");
  expect(resolveColorScheme("system", "dark")).toBe("dark");
  expect(resolveColorScheme("light", "dark")).toBe("light");
  expect(resolveColorScheme("dark", "light")).toBe("dark");
  expect(resolveColorScheme("system", "dark")).toBe("dark");
});

test("valid preferences persist and restore", async () => {
  const storage = memoryStorage();
  await saveThemePreference(storage, "dark");
  expect(storage.value).toBe("dark");
  expect(await loadThemePreference(storage)).toBe("dark");
});

test("storage failures safely fall back to System", async () => {
  const storage: PreferenceStorage = {
    getItem: async () => { throw new Error("read failed"); },
    setItem: async () => { throw new Error("write failed"); },
  };
  expect(await loadThemePreference(storage)).toBe("system");
  await expect(saveThemePreference(storage, "light")).resolves.toBeUndefined();
  expect(THEME_PREFERENCE_STORAGE_KEY).toBe("appearance-preference");
});

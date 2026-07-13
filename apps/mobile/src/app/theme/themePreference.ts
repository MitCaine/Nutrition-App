export const THEME_PREFERENCE_STORAGE_KEY = "appearance-preference";

export type ThemePreference = "system" | "light" | "dark";
export type ColorScheme = "light" | "dark";

export type PreferenceStorage = {
  getItem: (key: string) => Promise<string | null>;
  setItem: (key: string, value: string) => Promise<void>;
};

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

export function parseThemePreference(value: string | null): ThemePreference {
  return isThemePreference(value) ? value : "system";
}

export function resolveColorScheme(
  preference: ThemePreference,
  systemScheme: ColorScheme | null | undefined,
): ColorScheme {
  if (preference !== "system") {
    return preference;
  }
  return systemScheme === "dark" ? "dark" : "light";
}

export async function loadThemePreference(storage: PreferenceStorage): Promise<ThemePreference> {
  try {
    return parseThemePreference(await storage.getItem(THEME_PREFERENCE_STORAGE_KEY));
  } catch {
    return "system";
  }
}

export async function saveThemePreference(
  storage: PreferenceStorage,
  preference: ThemePreference,
): Promise<void> {
  try {
    await storage.setItem(THEME_PREFERENCE_STORAGE_KEY, preference);
  } catch {
    // Appearance persistence is best-effort and must never prevent theme switching.
  }
}

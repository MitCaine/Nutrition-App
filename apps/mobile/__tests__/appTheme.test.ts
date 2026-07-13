import { DARK_THEME, LIGHT_THEME, statusBarStyle, themeForColorScheme } from "../src/app/theme/AppTheme";

function perceptualLightness(hex: string): number {
  const channels = [1, 3, 5].map((start) => Number.parseInt(hex.slice(start, start + 2), 16) / 255);
  const linear = channels.map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  const luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  return 116 * Math.cbrt(luminance) - 16;
}

test("light and dark themes expose the same semantic roles", () => {
  expect(Object.keys(DARK_THEME.colors).sort()).toEqual(Object.keys(LIGHT_THEME.colors).sort());
  expect(LIGHT_THEME.colors.background).not.toBe(DARK_THEME.colors.background);
  expect(LIGHT_THEME.colors.accent).not.toBe(DARK_THEME.colors.accent);
  expect(DARK_THEME.colors.text).not.toBe(DARK_THEME.colors.background);
});

test("every semantic color has a valid defined value", () => {
  for (const theme of [LIGHT_THEME, DARK_THEME]) {
    for (const value of Object.values(theme.colors)) {
      expect(typeof value).toBe("string");
      expect(value.length).toBeGreaterThan(0);
    }
  }
});

test("semantic state colors remain distinct in both themes", () => {
  for (const theme of [LIGHT_THEME, DARK_THEME]) {
    expect(theme.colors.successText).not.toBe(theme.colors.successBackground);
    expect(theme.colors.warningText).not.toBe(theme.colors.warningBackground);
    expect(theme.colors.errorText).not.toBe(theme.colors.background);
    expect(theme.colors.activeBackground).not.toBe(theme.colors.secondarySurface);
    expect(theme.colors.text).not.toBe(theme.colors.input);
    expect(theme.colors.accentForeground).not.toBe(theme.colors.accent);
    expect(theme.colors.inactiveForeground).not.toBe(theme.colors.surface);
    expect(theme.colors.searchInputSurface).not.toBe(theme.colors.background);
    expect(theme.colors.searchInputBorder).not.toBe(theme.colors.searchInputSurface);
    expect(theme.colors.navigationSurface).not.toBe(theme.colors.searchInputSurface);
    expect(theme.colors.navigationBorder).not.toBe(theme.colors.navigationSurface);
    expect(theme.colors.listDivider).not.toBe(theme.colors.background);
    expect(theme.colors.controlSecondaryForeground).not.toBe(theme.colors.searchInputSurface);
    expect(theme.colors.primaryActionForeground).not.toBe(theme.colors.primaryActionBackground);
    expect(theme.colors.primaryActionBorder).not.toBe(theme.colors.background);
    expect(theme.colors.selectedNavigationForeground).not.toBe(theme.colors.selectedNavigationBackground);
  }
});

test("the dark FAB remains distinct from lower-emphasis selected navigation", () => {
  expect(DARK_THEME.colors.primaryActionBackground).not.toBe(DARK_THEME.colors.background);
  expect(DARK_THEME.colors.primaryActionBackground).not.toBe(DARK_THEME.colors.selectedNavigationBackground);
  expect(DARK_THEME.colors.primaryActionForeground).not.toBe(DARK_THEME.colors.selectedNavigationForeground);
  expect(DARK_THEME.colors.primaryActionBorder).not.toBe(DARK_THEME.colors.primaryActionBackground);
  expect(DARK_THEME.colors.navigationSurface).toBe("#2b3744");
  expect(DARK_THEME.colors.navigationBorder).toBe("#43576d");
  expect(DARK_THEME.colors.searchInputSurface).toBe("#303b49");
  expect(DARK_THEME.colors.searchInputBorder).toBe("#4a6078");
  expect(DARK_THEME.colors.inactiveForeground).toBe("#c0c9d4");
  expect(DARK_THEME.colors.listDivider).toBe("#465361");
});

test("dark fitted controls remain visibly raised from the screen", () => {
  const screenLightness = perceptualLightness(DARK_THEME.colors.background);
  const searchLightness = perceptualLightness(DARK_THEME.colors.searchInputSurface);
  const navigationLightness = perceptualLightness(DARK_THEME.colors.navigationSurface);
  expect(searchLightness - screenLightness).toBeGreaterThan(12);
  expect(navigationLightness - screenLightness).toBeGreaterThan(12);
  expect(searchLightness).toBeGreaterThan(navigationLightness);
});

test("light mode retains its established primary action blue", () => {
  expect(LIGHT_THEME.colors.primaryActionBackground).toBe(LIGHT_THEME.colors.accent);
  expect(LIGHT_THEME.colors.primaryActionForeground).toBe("#ffffff");
});

test("system appearance selection returns the matching live palette", () => {
  expect(themeForColorScheme("light")).toBe(LIGHT_THEME);
  expect(themeForColorScheme("dark")).toBe(DARK_THEME);
  expect(themeForColorScheme(null)).toBe(LIGHT_THEME);
});

test("status bar content follows appearance", () => {
  expect(statusBarStyle(LIGHT_THEME)).toBe("dark-content");
  expect(statusBarStyle(DARK_THEME)).toBe("light-content");
});

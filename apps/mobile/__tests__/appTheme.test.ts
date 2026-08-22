import { DARK_THEME, inactiveNavigationLabelColor, LIGHT_THEME, navigationCapsuleBorder, statusBarStyle, themeForColorScheme } from "../src/app/theme/AppTheme";

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
  expect(DARK_THEME.colors.primaryActionForeground).not.toBe(DARK_THEME.colors.selectedNavigationForeground);
  expect(DARK_THEME.colors.primaryActionBorder).not.toBe(DARK_THEME.colors.primaryActionBackground);
  expect(DARK_THEME.colors.navigationSurface).toBe("#38414d");
  expect(DARK_THEME.colors.navigationBorder).toBe("#43576d");
  expect(DARK_THEME.colors.searchInputSurface).toBe("#38414d");
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
  expect(searchLightness).toBe(navigationLightness);
});

test("navigation reuses the FAB edge highlight only in dark mode", () => {
  expect(navigationCapsuleBorder(DARK_THEME)).toBe(DARK_THEME.colors.primaryActionBorder);
  expect(navigationCapsuleBorder(LIGHT_THEME)).toBe(LIGHT_THEME.colors.navigationBorder);
});

test("inactive navigation labels use the FAB foreground in dark mode without losing light contrast", () => {
  expect(inactiveNavigationLabelColor(DARK_THEME)).toBe(DARK_THEME.colors.primaryActionForeground);
  expect(inactiveNavigationLabelColor(LIGHT_THEME)).toBe(LIGHT_THEME.colors.inactiveForeground);
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

const LEGACY_LIGHT_COLORS = {
  background: "#f8fafc",
  surface: "#ffffff",
  secondarySurface: "#f2f4f7",
  input: "#ffffff",
  text: "#17202a",
  secondaryText: "#5f6875",
  mutedText: "#78828f",
  border: "#dfe3e8",
  accent: "#1f6fb2",
  accentForeground: "#ffffff",
  activeBackground: "#dbeafe",
  inactiveForeground: "#5f6875",
  successBackground: "#e6f4ea",
  successBorder: "#137333",
  successText: "#0b5c2f",
  warningBackground: "#fff4d6",
  warningText: "#855000",
  errorText: "#b42318",
  destructive: "#b42318",
  modalBackdrop: "rgba(0, 0, 0, 0.35)",
  disabledBackground: "#e5e9ef",
  disabledText: "#7b8490",
  pressedBackground: "#e5e9ef",
  placeholder: "#7b8490",
  searchInputSurface: "#ffffff",
  searchInputBorder: "#dfe3e8",
  navigationSurface: "#f2f4f7",
  navigationBorder: "#dfe3e8",
  controlSecondaryForeground: "#5f6875",
  listDivider: "#dfe3e8",
  primaryActionBackground: "#1f6fb2",
  primaryActionForeground: "#ffffff",
  primaryActionBorder: "#1f6fb2",
  selectedNavigationBackground: "#dbeafe",
  selectedNavigationForeground: "#1f6fb2",
} as const;

const LEGACY_DARK_COLORS = {
  background: "#171d24",
  surface: "#1b2129",
  secondarySurface: "#242b35",
  input: "#202731",
  text: "#f1f4f7",
  secondaryText: "#b2bbc6",
  mutedText: "#8f9aa7",
  border: "#38414d",
  accent: "#65aef2",
  accentForeground: "#07121d",
  activeBackground: "#173d5d",
  inactiveForeground: "#c0c9d4",
  successBackground: "#173d2a",
  successBorder: "#3e9b68",
  successText: "#9ce0b5",
  warningBackground: "#463813",
  warningText: "#f4cf71",
  errorText: "#ff9b94",
  destructive: "#ff766e",
  modalBackdrop: "rgba(0, 0, 0, 0.65)",
  disabledBackground: "#2a313b",
  disabledText: "#77818d",
  pressedBackground: "#303946",
  placeholder: "#b3bec9",
  searchInputSurface: "#38414d",
  searchInputBorder: "#4a6078",
  navigationSurface: "#38414d",
  navigationBorder: "#43576d",
  controlSecondaryForeground: "#b9c4d0",
  listDivider: "#465361",
  primaryActionBackground: "#194170",
  primaryActionForeground: "#ffffff",
  primaryActionBorder: "#4b84bf",
  selectedNavigationBackground: "#194170",
  selectedNavigationForeground: "#65aef2",
} as const;

const P1_COLOR_ROLES = [
  "dailyLogForeground",
  "dailyLogBackground",
  "foodsForeground",
  "foodsBackground",
  "recipesForeground",
  "recipesBackground",
  "historyForeground",
  "historyBackground",
  "encouragementForeground",
  "encouragementBackground",
  "nutritionCaloriesSeries",
  "nutritionProteinSeries",
  "nutritionCarbohydrateSeries",
  "nutritionFatSeries",
] as const;

const P1_LIGHT_COLORS = {
  dailyLogForeground: "#1f6fb2",
  dailyLogBackground: "#eaf3fb",
  foodsForeground: "#0b7285",
  foodsBackground: "#e8f6f8",
  recipesForeground: "#7a3e9d",
  recipesBackground: "#f5ecfa",
  historyForeground: "#4f46a5",
  historyBackground: "#eef0ff",
  encouragementForeground: "#0f766e",
  encouragementBackground: "#e7f7f4",
  nutritionCaloriesSeries: "#1f6fb2",
  nutritionProteinSeries: "#0b7285",
  nutritionCarbohydrateSeries: "#9a5b00",
  nutritionFatSeries: "#7a3e9d",
} as const;

const P1_DARK_COLORS = {
  dailyLogForeground: "#65aef2",
  dailyLogBackground: "#173d5d",
  foodsForeground: "#67d4e2",
  foodsBackground: "#17363d",
  recipesForeground: "#c4a0f5",
  recipesBackground: "#342642",
  historyForeground: "#a5b4fc",
  historyBackground: "#292d4f",
  encouragementForeground: "#5eead4",
  encouragementBackground: "#153b37",
  nutritionCaloriesSeries: "#65aef2",
  nutritionProteinSeries: "#67d4e2",
  nutritionCarbohydrateSeries: "#f0b35b",
  nutritionFatSeries: "#c4a0f5",
} as const;

const FEATURE_COLOR_PAIRS = [
  ["dailyLogForeground", "dailyLogBackground"],
  ["foodsForeground", "foodsBackground"],
  ["recipesForeground", "recipesBackground"],
  ["historyForeground", "historyBackground"],
  ["encouragementForeground", "encouragementBackground"],
] as const;

const NUTRITION_SERIES_ROLES = [
  "nutritionCaloriesSeries",
  "nutritionProteinSeries",
  "nutritionCarbohydrateSeries",
  "nutritionFatSeries",
] as const;

function relativeLuminance(hex: string): number {
  const channels = [1, 3, 5].map(
    (start) =>
      Number.parseInt(
        hex.slice(start, start + 2),
        16,
      ) / 255,
  );

  const linear = channels.map(
    (value) =>
      value <= 0.04045
        ? value / 12.92
        : ((value + 0.055) / 1.055) ** 2.4,
  );

  return (
    0.2126 * linear[0]
    + 0.7152 * linear[1]
    + 0.0722 * linear[2]
  );
}

function contrastRatio(
  first: string,
  second: string,
): number {
  const luminances = [
    relativeLuminance(first),
    relativeLuminance(second),
  ].sort((left, right) => right - left);

  return (
    (luminances[0] + 0.05)
    / (luminances[1] + 0.05)
  );
}

test("P1 semantic color roles are exact and shared across themes", () => {
  const expectedRoles = [
    ...Object.keys(LEGACY_LIGHT_COLORS),
    ...P1_COLOR_ROLES,
  ].sort();

  expect(P1_COLOR_ROLES).toHaveLength(14);
  expect(expectedRoles).toHaveLength(49);

  expect(
    Object.keys(LIGHT_THEME.colors).sort(),
  ).toEqual(expectedRoles);

  expect(
    Object.keys(DARK_THEME.colors).sort(),
  ).toEqual(expectedRoles);

  for (
    const [role, value]
    of Object.entries(P1_LIGHT_COLORS)
  ) {
    expect(
      LIGHT_THEME.colors[
        role as keyof typeof LIGHT_THEME.colors
      ],
    ).toBe(value);
  }

  for (
    const [role, value]
    of Object.entries(P1_DARK_COLORS)
  ) {
    expect(
      DARK_THEME.colors[
        role as keyof typeof DARK_THEME.colors
      ],
    ).toBe(value);
  }
});

test("P1 preserves every legacy light and dark theme value", () => {
  expect(
    Object.keys(LEGACY_LIGHT_COLORS),
  ).toHaveLength(35);

  expect(
    Object.keys(LEGACY_DARK_COLORS),
  ).toHaveLength(35);

  for (
    const [role, value]
    of Object.entries(LEGACY_LIGHT_COLORS)
  ) {
    expect(
      LIGHT_THEME.colors[
        role as keyof typeof LIGHT_THEME.colors
      ],
    ).toBe(value);
  }

  for (
    const [role, value]
    of Object.entries(LEGACY_DARK_COLORS)
  ) {
    expect(
      DARK_THEME.colors[
        role as keyof typeof DARK_THEME.colors
      ],
    ).toBe(value);
  }

  expect(
    LIGHT_THEME.colors.primaryActionBackground,
  ).toBe("#1f6fb2");
});

test("P1 feature and encouragement colors meet text contrast thresholds", () => {
  for (
    const theme
    of [LIGHT_THEME, DARK_THEME]
  ) {
    for (
      const [foregroundRole, backgroundRole]
      of FEATURE_COLOR_PAIRS
    ) {
      const foreground =
        theme.colors[foregroundRole];

      expect(
        contrastRatio(
          foreground,
          theme.colors.background,
        ),
      ).toBeGreaterThanOrEqual(4.5);

      expect(
        contrastRatio(
          foreground,
          theme.colors.surface,
        ),
      ).toBeGreaterThanOrEqual(4.5);

      expect(
        contrastRatio(
          foreground,
          theme.colors[backgroundRole],
        ),
      ).toBeGreaterThanOrEqual(4.5);
    }
  }
});

test("P1 nutrition series colors meet graphical contrast thresholds", () => {
  for (
    const theme
    of [LIGHT_THEME, DARK_THEME]
  ) {
    for (
      const role
      of NUTRITION_SERIES_ROLES
    ) {
      const seriesColor =
        theme.colors[role];

      expect(
        contrastRatio(
          seriesColor,
          theme.colors.background,
        ),
      ).toBeGreaterThanOrEqual(3);

      expect(
        contrastRatio(
          seriesColor,
          theme.colors.surface,
        ),
      ).toBeGreaterThanOrEqual(3);
    }
  }
});

test("P1 encouragement semantics remain distinct from operation success", () => {
  for (
    const theme
    of [LIGHT_THEME, DARK_THEME]
  ) {
    expect(
      theme.colors.encouragementForeground,
    ).not.toBe(
      theme.colors.successText,
    );

    expect(
      theme.colors.encouragementBackground,
    ).not.toBe(
      theme.colors.successBackground,
    );

    expect(
      theme.colors.encouragementForeground,
    ).not.toBe(
      theme.colors.successBorder,
    );
  }
});

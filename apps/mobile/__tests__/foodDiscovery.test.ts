import React from "react";
import { Platform, Pressable, StyleSheet, Text, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { Food } from "../src/features/foods/api/types";
import { SavedFoodsScreen } from "../src/features/foods/screens/SavedFoodsScreen";
import { DARK_THEME, LIGHT_THEME } from "../src/app/theme/AppTheme";
import { foodAccessibilityLabel, formatRecentUse } from "../src/features/foods/utils/foodDiscovery";

const manual: Food = {
  id: "manual", name: "Greek yogurt", brand: null, source_type: "manual", source_id: null,
  is_recipe: false, source_kind: "ocr_confirmed", source_label: "Scanned label",
  is_favorite: true, can_favorite: true, serving_definitions: [], nutrients: [],
};
const usda: Food = { ...manual, id: "usda", name: "Banana", source_type: "usda", source_kind: "usda", source_label: "USDA", is_favorite: false };
const recipe: Food = {
  ...manual,
  id: "recipe",
  name: "Sheet pan dinner",
  source_type: "recipe",
  source_id: "recipe-publication-1",
  is_recipe: true,
  source_kind: "recipe",
  source_label: "Recipe",
  is_favorite: true,
};
const usdaSearchResult = {
  fdc_id: 1105314,
  description: "Banana, raw",
  data_type: "Foundation",
  brand_owner: null,
  food_category: "Fruits",
  publication_date: null,
  importable: true,
  nutrient_preview: [],
};
let mockUsdaFoods: typeof usdaSearchResult[];
let mockFavorites: Record<string, unknown>;
let mockRecents: Record<string, unknown>;
let mockSaved: Record<string, unknown>;
let mockUseDark = false;
const defaultPlatform = Platform.OS;

jest.mock("../src/shared/components/RootScreenHeader", () => ({ RootScreenHeader: () => null }));
jest.mock("../src/features/foods/hooks/useFoods", () => ({
  useFavoriteFoods: () => mockFavorites,
  useRecentFoods: () => mockRecents,
  useSavedFoods: () => mockSaved,
}));
jest.mock("../src/features/usda/hooks/useUsda", () => ({
  useUsdaSearch: () => ({
    data: { foods: mockUsdaFoods },
    isLoading: false,
    isError: false,
    refetch: jest.fn(),
  }),
}));
jest.mock("../src/features/foods/hooks/useDebouncedSearchQuery", () => ({ useDebouncedSearchQuery: (value: string) => value }));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...(mockUseDark ? actual.DARK_THEME : actual.LIGHT_THEME), preference: "system", effectiveScheme: mockUseDark ? "dark" : "light", setPreference: jest.fn() }) };
});

function textContent(node: TestRenderer.ReactTestInstance | string): string {
  return typeof node === "string" ? node : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join("");
}
function screenText(root: TestRenderer.ReactTestInstance) { return root.findAllByType(Text).map(textContent).join(" "); }

type IdentityColors = {
  foodsForeground: string;
  foodsBackground: string;
  recipesForeground: string;
  recipesBackground: string;
};

function exactRows(root: TestRenderer.ReactTestInstance, label: string) {
  return root.findAllByType(Pressable).filter(
    (node) => node.props.accessibilityLabel === label,
  );
}

function rowByLabelPrefix(root: TestRenderer.ReactTestInstance, prefix: string) {
  const matches = root.findAllByType(Pressable).filter(
    (node) =>
      typeof node.props.accessibilityLabel === "string"
      && node.props.accessibilityLabel.startsWith(prefix),
  );
  expect(matches).toHaveLength(1);
  return matches[0];
}

function assertIdentityBadge(
  row: TestRenderer.ReactTestInstance,
  expectedBadge: "Food" | "Recipe",
  expectedName: string,
  colors: IdentityColors,
) {
  const badges = row.findAllByType(Text).filter(
    (node) => textContent(node) === expectedBadge,
  );
  expect(badges).toHaveLength(1);

  const badge = badges[0];
  const badgeStyle = StyleSheet.flatten(badge.props.style);

  expect(badgeStyle).toEqual(expect.objectContaining({
    backgroundColor:
      expectedBadge === "Recipe"
        ? colors.recipesBackground
        : colors.foodsBackground,
    borderRadius: 10,
    color:
      expectedBadge === "Recipe"
        ? colors.recipesForeground
        : colors.foodsForeground,
    fontSize: 12,
    fontWeight: "700",
    lineHeight: 16,
    paddingHorizontal: 6,
    paddingVertical: 2,
  }));

  expect(badge.props.accessibilityLabel).toBeUndefined();
  expect(badge.props.accessibilityHint).toBeUndefined();
  expect(badge.props.accessibilityRole).toBeUndefined();
  expect(badge.props.testID).toBeUndefined();

  const container = badge.parent;
  expect(container).not.toBeNull();

  const containerStyle = StyleSheet.flatten(container?.props.style);
  expect(containerStyle).toEqual(expect.objectContaining({
    alignItems: "center",
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  }));

  const nameNodes = row.findAllByType(Text).filter(
    (node) => textContent(node) === expectedName,
  );
  expect(nameNodes).toHaveLength(1);

  const nameStyle = StyleSheet.flatten(nameNodes[0].props.style);
  expect(nameStyle).toEqual(expect.objectContaining({
    flexShrink: 1,
  }));
  expect(nameNodes[0].props.numberOfLines).toBeUndefined();
  expect(nameNodes[0].props.ellipsizeMode).toBeUndefined();
}

function assertPersistedIdentityContexts(
  root: TestRenderer.ReactTestInstance,
  colors: IdentityColors,
) {
  const manualLabel = foodAccessibilityLabel(manual);
  const recipeLabel = foodAccessibilityLabel(recipe);
  const usdaLabel = foodAccessibilityLabel(usda);

  expect(manualLabel).toBe(
    "Greek yogurt, Scanned label, favorite",
  );
  expect(recipeLabel).toBe(
    "Sheet pan dinner, Recipe, favorite",
  );
  expect(usdaLabel).toBe(
    "Banana, USDA",
  );

  // Favorites preview is rendered before the full Saved Foods list.
  const manualExact = exactRows(root, manualLabel);
  const recipeExact = exactRows(root, recipeLabel);

  expect(manualExact).toHaveLength(2);
  expect(recipeExact).toHaveLength(2);

  const favoriteManual = manualExact[0];
  const savedManual = manualExact[1];
  const favoriteRecipe = recipeExact[0];
  const savedRecipe = recipeExact[1];

  assertIdentityBadge(
    favoriteManual,
    "Food",
    manual.name,
    colors,
  );
  assertIdentityBadge(
    favoriteRecipe,
    "Recipe",
    recipe.name,
    colors,
  );
  assertIdentityBadge(
    savedManual,
    "Food",
    manual.name,
    colors,
  );
  assertIdentityBadge(
    savedRecipe,
    "Recipe",
    recipe.name,
    colors,
  );

  // Recent preview carries the same identity rule while preserving
  // independent recent-use metadata in the parent label.
  const recentManual = rowByLabelPrefix(
    root,
    `${manualLabel}, `,
  );
  const recentRecipe = rowByLabelPrefix(
    root,
    `${recipeLabel}, `,
  );
  const recentUsda = rowByLabelPrefix(
    root,
    `${usdaLabel}, `,
  );

  assertIdentityBadge(
    recentManual,
    "Food",
    manual.name,
    colors,
  );
  assertIdentityBadge(
    recentRecipe,
    "Recipe",
    recipe.name,
    colors,
  );
  assertIdentityBadge(
    recentUsda,
    "Food",
    usda.name,
    colors,
  );

  // USDA-origin persisted Food is still Food identity: provenance does not
  // drive the Food/Recipe mapping.
  const savedUsda = exactRows(root, usdaLabel);
  expect(savedUsda).toHaveLength(1);
  assertIdentityBadge(
    savedUsda[0],
    "Food",
    usda.name,
    colors,
  );

  const accessibilityLabels = root
    .findAllByType(Pressable)
    .map((node) => node.props.accessibilityLabel)
    .filter((value): value is string => typeof value === "string")
    .join(" ");

  expect(accessibilityLabels).not.toMatch(
    /teal|violet|plum|blue|purple/i,
  );
}

async function render(query = "") {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => { renderer = TestRenderer.create(React.createElement(SavedFoodsScreen, {
    onCreate: jest.fn(), onOpenFood: jest.fn(), onOpenUsdaPreview: jest.fn(), query,
    setQuery: jest.fn(), initialScrollOffset: 0, onScrollSessionChange: jest.fn(),
    onOpenSettings: jest.fn(), onScanNutritionLabel: jest.fn(),
  })); });
  return renderer;
}

beforeEach(() => {
  Object.defineProperty(Platform, "OS", { configurable: true, value: defaultPlatform });
  mockUseDark = false;
  mockUsdaFoods = [];
  mockFavorites = { data: [manual, recipe], isLoading: false, isError: false, refetch: jest.fn() };
  mockRecents = {
    data: [
      { food: recipe, last_used_at: "2026-07-14T12:00:00Z" },
      { food: usda, last_used_at: "2026-07-13T12:00:00Z" },
      { food: manual, last_used_at: "2026-07-12T12:00:00Z" },
    ],
    isLoading: false,
    isError: false,
    refetch: jest.fn(),
  };
  mockSaved = { data: [manual, recipe, usda], isLoading: false, isError: false };
});

afterEach(() => {
  Object.defineProperty(Platform, "OS", { configurable: true, value: defaultPlatform });
});

test("Saved Foods renders compact favorites, recents, all foods, source labels, and accessibility", async () => {
  const renderer = await render(); const text = screenText(renderer.root);
  expect(text).toContain("Favorites preview"); expect(text).toContain("Recent preview"); expect(text).toContain("All Saved Foods");
  expect(text.indexOf("Banana")).toBeLessThan(text.lastIndexOf("Greek yogurt"));
  expect(text).toContain("Scanned label"); expect(text).toContain("USDA");
  const favorite = renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Greek yogurt, Scanned label, favorite");
  expect(favorite).toBeDefined();
  expect(renderer.root.findByType(TextInput).props.maxFontSizeMultiplier).toBe(1.5);
  const fixedLabels = renderer.root.findAllByType(Text).filter((node) => ["Scan label", "+", "Custom Food"].includes(textContent(node)));
  expect(fixedLabels).toHaveLength(3);
  expect(fixedLabels.every((node) => node.props.maxFontSizeMultiplier === 1.5)).toBe(true);
  await act(async () => renderer.unmount());
});

test("persisted Food and Recipe identities use the exact light semantic roles in Favorites, Recent, and Saved rows", async () => {
  const renderer = await render();
  assertPersistedIdentityContexts(
    renderer.root,
    LIGHT_THEME.colors,
  );
  await act(async () => renderer.unmount());
});

test("persisted Food and Recipe identities use the exact dark semantic roles in Favorites, Recent, and Saved rows", async () => {
  mockUseDark = true;
  const renderer = await render();
  assertPersistedIdentityContexts(
    renderer.root,
    DARK_THEME.colors,
  );
  await act(async () => renderer.unmount());
});

test("USDA reference search results remain outside the persisted Food and Recipe identity treatment", async () => {
  mockUsdaFoods = [usdaSearchResult];

  const renderer = await render("banana");

  const referenceNames = renderer.root
    .findAllByType(Text)
    .filter((node) => textContent(node) === "Banana, raw");

  expect(referenceNames).toHaveLength(1);

  const referenceRow = referenceNames[0].parent;
  expect(referenceRow).not.toBeNull();

  const referenceText = referenceRow
    ?.findAllByType(Text)
    .map(textContent) ?? [];

  expect(referenceText).toContain("Banana, raw");
  expect(referenceText).not.toContain("Food");
  expect(referenceText).not.toContain("Recipe");

  await act(async () => renderer.unmount());
});

test("search retains the full Saved Foods result surface without discovery reordering", async () => {
  const renderer = await render("banana"); const text = screenText(renderer.root);
  expect(text).toContain("Saved Foods"); expect(text).not.toContain("Favorites preview"); expect(text).not.toContain("Recent preview");
  await act(async () => renderer.unmount());
});

test("empty and recoverable discovery states are accessible in dark theme", async () => {
  mockUseDark = true;
  const favoriteRetry = jest.fn(); const recentRetry = jest.fn();
  mockFavorites = { data: undefined, isLoading: false, isError: true, refetch: favoriteRetry };
  mockRecents = { data: [], isLoading: false, isError: false, refetch: recentRetry };
  const renderer = await render();
  expect(screenText(renderer.root)).toContain("No recently logged foods");
  const retry = renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Retry favorites");
  await act(async () => retry?.props.onPress()); expect(favoriteRetry).toHaveBeenCalled();
  await act(async () => renderer.unmount());
});

test("recent formatting uses device-local readable text and never exposes raw ISO labels", () => {
  expect(formatRecentUse("2026-07-14T12:00:00Z", new Date("2026-07-14T18:00:00Z"))).toBe("Used today");
  expect(formatRecentUse("2025-07-14T12:00:00Z", new Date("2026-07-14T18:00:00Z"))).toMatch(/^Used /);
  expect(foodAccessibilityLabel(usda)).toBe("Banana, USDA");
});

test("discovery headings disclose the intentional five-row preview limit", async () => {
  mockFavorites = {
    data: Array.from({ length: 7 }, (_, index) => ({ ...manual, id: `favorite-${index}`, name: `Favorite ${index}` })),
    isLoading: false, isError: false, refetch: jest.fn(),
  };
  mockRecents = {
    data: Array.from({ length: 10 }, (_, index) => ({
      food: { ...usda, id: `recent-${index}`, name: `Recent ${index}` },
      last_used_at: `2026-07-${String(13 - index).padStart(2, "0")}T12:00:00Z`,
    })),
    isLoading: false, isError: false, refetch: jest.fn(),
  };
  const renderer = await render();
  const headings = renderer.root.findAll((node) => node.props.accessibilityRole === "header").map(textContent);
  expect(headings).toEqual(expect.arrayContaining(["Favorites preview", "Recent preview"]));
  expect(screenText(renderer.root)).toContain("Favorite 4");
  expect(screenText(renderer.root)).not.toContain("Favorite 5");
  expect(screenText(renderer.root)).toContain("Recent 4");
  expect(screenText(renderer.root)).not.toContain("Recent 5");
  await act(async () => renderer.unmount());
});

test("Android omits the unsupported Scan Label action", async () => {
  Object.defineProperty(Platform, "OS", { configurable: true, value: "android" });
  const renderer = await render();
  expect(renderer.root.findAllByProps({ accessibilityLabel: "Scan nutrition label" })).toHaveLength(0);
  expect(screenText(renderer.root)).toContain("Custom Food");
  await act(async () => renderer.unmount());
});

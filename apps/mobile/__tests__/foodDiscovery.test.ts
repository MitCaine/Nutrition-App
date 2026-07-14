import React from "react";
import { Pressable, Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { Food } from "../src/features/foods/api/types";
import { SavedFoodsScreen } from "../src/features/foods/screens/SavedFoodsScreen";
import { foodAccessibilityLabel, formatRecentUse } from "../src/features/foods/utils/foodDiscovery";

const manual: Food = {
  id: "manual", name: "Greek yogurt", brand: null, source_type: "manual", source_id: null,
  is_recipe: false, source_kind: "ocr_confirmed", source_label: "Scanned label",
  is_favorite: true, can_favorite: true, serving_definitions: [], nutrients: [],
};
const usda: Food = { ...manual, id: "usda", name: "Banana", source_type: "usda", source_kind: "usda", source_label: "USDA", is_favorite: false };
let mockFavorites: Record<string, unknown>;
let mockRecents: Record<string, unknown>;
let mockSaved: Record<string, unknown>;
let mockUseDark = false;

jest.mock("../src/shared/components/RootScreenHeader", () => ({ RootScreenHeader: () => null }));
jest.mock("../src/features/foods/hooks/useFoods", () => ({
  useFavoriteFoods: () => mockFavorites,
  useRecentFoods: () => mockRecents,
  useSavedFoods: () => mockSaved,
}));
jest.mock("../src/features/usda/hooks/useUsda", () => ({ useUsdaSearch: () => ({ data: { foods: [] }, isLoading: false, isError: false }) }));
jest.mock("../src/features/foods/hooks/useDebouncedSearchQuery", () => ({ useDebouncedSearchQuery: (value: string) => value }));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...(mockUseDark ? actual.DARK_THEME : actual.LIGHT_THEME), preference: "system", effectiveScheme: mockUseDark ? "dark" : "light", setPreference: jest.fn() }) };
});

function textContent(node: TestRenderer.ReactTestInstance | string): string {
  return typeof node === "string" ? node : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join("");
}
function screenText(root: TestRenderer.ReactTestInstance) { return root.findAllByType(Text).map(textContent).join(" "); }
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
  mockUseDark = false;
  mockFavorites = { data: [manual], isLoading: false, isError: false, refetch: jest.fn() };
  mockRecents = { data: [{ food: usda, last_used_at: "2026-07-13T12:00:00Z" }, { food: manual, last_used_at: "2026-07-12T12:00:00Z" }], isLoading: false, isError: false, refetch: jest.fn() };
  mockSaved = { data: [manual, usda], isLoading: false, isError: false };
});

test("Saved Foods renders compact favorites, recents, all foods, source labels, and accessibility", async () => {
  const renderer = await render(); const text = screenText(renderer.root);
  expect(text).toContain("Favorites"); expect(text).toContain("Recent"); expect(text).toContain("All Saved Foods");
  expect(text.indexOf("Banana")).toBeLessThan(text.lastIndexOf("Greek yogurt"));
  expect(text).toContain("Scanned label"); expect(text).toContain("USDA");
  const favorite = renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Greek yogurt, Scanned label, favorite");
  expect(favorite).toBeDefined();
  await act(async () => renderer.unmount());
});

test("search retains the full Saved Foods result surface without discovery reordering", async () => {
  const renderer = await render("banana"); const text = screenText(renderer.root);
  expect(text).toContain("Saved Foods"); expect(text).not.toContain("Favorites"); expect(text).not.toContain("Recent");
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

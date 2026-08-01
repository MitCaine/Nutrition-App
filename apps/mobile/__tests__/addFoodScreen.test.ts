import React from "react";
import { Platform, Pressable, Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { Food, RecentFood } from "../src/features/foods/api/types";
import type { RecentEntry } from "../src/features/logging/api/types";
import { AddFoodScreen, discoveryReadState } from "../src/features/logging/screens/AddFoodScreen";
import { createAddFoodFlow } from "../src/features/logging/utils/addFoodFlow";

let mockFavorites: Record<string, unknown>;
let mockRecent: Record<string, unknown>;
let mockSaved: Record<string, unknown>;
let mockEntries: Record<string, unknown>;
let mockRecentEntries: Record<string, unknown>;
const defaultPlatform = Platform.OS;

jest.mock("../src/shared/components/RootScreenHeader", () => ({ RootScreenHeader: ({ title }: { title: string }) => require("react").createElement(require("react-native").Text, null, title) }));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...actual.LIGHT_THEME, preference: "system", effectiveScheme: "light", setPreference: jest.fn() }) };
});
jest.mock("../src/features/foods/hooks/useFoods", () => ({
  useFavoriteFoods: () => mockFavorites,
  useRecentFoods: () => mockRecent,
  useSavedFoods: () => mockSaved,
}));
jest.mock("../src/features/usda/hooks/useUsda", () => ({
  useUsdaSearch: () => ({ data: undefined, isError: false, isFetching: false, isLoading: false, refetch: jest.fn() }),
}));
jest.mock("../src/features/logging/hooks/useLogs", () => ({
  ...jest.requireActual("../src/features/logging/hooks/useLogs"),
  useDailyLogs: () => mockEntries,
  useRecentEntries: () => mockRecentEntries,
}));

const food = (id: string, name: string): Food => ({
  id,
  name,
  brand: null,
  notes: null,
  source_type: "manual",
  source_id: null,
  is_recipe: false,
  source_kind: "manual",
  source_label: "Manual",
  is_favorite: false,
  can_favorite: true,
  serving_definitions: [],
  nutrients: [],
});

function textContent(node: TestRenderer.ReactTestInstance | string): string {
  return typeof node === "string" ? node : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join("");
}

function allText(root: TestRenderer.ReactTestInstance): string {
  return root.findAllByType(Text).map(textContent).join(" ");
}

async function render(mutationEnabled = true, onRepeatRecentEntry = jest.fn()) {
  let renderer!: TestRenderer.ReactTestRenderer;
  const onSelectFood = jest.fn();
  const onCancel = jest.fn();
  const onCreateCustomFood = jest.fn();
  const onScanNutritionLabel = jest.fn();
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(AddFoodScreen, {
      flow: createAddFoodFlow("2026-07-14", "lunch"),
      mutationEnabled,
      onCancel,
      onOpenSettings: jest.fn(),
      onSelectFood,
      onRepeatRecentEntry,
      onCreateCustomFood,
      onScanNutritionLabel,
      onScrollSessionChange: jest.fn(),
    }));
  });
  return { renderer, onSelectFood, onRepeatRecentEntry, onCancel, onCreateCustomFood, onScanNutritionLabel };
}

beforeEach(() => {
  mockEntries = { data: [], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() };
  mockRecentEntries = { data: [], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() };
  mockFavorites = { data: [food("favorite", "Favorite Food")], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() };
  const recentFood: RecentFood = { food: food("recent", "Recent Food"), last_used_at: "2026-07-14T08:00:00Z" };
  mockRecent = { data: [recentFood], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() };
  mockSaved = { data: [food("saved", "Saved Food")], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() };
});

afterEach(() => {
  Object.defineProperty(Platform, "OS", { configurable: true, value: defaultPlatform });
});

test("renders the E1-08 browse sections in order and selects directly", async () => {
  const rendered = await render();
  const text = allText(rendered.renderer.root);
  expect(text.indexOf("Recent Entries")).toBeLessThan(text.indexOf("Favorites"));
  expect(text.indexOf("Favorites")).toBeLessThan(text.indexOf("Recent Foods"));
  expect(text.indexOf("Recent Foods")).toBeLessThan(text.lastIndexOf("Saved Foods"));
  expect(text).not.toContain("Food Details");
  const saved = rendered.renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Saved Food, Manual");
  await act(async () => saved?.props.onPress());
  expect(rendered.onSelectFood).toHaveBeenCalledWith("saved");
  await act(async () => rendered.renderer.unmount());
});

test("entry failure warns about duplicate logging while discovery remains available", async () => {
  mockEntries = { data: undefined, isError: true, isFetching: false, isLoading: false, refetch: jest.fn() };
  const rendered = await render();
  expect(allText(rendered.renderer.root)).toContain("Duplicate logging is possible.");
  expect(allText(rendered.renderer.root)).toContain("Saved Food");
  await act(async () => rendered.renderer.unmount());
});

test("Recent Entries renders historical intent and emits a single-entry Repeat handoff", async () => {
  const entry: RecentEntry = {
    id: "log-1",
    food_item_id: "food-1",
    food_name_snapshot: "Oatmeal",
    logged_date: "2026-07-13",
    meal_type: "breakfast",
    amount_quantity: "2",
    amount_unit: "serving",
    serving_definition_id: "serving-1",
    recipe_publication_revision_id: null,
    recipe_publication_amount_definition_id: null,
    historical_serving_label: "1 bowl",
    notes: "with berries",
    note_present: true,
    note_reference: "with berries",
    note_copy_allowed: true,
    created_at: "2026-07-13T10:00:00Z",
    source_food_updated_at: "2026-07-13T09:00:00Z",
    source_recipe_publication_revision_id: null,
    current_source_loggable: true,
    current_amount_unit: "serving",
    current_amount_definition_id: "serving-1",
    current_amount_label: "1 bowl",
    reuse_status: "exact",
  };
  mockRecentEntries = { data: [entry], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() };
  const onRepeat = jest.fn();
  const rendered = await render(true, onRepeat);
  expect(allText(rendered.renderer.root)).toContain("Oatmeal");
  expect(allText(rendered.renderer.root)).toContain("2026-07-13 · 2 serving · breakfast · Note");
  const repeat = rendered.renderer.root.findByProps({ accessibilityLabel: "Repeat Oatmeal" });
  await act(async () => repeat.props.onPress());
  expect(onRepeat).toHaveBeenCalledWith(entry);
  await act(async () => rendered.renderer.unmount());
});

test("discovery sources retain independent failures and retries", async () => {
  const favoriteRetry = jest.fn();
  mockFavorites = { data: undefined, isError: true, isFetching: false, isLoading: false, refetch: favoriteRetry };
  const rendered = await render();
  const retryButton = rendered.renderer.root.findByProps({ accessibilityLabel: "Retry favorites" });
  await act(async () => retryButton.props.onPress());
  expect(favoriteRetry).toHaveBeenCalledTimes(1);
  expect(allText(rendered.renderer.root)).toContain("Recent Food");
  expect(allText(rendered.renderer.root)).toContain("Saved Food");
  await act(async () => rendered.renderer.unmount());
});

test("mutation-ineligible dates do not expose selectable Foods", async () => {
  const rendered = await render(false);
  const saved = rendered.renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Saved Food, Manual");
  expect(saved?.props.disabled).toBe(true);
  await act(async () => saved?.props.onPress());
  expect(rendered.onSelectFood).not.toHaveBeenCalled();
  await act(async () => rendered.renderer.unmount());
});

test("Add Food exposes reusable custom and supported scan acquisitions", async () => {
  const rendered = await render();
  const custom = rendered.renderer.root.findByProps({ accessibilityLabel: "Add custom food" });
  await act(async () => custom.props.onPress());
  expect(rendered.onCreateCustomFood).toHaveBeenCalledTimes(1);
  const scan = rendered.renderer.root.findByProps({ accessibilityLabel: "Scan nutrition label" });
  await act(async () => scan.props.onPress());
  expect(rendered.onScanNutritionLabel).toHaveBeenCalledTimes(1);
  await act(async () => rendered.renderer.unmount());
});

test("mutation-ineligible dates disable acquisition handoffs", async () => {
  const rendered = await render(false);
  const custom = rendered.renderer.root.findByProps({ accessibilityLabel: "Add custom food" });
  const scan = rendered.renderer.root.findByProps({ accessibilityLabel: "Scan nutrition label" });
  expect(custom.props.disabled).toBe(true);
  expect(scan.props.disabled).toBe(true);
  await act(async () => custom.props.onPress());
  await act(async () => scan.props.onPress());
  expect(rendered.onCreateCustomFood).not.toHaveBeenCalled();
  expect(rendered.onScanNutritionLabel).not.toHaveBeenCalled();
  await act(async () => rendered.renderer.unmount());
});

test("Android has no unsupported Scan Label handoff in Add Food", async () => {
  Object.defineProperty(Platform, "OS", { configurable: true, value: "android" });
  const rendered = await render();
  expect(rendered.renderer.root.findAllByProps({ accessibilityLabel: "Scan nutrition label" })).toHaveLength(0);
  expect(rendered.renderer.root.findByProps({ accessibilityLabel: "Add custom food" })).toBeDefined();
  await act(async () => rendered.renderer.unmount());
});

test("discovery translator distinguishes loading, success, empty, refresh, and failures", () => {
  const base = { isError: false, isFetching: false, isLoading: false, refetch: jest.fn() };
  expect(discoveryReadState({ ...base, data: undefined, isLoading: true }).kind).toBe("initial-loading");
  expect(discoveryReadState({ ...base, data: undefined, isError: true, error: new Error("offline") }).kind).toBe("initial-failure");
  expect(discoveryReadState({ ...base, data: [] }).kind).toBe("empty");
  expect(discoveryReadState({ ...base, data: [food("1", "Food")] }).kind).toBe("success");
  expect(discoveryReadState({ ...base, data: [food("1", "Food")], isFetching: true }).kind).toBe("refreshing");
  expect(discoveryReadState({ ...base, data: [food("1", "Food")], isError: true, isRefetchError: true, error: new Error("offline") }).kind).toBe("refresh-failure");
});

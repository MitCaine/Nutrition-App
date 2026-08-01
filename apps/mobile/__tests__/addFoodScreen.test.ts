import React from "react";
import { Pressable, Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { Food, RecentFood } from "../src/features/foods/api/types";
import { AddFoodScreen, discoveryReadState } from "../src/features/logging/screens/AddFoodScreen";
import { createAddFoodFlow } from "../src/features/logging/utils/addFoodFlow";

let mockFavorites: Record<string, unknown>;
let mockRecent: Record<string, unknown>;
let mockSaved: Record<string, unknown>;
let mockEntries: Record<string, unknown>;

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
jest.mock("../src/features/logging/hooks/useLogs", () => ({
  ...jest.requireActual("../src/features/logging/hooks/useLogs"),
  useDailyLogs: () => mockEntries,
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

async function render(mutationEnabled = true) {
  let renderer!: TestRenderer.ReactTestRenderer;
  const onSelectFood = jest.fn();
  const onCancel = jest.fn();
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(AddFoodScreen, {
      flow: createAddFoodFlow("2026-07-14", "lunch"),
      mutationEnabled,
      onCancel,
      onOpenSettings: jest.fn(),
      onSelectFood,
      onScrollSessionChange: jest.fn(),
    }));
  });
  return { renderer, onSelectFood, onCancel };
}

beforeEach(() => {
  mockEntries = { data: [], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() };
  mockFavorites = { data: [food("favorite", "Favorite Food")], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() };
  const recentFood: RecentFood = { food: food("recent", "Recent Food"), last_used_at: "2026-07-14T08:00:00Z" };
  mockRecent = { data: [recentFood], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() };
  mockSaved = { data: [food("saved", "Saved Food")], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() };
});

test("renders the E1-08 browse sections in order and selects directly", async () => {
  const rendered = await render();
  const text = allText(rendered.renderer.root);
  expect(text.indexOf("Recent Entries")).toBeLessThan(text.indexOf("Favorites"));
  expect(text.indexOf("Favorites")).toBeLessThan(text.indexOf("Recent Foods"));
  expect(text.indexOf("Recent Foods")).toBeLessThan(text.indexOf("Saved Foods"));
  expect(text).not.toContain("Food Details");
  const saved = rendered.renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel?.startsWith("Saved Food"));
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
  const saved = rendered.renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel?.startsWith("Saved Food"));
  expect(saved?.props.disabled).toBe(true);
  await act(async () => saved?.props.onPress());
  expect(rendered.onSelectFood).not.toHaveBeenCalled();
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

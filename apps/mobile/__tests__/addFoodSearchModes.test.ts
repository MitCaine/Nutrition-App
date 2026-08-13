import React, { useState } from "react";
import { ScrollView, Text, TextInput } from "react-native";
import TestRenderer, { act, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import type { Food } from "../src/features/foods/api/types";
import type { UsdaSearchResponse } from "../src/features/usda/api/types";
import { AddFoodScreen, discoveryReadState, usdaDiscoveryReadState } from "../src/features/logging/screens/AddFoodScreen";
import { createAddFoodFlow, updateAddFoodFlow, type AddFoodFlowState } from "../src/features/logging/utils/addFoodFlow";

let mockSaved: Record<string, unknown>;
let mockUsda: Record<string, unknown>;
let mockSavedQuery: string;
let mockUsdaQuery: string;
let mockSelectSaved: jest.Mock;
let mockSelectUsda: jest.Mock;
let mockRerender: () => void;

jest.mock("../src/shared/components/RootScreenHeader", () => ({
  RootScreenHeader: ({ title }: { title: string }) => require("react").createElement(require("react-native").Text, null, title),
}));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...actual.LIGHT_THEME, preference: "system", effectiveScheme: "light", setPreference: jest.fn() }) };
});
jest.mock("../src/features/logging/hooks/useLogs", () => ({
  ...jest.requireActual("../src/features/logging/hooks/useLogs"),
  useDailyLogs: () => ({ data: [], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() }),
  useRecentEntries: () => ({ data: [], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() }),
}));
jest.mock("../src/features/foods/hooks/useFoods", () => ({
  useFavoriteFoods: () => ({ data: [], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() }),
  useRecentFoods: () => ({ data: [], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() }),
  useSavedFoods: (query: string) => { mockSavedQuery = query; return mockSaved; },
}));
jest.mock("../src/features/usda/hooks/useUsda", () => ({
  useUsdaSearch: (query: string) => { mockUsdaQuery = query; return mockUsda; },
}));

const savedFood: Food = {
  id: "saved-1",
  name: "Oatmeal",
  source_type: "manual",
  source_id: null,
  is_recipe: false,
  source_kind: "manual",
  source_label: "Manual",
  is_favorite: false,
  can_favorite: true,
  serving_definitions: [],
  nutrients: [],
};

const usdaResponse: UsdaSearchResponse = {
  query: "banana",
  page_number: 1,
  page_size: 20,
  total_hits: 1,
  foods: [{
    fdc_id: 1105314,
    description: "Banana, raw",
    data_type: "Foundation",
    brand_owner: null,
    food_category: "Fruits",
    publication_date: null,
    importable: true,
    nutrient_preview: [],
  }],
};

function queryState<T>(data: T): Record<string, unknown> {
  return { data, isError: false, isFetching: false, isLoading: false, refetch: jest.fn() };
}

function resetMocks() {
  mockSaved = queryState([savedFood]);
  mockUsda = queryState(usdaResponse);
  mockSavedQuery = "";
  mockUsdaQuery = "";
  mockSelectSaved = jest.fn();
  mockSelectUsda = jest.fn();
}

function textContent(node: ReactTestInstance): string {
  return node.children.map((child) => (typeof child === "string" ? child : textContent(child))).join("");
}

function screenText(root: ReactTestInstance): string {
  return root.findAllByType(Text).map(textContent).join(" ");
}

async function renderHarness(): Promise<ReactTestRenderer> {
  function Harness() {
    const [flow, setFlow] = useState<AddFoodFlowState>(() => createAddFoodFlow("2026-07-13", "lunch"));
    const [, setTick] = useState(0);
    mockRerender = () => setTick((value) => value + 1);
    return React.createElement(AddFoodScreen, {
      flow,
      mutationEnabled: true,
      onCancel: jest.fn(),
      onOpenSettings: jest.fn(),
      onSelectFood: mockSelectSaved,
      onSelectUsdaFood: mockSelectUsda,
      onQueryChange: (query) => setFlow((current) => updateAddFoodFlow(current, { query })),
      onScrollSessionChange: (query, offset) => setFlow((current) => updateAddFoodFlow(current, query.trim() ? { searchScrollOffset: offset } : { browseScrollOffset: offset })),
    });
  }
  let renderer!: ReactTestRenderer;
  await act(async () => { renderer = TestRenderer.create(React.createElement(Harness)); });
  return renderer;
}

beforeEach(() => {
  jest.useFakeTimers();
  resetMocks();
});

afterEach(() => jest.useRealTimers());

test("empty query is browse mode and entering one query shows separate Saved and USDA groups", async () => {
  const renderer = await renderHarness();
  let text = screenText(renderer.root);
  expect(text.indexOf("Recent Entries")).toBeLessThan(text.indexOf("Favorites"));
  expect(text.indexOf("Favorites")).toBeLessThan(text.indexOf("Recent Foods"));
  expect(text.indexOf("Recent Foods")).toBeLessThan(text.indexOf("Saved Foods"));
  await act(async () => renderer.root.findByType(TextInput).props.onChangeText("  banana  "));
  await act(async () => jest.advanceTimersByTime(300));
  text = screenText(renderer.root);
  expect(text).not.toContain("Recent Entries");
  expect(text).not.toContain("Favorites");
  expect(text).not.toContain("Recent Foods");
  expect(text).toContain("Saved Foods");
  expect(text).toContain("USDA Results");
  expect(text).toContain("Oatmeal");
  expect(text).toContain("Banana, raw");
  expect(mockSavedQuery).toBe("banana");
  expect(mockUsdaQuery).toBe("banana");
  await act(async () => renderer.unmount());
});

test("clearing the unified query restores browse content and its scroll context", async () => {
  const renderer = await renderHarness();
  const input = renderer.root.findByType(TextInput);
  const browseScroll = renderer.root.findByType(ScrollView);
  await act(async () => browseScroll.props.onScroll({ nativeEvent: { contentOffset: { y: 37 } } }));
  await act(async () => input.props.onChangeText("banana"));
  await act(async () => jest.advanceTimersByTime(300));
  await act(async () => renderer.root.findByType(ScrollView).props.onScroll({ nativeEvent: { contentOffset: { y: 83 } } }));
  await act(async () => renderer.root.findByType(TextInput).props.onChangeText(""));
  expect(renderer.root.findByType(TextInput).props.value).toBe("");
  expect(screenText(renderer.root)).toContain("Recent Entries");
  expect(screenText(renderer.root)).toContain("Logging for 2026-07-13");
  expect(screenText(renderer.root)).toContain("Initial meal: lunch");
  const returnedBrowseScroll = renderer.root.findByType(ScrollView);
  await act(async () => returnedBrowseScroll.props.onContentSizeChange());
  expect((returnedBrowseScroll.instance as unknown as { scrollTo: jest.Mock }).scrollTo).toHaveBeenCalledWith({ y: 37, animated: false });
  await act(async () => renderer.unmount());
});

test("Saved Foods and USDA retain independent failures and retry behavior", async () => {
  mockSaved = { data: undefined, isError: true, isFetching: false, isLoading: false, refetch: jest.fn() };
  mockUsda = queryState(usdaResponse);
  const renderer = await renderHarness();
  await act(async () => renderer.root.findByType(TextInput).props.onChangeText("banana"));
  await act(async () => jest.advanceTimersByTime(300));
  expect(screenText(renderer.root)).toContain("Saved Foods are unavailable");
  expect(screenText(renderer.root)).toContain("Banana, raw");
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Retry saved foods" }).props.onPress());
  expect((mockSaved.refetch as jest.Mock)).toHaveBeenCalledTimes(1);

  mockSaved = queryState([savedFood]);
  mockUsda = { data: undefined, isError: true, isFetching: false, isLoading: false, refetch: jest.fn() };
  await act(async () => mockRerender());
  expect(screenText(renderer.root)).toContain("Oatmeal");
  expect(screenText(renderer.root)).toContain("USDA search is unavailable");
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Retry USDA search" }).props.onPress());
  expect((mockUsda.refetch as jest.Mock)).toHaveBeenCalledTimes(1);

  mockSaved = { ...queryState([savedFood]), isError: true, isRefetchError: true, error: new Error("saved refresh") };
  mockUsda = { ...queryState(usdaResponse), isError: true, isRefetchError: true, error: new Error("USDA refresh") };
  await act(async () => mockRerender());
  expect(screenText(renderer.root)).toContain("Saved Foods could not be refreshed");
  expect(screenText(renderer.root)).toContain("USDA search could not be refreshed");
  expect(screenText(renderer.root)).toContain("Oatmeal");
  expect(screenText(renderer.root)).toContain("Banana, raw");
  await act(async () => renderer.unmount());
});

test("Saved selection and USDA selection expose separate direct handoffs", async () => {
  const renderer = await renderHarness();
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Oatmeal, Manual" }).props.onPress());
  expect(mockSelectSaved).toHaveBeenCalledWith("saved-1");
  await act(async () => renderer.root.findByType(TextInput).props.onChangeText("banana"));
  await act(async () => jest.advanceTimersByTime(300));
  const usdaResult = renderer.root.findByProps({ accessibilityLabel: "Select Banana, raw, Fruits, Foundation" });
  expect(usdaResult.props.accessibilityLabel).not.toContain("1105314");
  expect(usdaResult.props.accessibilityHint).toContain("before import");
  await act(async () => usdaResult.props.onPress());
  expect(mockSelectUsda).toHaveBeenCalledWith(1105314);
  await act(async () => renderer.unmount());
});

test("search-state translators distinguish USDA prompt, loading, empty, and refresh failure", () => {
  const refetch = jest.fn();
  const base = { isError: false, isFetching: false, isLoading: false, refetch };
  expect(usdaDiscoveryReadState("", "", { ...base }).kind).toBe("prompt");
  expect(usdaDiscoveryReadState("banana", "", { ...base, isLoading: true }).kind).toBe("searching");
  expect(usdaDiscoveryReadState("banana", "banana", { ...base, data: { ...usdaResponse, foods: [] } }).kind).toBe("empty");
  expect(usdaDiscoveryReadState("banana", "banana", { ...base, data: usdaResponse, isError: true, isRefetchError: true }).kind).toBe("refresh-failure");
  expect(discoveryReadState({ ...base, data: undefined, isError: true }).kind).toBe("initial-failure");
});

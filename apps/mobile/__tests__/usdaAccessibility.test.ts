import React from "react";
import { Pressable, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

let mockSearch: Record<string, unknown>;
let mockPreview: Record<string, unknown>;
let mockImporter: Record<string, unknown>;

jest.mock("../src/features/usda/hooks/useUsda", () => ({
  useUsdaSearch: () => mockSearch,
  useUsdaPreview: () => mockPreview,
  useUsdaImport: () => mockImporter,
}));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...actual.LIGHT_THEME, preference: "system", effectiveScheme: "light", setPreference: jest.fn() }) };
});

import { UsdaPreviewScreen } from "../src/features/usda/screens/UsdaPreviewScreen";
import { UsdaSearchScreen } from "../src/features/usda/screens/UsdaSearchScreen";

const searchFood = {
  fdc_id: 555000,
  description: "Example Protein Bar",
  data_type: "Branded",
  brand_owner: "Example Foods",
  food_category: "Bars",
  publication_date: null,
  importable: true,
  nutrient_preview: [],
};

beforeEach(() => {
  mockSearch = {
    data: { query: "bar", page_number: 1, page_size: 20, foods: [searchFood] },
    isLoading: false,
    isError: false,
    refetch: jest.fn(),
  };
  mockPreview = {
    data: {
      name: "Example Protein Bar",
      data_type: "Branded",
      brand: "Example Foods",
      food_category: "Bars",
      serving_definitions: [{ candidate_id: "bar", label: "1 bar", gram_weight: "50" }],
      nutrients: [],
      diagnostics: [],
    },
    isLoading: false,
    isError: false,
    refetch: jest.fn(),
  };
  mockImporter = { isPending: false, isError: false, mutate: jest.fn() };
});

test("USDA search uses a persistent label and meaningful result identity", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(UsdaSearchScreen, {
      query: "bar",
      setQuery: jest.fn(),
      onBack: jest.fn(),
      onOpenPreview: jest.fn(),
    }));
  });
  expect(renderer.root.findByType(TextInput).props["aria-labelledby"]).toBe("usda-search-label");
  const result = renderer.root.findByProps({ accessibilityLabel: "Select Example Protein Bar, Example Foods, Bars, Branded - Example Foods" });
  expect(result.props.accessibilityLabel).not.toContain("555000");
  expect(result.props.accessibilityHint).toContain("before import");
  expect(renderer.root.findByProps({ accessibilityRole: "header", children: "Search USDA" })).toBeDefined();
  await act(async () => renderer.unmount());
});

test("USDA preview exposes confirmation handoff and import busy state", async () => {
  mockImporter = { isPending: true, isError: false, mutate: jest.fn() };
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(UsdaPreviewScreen, {
      fdcId: 555000,
      onBack: jest.fn(),
      onImported: jest.fn(),
    }));
  });
  const action = renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Importing Example Protein Bar")!;
  expect(action.props.accessibilityState).toMatchObject({ busy: true, disabled: true });
  expect(action.props.accessibilityHint).toContain("logging confirmation");
  expect(renderer.root.findByProps({ accessibilityRole: "header", children: "Example Protein Bar" })).toBeDefined();
  await act(async () => renderer.unmount());
});

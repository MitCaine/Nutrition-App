import React from "react";
import { Pressable, ScrollView, Text, TextInput } from "react-native";
import TestRenderer, { act, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import type { Food, FoodResolvedNutrition } from "../src/features/foods/api/types";
import type { DailyLog, DailySummary } from "../src/features/logging/api/types";
import type { DailyTargetComparison } from "../src/features/targets/api/types";
import type { UsdaFoodPreview, UsdaSearchResponse } from "../src/features/usda/api/types";
import { AppNavigator } from "../src/app/navigation/AppNavigator";
import { remoteNutritionRuntime } from "../src/runtime/remote/remoteNutritionRuntime";
import { createNutritionTestRuntime, withNutritionRuntime } from "./nutritionRuntimeTestSupport";

let mockLogs: QueryState<DailyLog[]>;
let mockSummary: QueryState<DailySummary>;
let mockTargets: QueryState<DailyTargetComparison>;
let mockCalendar: QueryState<CalendarState>;
let mockFoodQuery: QueryState<Food>;
let mockResolvedNutrition: QueryState<FoodResolvedNutrition>;
let mockUsdaSearch: QueryState<UsdaSearchResponse>;
let mockUsdaPreview: QueryState<UsdaFoodPreview>;
let mockUsdaImport: { isPending: boolean; isError: boolean; mutate: jest.Mock };
const mockAccessibilityAnnounce = jest.fn(() => jest.fn());
let mockScanGeneration = 0;
const activeRenderers = new Set<ReactTestRenderer>();

type QueryState<T> = {
  data?: T;
  error?: unknown;
  isError: boolean;
  isFetching: boolean;
  isLoading: boolean;
  isRefetchError?: boolean;
  refetch: jest.Mock;
};

type CalendarState = {
  is_established: boolean;
  authoritative_time_zone: string | null;
  calendar_revision: number;
  today: string;
};

jest.mock("@expo/vector-icons", () => ({
  Ionicons: () => null,
}));

jest.mock("../src/shared/components/RootScreenHeader", () => {
  const mockReact = require("react");
  const { Pressable: MockPressable, Text: MockText } = require("react-native");
  return {
    RootScreenHeader: ({ title, onOpenSettings }: { title: string; onOpenSettings?: () => void }) => mockReact.createElement(
      mockReact.Fragment,
      null,
      mockReact.createElement(MockText, null, title),
      onOpenSettings ? mockReact.createElement(MockPressable, { accessibilityLabel: "Open settings", onPress: onOpenSettings }, mockReact.createElement(MockText, null, "Open settings")) : null,
    ),
  };
});

jest.mock("../src/shared/accessibility/announcements", () => ({
  ...jest.requireActual("../src/shared/accessibility/announcements"),
  useAccessibilityAnnouncement: () => mockAccessibilityAnnounce,
}));

jest.mock("../src/app/navigation/BottomNavigation", () => {
  const mockReact = require("react");
  const { Pressable: MockPressable, Text: MockText } = require("react-native");
  return {
    BottomNavigation: ({ onSelect }: { onSelect: (tab: "daily-log" | "foods") => void }) => mockReact.createElement(
      mockReact.Fragment,
      null,
      mockReact.createElement(MockPressable, { accessibilityLabel: "Foods tab", onPress: () => onSelect("foods") }, mockReact.createElement(MockText, null, "Foods tab")),
      mockReact.createElement(MockPressable, { accessibilityLabel: "Daily Log tab", onPress: () => onSelect("daily-log") }, mockReact.createElement(MockText, null, "Daily Log tab")),
    ),
  };
});

// These routes are outside the E1-08 contract. Keeping them inert makes this
// test exercise the real navigator and logging routes without booting their
// unrelated data dependencies.
jest.mock("../src/features/foods/screens/FoodDetailsScreen", () => {
  const mockReact = require("react");
  const { Pressable: MockPressable, Text: MockText } = require("react-native");
  return {
    FoodDetailsScreen: ({ foodId, onLog }: { foodId: string; onLog: (initialAmount: unknown) => void }) => mockReact.createElement(
      mockReact.Fragment,
      null,
      mockReact.createElement(MockText, null, `Food Detail ${foodId}`),
      mockReact.createElement(MockPressable, {
        accessibilityLabel: "Log food from detail",
        onPress: () => onLog({ amountDefinitionId: "serving-1", amountQuantity: "2.5", amountUnit: "serving" }),
      }, mockReact.createElement(MockText, null, "Log food from detail")),
    ),
  };
});
jest.mock("../src/features/foods/screens/FoodFormScreen", () => {
  const mockReact = require("react");
  const { Pressable: MockPressable, Text: MockText } = require("react-native");
  return {
    FoodFormScreen: ({ onCancel, onSaved }: { onCancel: () => void; onSaved: (foodId: string) => void }) => mockReact.createElement(
      mockReact.Fragment,
      null,
      mockReact.createElement(MockText, null, "Custom Food form"),
      mockReact.createElement(MockPressable, { accessibilityLabel: "Save custom food", onPress: () => onSaved("food-custom") }, mockReact.createElement(MockText, null, "Save custom food")),
      mockReact.createElement(MockPressable, { accessibilityLabel: "Cancel custom food", onPress: onCancel }, mockReact.createElement(MockText, null, "Cancel custom food")),
    ),
  };
});
jest.mock("../src/features/foods/screens/SavedFoodsScreen", () => {
  const mockReact = require("react");
  const { Pressable: MockPressable, Text: MockText } = require("react-native");
  return {
    SavedFoodsScreen: ({
      onOpenFood,
      onOpenSettings,
      onScanNutritionLabel,
    }: {
      onOpenFood: (foodId: string) => void;
      onOpenSettings: () => void;
      onScanNutritionLabel?: () => void;
    }) => mockReact.createElement(
      mockReact.Fragment,
      null,
      mockReact.createElement(MockText, null, "Saved Foods root"),
      mockReact.createElement(MockPressable, { accessibilityLabel: "Open Oatmeal detail", onPress: () => onOpenFood("food-oatmeal") }, mockReact.createElement(MockText, null, "Open Oatmeal detail")),
      mockReact.createElement(MockPressable, { accessibilityLabel: "Open Food settings", onPress: onOpenSettings }, mockReact.createElement(MockText, null, "Open Food settings")),
      onScanNutritionLabel ? mockReact.createElement(MockPressable, { accessibilityLabel: "Scan nutrition label from Foods", onPress: onScanNutritionLabel }, mockReact.createElement(MockText, null, "Scan nutrition label from Foods")) : null,
    ),
  };
});
jest.mock("../src/features/recipes/screens/IngredientPickerScreen", () => ({ IngredientPickerScreen: () => null }));
jest.mock("../src/features/recipes/screens/RecipeDetailScreen", () => ({ RecipeDetailScreen: () => null }));
jest.mock("../src/features/recipes/screens/RecipeFormScreen", () => ({ RecipeFormScreen: () => null }));
jest.mock("../src/features/recipes/screens/RecipeListScreen", () => ({ RecipeListScreen: () => null }));
jest.mock("../src/features/usda/screens/UsdaSearchScreen", () => ({ UsdaSearchScreen: () => null }));
jest.mock("../src/features/ocr/diagnostics/OcrDiagnosticsScreen", () => ({ OcrDiagnosticsScreen: () => null }));
jest.mock("../src/features/ocr/screens/NutritionScanScreen", () => {
  const mockReact = require("react");
  const { Pressable: MockPressable, Text: MockText } = require("react-native");
  return {
    NutritionScanScreen: ({
      autoAcquireCamera,
      onCancel,
      onReady,
    }: {
      autoAcquireCamera?: boolean;
      onCancel: () => void;
      onReady: (draft: unknown) => void;
    }) => mockReact.createElement(
      mockReact.Fragment,
      null,
      mockReact.createElement(MockText, null, "Scan nutrition label"),
      autoAcquireCamera ? mockReact.createElement(MockText, null, "Camera acquisition requested") : null,
      mockReact.createElement(MockPressable, {
        accessibilityLabel: "Finish label scan",
        onPress: () => {
          mockScanGeneration += 1;
          onReady({ scanGeneration: mockScanGeneration });
        },
      }, mockReact.createElement(MockText, null, "Finish label scan")),
      mockReact.createElement(MockPressable, { accessibilityLabel: "Cancel label scan", onPress: onCancel }, mockReact.createElement(MockText, null, "Cancel label scan")),
    ),
  };
});
jest.mock("../src/features/ocr/screens/NutritionConfirmationScreen", () => {
  const mockReact = require("react");
  const { Pressable: MockPressable, Text: MockText } = require("react-native");
  return {
    NutritionConfirmationScreen: ({
      initialDraft,
      onCancel,
      onCreated,
      onRetake,
    }: {
      initialDraft: { scanGeneration?: number };
      onCancel: () => void;
      onCreated: (foodId: string) => void;
      onRetake: () => void;
    }) => mockReact.createElement(
      mockReact.Fragment,
      null,
      mockReact.createElement(MockText, null, `Review extracted nutrition ${initialDraft.scanGeneration ?? "unknown"}`),
      mockReact.createElement(MockPressable, { accessibilityLabel: "Create scanned food", onPress: () => onCreated("food-scanned") }, mockReact.createElement(MockText, null, "Create scanned food")),
      mockReact.createElement(MockPressable, { accessibilityLabel: "Retake nutrition label photo", onPress: onRetake }, mockReact.createElement(MockText, null, "Retake photo")),
      mockReact.createElement(MockPressable, { accessibilityLabel: "Cancel nutrition review", onPress: onCancel }, mockReact.createElement(MockText, null, "Cancel nutrition review")),
    ),
  };
});
jest.mock("../src/app/settings/SettingsScreen", () => {
  const mockReact = require("react");
  const { Text: MockText } = require("react-native");
  return { SettingsScreen: () => mockReact.createElement(MockText, null, "Settings screen") };
});
jest.mock("../src/features/targets/TargetSettingsScreen", () => ({ TargetSettingsScreen: () => null }));
jest.mock("@react-native-community/datetimepicker", () => ({ __esModule: true, default: () => null }));

jest.mock("../src/features/calendar/hooks/useCalendar", () => ({
  useCalendarState: () => mockCalendar,
}));

jest.mock("../src/features/targets/hooks/useDailyTargetComparison", () => ({
  ...jest.requireActual("../src/features/targets/hooks/useDailyTargetComparison"),
  useDailyTargetComparison: () => mockTargets,
  useTargetConfiguration: () => ({
    data: {
      trackingPreferences: {},
    },
    isLoading: false,
    isFetching: false,
    isError: false,
  }),
}));

jest.mock("../src/features/usda/hooks/useUsda", () => ({
  useUsdaSearch: () => mockUsdaSearch,
  useUsdaPreview: () => mockUsdaPreview,
  useUsdaImport: () => mockUsdaImport,
}));

jest.mock("../src/features/foods/hooks/useFoods", () => ({
  useFoods: () => ({ data: [], isLoading: false, isFetching: false, isError: false, refetch: jest.fn() }),
  useFavoriteFoods: () => ({ data: [], isLoading: false, isFetching: false, isError: false, refetch: jest.fn() }),
  useRecentFoods: () => ({ data: [], isLoading: false, isFetching: false, isError: false, refetch: jest.fn() }),
  useSavedFoods: (query: string) => ({ data: query ? [] : [mockFoodQuery.data], isLoading: false, isFetching: false, isError: false, refetch: jest.fn() }),
  useFood: () => mockFoodQuery,
  useFoodResolvedNutrition: () => mockResolvedNutrition,
}));

jest.mock("../src/features/logging/hooks/useLogs", () => ({
  ...jest.requireActual("../src/features/logging/hooks/useLogs"),
  useDailyLogs: () => mockLogs,
  useFutureLogs: () => ({ data: [], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() }),
  useRecentEntries: () => ({ data: [], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() }),
  useDailySummary: () => mockSummary,
  useLogEditContext: () => ({ data: undefined, isLoading: false, isError: false, refetch: jest.fn() }),
  useLogMutations: () => ({
    createLog: { mutateAsync: mockCreateLog, isPending: false },
    updateLog: { mutateAsync: jest.fn(), isPending: false },
    deleteLog: { mutate: jest.fn(), isPending: false },
  }),
}));

jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return {
    ...actual,
    useAppTheme: () => ({ ...actual.LIGHT_THEME, preference: "system", effectiveScheme: "light", setPreference: jest.fn() }),
  };
});

const food: Food = {
  id: "food-oatmeal",
  name: "Oatmeal",
  source_type: "manual",
  source_id: null,
  is_recipe: false,
  source_kind: "manual",
  source_label: "Saved food",
  is_favorite: false,
  can_favorite: true,
  serving_definitions: [{
    id: "serving-1",
    label: "1 bowl",
    quantity: "1",
    unit: "bowl",
    gram_weight: "200",
    is_default: true,
    source: "manual",
    is_user_confirmed: true,
  }],
  nutrients: [],
};

const nutrition: FoodResolvedNutrition = {
  nutrition_authority: "food_item",
  recipe_id: null,
  recipe_publication_revision_id: null,
  amounts: [{
    amount_definition_id: "serving-1",
    display_label: "1 bowl",
    is_default: true,
    entered_quantity: "1",
    semantic_amount_mode: "serving",
    resolved_grams: "200",
    valid_for_logging: true,
    nutrients: [],
  }],
};

const importedFood: Food = {
  ...food,
  id: "food-imported-banana",
  name: "Imported Banana",
  source_kind: "usda",
  source_label: "USDA",
};

const usdaSearchResponse: UsdaSearchResponse = {
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

const usdaPreview: UsdaFoodPreview = {
  source_type: "usda",
  external_id: "1105314",
  fdc_id: 1105314,
  name: "Banana, raw",
  brand: null,
  data_type: "Foundation",
  food_category: "Fruits",
  publication_date: null,
  nutrients: [],
  serving_definitions: [],
  diagnostics: [],
};

const total = {
  nutrientId: "calories",
  amountKnown: "250",
  amountEstimated: "0",
  unit: "kcal" as const,
  hasUnknownContributors: false,
  unknownContributorCount: 0,
};

const targets: DailyTargetComparison = {
  date: "2026-07-13",
  dailyValueCatalogVersion: "test",
  driDatasetVersion: "test",
  targetDirectionSemanticsVersion: "test",
  comparisons: [{
    nutrientId: "calories",
    consumedAmount: "250",
    targetAmount: "2000",
    unit: "kcal",
    percentage: "12.5",
    authority: "manual_override",
    direction: "target",
    trackingMode: "custom",
    status: "available",
    reasonCode: null,
    noteCode: null,
    hasUnknownContributors: false,
    referenceType: null,
    sourceVersion: null,
    sourceId: null,
    calculationBasis: null,
  }],
};

const mockCreateLog = jest.fn(async (input: Record<string, unknown>) => {
  const entry: DailyLog = {
    id: `log-${(mockLogs.data ?? []).length + 1}`,
    food_item_id: String(input.food_item_id),
    food_name_snapshot: String(input.food_item_id) === importedFood.id ? importedFood.name : food.name,
    meal_type: (input.meal_type as string | null | undefined) ?? null,
    source_food_available: true,
    logged_date: String(input.logged_date),
    amount_quantity: String(input.amount_quantity),
    amount_unit: input.amount_unit as "serving" | "g",
    serving_definition_id: input.serving_definition_id as string | null | undefined,
    notes: (input.notes as string | null | undefined) ?? null,
    updated_at: "2026-07-13T12:00:00Z",
  };
  mockLogs.data = [...(mockLogs.data ?? []), entry];
  mockSummary.data = { logged_date: entry.logged_date, is_complete: false, totals: [total] };
  mockTargets.data = { ...targets, date: entry.logged_date };
  return entry;
});

const mockUsdaImportMutation = jest.fn((_fdcId: number, options: { onSuccess: (food: Food) => void }) => {
  mockFoodQuery = emptyQuery(importedFood);
  options.onSuccess(importedFood);
});

const testRuntime = createNutritionTestRuntime({
  dailyLogs: {
    ...remoteNutritionRuntime.dailyLogs,
    create: async (input) => await mockCreateLog(input) as DailyLog,
  },
});

function emptyQuery<T>(data: T): QueryState<T> {
  return { data, isLoading: false, isFetching: false, isError: false, refetch: jest.fn() };
}

function resetState() {
  mockLogs = emptyQuery([]);
  mockSummary = emptyQuery({ logged_date: "2026-07-14", is_complete: false, totals: [] });
  mockTargets = emptyQuery(targets);
  mockCalendar = emptyQuery({ is_established: true, authoritative_time_zone: "UTC", calendar_revision: 4, today: "2026-07-14" });
  mockFoodQuery = emptyQuery(food);
  mockResolvedNutrition = emptyQuery(nutrition);
  mockUsdaSearch = emptyQuery(usdaSearchResponse);
  mockUsdaPreview = emptyQuery(usdaPreview);
  mockUsdaImportMutation.mockClear();
  mockUsdaImport = { isPending: false, isError: false, mutate: mockUsdaImportMutation };
  mockCreateLog.mockClear();
  mockAccessibilityAnnounce.mockClear();
  mockScanGeneration = 0;
}

async function renderNavigator(): Promise<ReactTestRenderer> {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(withNutritionRuntime(React.createElement(AppNavigator), testRuntime));
  });
  activeRenderers.add(renderer);
  return renderer;
}

function updateNavigator(renderer: ReactTestRenderer): void {
  renderer.update(withNutritionRuntime(React.createElement(AppNavigator), testRuntime));
}

function rendererIsMounted(renderer: ReactTestRenderer): boolean {
  try {
    void renderer.root;
    return true;
  } catch {
    return false;
  }
}

function textContent(node: ReactTestInstance): string {
  return node.children.map((child) => (typeof child === "string" ? child : textContent(child))).join("");
}

function screenText(root: ReactTestInstance): string {
  return root.findAllByType(Text).map(textContent).join(" ");
}

function labeled(root: ReactTestInstance, label: string): ReactTestInstance {
  return root.findByProps({ accessibilityLabel: label });
}

function optionalLabeled(root: ReactTestInstance, label: string): ReactTestInstance | undefined {
  return root.findAllByProps({ accessibilityLabel: label })[0];
}

function buttonWithText(root: ReactTestInstance, value: string): ReactTestInstance {
  return root.findAllByType(Pressable).find((node) => textContent(node) === value)!;
}

async function openDailyLog(renderer: ReactTestRenderer) {
  await act(async () => labeled(renderer.root, "Daily Log tab").props.onPress());
  await act(async () => buttonWithText(renderer.root, "Previous Day").props.onPress());
}

async function selectSavedFood(renderer: ReactTestRenderer) {
  await act(async () => labeled(renderer.root, "Oatmeal, Saved food").props.onPress());
}

beforeEach(() => {
  jest.useFakeTimers({ now: new Date("2026-07-14T12:00:00Z") });
  resetState();
});

afterEach(async () => {
  await act(async () => {
    activeRenderers.forEach((renderer) => {
      if (rendererIsMounted(renderer)) renderer.unmount();
    });
  });
  activeRenderers.clear();
  jest.useRealTimers();
});

test("Food Detail Log enters shared Log Food with the selected amount when calendar mutations are unavailable", async () => {
  const renderer = await renderNavigator();
  mockCalendar.data = { is_established: false, authoritative_time_zone: null, calendar_revision: 4, today: "2026-07-14" };
  await act(async () => updateNavigator(renderer));
  await act(async () => labeled(renderer.root, "Open Oatmeal detail").props.onPress());
  expect(screenText(renderer.root)).toContain("Food Detail food-oatmeal");
  await act(async () => labeled(renderer.root, "Log food from detail").props.onPress());
  expect(screenText(renderer.root)).toContain("Log Food");
  expect(screenText(renderer.root)).not.toContain("Settings screen");
  expect(renderer.root.findByProps({ accessibilityLabel: "Amount quantity" }).props.value).toBe("2.5");
  await act(async () => renderer.unmount());
});

test("selecting the active Daily Log tab closes a Settings overlay opened from Daily Log", async () => {
  const renderer = await renderNavigator();
  await act(async () => labeled(renderer.root, "Daily Log tab").props.onPress());
  expect(screenText(renderer.root)).toContain("Daily Log");
  await act(async () => labeled(renderer.root, "Open settings").props.onPress());
  expect(screenText(renderer.root)).toContain("Settings screen");
  await act(async () => labeled(renderer.root, "Daily Log tab").props.onPress());
  expect(screenText(renderer.root)).toContain("Daily Log");
  expect(screenText(renderer.root)).not.toContain("Settings screen");
  await act(async () => renderer.unmount());
});

test("named and general Add Food flows use real navigator transitions and return the originating date", async () => {
  const renderer = await renderNavigator();
  await openDailyLog(renderer);

  await act(async () => labeled(renderer.root, "Add Food to Breakfast").props.onPress());
  expect(screenText(renderer.root)).toContain("Logging for 2026-07-13");
  expect(screenText(renderer.root)).toContain("Initial meal: breakfast");
  await selectSavedFood(renderer);
  expect(screenText(renderer.root)).toContain("Meal");
  expect(labeled(renderer.root, "Meal breakfast").props.accessibilityState.checked).toBe(true);
  await act(async () => labeled(renderer.root, "Save log").props.onPress());
  expect(screenText(renderer.root)).toContain("Daily Log");
  expect(screenText(renderer.root)).toContain("Oatmeal");
  expect(screenText(renderer.root)).toContain("Breakfast");
  expect(mockCreateLog).toHaveBeenCalledWith(expect.objectContaining({ logged_date: "2026-07-13", meal_type: "breakfast" }));
  expect(mockAccessibilityAnnounce).toHaveBeenCalledWith(
    "Logged Oatmeal for 2026-07-13.",
    expect.objectContaining({ key: expect.stringMatching(/^create:log-1:/), kind: "mutation-outcome" }),
  );

  // A second flow starts with no meal assignment and reaches the same route.
  await act(async () => labeled(renderer.root, "Add Food without meal").props.onPress());
  expect(screenText(renderer.root)).toContain("No meal selected");
  await selectSavedFood(renderer);
  expect(labeled(renderer.root, "Meal none").props.accessibilityState.checked).toBe(true);
  await act(async () => labeled(renderer.root, "Save log").props.onPress());
  expect(screenText(renderer.root)).toContain("Oatmeal");
  expect(screenText(renderer.root)).not.toContain("Past date");
  await act(async () => renderer.unmount());
});

test("normal tab navigation restores the shared confirmation draft", async () => {
  const renderer = await renderNavigator();
  await openDailyLog(renderer);
  await act(async () => labeled(renderer.root, "Add Food to Breakfast").props.onPress());
  await selectSavedFood(renderer);
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Amount quantity" }).props.onChangeText("6"));
  await act(async () => labeled(renderer.root, "Meal lunch").props.onPress());
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Notes" }).props.onChangeText("after workout"));

  await act(async () => labeled(renderer.root, "Foods tab").props.onPress());
  await act(async () => labeled(renderer.root, "Daily Log tab").props.onPress());

  expect(screenText(renderer.root)).toContain("Log Food");
  expect(renderer.root.findByProps({ accessibilityLabel: "Amount quantity" }).props.value).toBe("6");
  expect(labeled(renderer.root, "Meal lunch").props.accessibilityState.checked).toBe(true);
  expect(renderer.root.findByProps({ accessibilityLabel: "Notes" }).props.value).toBe("after workout");
  await act(async () => renderer.unmount());
});

test("restored confirmation revalidates a changed calendar revision without changing date", async () => {
  const renderer = await renderNavigator();
  await openDailyLog(renderer);
  await act(async () => labeled(renderer.root, "Add Food to Dinner").props.onPress());
  await selectSavedFood(renderer);
  await act(async () => labeled(renderer.root, "Foods tab").props.onPress());
  mockCalendar.data = { ...mockCalendar.data!, calendar_revision: 5 };
  await act(async () => labeled(renderer.root, "Daily Log tab").props.onPress());
  expect(screenText(renderer.root)).toContain("The authoritative calendar changed.");
  expect(labeled(renderer.root, "Log date 2026-07-13")).toBeDefined();
  await act(async () => labeled(renderer.root, "Save log").props.onPress());
  expect(mockCreateLog).toHaveBeenCalledWith(expect.objectContaining({ calendar_revision: 5, logged_date: "2026-07-13" }));
  await act(async () => renderer.unmount());
});

test("USDA search imports through the existing handoff and opens shared confirmation", async () => {
  const renderer = await renderNavigator();
  await openDailyLog(renderer);
  await act(async () => labeled(renderer.root, "Add Food to Breakfast").props.onPress());
  await act(async () => renderer.root.findByType(TextInput).props.onChangeText("banana"));
  await act(async () => jest.advanceTimersByTime(300));
  await act(async () => labeled(renderer.root, "Select Banana, raw, Fruits, Foundation").props.onPress());
  expect(screenText(renderer.root)).toContain("Banana, raw");
  await act(async () => buttonWithText(renderer.root, "Import Food").props.onPress());
  expect(mockUsdaImportMutation).toHaveBeenCalledWith(1105314, expect.objectContaining({ onSuccess: expect.any(Function) }));
  expect(screenText(renderer.root)).toContain("Imported Banana");
  expect(screenText(renderer.root)).toContain("Logging for 2026-07-13");
  expect(labeled(renderer.root, "Meal breakfast").props.accessibilityState.checked).toBe(true);
  await act(async () => labeled(renderer.root, "Save log").props.onPress());
  expect(mockCreateLog).toHaveBeenCalledWith(expect.objectContaining({ food_item_id: importedFood.id, logged_date: "2026-07-13", meal_type: "breakfast" }));
  expect(screenText(renderer.root)).toContain("Imported Banana");
  expect(screenText(renderer.root)).toContain("Breakfast");
  await act(async () => renderer.unmount());
});

test("Custom Food handoff preserves date and meal through shared confirmation", async () => {
  const renderer = await renderNavigator();
  await openDailyLog(renderer);
  await act(async () => labeled(renderer.root, "Add Food to Breakfast").props.onPress());
  await act(async () => labeled(renderer.root, "Add custom food").props.onPress());
  expect(screenText(renderer.root)).toContain("Custom Food form");
  await act(async () => labeled(renderer.root, "Save custom food").props.onPress());
  expect(screenText(renderer.root)).toContain("Log Food");
  expect(labeled(renderer.root, "Meal breakfast").props.accessibilityState.checked).toBe(true);
  await act(async () => labeled(renderer.root, "Save log").props.onPress());
  expect(mockCreateLog).toHaveBeenCalledWith(expect.objectContaining({
    food_item_id: "food-custom",
    logged_date: "2026-07-13",
    meal_type: "breakfast",
  }));
  await act(async () => renderer.unmount());
});

test("cancelling after Custom Food creation returns to discovery without creating a log", async () => {
  const renderer = await renderNavigator();
  await openDailyLog(renderer);
  await act(async () => labeled(renderer.root, "Add Food to Lunch").props.onPress());
  await act(async () => labeled(renderer.root, "Add custom food").props.onPress());
  await act(async () => labeled(renderer.root, "Save custom food").props.onPress());
  await act(async () => labeled(renderer.root, "Cancel logging").props.onPress());
  expect(optionalLabeled(renderer.root, "Cancel Add Food")).toBeDefined();
  expect(screenText(renderer.root)).toContain("Initial meal: lunch");
  expect(mockCreateLog).not.toHaveBeenCalled();
  await act(async () => renderer.unmount());
});

test("supported Scan Label handoff reaches shared confirmation with the originating flow", async () => {
  const renderer = await renderNavigator();
  await openDailyLog(renderer);
  await act(async () => labeled(renderer.root, "Add Food to Dinner").props.onPress());
  await act(async () => labeled(renderer.root, "Scan nutrition label").props.onPress());
  expect(screenText(renderer.root)).toContain("Scan nutrition label");
  await act(async () => labeled(renderer.root, "Finish label scan").props.onPress());
  expect(screenText(renderer.root)).toContain("Review extracted nutrition");
  await act(async () => labeled(renderer.root, "Create scanned food").props.onPress());
  expect(screenText(renderer.root)).toContain("Log Food");
  expect(labeled(renderer.root, "Meal dinner").props.accessibilityState.checked).toBe(true);
  await act(async () => labeled(renderer.root, "Save log").props.onPress());
  expect(mockCreateLog).toHaveBeenCalledWith(expect.objectContaining({
    food_item_id: "food-scanned",
    logged_date: "2026-07-13",
    meal_type: "dinner",
  }));
  await act(async () => renderer.unmount());
});

test("Scan Label retake opens the camera directly, replaces the abandoned draft, and preserves Add Food context", async () => {
  const renderer = await renderNavigator();
  await openDailyLog(renderer);
  await act(async () => labeled(renderer.root, "Add Food to Dinner").props.onPress());
  await act(async () => labeled(renderer.root, "Scan nutrition label").props.onPress());
  await act(async () => labeled(renderer.root, "Finish label scan").props.onPress());
  expect(screenText(renderer.root)).toContain("Review extracted nutrition 1");

  await act(async () => labeled(renderer.root, "Retake nutrition label photo").props.onPress());
  expect(screenText(renderer.root)).toContain("Camera acquisition requested");

  await act(async () => labeled(renderer.root, "Finish label scan").props.onPress());
  expect(screenText(renderer.root)).toContain("Review extracted nutrition 2");
  expect(screenText(renderer.root)).not.toContain("Review extracted nutrition 1");

  await act(async () => labeled(renderer.root, "Create scanned food").props.onPress());
  expect(screenText(renderer.root)).toContain("Log Food");
  expect(labeled(renderer.root, "Meal dinner").props.accessibilityState.checked).toBe(true);
  await act(async () => renderer.unmount());
});

test("cancelling the camera after an Add Food retake returns to the originating discovery flow", async () => {
  const renderer = await renderNavigator();
  await openDailyLog(renderer);
  await act(async () => labeled(renderer.root, "Add Food to Snack").props.onPress());
  await act(async () => labeled(renderer.root, "Scan nutrition label").props.onPress());
  await act(async () => labeled(renderer.root, "Finish label scan").props.onPress());
  await act(async () => labeled(renderer.root, "Retake nutrition label photo").props.onPress());
  expect(screenText(renderer.root)).toContain("Camera acquisition requested");

  await act(async () => labeled(renderer.root, "Cancel label scan").props.onPress());
  expect(screenText(renderer.root)).toContain("Logging for 2026-07-13");
  expect(screenText(renderer.root)).toContain("Initial meal: snack");
  await act(async () => renderer.unmount());
});

test("standalone Food scan retake opens the camera directly and uses only the replacement draft", async () => {
  const renderer = await renderNavigator();
  await act(async () => labeled(renderer.root, "Scan nutrition label from Foods").props.onPress());
  await act(async () => labeled(renderer.root, "Finish label scan").props.onPress());
  expect(screenText(renderer.root)).toContain("Review extracted nutrition 1");

  await act(async () => labeled(renderer.root, "Retake nutrition label photo").props.onPress());
  expect(screenText(renderer.root)).toContain("Camera acquisition requested");
  await act(async () => labeled(renderer.root, "Finish label scan").props.onPress());

  expect(screenText(renderer.root)).toContain("Review extracted nutrition 2");
  expect(screenText(renderer.root)).not.toContain("Review extracted nutrition 1");
  await act(async () => labeled(renderer.root, "Create scanned food").props.onPress());
  expect(screenText(renderer.root)).toContain("Food Detail food-scanned");
  await act(async () => renderer.unmount());
});

test("cancelling Scan Label review restores the scan acquisition path", async () => {
  const renderer = await renderNavigator();
  await openDailyLog(renderer);
  await act(async () => labeled(renderer.root, "Add Food to Snack").props.onPress());
  await act(async () => labeled(renderer.root, "Scan nutrition label").props.onPress());
  await act(async () => labeled(renderer.root, "Finish label scan").props.onPress());
  await act(async () => labeled(renderer.root, "Cancel nutrition review").props.onPress());
  expect(screenText(renderer.root)).toContain("Scan nutrition label");
  expect(optionalLabeled(renderer.root, "Finish label scan")).toBeDefined();
  await act(async () => labeled(renderer.root, "Cancel label scan").props.onPress());
  expect(screenText(renderer.root)).toContain("Initial meal: snack");
  await act(async () => renderer.unmount());
});

test("USDA import failure keeps the preview and discovery workflow context retryable", async () => {
  const renderer = await renderNavigator();
  await openDailyLog(renderer);
  await act(async () => labeled(renderer.root, "Add Food to Lunch").props.onPress());
  await act(async () => renderer.root.findByType(TextInput).props.onChangeText("banana"));
  await act(async () => jest.advanceTimersByTime(300));
  await act(async () => labeled(renderer.root, "Select Banana, raw, Fruits, Foundation").props.onPress());
  mockUsdaImportMutation.mockImplementationOnce(() => {
    mockUsdaImport.isError = true;
  });
  await act(async () => buttonWithText(renderer.root, "Import Food").props.onPress());
  await act(async () => updateNavigator(renderer));
  expect(screenText(renderer.root)).toContain("Import failed. Try again later.");
  expect(screenText(renderer.root)).toContain("Banana, raw");
  await act(async () => buttonWithText(renderer.root, "Back").props.onPress());
  expect(renderer.root.findByType(TextInput).props.value).toBe("banana");
  expect(screenText(renderer.root)).toContain("USDA Results");
  await act(async () => renderer.unmount());
});

test("cancelling USDA confirmation returns to the same mode and query", async () => {
  const renderer = await renderNavigator();
  await openDailyLog(renderer);
  await act(async () => labeled(renderer.root, "Add Food to Lunch").props.onPress());
  await act(async () => renderer.root.findByType(TextInput).props.onChangeText("banana"));
  await act(async () => jest.advanceTimersByTime(300));
  await act(async () => labeled(renderer.root, "Select Banana, raw, Fruits, Foundation").props.onPress());
  await act(async () => buttonWithText(renderer.root, "Import Food").props.onPress());
  await act(async () => labeled(renderer.root, "Cancel logging").props.onPress());
  expect(renderer.root.findByType(TextInput).props.value).toBe("banana");
  expect(screenText(renderer.root)).toContain("USDA Results");
  expect(screenText(renderer.root)).toContain("Logging for 2026-07-13");
  expect(screenText(renderer.root)).toContain("Initial meal: lunch");
  await act(async () => renderer.unmount());
});

test("confirmation and discovery cancellation preserve the flow context", async () => {
  const renderer = await renderNavigator();
  await openDailyLog(renderer);
  await act(async () => labeled(renderer.root, "Add Food to Lunch").props.onPress());
  const resultsScroll = renderer.root.findAllByType(ScrollView).at(-1)!;
  await act(async () => resultsScroll.props.onScroll({ nativeEvent: { contentOffset: { y: 73 } } }));
  await selectSavedFood(renderer);
  await act(async () => labeled(renderer.root, "Cancel logging").props.onPress());
  expect(screenText(renderer.root)).toContain("Logging for 2026-07-13");
  expect(screenText(renderer.root)).toContain("Initial meal: lunch");
  expect(optionalLabeled(renderer.root, "Cancel Add Food")).toBeDefined();
  const returnedResultsScroll = renderer.root.findAllByType(ScrollView).at(-1)!;
  await act(async () => returnedResultsScroll.props.onContentSizeChange());
  expect((returnedResultsScroll.instance as unknown as { scrollTo: jest.Mock }).scrollTo).toHaveBeenCalledWith({ y: 73, animated: false });
  expect(screenText(renderer.root)).toContain("Saved Foods");
  await act(async () => labeled(renderer.root, "Cancel Add Food").props.onPress());
  expect(screenText(renderer.root)).not.toContain("Past date");
  expect(optionalLabeled(renderer.root, "Add Food to Lunch")).toBeDefined();
  await act(async () => renderer.unmount());
});

test("restricted origin dates are revalidated in confirmation without substitution", async () => {
  const renderer = await renderNavigator();
  await openDailyLog(renderer);
  await act(async () => labeled(renderer.root, "Add Food to Dinner").props.onPress());
  await selectSavedFood(renderer);
  mockCalendar.data = { ...mockCalendar.data!, today: "2026-07-12" };
  await act(async () => updateNavigator(renderer));
  expect(screenText(renderer.root)).toContain("Logging for 2026-07-13");
  await act(async () => labeled(renderer.root, "Save log").props.onPress());
  expect(screenText(renderer.root)).toContain("This date is no longer eligible for logging. No entry was created.");
  expect(mockCreateLog).not.toHaveBeenCalled();
  await act(async () => renderer.unmount());
});

test("confirmed projection remains visible when independent refreshes fail", async () => {
  const renderer = await renderNavigator();
  await openDailyLog(renderer);
  await act(async () => labeled(renderer.root, "Add Food to Snack").props.onPress());
  await selectSavedFood(renderer);
  await act(async () => labeled(renderer.root, "Save log").props.onPress());
  mockLogs = { ...mockLogs, isError: true, isRefetchError: true, error: new Error("entries offline") };
  mockSummary = { ...mockSummary, isError: true, isRefetchError: true, error: new Error("totals offline") };
  mockTargets = { ...mockTargets, isError: true, isRefetchError: true, error: new Error("targets offline") };
  await act(async () => updateNavigator(renderer));
  const text = screenText(renderer.root);
  expect(text).toContain("Oatmeal");
  expect(text).toContain("Entries could not be refreshed; showing the last confirmed entries.");

  // E4-07 removes the old full Totals and Target Progress
  // surfaces. Cached target-comparison evidence still
  // drives the compact four-row summary.
  expect(text).toContain("Nutrition");
  expect(text).toContain("250 / 2,000 kcal");
  expect(text).not.toContain("Totals could not be refreshed; showing the last confirmed totals.");
  expect(text).not.toContain("Target comparisons could not be refreshed; showing the last confirmed progress.");
  expect(text).not.toContain("Could not save this log");
  await act(async () => renderer.unmount());
});

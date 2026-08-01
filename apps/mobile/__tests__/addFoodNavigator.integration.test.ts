import React from "react";
import { Pressable, ScrollView, Text } from "react-native";
import TestRenderer, { act, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import type { Food, FoodResolvedNutrition } from "../src/features/foods/api/types";
import type { DailyLog, DailySummary } from "../src/features/logging/api/types";
import type { DailyTargetComparison } from "../src/features/targets/api/types";
import { AppNavigator } from "../src/app/navigation/AppNavigator";

let mockLogs: QueryState<DailyLog[]>;
let mockSummary: QueryState<DailySummary>;
let mockTargets: QueryState<DailyTargetComparison>;
let mockCalendar: QueryState<CalendarState>;
let mockFoodQuery: QueryState<Food>;
let mockResolvedNutrition: QueryState<FoodResolvedNutrition>;

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

jest.mock("../src/shared/components/RootScreenHeader", () => {
  const mockReact = require("react");
  const { Text: MockText } = require("react-native");
  return { RootScreenHeader: ({ title }: { title: string }) => mockReact.createElement(MockText, null, title) };
});

jest.mock("../src/app/navigation/BottomNavigation", () => {
  const mockReact = require("react");
  const { Pressable: MockPressable, Text: MockText } = require("react-native");
  return {
    BottomNavigation: ({ onSelect }: { onSelect: (tab: "daily-log") => void }) => mockReact.createElement(
      MockPressable,
      { accessibilityLabel: "Daily Log tab", onPress: () => onSelect("daily-log") },
      mockReact.createElement(MockText, null, "Daily Log tab"),
    ),
  };
});

// These routes are outside the E1-08 contract. Keeping them inert makes this
// test exercise the real navigator and logging routes without booting their
// unrelated data dependencies.
jest.mock("../src/features/foods/screens/FoodDetailsScreen", () => ({ FoodDetailsScreen: () => null }));
jest.mock("../src/features/foods/screens/FoodFormScreen", () => ({ FoodFormScreen: () => null }));
jest.mock("../src/features/foods/screens/SavedFoodsScreen", () => ({ SavedFoodsScreen: () => null }));
jest.mock("../src/features/recipes/screens/IngredientPickerScreen", () => ({ IngredientPickerScreen: () => null }));
jest.mock("../src/features/recipes/screens/RecipeDetailScreen", () => ({ RecipeDetailScreen: () => null }));
jest.mock("../src/features/recipes/screens/RecipeFormScreen", () => ({ RecipeFormScreen: () => null }));
jest.mock("../src/features/recipes/screens/RecipeListScreen", () => ({ RecipeListScreen: () => null }));
jest.mock("../src/features/usda/screens/UsdaPreviewScreen", () => ({ UsdaPreviewScreen: () => null }));
jest.mock("../src/features/usda/screens/UsdaSearchScreen", () => ({ UsdaSearchScreen: () => null }));
jest.mock("../src/features/ocr/diagnostics/OcrDiagnosticsScreen", () => ({ OcrDiagnosticsScreen: () => null }));
jest.mock("../src/features/ocr/screens/NutritionScanScreen", () => ({ NutritionScanScreen: () => null }));
jest.mock("../src/features/ocr/screens/NutritionConfirmationScreen", () => ({ NutritionConfirmationScreen: () => null }));
jest.mock("../src/app/settings/SettingsScreen", () => ({ SettingsScreen: () => null }));
jest.mock("../src/features/targets/TargetSettingsScreen", () => ({ TargetSettingsScreen: () => null }));
jest.mock("@react-native-community/datetimepicker", () => ({ __esModule: true, default: () => null }));

jest.mock("../src/features/calendar/hooks/useCalendar", () => ({
  useCalendarState: () => mockCalendar,
}));

jest.mock("../src/features/targets/hooks/useDailyTargetComparison", () => ({
  ...jest.requireActual("../src/features/targets/hooks/useDailyTargetComparison"),
  useDailyTargetComparison: () => mockTargets,
}));

jest.mock("../src/features/foods/hooks/useFoods", () => ({
  useFoods: () => ({ data: [], isLoading: false, isFetching: false, isError: false, refetch: jest.fn() }),
  useFavoriteFoods: () => ({ data: [], isLoading: false, isFetching: false, isError: false, refetch: jest.fn() }),
  useRecentFoods: () => ({ data: [], isLoading: false, isFetching: false, isError: false, refetch: jest.fn() }),
  useSavedFoods: () => ({ data: [mockFoodQuery.data], isLoading: false, isFetching: false, isError: false, refetch: jest.fn() }),
  useFood: () => mockFoodQuery,
  useFoodResolvedNutrition: () => mockResolvedNutrition,
}));

jest.mock("../src/features/logging/hooks/useLogs", () => ({
  ...jest.requireActual("../src/features/logging/hooks/useLogs"),
  useDailyLogs: () => mockLogs,
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
  targetDirectionSemanticsVersion: "test",
  comparisons: [{
    nutrientId: "calories",
    consumedAmount: "250",
    targetAmount: "2000",
    unit: "kcal",
    percentage: "12.5",
    authority: "manual_override",
    direction: "target",
    status: "available",
    reasonCode: null,
    noteCode: null,
    hasUnknownContributors: false,
  }],
};

const mockCreateLog = jest.fn(async (input: Record<string, unknown>) => {
  const entry: DailyLog = {
    id: `log-${(mockLogs.data ?? []).length + 1}`,
    food_item_id: String(input.food_item_id),
    food_name_snapshot: food.name,
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
  mockSummary.data = { logged_date: entry.logged_date, totals: [total] };
  mockTargets.data = { ...targets, date: entry.logged_date };
  return entry;
});

function emptyQuery<T>(data: T): QueryState<T> {
  return { data, isLoading: false, isFetching: false, isError: false, refetch: jest.fn() };
}

function resetState() {
  mockLogs = emptyQuery([]);
  mockSummary = emptyQuery({ logged_date: "2026-07-14", totals: [] });
  mockTargets = emptyQuery(targets);
  mockCalendar = emptyQuery({ is_established: true, authoritative_time_zone: "UTC", calendar_revision: 4, today: "2026-07-14" });
  mockFoodQuery = emptyQuery(food);
  mockResolvedNutrition = emptyQuery(nutrition);
  mockCreateLog.mockClear();
}

async function renderNavigator(): Promise<ReactTestRenderer> {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(AppNavigator));
  });
  return renderer;
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

afterEach(() => {
  jest.useRealTimers();
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

  // A second flow starts with no meal assignment and reaches the same route.
  await act(async () => labeled(renderer.root, "Add Food without meal").props.onPress());
  expect(screenText(renderer.root)).toContain("No meal selected");
  await selectSavedFood(renderer);
  expect(labeled(renderer.root, "Meal none").props.accessibilityState.checked).toBe(true);
  await act(async () => labeled(renderer.root, "Save log").props.onPress());
  expect(screenText(renderer.root)).toContain("Oatmeal");
  expect(screenText(renderer.root)).toContain("Past date");
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
  expect(screenText(renderer.root)).toContain("Past date");
  expect(optionalLabeled(renderer.root, "Add Food to Lunch")).toBeDefined();
  await act(async () => renderer.unmount());
});

test("restricted origin dates are revalidated in confirmation without substitution", async () => {
  const renderer = await renderNavigator();
  await openDailyLog(renderer);
  await act(async () => labeled(renderer.root, "Add Food to Dinner").props.onPress());
  await selectSavedFood(renderer);
  mockCalendar.data = { ...mockCalendar.data!, today: "2026-07-12" };
  await act(async () => renderer.update(React.createElement(AppNavigator)));
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
  await act(async () => renderer.update(React.createElement(AppNavigator)));
  const text = screenText(renderer.root);
  expect(text).toContain("Oatmeal");
  expect(text).toContain("Entries could not be refreshed; showing the last confirmed entries.");
  expect(text).toContain("Totals could not be refreshed; showing the last confirmed totals.");
  expect(text).toContain("Target comparisons could not be refreshed; showing the last confirmed progress.");
  expect(text).toContain("250");
  expect(text).not.toContain("Could not save this log");
  await act(async () => renderer.unmount());
});

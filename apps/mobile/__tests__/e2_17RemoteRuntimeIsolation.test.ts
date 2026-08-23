import AsyncStorage from "@react-native-async-storage/async-storage";
import React from "react";
import TestRenderer, { act } from "react-test-renderer";

let mockLocalRuntimeModuleEvaluations = 0;
let mockTransferGateModuleEvaluations = 0;
let mockSqliteModuleEvaluations = 0;
const mockOpenDatabaseAsync = jest.fn();

jest.mock("../src/runtime/local/localRuntimeFoundation", () => {
  mockLocalRuntimeModuleEvaluations += 1;
  return { openLocalRuntimeFoundation: jest.fn() };
});

jest.mock("../src/transfer/e2_15/LocalFirstStartGate", () => {
  mockTransferGateModuleEvaluations += 1;
  return { LocalFirstStartRuntimeBootstrap: () => null };
});

jest.mock("expo-sqlite", () => {
  mockSqliteModuleEvaluations += 1;
  return { openDatabaseAsync: mockOpenDatabaseAsync };
});

jest.mock("../src/runtime/RuntimeBootstrapGate", () => ({
  ApplicationRuntimeBootstrap: () => null,
  RuntimeBootstrapStatus: () => null,
}));

jest.mock("../src/app/navigation/AppNavigator", () => ({ AppNavigator: () => null }));
jest.mock("../src/app/providers/AppProviders", () => ({ AppProviders: () => null }));
jest.mock("../src/app/theme/AppTheme", () => ({
  statusBarStyle: () => "dark",
  useAppTheme: () => ({ colors: { background: "white" } }),
}));

import { remoteNutritionRuntime } from "../src/runtime/remote/remoteNutritionRuntime";
import {
  bootstrapApplicationRuntime,
} from "../src/runtime/applicationRuntimeBootstrap";
import App from "../src/App";

const REMOTE_CONFIGURATION = {
  dataAuthority: "remote" as const,
  deploymentMode: "test" as const,
  apiBaseUrl: "http://localhost:8000/api/v1",
};

type ObservedRequest = Readonly<{ target: string; method: string }>;

function successfulResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as Response;
}

function missingField() {
  return {
    value: null,
    comparison: null,
    source_text: "",
    source_observation_ids: [],
    confidence: 0,
    status: "missing",
    warning_codes: [],
  };
}

function parsedNutritionLabelResponse() {
  return {
    serving: null,
    calories: missingField(),
    nutrients: [],
    unparsed_lines: [],
    warnings: [],
    parser_version: "nutrition_label_v1",
  };
}

function comparisonResponse() {
  return {
    date: "2026-08-13",
    daily_value_catalog_version: "2026-01",
    dri_dataset_version: "nasem_dri_adults_2026_v1",
    target_direction_semantics_version: "v1",
    comparisons: [],
  };
}

function calendarStateResponse() {
  return {
    is_established: false,
    authoritative_time_zone: null,
    calendar_revision: 0,
    today: null,
  };
}

function nutrientDefinitionListResponse() {
  return [];
}

function resolvedNutritionResponse() {
  return {
    nutrition_authority: "food_item",
    recipe_id: null,
    recipe_publication_revision_id: null,
    amounts: [],
  };
}

function recipeResponse() {
  return {
    id: "00000000-0000-4000-8000-000000000801",
    user_id: "00000000-0000-4000-8000-000000000802",
    published_food_item_id: null,
    name: "Remote Recipe",
    notes: null,
    serving_count_yield: null,
    final_cooked_weight_grams: null,
    final_cooked_weight_display_quantity: null,
    final_cooked_weight_display_unit: null,
    needs_republish: false,
    created_at: "2026-08-13T12:00:00Z",
    updated_at: "2026-08-13T12:00:00Z",
    ingredients: [],
  };
}

function usdaSearchResponse() {
  return {
    query: "beans",
    page_number: 1,
    page_size: 20,
    total_hits: 0,
    foods: [],
  };
}

beforeEach(() => {
  (AsyncStorage.getItem as jest.Mock).mockClear();
  (AsyncStorage.setItem as jest.Mock).mockClear();
  (AsyncStorage.removeItem as jest.Mock).mockClear();
  mockOpenDatabaseAsync.mockClear();
});

test("remote bootstrap evaluates only the remote registry and leaves local startup seams untouched", async () => {
  const handle = await bootstrapApplicationRuntime(REMOTE_CONFIGURATION);

  expect(handle.runtime).toBe(remoteNutritionRuntime);
  await handle.close();
  expect({
    localRuntimeModuleEvaluations: mockLocalRuntimeModuleEvaluations,
    transferGateModuleEvaluations: mockTransferGateModuleEvaluations,
    sqliteModuleEvaluations: mockSqliteModuleEvaluations,
    sqliteOpenCalls: mockOpenDatabaseAsync.mock.calls.length,
  }).toEqual({
    localRuntimeModuleEvaluations: 0,
    transferGateModuleEvaluations: 0,
    sqliteModuleEvaluations: 0,
    sqliteOpenCalls: 0,
  });
});

test("the remote application branch does not evaluate the local startup or SQLite modules", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(App));
    await Promise.resolve();
  });

  expect({
    transferGateModuleEvaluations: mockTransferGateModuleEvaluations,
    sqliteModuleEvaluations: mockSqliteModuleEvaluations,
    sqliteOpenCalls: mockOpenDatabaseAsync.mock.calls.length,
  }).toEqual({
    transferGateModuleEvaluations: 0,
    sqliteModuleEvaluations: 0,
    sqliteOpenCalls: 0,
  });
  await act(async () => { renderer.unmount(); });
});

test("remote capability calls use the central application-data HTTP path and never initialize local state", async () => {
  const requests: ObservedRequest[] = [];
  const fetchSpy = jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const target = String(input);
    const method = String(init?.method ?? "GET");
    requests.push({ target, method });
    if (target.endsWith("/settings/calendar")) {
      return successfulResponse(
        calendarStateResponse(),
      );
    }
    if (target.endsWith("/nutrients")) {
      return successfulResponse(
        nutrientDefinitionListResponse(),
      );
    }
    if (
      target.endsWith(
        "/foods/food-1/resolved-nutrition",
      )
    ) {
      return successfulResponse(
        resolvedNutritionResponse(),
      );
    }
    if (target.endsWith("/recipes/recipe-1")) {
      return successfulResponse(
        recipeResponse(),
      );
    }
    if (target.includes("/targets/daily-comparison?")) return successfulResponse(comparisonResponse());
    if (target.endsWith("/ocr/nutrition-label/parse")) return successfulResponse(parsedNutritionLabelResponse());
    if (target.includes("/logs?date=")) return successfulResponse({ logs: [] });
    if (target.includes("/logs/mutations/")) {
      return successfulResponse({
        operation: "create",
        client_request_id: "00000000-0000-4000-8000-000000000901",
        status: "confirmed_non_commit",
        log_id: null,
        source_logged_date: null,
        destination_logged_date: null,
        result: null,
        completion: null,
      });
    }
    if (
      target.endsWith(
        "/usda/foods/search?query=beans&page_size=20",
      )
    ) {
      return successfulResponse(
        usdaSearchResponse(),
      );
    }
    return successfulResponse({});
  });

  await remoteNutritionRuntime.calendar.getState();
  await remoteNutritionRuntime.nutrients.list();
  await remoteNutritionRuntime.foods.getResolvedNutrition("food-1");
  await remoteNutritionRuntime.recipes.get("recipe-1");
  await remoteNutritionRuntime.dailyLogs.list("2026-08-13");
  await remoteNutritionRuntime.dailyLogs.getMutationStatus(
    "00000000-0000-4000-8000-000000000901",
    "create",
  );
  await remoteNutritionRuntime.targets.getDailyComparison("2026-08-13");
  await remoteNutritionRuntime.ocr.parseNutritionLabel({
    fullText: "Nutrition Facts",
    observations: [],
    image: { width: 100, height: 100, orientationApplied: true },
    recognition: {
      platform: "ios",
      recognitionLevel: "accurate",
      languages: ["en-US"],
      durationMs: 1,
    },
  });
  await remoteNutritionRuntime.usda.search("beans");

  expect(requests).toEqual([
    { target: "http://localhost:8000/api/v1/settings/calendar", method: "GET" },
    { target: "http://localhost:8000/api/v1/nutrients", method: "GET" },
    { target: "http://localhost:8000/api/v1/foods/food-1/resolved-nutrition", method: "GET" },
    { target: "http://localhost:8000/api/v1/recipes/recipe-1", method: "GET" },
    { target: "http://localhost:8000/api/v1/logs?date=2026-08-13", method: "GET" },
    { target: "http://localhost:8000/api/v1/logs/mutations/00000000-0000-4000-8000-000000000901?operation=create", method: "GET" },
    { target: "http://localhost:8000/api/v1/targets/daily-comparison?date=2026-08-13", method: "GET" },
    { target: "http://localhost:8000/api/v1/ocr/nutrition-label/parse", method: "POST" },
    { target: "http://localhost:8000/api/v1/usda/foods/search?query=beans&page_size=20", method: "GET" },
  ]);
  expect(fetchSpy).toHaveBeenCalledTimes(9);

  const localPersistenceObservations = {
    localRuntimeModuleEvaluations: mockLocalRuntimeModuleEvaluations,
    transferGateModuleEvaluations: mockTransferGateModuleEvaluations,
    sqliteModuleEvaluations: mockSqliteModuleEvaluations,
    sqliteOpenCalls: mockOpenDatabaseAsync.mock.calls.length,
    recoveryMetadataReads: (AsyncStorage.getItem as jest.Mock).mock.calls.length,
    recoveryMetadataWrites: (AsyncStorage.setItem as jest.Mock).mock.calls.length,
    recoveryMetadataRemovals: (AsyncStorage.removeItem as jest.Mock).mock.calls.length,
  };
  expect(localPersistenceObservations).toEqual({
    localRuntimeModuleEvaluations: 0,
    transferGateModuleEvaluations: 0,
    sqliteModuleEvaluations: 0,
    sqliteOpenCalls: 0,
    recoveryMetadataReads: 0,
    recoveryMetadataWrites: 0,
    recoveryMetadataRemovals: 0,
  });

  fetchSpy.mockRestore();
});

test("a remote operation failure remains unresolved in remote authority without local fallback", async () => {
  const fetchSpy = jest.spyOn(global, "fetch")
    .mockRejectedValue(new TypeError("remote transport unavailable"));

  await expect(remoteNutritionRuntime.foods.create({} as never)).rejects.toMatchObject({
    kind: "unavailable",
    mutationOutcome: "unresolved",
    retryable: true,
  });
  expect(fetchSpy).toHaveBeenCalledTimes(1);
  expect(String(fetchSpy.mock.calls[0][0])).toBe("http://localhost:8000/api/v1/foods");
  expect({
    localRuntimeModuleEvaluations: mockLocalRuntimeModuleEvaluations,
    transferGateModuleEvaluations: mockTransferGateModuleEvaluations,
    sqliteModuleEvaluations: mockSqliteModuleEvaluations,
    sqliteOpenCalls: mockOpenDatabaseAsync.mock.calls.length,
  }).toEqual({
    localRuntimeModuleEvaluations: 0,
    transferGateModuleEvaluations: 0,
    sqliteModuleEvaluations: 0,
    sqliteOpenCalls: 0,
  });

  fetchSpy.mockRestore();
});

jest.mock("../src/features/calendar/api/calendarApi", () => ({
  getCalendarState: jest.fn(async () => ({ marker: "calendar" })),
}));
jest.mock("../src/features/foods/api/foodApi", () => ({
  listNutrients: jest.fn(async () => [{ id: "sodium" }, { id: "calories" }]),
  listFoods: jest.fn(async () => [{ id: "food-b" }, { id: "food-a" }]),
}));
jest.mock("../src/features/recipes/api/recipeApi", () => ({
  listRecipes: jest.fn(async () => [{ id: "recipe-b" }, { id: "recipe-a" }]),
}));
jest.mock("../src/features/logging/api/logApi", () => ({
  listLogs: jest.fn(async () => [{ id: "log-b" }, { id: "log-a" }]),
}));
jest.mock("../src/features/targets/api/targetApi", () => ({
  getTargets: jest.fn(async () => ({ marker: "targets" })),
}));
jest.mock("../src/features/ocr/api/ocrApi", () => ({
  parseNutritionLabel: jest.fn(async () => ({ marker: "ocr" })),
}));
jest.mock("../src/features/usda/api/usdaApi", () => ({
  searchUsdaFoods: jest.fn(async () => ({ foods: [{ fdc_id: 2 }, { fdc_id: 1 }] })),
}));

import * as calendarApi from "../src/features/calendar/api/calendarApi";
import * as foodApi from "../src/features/foods/api/foodApi";
import * as recipeApi from "../src/features/recipes/api/recipeApi";
import * as logApi from "../src/features/logging/api/logApi";
import * as targetApi from "../src/features/targets/api/targetApi";
import * as ocrApi from "../src/features/ocr/api/ocrApi";
import * as usdaApi from "../src/features/usda/api/usdaApi";
import { remoteNutritionRuntime } from "../src/runtime/remote/remoteNutritionRuntime";

const mockGetCalendarState = calendarApi.getCalendarState as jest.Mock;
const mockListNutrients = foodApi.listNutrients as jest.Mock;
const mockListFoods = foodApi.listFoods as jest.Mock;
const mockListRecipes = recipeApi.listRecipes as jest.Mock;
const mockListLogs = logApi.listLogs as jest.Mock;
const mockGetTargets = targetApi.getTargets as jest.Mock;
const mockParseNutritionLabel = ocrApi.parseNutritionLabel as jest.Mock;
const mockSearchUsdaFoods = usdaApi.searchUsdaFoods as jest.Mock;
const parityFixture = require("../../../packages/shared-contracts/e2-02/parity-fixtures.json") as {
  behavioral_fixtures: Array<{ kind: string; payload: unknown }>;
};

test("one composed runtime exposes every approved feature interface", () => {
  expect(Object.keys(remoteNutritionRuntime)).toEqual([
    "authority",
    "calendar",
    "nutrients",
    "foods",
    "recipes",
    "dailyLogs",
    "targets",
    "ocr",
    "usda",
  ]);
  expect(Object.keys(remoteNutritionRuntime.calendar)).toEqual([
    "getState", "establishTimeZone", "previewTimeZoneChange", "confirmTimeZoneChange",
  ]);
  expect(Object.keys(remoteNutritionRuntime.nutrients)).toEqual(["list"]);
  expect(Object.keys(remoteNutritionRuntime.foods)).toEqual([
    "list", "get", "listFavorites", "listRecent", "setFavorite",
    "getResolvedNutrition", "create", "update", "delete", "duplicate",
    "createServingDefinition",
  ]);
  expect(Object.keys(remoteNutritionRuntime.recipes)).toEqual([
    "list", "get", "create", "update", "delete", "getNutrition", "publish",
  ]);
  expect(Object.keys(remoteNutritionRuntime.dailyLogs)).toEqual([
    "list", "listFuture", "listRecentEntries", "create", "update",
    "getEditContext", "delete", "getMutationStatus", "getDailySummary",
  ]);
  expect(Object.keys(remoteNutritionRuntime.targets)).toEqual([
    "getConfiguration", "updateConfiguration", "resetOverride", "getDailyComparison",
  ]);
  expect(Object.keys(remoteNutritionRuntime.ocr)).toEqual([
    "parseNutritionLabel", "confirmNutritionLabel",
  ]);
  expect(Object.keys(remoteNutritionRuntime.usda)).toEqual([
    "search", "getPreview", "importFood",
  ]);
});

test("representative operations delegate once for all eight feature surfaces and preserve order", async () => {
  const results = await Promise.all([
    remoteNutritionRuntime.calendar.getState(),
    remoteNutritionRuntime.nutrients.list(),
    remoteNutritionRuntime.foods.list("query"),
    remoteNutritionRuntime.recipes.list("query"),
    remoteNutritionRuntime.dailyLogs.list("2026-08-08"),
    remoteNutritionRuntime.targets.getConfiguration(),
    remoteNutritionRuntime.ocr.parseNutritionLabel({
      fullText: "label",
      observations: [],
      image: { width: 100, height: 100, orientationApplied: true },
      recognition: {
        platform: "ios",
        recognitionLevel: "accurate",
        languages: ["en-US"],
        durationMs: 1,
      },
    }),
    remoteNutritionRuntime.usda.search("beans"),
  ]);

  expect(mockGetCalendarState).toHaveBeenCalledTimes(1);
  expect(mockListNutrients).toHaveBeenCalledTimes(1);
  expect(mockListFoods).toHaveBeenCalledWith("query", undefined);
  expect(mockListRecipes).toHaveBeenCalledWith("query");
  expect(mockListLogs).toHaveBeenCalledWith("2026-08-08");
  expect(mockGetTargets).toHaveBeenCalledTimes(1);
  expect(mockParseNutritionLabel).toHaveBeenCalledTimes(1);
  expect(mockSearchUsdaFoods).toHaveBeenCalledWith("beans");
  expect(results[1]).toEqual([{ id: "sodium" }, { id: "calories" }]);
  expect(results[2]).toEqual([{ id: "food-b" }, { id: "food-a" }]);
  expect(results[3]).toEqual([{ id: "recipe-b" }, { id: "recipe-a" }]);
  expect(results[4]).toEqual([{ id: "log-b" }, { id: "log-a" }]);
  expect(results[7]).toEqual({ foods: [{ fdc_id: 2 }, { fdc_id: 1 }] });
});

test("remote adapter passes shared parity payloads without numeric coercion", async () => {
  const food = parityFixture.behavioral_fixtures.find(({ kind }) => kind === "food")?.payload;
  const snapshot = parityFixture.behavioral_fixtures.find(({ kind }) => kind === "daily_log_snapshot")?.payload;
  expect(food).toBeDefined();
  expect(snapshot).toBeDefined();

  mockListFoods.mockResolvedValueOnce([food]);
  mockListLogs.mockResolvedValueOnce([snapshot]);

  await expect(remoteNutritionRuntime.foods.list()).resolves.toEqual([food]);
  await expect(remoteNutritionRuntime.dailyLogs.list("2026-02-28")).resolves.toEqual([snapshot]);
});

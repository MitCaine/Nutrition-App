jest.mock("../src/features/calendar/api/calendarApi", () => ({
  getCalendarState: jest.fn(async () => ({ marker: "calendar" })),
  establishCalendarTimeZone: jest.fn(async () => ({ marker: "calendar-establish" })),
  previewCalendarTimeZoneChange: jest.fn(async () => ({ marker: "calendar-preview" })),
  confirmCalendarTimeZoneChange: jest.fn(async () => ({ marker: "calendar-confirm" })),
}));
jest.mock("../src/features/foods/api/foodApi", () => ({
  listNutrients: jest.fn(async () => [{ id: "sodium" }, { id: "calories" }]),
  listFoods: jest.fn(async () => [{ id: "food-b" }, { id: "food-a" }]),
  getFood: jest.fn(async () => ({ marker: "food-get" })),
  listFavoriteFoods: jest.fn(async () => [{ marker: "food-favorites" }]),
  listRecentFoods: jest.fn(async () => [{ marker: "food-recent" }]),
  setFoodFavorite: jest.fn(async () => ({ marker: "food-favorite" })),
  getFoodResolvedNutrition: jest.fn(async () => ({ marker: "food-nutrition" })),
  createFood: jest.fn(async () => ({ marker: "food-create" })),
  updateFood: jest.fn(async () => ({ marker: "food-update" })),
  deleteFood: jest.fn(async () => ({ marker: "food-delete" })),
  duplicateFood: jest.fn(async () => ({ marker: "food-duplicate" })),
  createFoodServing: jest.fn(async () => ({ marker: "food-serving" })),
}));
jest.mock("../src/features/recipes/api/recipeApi", () => ({
  listRecipes: jest.fn(async () => [{ id: "recipe-b" }, { id: "recipe-a" }]),
  getRecipe: jest.fn(async () => ({ marker: "recipe-get" })),
  createRecipe: jest.fn(async () => ({ marker: "recipe-create" })),
  updateRecipe: jest.fn(async () => ({ marker: "recipe-update" })),
  deleteRecipe: jest.fn(async () => undefined),
  duplicateRecipe: jest.fn(async () => ({ marker: "recipe-duplicate" })),
  getRecipeNutrition: jest.fn(async () => ({ marker: "recipe-nutrition" })),
  publishRecipe: jest.fn(async () => ({ marker: "recipe-publish" })),
}));
jest.mock("../src/features/logging/api/logApi", () => ({
  listLogs: jest.fn(async () => [{ id: "log-b" }, { id: "log-a" }]),
  listFutureEntries: jest.fn(async () => [{ marker: "log-future" }]),
  listRecentEntries: jest.fn(async () => [{ marker: "log-recent" }]),
  createLog: jest.fn(async () => ({ marker: "log-create" })),
  updateLog: jest.fn(async () => ({ marker: "log-update" })),
  getLogEditContext: jest.fn(async () => ({ marker: "log-edit-context" })),
  deleteLog: jest.fn(async () => undefined),
  markDayComplete: jest.fn(async () => ({ marker: "log-complete" })),
  getLogMutationStatus: jest.fn(async () => ({ marker: "log-status" })),
  getDailySummary: jest.fn(async () => ({ marker: "log-summary" })),
}));
jest.mock("../src/features/targets/api/targetApi", () => ({
  getTargets: jest.fn(async () => ({ marker: "targets" })),
  updateTargets: jest.fn(async () => ({ marker: "targets-update" })),
  resetTargetOverride: jest.fn(async () => ({ marker: "targets-reset" })),
  getDailyTargetComparison: jest.fn(async () => ({ marker: "targets-comparison" })),
}));
jest.mock("../src/features/ocr/api/ocrApi", () => ({
  parseNutritionLabel: jest.fn(async () => ({ marker: "ocr" })),
  confirmNutritionLabel: jest.fn(async () => ({ marker: "ocr-confirm" })),
}));
jest.mock("../src/features/usda/api/usdaApi", () => ({
  searchUsdaFoods: jest.fn(async () => ({ foods: [{ fdc_id: 2 }, { fdc_id: 1 }] })),
  getUsdaFoodPreview: jest.fn(async () => ({ marker: "usda-preview" })),
  importUsdaFood: jest.fn(async () => ({ marker: "usda-import" })),
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
const mockEstablishCalendarTimeZone = calendarApi.establishCalendarTimeZone as jest.Mock;
const mockPreviewCalendarTimeZoneChange = calendarApi.previewCalendarTimeZoneChange as jest.Mock;
const mockConfirmCalendarTimeZoneChange = calendarApi.confirmCalendarTimeZoneChange as jest.Mock;
const mockListNutrients = foodApi.listNutrients as jest.Mock;
const mockListFoods = foodApi.listFoods as jest.Mock;
const mockGetFood = foodApi.getFood as jest.Mock;
const mockListFavoriteFoods = foodApi.listFavoriteFoods as jest.Mock;
const mockListRecentFoods = foodApi.listRecentFoods as jest.Mock;
const mockSetFoodFavorite = foodApi.setFoodFavorite as jest.Mock;
const mockGetFoodResolvedNutrition = foodApi.getFoodResolvedNutrition as jest.Mock;
const mockCreateFood = foodApi.createFood as jest.Mock;
const mockUpdateFood = foodApi.updateFood as jest.Mock;
const mockDeleteFood = foodApi.deleteFood as jest.Mock;
const mockDuplicateFood = foodApi.duplicateFood as jest.Mock;
const mockCreateFoodServing = foodApi.createFoodServing as jest.Mock;
const mockListRecipes = recipeApi.listRecipes as jest.Mock;
const mockGetRecipe = recipeApi.getRecipe as jest.Mock;
const mockCreateRecipe = recipeApi.createRecipe as jest.Mock;
const mockUpdateRecipe = recipeApi.updateRecipe as jest.Mock;
const mockDeleteRecipe = recipeApi.deleteRecipe as jest.Mock;
const mockDuplicateRecipe = recipeApi.duplicateRecipe as jest.Mock;
const mockGetRecipeNutrition = recipeApi.getRecipeNutrition as jest.Mock;
const mockPublishRecipe = recipeApi.publishRecipe as jest.Mock;
const mockListLogs = logApi.listLogs as jest.Mock;
const mockListFutureEntries = logApi.listFutureEntries as jest.Mock;
const mockListRecentEntries = logApi.listRecentEntries as jest.Mock;
const mockCreateLog = logApi.createLog as jest.Mock;
const mockUpdateLog = logApi.updateLog as jest.Mock;
const mockGetLogEditContext = logApi.getLogEditContext as jest.Mock;
const mockDeleteLog = logApi.deleteLog as jest.Mock;
const mockMarkDayComplete = logApi.markDayComplete as jest.Mock;
const mockGetLogMutationStatus = logApi.getLogMutationStatus as jest.Mock;
const mockGetDailySummary = logApi.getDailySummary as jest.Mock;
const mockGetTargets = targetApi.getTargets as jest.Mock;
const mockUpdateTargets = targetApi.updateTargets as jest.Mock;
const mockResetTargetOverride = targetApi.resetTargetOverride as jest.Mock;
const mockGetDailyTargetComparison = targetApi.getDailyTargetComparison as jest.Mock;
const mockParseNutritionLabel = ocrApi.parseNutritionLabel as jest.Mock;
const mockConfirmNutritionLabel = ocrApi.confirmNutritionLabel as jest.Mock;
const mockSearchUsdaFoods = usdaApi.searchUsdaFoods as jest.Mock;
const mockGetUsdaFoodPreview = usdaApi.getUsdaFoodPreview as jest.Mock;
const mockImportUsdaFood = usdaApi.importUsdaFood as jest.Mock;
const parityFixture = require("../../../packages/shared-contracts/e2-02/parity-fixtures.json") as {
  behavioral_fixtures: Array<{ kind: string; payload: unknown }>;
};

beforeEach(() => {
  jest.clearAllMocks();
});

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
    "list", "get", "create", "update", "delete", "duplicate", "getNutrition", "publish",
  ]);
  expect(Object.keys(remoteNutritionRuntime.dailyLogs)).toEqual([
    "list", "listFuture", "listRecentEntries", "create", "update",
    "getEditContext", "delete", "markDayComplete", "getMutationStatus", "getHistoryRange",
    "getDailySummary",
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

test("every remote runtime operation delegates to its remote feature API exactly once", async () => {
  const calendarConfirmation = {
    timeZone: "UTC",
    calendarRevision: 1,
    previewToken: "preview-1",
  } as never;
  const foodInput = { name: "Food" } as never;
  const foodUpdate = { name: "Updated Food" } as never;
  const servingInput = { label: "1 serving" } as never;
  const recipeInput = { name: "Recipe" } as never;
  const recipeUpdate = { name: "Updated Recipe" } as never;
  const logInput = { client_request_id: "request-1" } as never;
  const logUpdate = { client_request_id: "request-2" } as never;
  const logDelete = { client_request_id: "request-3" } as never;
  const completeInput = {
    client_request_id: "request-6",
    calendar_revision: 4,
    logged_date: "2026-08-13",
  } as never;
  const targetInput = { profile: null } as never;
  const ocrInput = {} as never;

  await Promise.all([
    remoteNutritionRuntime.calendar.getState(),
    remoteNutritionRuntime.calendar.establishTimeZone("UTC"),
    remoteNutritionRuntime.calendar.previewTimeZoneChange("UTC"),
    remoteNutritionRuntime.calendar.confirmTimeZoneChange(calendarConfirmation),
    remoteNutritionRuntime.nutrients.list(),
    remoteNutritionRuntime.foods.list("query", "saved"),
    remoteNutritionRuntime.foods.get("food-1"),
    remoteNutritionRuntime.foods.listFavorites(),
    remoteNutritionRuntime.foods.listRecent(5),
    remoteNutritionRuntime.foods.setFavorite("food-1", true),
    remoteNutritionRuntime.foods.getResolvedNutrition("food-1"),
    remoteNutritionRuntime.foods.create(foodInput),
    remoteNutritionRuntime.foods.update("food-1", foodUpdate),
    remoteNutritionRuntime.foods.delete({ foodId: "food-1", removeFromRecipes: true }),
    remoteNutritionRuntime.foods.duplicate({ foodId: "food-1", clientRequestId: "request-4" }),
    remoteNutritionRuntime.foods.createServingDefinition("food-1", servingInput),
    remoteNutritionRuntime.recipes.list("query"),
    remoteNutritionRuntime.recipes.get("recipe-1"),
    remoteNutritionRuntime.recipes.create(recipeInput),
    remoteNutritionRuntime.recipes.update("recipe-1", recipeUpdate),
    remoteNutritionRuntime.recipes.delete({ recipeId: "recipe-1", removeFromRecipes: true }),
    remoteNutritionRuntime.recipes.duplicate({ recipeId: "recipe-1", clientRequestId: "request-duplicate" }),
    remoteNutritionRuntime.recipes.getNutrition("recipe-1"),
    remoteNutritionRuntime.recipes.publish({ recipeId: "recipe-1", clientRequestId: "request-5" }),
    remoteNutritionRuntime.dailyLogs.list("2026-08-13"),
    remoteNutritionRuntime.dailyLogs.listFuture("2026-08-13"),
    remoteNutritionRuntime.dailyLogs.listRecentEntries(),
    remoteNutritionRuntime.dailyLogs.create(logInput),
    remoteNutritionRuntime.dailyLogs.update("log-1", logUpdate),
    remoteNutritionRuntime.dailyLogs.getEditContext("log-1"),
    remoteNutritionRuntime.dailyLogs.delete("log-1", logDelete),
    remoteNutritionRuntime.dailyLogs.markDayComplete(completeInput),
    remoteNutritionRuntime.dailyLogs.getMutationStatus("request-1", "create"),
    remoteNutritionRuntime.dailyLogs.getDailySummary("2026-08-13"),
    remoteNutritionRuntime.targets.getConfiguration(),
    remoteNutritionRuntime.targets.updateConfiguration(targetInput),
    remoteNutritionRuntime.targets.resetOverride("protein"),
    remoteNutritionRuntime.targets.getDailyComparison("2026-08-13"),
    remoteNutritionRuntime.ocr.parseNutritionLabel(ocrInput),
    remoteNutritionRuntime.ocr.confirmNutritionLabel(ocrInput),
    remoteNutritionRuntime.usda.search("beans"),
    remoteNutritionRuntime.usda.getPreview(123),
    remoteNutritionRuntime.usda.importFood(123),
  ]);

  const delegatedOperations = [
    mockGetCalendarState, mockEstablishCalendarTimeZone, mockPreviewCalendarTimeZoneChange,
    mockConfirmCalendarTimeZoneChange, mockListNutrients, mockListFoods, mockGetFood,
    mockListFavoriteFoods, mockListRecentFoods, mockSetFoodFavorite, mockGetFoodResolvedNutrition,
    mockCreateFood, mockUpdateFood, mockDeleteFood, mockDuplicateFood, mockCreateFoodServing,
    mockListRecipes, mockGetRecipe, mockCreateRecipe, mockUpdateRecipe, mockDeleteRecipe,
    mockDuplicateRecipe,
    mockGetRecipeNutrition, mockPublishRecipe, mockListLogs, mockListFutureEntries,
    mockListRecentEntries, mockCreateLog, mockUpdateLog, mockGetLogEditContext, mockDeleteLog,
    mockMarkDayComplete, mockGetLogMutationStatus, mockGetDailySummary, mockGetTargets, mockUpdateTargets,
    mockResetTargetOverride, mockGetDailyTargetComparison, mockParseNutritionLabel,
    mockConfirmNutritionLabel, mockSearchUsdaFoods, mockGetUsdaFoodPreview, mockImportUsdaFood,
  ];
  expect(delegatedOperations).toHaveLength(43);
  for (const operation of delegatedOperations) expect(operation).toHaveBeenCalledTimes(1);

  expect(mockEstablishCalendarTimeZone).toHaveBeenCalledWith("UTC");
  expect(mockPreviewCalendarTimeZoneChange).toHaveBeenCalledWith("UTC");
  expect(mockConfirmCalendarTimeZoneChange).toHaveBeenCalledWith(calendarConfirmation);
  expect(mockListFoods).toHaveBeenCalledWith("query", "saved");
  expect(mockGetFood).toHaveBeenCalledWith("food-1");
  expect(mockDuplicateRecipe).toHaveBeenCalledWith({
    recipeId: "recipe-1",
    clientRequestId: "request-duplicate",
  });
  expect(mockListRecentFoods).toHaveBeenCalledWith(5);
  expect(mockSetFoodFavorite).toHaveBeenCalledWith("food-1", true);
  expect(mockCreateFood).toHaveBeenCalledWith(foodInput);
  expect(mockUpdateFood).toHaveBeenCalledWith("food-1", foodUpdate);
  expect(mockDeleteFood).toHaveBeenCalledWith({ foodId: "food-1", removeFromRecipes: true });
  expect(mockDuplicateFood).toHaveBeenCalledWith({ foodId: "food-1", clientRequestId: "request-4" });
  expect(mockCreateFoodServing).toHaveBeenCalledWith("food-1", servingInput);
  expect(mockListRecipes).toHaveBeenCalledWith("query");
  expect(mockGetRecipe).toHaveBeenCalledWith("recipe-1");
  expect(mockCreateRecipe).toHaveBeenCalledWith(recipeInput);
  expect(mockUpdateRecipe).toHaveBeenCalledWith("recipe-1", recipeUpdate);
  expect(mockDeleteRecipe).toHaveBeenCalledWith({ recipeId: "recipe-1", removeFromRecipes: true });
  expect(mockPublishRecipe).toHaveBeenCalledWith({ recipeId: "recipe-1", clientRequestId: "request-5" });
  expect(mockListLogs).toHaveBeenCalledWith("2026-08-13");
  expect(mockListFutureEntries).toHaveBeenCalledWith("2026-08-13");
  expect(mockCreateLog).toHaveBeenCalledWith(logInput);
  expect(mockUpdateLog).toHaveBeenCalledWith("log-1", logUpdate);
  expect(mockGetLogEditContext).toHaveBeenCalledWith("log-1");
  expect(mockDeleteLog).toHaveBeenCalledWith("log-1", logDelete);
  expect(mockMarkDayComplete).toHaveBeenCalledWith(completeInput);
  expect(mockGetLogMutationStatus).toHaveBeenCalledWith("request-1", "create");
  expect(mockGetDailySummary).toHaveBeenCalledWith("2026-08-13");
  expect(mockUpdateTargets).toHaveBeenCalledWith(targetInput);
  expect(mockResetTargetOverride).toHaveBeenCalledWith("protein");
  expect(mockGetDailyTargetComparison).toHaveBeenCalledWith("2026-08-13");
  expect(mockParseNutritionLabel).toHaveBeenCalledWith(ocrInput);
  expect(mockConfirmNutritionLabel).toHaveBeenCalledWith(ocrInput);
  expect(mockSearchUsdaFoods).toHaveBeenCalledWith("beans");
  expect(mockGetUsdaFoodPreview).toHaveBeenCalledWith(123);
  expect(mockImportUsdaFood).toHaveBeenCalledWith(123);
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

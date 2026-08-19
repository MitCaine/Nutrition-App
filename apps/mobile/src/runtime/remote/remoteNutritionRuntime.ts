import { clientOwnerScope } from "../../shared/api/client";
import {
  confirmCalendarTimeZoneChange,
  establishCalendarTimeZone,
  getCalendarState,
  previewCalendarTimeZoneChange,
} from "../../features/calendar/api/calendarApi";
import {
  createFood,
  createFoodServing,
  deleteFood,
  duplicateFood,
  getFood,
  getFoodResolvedNutrition,
  listFavoriteFoods,
  listFoods,
  listNutrients,
  listRecentFoods,
  setFoodFavorite,
  updateFood,
} from "../../features/foods/api/foodApi";
import {
  createRecipe,
  deleteRecipe,
  getRecipe,
  getRecipeNutrition,
  listRecipes,
  publishRecipe,
  updateRecipe,
} from "../../features/recipes/api/recipeApi";
import {
  createLog,
  deleteLog,
  getDailySummary,
  getHistoryRange,
  getLogEditContext,
  getLogMutationStatus,
  listFutureEntries,
  listLogs,
  listRecentEntries,
  markDayComplete,
  updateLog,
} from "../../features/logging/api/logApi";
import {
  getDailyTargetComparison,
  getTargets,
  resetTargetOverride,
  updateTargets,
} from "../../features/targets/api/targetApi";
import {
  confirmNutritionLabel,
  parseNutritionLabel,
} from "../../features/ocr/api/ocrApi";
import {
  getUsdaFoodPreview,
  importUsdaFood,
  searchUsdaFoods,
} from "../../features/usda/api/usdaApi";
import type { NutritionRuntime } from "../NutritionRuntime";
import { remoteAuthorityIdentity } from "../authorityIdentity";
import { remoteOperation } from "./mapRemoteError";

const read = <T>(execute: () => Promise<T>) => remoteOperation("read", execute);
const mutate = <T>(execute: () => Promise<T>) => remoteOperation("mutation", execute);

/**
 * The only production runtime selectable in E2-01. Feature API modules remain
 * private transport/mapping implementations beneath this stable object.
 */
const runtime: NutritionRuntime = {
  authority: remoteAuthorityIdentity(clientOwnerScope()),
  calendar: {
    getState: () => read(getCalendarState),
    establishTimeZone: (timeZone) => mutate(() => establishCalendarTimeZone(timeZone)),
    previewTimeZoneChange: (timeZone) => read(() => previewCalendarTimeZoneChange(timeZone)),
    confirmTimeZoneChange: (input) => mutate(() => confirmCalendarTimeZoneChange(input)),
  },
  nutrients: {
    list: () => read(listNutrients),
  },
  foods: {
    list: (query, view) => read(() => listFoods(query, view)),
    get: (foodId) => read(() => getFood(foodId)),
    listFavorites: () => read(listFavoriteFoods),
    listRecent: (limit) => read(() => listRecentFoods(limit)),
    setFavorite: (foodId, favorite) => mutate(() => setFoodFavorite(foodId, favorite)),
    getResolvedNutrition: (foodId) => read(() => getFoodResolvedNutrition(foodId)),
    create: (input) => mutate(() => createFood(input)),
    update: (foodId, input) => mutate(() => updateFood(foodId, input)),
    delete: (input) => mutate(() => deleteFood(input)),
    duplicate: (input) => mutate(() => duplicateFood(input)),
    createServingDefinition: (foodId, input) => mutate(() => createFoodServing(foodId, input)),
  },
  recipes: {
    list: (query) => read(() => listRecipes(query)),
    get: (recipeId) => read(() => getRecipe(recipeId)),
    create: (input) => mutate(() => createRecipe(input)),
    update: (recipeId, input) => mutate(() => updateRecipe(recipeId, input)),
    delete: (input) => mutate(() => deleteRecipe(input)),
    getNutrition: (recipeId) => read(() => getRecipeNutrition(recipeId)),
    publish: (input) => mutate(() => publishRecipe(input)),
  },
  dailyLogs: {
    list: (date) => read(() => listLogs(date)),
    listFuture: (date) => read(() => listFutureEntries(date)),
    listRecentEntries: () => read(listRecentEntries),
    create: (input) => mutate(() => createLog(input)),
    update: (logId, input) => mutate(() => updateLog(logId, input)),
    getEditContext: (logId) => read(() => getLogEditContext(logId)),
    delete: (logId, input) => mutate(() => deleteLog(logId, input)),
    markDayComplete: (input) => mutate(() => markDayComplete(input)),
    getMutationStatus: (clientRequestId, operation) => read(
      () => getLogMutationStatus(clientRequestId, operation),
    ),
    getHistoryRange: (startDate, endDate) => read(
      () => getHistoryRange(startDate, endDate),
    ),
    getDailySummary: (date) => read(() => getDailySummary(date)),
  },
  targets: {
    getConfiguration: () => read(getTargets),
    updateConfiguration: (input) => mutate(() => updateTargets(input)),
    resetOverride: (nutrientId) => mutate(() => resetTargetOverride(nutrientId)),
    getDailyComparison: (date) => read(() => getDailyTargetComparison(date)),
  },
  ocr: {
    parseNutritionLabel: (result) => read(() => parseNutritionLabel(result)),
    confirmNutritionLabel: (input) => mutate(() => confirmNutritionLabel(input)),
  },
  usda: {
    search: (query) => read(() => searchUsdaFoods(query)),
    getPreview: (fdcId) => read(() => getUsdaFoodPreview(fdcId)),
    importFood: (fdcId) => mutate(() => importUsdaFood(fdcId)),
  },
};

for (const feature of [
  runtime.calendar,
  runtime.nutrients,
  runtime.foods,
  runtime.recipes,
  runtime.dailyLogs,
  runtime.targets,
  runtime.ocr,
  runtime.usda,
]) {
  Object.freeze(feature);
}

export const remoteNutritionRuntime = Object.freeze(runtime);

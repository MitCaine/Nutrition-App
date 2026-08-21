import type { OcrRecognitionResult } from "../native/ocr/NutritionOcr";
import type {
  Food,
  FoodCreateInput,
  FoodDeleteResult,
  FoodMutationInput,
  FoodResolvedNutrition,
  NutrientDefinition,
  RecentFood,
  ServingDefinitionCreateInput,
} from "../features/foods/api/types";
import type {
  Recipe,
  RecipeCreateInput,
  RecipeMutationInput,
  RecipeNutritionResponse,
  RecipePublishResponse,
} from "../features/recipes/api/types";
import type {
  DailyLog,
  DailyLogCompleteInput,
  DailyLogCompletion,
  DailyLogCreateInput,
  DailyLogDeleteInput,
  DailyLogEditContext,
  DailyLogMutationStatus,
  DailyLogUpdateInput,
  DailySummary,
  HistoryRangeEvidence,
  RecentEntry,
} from "../features/logging/api/types";
import type {
  DailyTargetComparison,
  TargetConfiguration,
  TargetConfigurationInput,
} from "../features/targets/api/types";
import type {
  OcrConfirmationInput,
  OcrConfirmationResponse,
  ParsedNutritionLabel,
} from "../features/ocr/api/types";
import type {
  UsdaFoodPreview,
  UsdaImportResult,
  UsdaSearchResponse,
} from "../features/usda/api/types";
import type {
  CalendarImpactPreview,
  CalendarState,
} from "../features/calendar/types";
import type { RuntimeAuthorityIdentity } from "./authorityIdentity";

export interface CalendarRuntime {
  getState(): Promise<CalendarState>;
  establishTimeZone(timeZone: string): Promise<CalendarState>;
  previewTimeZoneChange(timeZone: string): Promise<CalendarImpactPreview>;
  confirmTimeZoneChange(input: {
    timeZone: string;
    calendarRevision: number;
    previewToken: string;
  }): Promise<CalendarState>;
}

export interface NutrientsRuntime {
  /** Returns the runtime's authoritative catalog order unchanged. */
  list(): Promise<NutrientDefinition[]>;
}

export interface FoodsRuntime {
  list(query?: string, view?: "saved"): Promise<Food[]>;
  get(foodId: string): Promise<Food>;
  listFavorites(): Promise<Food[]>;
  listRecent(limit?: number): Promise<RecentFood[]>;
  setFavorite(foodId: string, favorite: boolean): Promise<Food>;
  getResolvedNutrition(foodId: string): Promise<FoodResolvedNutrition>;
  create(input: FoodCreateInput): Promise<Food>;
  update(foodId: string, input: FoodMutationInput): Promise<Food>;
  delete(input: { foodId: string; removeFromRecipes?: boolean }): Promise<FoodDeleteResult>;
  duplicate(input: { foodId: string; clientRequestId: string }): Promise<Food>;
  createServingDefinition(foodId: string, input: ServingDefinitionCreateInput): Promise<Food>;
}

export interface RecipesRuntime {
  list(query?: string): Promise<Recipe[]>;
  get(recipeId: string): Promise<Recipe>;
  create(input: RecipeCreateInput): Promise<Recipe>;
  duplicate(input: { recipeId: string; clientRequestId: string }): Promise<Recipe>;
  update(recipeId: string, input: RecipeMutationInput): Promise<Recipe>;
  delete(input: { recipeId: string; removeFromRecipes?: boolean }): Promise<void>;
  getNutrition(recipeId: string): Promise<RecipeNutritionResponse>;
  publish(input: { recipeId: string; clientRequestId: string }): Promise<RecipePublishResponse>;
}

/** Existing Daily Log operations retained as the shared mutation/reconciliation substrate. */
export interface DailyLogsRuntime {
  list(date: string): Promise<DailyLog[]>;
  listFuture(date: string): Promise<DailyLog[]>;
  listRecentEntries(): Promise<RecentEntry[]>;
  create(input: DailyLogCreateInput): Promise<DailyLog>;
  update(logId: string, input: Partial<DailyLogUpdateInput>): Promise<DailyLog>;
  getEditContext(logId: string): Promise<DailyLogEditContext>;
  delete(logId: string, input?: DailyLogDeleteInput): Promise<void>;
  getMutationStatus(
    clientRequestId: string,
    operation?: DailyLogMutationStatus["operation"],
  ): Promise<DailyLogMutationStatus>;
  getHistoryRange(startDate: string, endDate: string): Promise<HistoryRangeEvidence>;
  getDailySummary(date: string): Promise<DailySummary>;
}

/** E4-02 extends the existing Daily Logs capability; it does not add a ninth capability. */
export interface CompleteDailyLogsRuntime extends DailyLogsRuntime {
  markDayComplete(input: DailyLogCompleteInput): Promise<DailyLogCompletion>;
}

export interface TargetsRuntime {
  getConfiguration(): Promise<TargetConfiguration>;
  updateConfiguration(input: TargetConfigurationInput): Promise<TargetConfiguration>;
  resetOverride(nutrientId: string): Promise<TargetConfiguration>;
  getDailyComparison(date: string): Promise<DailyTargetComparison>;
}

export interface OcrRuntime {
  parseNutritionLabel(result: OcrRecognitionResult): Promise<ParsedNutritionLabel>;
  confirmNutritionLabel(input: OcrConfirmationInput): Promise<OcrConfirmationResponse>;
}

export interface UsdaRuntime {
  search(query: string): Promise<UsdaSearchResponse>;
  getPreview(fdcId: number): Promise<UsdaFoodPreview>;
  importFood(fdcId: number): Promise<UsdaImportResult>;
}

/** Collection-returning operations preserve each authority's established order exactly. */
export interface NutritionRuntime {
  readonly authority: RuntimeAuthorityIdentity;
  readonly calendar: CalendarRuntime;
  readonly nutrients: NutrientsRuntime;
  readonly foods: FoodsRuntime;
  readonly recipes: RecipesRuntime;
  readonly dailyLogs: CompleteDailyLogsRuntime;
  readonly targets: TargetsRuntime;
  readonly ocr: OcrRuntime;
  readonly usda: UsdaRuntime;
}

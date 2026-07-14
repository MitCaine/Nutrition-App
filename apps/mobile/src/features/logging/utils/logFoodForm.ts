import type { Food, FoodResolvedNutrition, ResolvedFoodAmount } from "../../foods/api/types";
import { defaultServing } from "../../foods/utils/foodDisplay";
import { formatAmountWithUnit, formatDisplayNumber } from "../../../shared/nutrition/display";
import type { DailyLog, DailyLogEditContext, DailyLogInput, DailyLogUpdateInput } from "../api/types";

export type LogServingChoice = {
  id: string;
  label: string;
  gram_weight: string | null;
  is_default: boolean;
};

export type LogFoodInitialAmount = {
  amountDefinitionId: string;
  amountQuantity: string;
  amountUnit: "serving" | "g";
};

export type CreateLogInitialization = {
  amount: string;
  unit: "serving" | "g";
  selectedAmountId: string | null;
  selectedAmountMode: "serving" | "g" | null;
};

export function shouldApplyCreateLogInitialization({
  isEditMode,
  initializedFoodId,
  foodId,
  authoritativeChoicesReady,
}: {
  isEditMode: boolean;
  initializedFoodId: string | null;
  foodId: string;
  authoritativeChoicesReady: boolean;
}): boolean {
  return !isEditMode && authoritativeChoicesReady && initializedFoodId !== foodId;
}

export function foodDetailLogInitialAmount(
  amount: ResolvedFoodAmount | undefined,
): LogFoodInitialAmount | undefined {
  if (!amount?.valid_for_logging || !amount.amount_definition_id) {
    return undefined;
  }
  return {
    amountDefinitionId: amount.amount_definition_id,
    amountQuantity: amount.entered_quantity,
    amountUnit: amount.semantic_amount_mode,
  };
}

export function resolveCreateLogInitialization(
  food: Food | undefined,
  resolvedNutrition: FoodResolvedNutrition | undefined,
  initialAmount: LogFoodInitialAmount | undefined,
): CreateLogInitialization {
  const passedChoice = initialAmount
    ? resolvedNutrition?.amounts.find(
        (choice) =>
          choice.valid_for_logging &&
          choice.amount_definition_id === initialAmount.amountDefinitionId &&
          choice.semantic_amount_mode === initialAmount.amountUnit,
      )
    : undefined;
  if (passedChoice && initialAmount) {
    return {
      amount: positiveInitialQuantity(initialAmount.amountQuantity),
      unit: initialAmount.amountUnit,
      selectedAmountId: passedChoice.amount_definition_id,
      selectedAmountMode: passedChoice.semantic_amount_mode,
    };
  }

  const revisionDefault =
    resolvedNutrition?.nutrition_authority === "recipe_publication_revision"
      ? resolvedNutrition.amounts.find(
          (choice) =>
            choice.valid_for_logging &&
            choice.is_default &&
            choice.semantic_amount_mode === "serving",
        ) ??
        resolvedNutrition.amounts.find(
          (choice) => choice.valid_for_logging && choice.semantic_amount_mode === "serving",
        )
      : undefined;
  return {
    amount: "1",
    unit: "serving",
    selectedAmountId: revisionDefault?.amount_definition_id ?? initialServingId(food),
    selectedAmountMode: "serving",
  };
}

export function createServingChoices(
  food: Food | undefined,
  resolvedNutrition: FoodResolvedNutrition | undefined,
): LogServingChoice[] {
  if (resolvedNutrition?.nutrition_authority === "recipe_publication_revision") {
    return resolvedNutrition.amounts
      .filter((choice) => choice.valid_for_logging && choice.semantic_amount_mode === "serving")
      .map((choice) => ({
        id: choice.amount_definition_id,
        label: choice.display_label,
        gram_weight: choice.resolved_grams,
        is_default: choice.is_default,
      }));
  }
  return editServingChoices(food, undefined);
}

function positiveInitialQuantity(value: string): string {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? formatInitialLogAmount(value) : "1";
}

export function initialServingId(food?: Food, logServingId?: string | null): string | null {
  if (logServingId) {
    return logServingId;
  }
  return defaultServing(food?.serving_definitions ?? [])?.id ?? null;
}

export function editServingChoices(
  food: Food | undefined,
  context: DailyLogEditContext | undefined,
): LogServingChoice[] {
  if (context?.is_revision_backed) {
    return context.amount_choices
      .filter((choice) => choice.semantic_mode === "serving")
      .map((choice) => ({
        id: choice.amount_definition_id,
        label: choice.display_label,
        gram_weight: choice.gram_equivalent,
        is_default: choice.is_default,
      }));
  }
  return (food?.serving_definitions ?? []).map((serving) => ({
    id: serving.id,
    label: serving.label,
    gram_weight: serving.gram_weight ?? null,
    is_default: serving.is_default,
  }));
}

export function initialEditAmountId(
  food: Food | undefined,
  log: DailyLog | undefined,
  context?: DailyLogEditContext,
): string | null {
  if (context?.is_revision_backed) {
    return context.selected_amount_definition_id;
  }
  return initialServingId(food, log?.serving_definition_id);
}

export function buildLogInput(params: {
  foodId: string;
  date: string;
  amount: string;
  unit: "serving" | "g";
  selectedServingId: string | null;
  selectedAmountMode?: "serving" | "g" | null;
}): DailyLogInput {
  return {
    food_item_id: params.foodId,
    logged_date: params.date,
    amount_quantity: params.amount,
    amount_unit: params.unit,
    serving_definition_id:
      params.unit === "serving" || params.selectedAmountMode === params.unit
        ? params.selectedServingId
        : null,
  };
}

export function buildLogUpdateInput(input: DailyLogInput): DailyLogUpdateInput {
  const { food_item_id: _foodItemId, ...supportedFields } = input;
  return supportedFields;
}

export function formatInitialLogAmount(amount?: string | null): string {
  return amount ? formatDisplayNumber(amount) : "1";
}

export function formatServingGramWeight(gramWeight?: string | null): string | null {
  return gramWeight ? formatAmountWithUnit(gramWeight, "g") : null;
}

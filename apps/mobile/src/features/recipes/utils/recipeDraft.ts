import type { Food, ServingDefinition, ServingDefinitionInput } from "../../foods/api/types";
import { defaultServing } from "../../foods/utils/foodDisplay";
import { generatedAmountLabel, normalizedAmountUnit } from "../../foods/utils/amountForm";
import { formatAmountWithUnit, formatDisplayNumber } from "../../../shared/nutrition/display";
import type { Recipe, RecipeIngredientInput, RecipeMutationInput } from "../api/types";
import {
  formatMassAmount,
  massToGrams,
  multiplyDecimalInputs,
  normalizeDecimalInput,
  type MassUnit,
} from "./massUnits";

export type DraftIngredient = {
  localId: string;
  food: Food;
  amountQuantity: string;
  amountUnit: "serving" | "g";
  massUnit: MassUnit;
  servingDefinitionId: string | null;
  preparationNote: string;
};

export type LegacyCookedWeight = {
  normalizedGrams: string;
  displayQuantity?: string | null;
  displayUnit?: string | null;
};

export type FinishedWeightDraft = {
  quantity: string;
  unit: MassUnit;
};

export type RecipeDraft = {
  recipeId?: string;
  publishedFoodItemId?: string | null;
  name: string;
  notes: string;
  servingCountYield: string;
  /**
   * Undefined means a new draft has never authored finished-weight state.
   * Loaded Recipes always receive an explicit value so updates preserve or
   * intentionally clear the existing finished-weight measurement.
   */
  finishedWeight?: FinishedWeightDraft;
  legacyCookedWeight: LegacyCookedWeight | null;
  ingredients: DraftIngredient[];
};

export type RecipeDraftInitResult =
  | { ok: true; draft: RecipeDraft }
  | { ok: false; missingFoodItemIds: string[] };

export type CustomServingDraft = {
  quantity: string;
  unit: string;
  gramWeightPerUnit: string;
  customLabel: string;
  useCustomLabel: boolean;
};

export function emptyRecipeDraft(): RecipeDraft {
  return {
    name: "",
    notes: "",
    servingCountYield: "",
    legacyCookedWeight: null,
    ingredients: [],
  };
}

export function recipeToDraft(recipe: Recipe, foods: Food[]): RecipeDraftInitResult {
  const foodsById = new Map(foods.map((food) => [food.id, food]));
  const sortedIngredients = [...recipe.ingredients].sort((a, b) => a.position - b.position);
  const missingFoodItemIds = sortedIngredients
    .filter((ingredient) => !foodsById.has(ingredient.food_item_id))
    .map((ingredient) => ingredient.food_item_id);

  if (missingFoodItemIds.length > 0) {
    return { ok: false, missingFoodItemIds };
  }

  return {
    ok: true,
    draft: {
      recipeId: recipe.id,
      publishedFoodItemId: recipe.published_food_item_id,
      name: recipe.name,
      notes: recipe.notes ?? "",
      servingCountYield: recipe.serving_count_yield ? formatDisplayNumber(recipe.serving_count_yield) : "",
      finishedWeight: finishedWeightDraftForRecipe(recipe),
      legacyCookedWeight: legacyCookedWeightForRecipe(recipe),
      ingredients: sortedIngredients.map((ingredient) => ({
        localId: ingredient.id,
        food: foodsById.get(ingredient.food_item_id) as Food,
        amountQuantity: ingredient.amount_display_quantity
          ? formatDisplayNumber(ingredient.amount_display_quantity)
          : formatDisplayNumber(ingredient.amount_quantity),
        amountUnit: ingredient.amount_unit,
        massUnit: (ingredient.amount_display_unit as MassUnit | null) ?? "g",
        servingDefinitionId: ingredient.serving_definition_id ?? null,
        preparationNote: ingredient.preparation_note ?? "",
      })),
    },
  };
}

export function ingredientForFood(food: Food): DraftIngredient {
  const serving = defaultServing(food.serving_definitions);
  return {
    localId: `${food.id}-${Date.now()}`,
    food,
    amountQuantity: "1",
    amountUnit: serving ? "serving" : "g",
    massUnit: "g",
    servingDefinitionId: serving?.id ?? null,
    preparationNote: "",
  };
}

export function switchIngredientMode(
  ingredient: DraftIngredient,
  amountUnit: "serving" | "g",
): DraftIngredient {
  if (amountUnit === "g") {
    return { ...ingredient, amountUnit, servingDefinitionId: null, amountQuantity: "100", massUnit: "g" };
  }
  return {
    ...ingredient,
    amountUnit,
    servingDefinitionId: defaultServing(ingredient.food.serving_definitions)?.id ?? null,
    amountQuantity: "1",
  };
}

export function buildRecipePayload(draft: RecipeDraft): RecipeMutationInput | null {
  if (validateRecipeDraft(draft)) {
    return null;
  }
  return {
    name: draft.name.trim(),
    notes: draft.notes.trim() || null,
    serving_count_yield: draft.servingCountYield.trim() || null,
    ...(draft.finishedWeight !== undefined
      ? buildFinishedWeightPayload(draft.finishedWeight)
      : {}),
    ingredients: draft.ingredients.map<RecipeIngredientInput>((ingredient, position) => ({
      food_item_id: ingredient.food.id,
      position,
      amount_quantity:
        ingredient.amountUnit === "g"
          ? (massToGrams(ingredient.amountQuantity, ingredient.massUnit) ?? ingredient.amountQuantity.trim())
          : ingredient.amountQuantity.trim(),
      amount_unit: ingredient.amountUnit,
      serving_definition_id:
        ingredient.amountUnit === "serving" ? ingredient.servingDefinitionId : null,
      preparation_note: ingredient.preparationNote.trim() || null,
      amount_display_quantity: ingredient.amountUnit === "g" ? ingredient.amountQuantity.trim() : null,
      amount_display_unit: ingredient.amountUnit === "g" ? ingredient.massUnit : null,
    })),
  };
}

export function validateRecipeDraft(draft: RecipeDraft): string | null {
  if (!draft.name.trim()) {
    return "Recipe name is required.";
  }
  for (const ingredient of draft.ingredients) {
    if (!ingredient.food?.id) {
      return "Each ingredient needs a saved food.";
    }
    if (!(Number(ingredient.amountQuantity) > 0)) {
      return "Ingredient amounts must be greater than zero.";
    }
    if (ingredient.amountUnit === "g" && !massToGrams(ingredient.amountQuantity, ingredient.massUnit)) {
      return "Ingredient mass must be a valid number.";
    }
    if (ingredient.amountUnit === "serving" && !ingredient.servingDefinitionId) {
      return "Serving ingredients need a selected serving.";
    }
    if (
      ingredient.amountUnit === "serving" &&
      !ingredient.food.serving_definitions.some((serving) => serving.id === ingredient.servingDefinitionId)
    ) {
      return "Selected serving is no longer available for an ingredient.";
    }
  }
  if (draft.servingCountYield.trim() && !(Number(draft.servingCountYield) > 0)) {
    return "Portions must be greater than zero.";
  }

  if (draft.finishedWeight?.quantity.trim()) {
    const normalized = normalizeDecimalInput(draft.finishedWeight.quantity);
    if (
      normalized === null
      || !(Number(normalized) > 0)
      || massToGrams(normalized, draft.finishedWeight.unit) === null
    ) {
      return "Finished weight must be a valid amount greater than zero.";
    }
  }

  return null;
}

export function canPublishRecipe(draft: { servingCountYield: string; finalCookedWeightGrams: string }) {
  return Number(draft.servingCountYield) > 0 || Number(normalizeDecimalInput(draft.finalCookedWeightGrams)) > 0;
}

function buildFinishedWeightPayload(
  finishedWeight: FinishedWeightDraft,
): Pick<
  RecipeMutationInput,
  | "final_cooked_weight_grams"
  | "final_cooked_weight_display_quantity"
  | "final_cooked_weight_display_unit"
> {
  const normalizedQuantity = normalizeDecimalInput(finishedWeight.quantity);

  if (!normalizedQuantity) {
    return {
      final_cooked_weight_grams: null,
      final_cooked_weight_display_quantity: null,
      final_cooked_weight_display_unit: null,
    };
  }

  const normalizedGrams = massToGrams(normalizedQuantity, finishedWeight.unit);

  if (!normalizedGrams) {
    return {
      final_cooked_weight_grams: null,
      final_cooked_weight_display_quantity: null,
      final_cooked_weight_display_unit: null,
    };
  }

  return {
    final_cooked_weight_grams: normalizedGrams,
    final_cooked_weight_display_quantity: normalizedQuantity,
    final_cooked_weight_display_unit: finishedWeight.unit,
  };
}

export function finishedWeightDraftForRecipe(
  recipe: Pick<
    Recipe,
    | "final_cooked_weight_grams"
    | "final_cooked_weight_display_quantity"
    | "final_cooked_weight_display_unit"
  >,
): FinishedWeightDraft {
  const displayUnit = recipe.final_cooked_weight_display_unit?.trim().toLowerCase();

  if (
    recipe.final_cooked_weight_display_quantity
    && (displayUnit === "g" || displayUnit === "oz" || displayUnit === "lb")
  ) {
    return {
      quantity: formatDisplayNumber(recipe.final_cooked_weight_display_quantity),
      unit: displayUnit,
    };
  }

  if (recipe.final_cooked_weight_grams) {
    return {
      quantity: formatDisplayNumber(recipe.final_cooked_weight_grams),
      unit: "g",
    };
  }

  return {
    quantity: "",
    unit: "g",
  };
}

export function legacyCookedWeightForRecipe(
  recipe: Pick<
    Recipe,
    | "final_cooked_weight_grams"
    | "final_cooked_weight_display_quantity"
    | "final_cooked_weight_display_unit"
  >,
): LegacyCookedWeight | null {
  if (!recipe.final_cooked_weight_grams) {
    return null;
  }
  return {
    normalizedGrams: recipe.final_cooked_weight_grams,
    displayQuantity: recipe.final_cooked_weight_display_quantity,
    displayUnit: recipe.final_cooked_weight_display_unit,
  };
}

export function formatLegacyCookedWeight(value: LegacyCookedWeight): string {
  if (value.displayQuantity && value.displayUnit) {
    return `${formatDisplayNumber(value.displayQuantity)} ${value.displayUnit}`;
  }
  return `${formatDisplayNumber(value.normalizedGrams)} g`;
}

export function buildCustomServingDefinition(draft: CustomServingDraft): ServingDefinitionInput | null {
  const quantity = draft.quantity.trim();
  const rawUnit = draft.unit.trim();
  const gramWeightPerUnit = draft.gramWeightPerUnit.trim();
  // The Recipe form asks for one unit's weight, while the persisted serving
  // definition keeps the total weight of the full structured serving.
  const gramWeight = multiplyDecimalInputs(quantity, gramWeightPerUnit);
  if (
    !(Number(quantity) > 0)
    || !rawUnit
    || !(Number(gramWeightPerUnit) > 0)
    || gramWeight === null
    || !(Number(gramWeight) > 0)
  ) {
    return null;
  }
  const unit = normalizedAmountUnit(rawUnit) ?? rawUnit.toLowerCase().replace(/\s+/g, " ");
  const automaticLabel = generatedAmountLabel(quantity, unit);
  const label = draft.useCustomLabel ? draft.customLabel.trim() : automaticLabel;
  if (!label) {
    return null;
  }
  return {
    label,
    quantity,
    unit,
    gram_weight: gramWeight,
    is_default: false,
  };
}

export function formatServingMultiplier(quantity: string, servingLabel: string): string {
  const displayQuantity = formatDisplayNumber(quantity);
  return Number(quantity) === 1 ? servingLabel : `${displayQuantity} × ${servingLabel}`;
}

export function formatIngredientAmount(ingredient: DraftIngredient): string {
  if (ingredient.amountUnit === "g") {
    return formatMassAmount(ingredient.amountQuantity, ingredient.massUnit);
  }
  const serving = ingredient.food.serving_definitions.find(
    (item) => item.id === ingredient.servingDefinitionId,
  );
  return formatServingMultiplier(ingredient.amountQuantity, serving?.label ?? "serving");
}

export function formatServingChoiceLabel(serving: { label: string; gram_weight?: string | null }): string {
  if (!serving.gram_weight || servingLabelAlreadyIncludesGramWeight(serving.label, serving.gram_weight)) {
    return serving.label;
  }
  return `${serving.label} (${formatAmountWithUnit(serving.gram_weight, "g")})`;
}

function servingLabelAlreadyIncludesGramWeight(label: string, gramWeight: string): boolean {
  const match = label.trim().match(/^([0-9]+(?:\.[0-9]+)?)\s*(?:g|gram|grams)$/i);
  if (!match) {
    return false;
  }
  return Number(match[1]) === Number(gramWeight);
}

export function usefulServingDefinitions<T extends { label: string; gram_weight?: string | null }>(servings: T[]): T[] {
  return servings
    .filter((serving) => {
      const label = serving.label.trim().toLowerCase();
      return Boolean(serving.gram_weight) && label !== "quantity not specified";
    })
    .sort((a, b) => servingUsefulnessRank(a.label) - servingUsefulnessRank(b.label));
}

function servingUsefulnessRank(label: string): number {
  const normalized = label.trim().toLowerCase();
  if (normalized.includes("racc") || normalized === "edible") {
    return 1;
  }
  return 0;
}


function canonicalServingSemanticDecimal(value: string | null | undefined): string {
  if (value == null) {
    return "";
  }
  const normalized = normalizeDecimalInput(String(value));
  if (normalized === null) {
    return String(value).trim();
  }
  const [whole, fraction = ""] = normalized.split(".");
  const canonicalWhole = whole.replace(/^0+(?=\d)/, "") || "0";
  const canonicalFraction = fraction.replace(/0+$/, "");
  return canonicalFraction ? `${canonicalWhole}.${canonicalFraction}` : canonicalWhole;
}

function servingSemanticKey(
  serving: Pick<ServingDefinition, "quantity" | "unit" | "gram_weight">,
): string {
  return [
    canonicalServingSemanticDecimal(serving.quantity),
    serving.unit.trim().toLowerCase(),
    canonicalServingSemanticDecimal(serving.gram_weight),
  ].join("\u0000");
}

/**
 * Food updates replace serving-definition rows, so Recipe drafts cannot retain
 * the old serving IDs blindly. Mirror the authoritative Food mutation rule:
 * preserve a serving selection only when exactly one replacement has the same
 * quantity/unit/gram-weight semantics. Otherwise require explicit reselection.
 */
export function reconcileRecipeDraftFoodAfterServingManagement(
  draft: RecipeDraft,
  updatedFood: Food,
): RecipeDraft {
  let foundFood = false;

  const ingredients = draft.ingredients.map((ingredient) => {
    if (ingredient.food.id !== updatedFood.id) {
      return ingredient;
    }

    foundFood = true;

    if (
      ingredient.amountUnit !== "serving"
      || ingredient.servingDefinitionId === null
    ) {
      return { ...ingredient, food: updatedFood };
    }

    const previousServing = ingredient.food.serving_definitions.find(
      (serving) => serving.id === ingredient.servingDefinitionId,
    );

    if (!previousServing) {
      return {
        ...ingredient,
        food: updatedFood,
        servingDefinitionId: null,
      };
    }

    const semanticKey = servingSemanticKey(previousServing);
    const successors = updatedFood.serving_definitions.filter(
      (serving) => servingSemanticKey(serving) === semanticKey,
    );

    return {
      ...ingredient,
      food: updatedFood,
      servingDefinitionId: successors.length === 1 ? successors[0]!.id : null,
    };
  });

  return foundFood ? { ...draft, ingredients } : draft;
}

export function moveIngredient(
  ingredients: DraftIngredient[],
  fromIndex: number,
  direction: -1 | 1,
): DraftIngredient[] {
  const toIndex = fromIndex + direction;
  if (toIndex < 0 || toIndex >= ingredients.length) {
    return ingredients;
  }
  const next = [...ingredients];
  const [item] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, item);
  return next;
}

export function applyImportedIngredient(
  draft: RecipeDraft,
  food: Food,
  editingIngredientId?: string | null,
): RecipeDraft {
  const ingredient = ingredientForFood(food);
  if (!editingIngredientId) {
    return { ...draft, ingredients: [...draft.ingredients, ingredient] };
  }
  return {
    ...draft,
    ingredients: draft.ingredients.map((item) =>
      item.localId === editingIngredientId ? { ...ingredient, localId: editingIngredientId } : item,
    ),
  };
}

export function foodMeta(food: Food): string {
  if (food.brand) {
    return `${food.brand} · ${food.source_label}`;
  }
  return food.source_label;
}

export function formatRecipeIngredientDetail(params: {
  food?: Food;
  amountQuantity: string;
  amountUnit: "serving" | "g";
  servingDefinitionId?: string | null;
  massUnit?: MassUnit;
  preparationNote?: string | null;
}): string {
  const foodName = params.food?.name ?? "Unknown food";
  if (params.amountUnit === "g") {
    return `${foodName} - ${formatMassAmount(params.amountQuantity, params.massUnit ?? "g")}`;
  }
  const serving = params.food?.serving_definitions.find((item) => item.id === params.servingDefinitionId);
  const amount = formatServingMultiplier(params.amountQuantity, serving?.label ?? "serving");
  return `${foodName} - ${amount}`;
}

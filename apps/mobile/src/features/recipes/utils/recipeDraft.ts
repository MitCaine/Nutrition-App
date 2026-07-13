import type { Food } from "../../foods/api/types";
import { defaultServing } from "../../foods/utils/foodDisplay";
import { formatAmountWithUnit, formatDisplayNumber } from "../../../shared/nutrition/display";
import type { Recipe, RecipeIngredientInput, RecipeMutationInput } from "../api/types";
import { formatMassAmount, massToGrams, normalizeDecimalInput, type MassUnit } from "./massUnits";

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

export type RecipeDraft = {
  recipeId?: string;
  publishedFoodItemId?: string | null;
  name: string;
  notes: string;
  servingCountYield: string;
  legacyCookedWeight: LegacyCookedWeight | null;
  ingredients: DraftIngredient[];
};

export type RecipeDraftInitResult =
  | { ok: true; draft: RecipeDraft }
  | { ok: false; missingFoodItemIds: string[] };

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
    return "Serving yield must be greater than zero.";
  }
  return null;
}

export function canPublishRecipe(draft: { servingCountYield: string; finalCookedWeightGrams: string }) {
  return Number(draft.servingCountYield) > 0 || Number(normalizeDecimalInput(draft.finalCookedWeightGrams)) > 0;
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

export function formatIngredientAmount(ingredient: DraftIngredient): string {
  if (ingredient.amountUnit === "g") {
    return formatMassAmount(ingredient.amountQuantity, ingredient.massUnit);
  }
  const serving = ingredient.food.serving_definitions.find(
    (item) => item.id === ingredient.servingDefinitionId,
  );
  return `${formatDisplayNumber(ingredient.amountQuantity)} ${serving?.label ?? "serving"}`;
}

export function formatServingChoiceLabel(serving: { label: string; gram_weight?: string | null }): string {
  return serving.gram_weight ? `${serving.label} (${formatAmountWithUnit(serving.gram_weight, "g")})` : serving.label;
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
    return food.brand;
  }
  if (food.is_recipe) {
    return "Recipe";
  }
  return food.source_type === "usda" ? "USDA" : "Manual";
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
  const amount = `${formatDisplayNumber(params.amountQuantity)} ${serving?.label ?? "serving"}`;
  return `${foodName} - ${amount}`;
}

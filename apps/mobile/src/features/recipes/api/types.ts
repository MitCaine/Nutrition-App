import type { Food } from "../../foods/api/types";
import type { AggregatedNutrientTotal } from "../../../shared/nutrition/types";

export type RecipeIngredientInput = {
  food_item_id: string;
  position: number;
  amount_quantity: string;
  amount_unit: "serving" | "g";
  serving_definition_id?: string | null;
  preparation_note?: string | null;
  amount_display_quantity?: string | null;
  amount_display_unit?: string | null;
};

export type RecipeMutationInput = {
  name: string;
  notes?: string | null;
  serving_count_yield?: string | number | null;
  final_cooked_weight_grams?: string | number | null;
  final_cooked_weight_display_quantity?: string | number | null;
  final_cooked_weight_display_unit?: string | null;
  ingredients: RecipeIngredientInput[];
};

export type RecipeIngredient = RecipeIngredientInput & {
  id: string;
  recipe_id: string;
  resolved_gram_amount?: string | null;
};

export type Recipe = {
  id: string;
  user_id: string;
  published_food_item_id?: string | null;
  name: string;
  notes?: string | null;
  serving_count_yield?: string | null;
  final_cooked_weight_grams?: string | null;
  final_cooked_weight_display_quantity?: string | null;
  final_cooked_weight_display_unit?: string | null;
  needs_republish?: boolean;
  created_at: string;
  updated_at: string;
  ingredients: RecipeIngredient[];
};

export type RecipeNutrientTotalResponse = {
  nutrient_id: string;
  amount_known: string;
  amount_estimated: string;
  unit: AggregatedNutrientTotal["unit"];
  has_unknown_contributors: boolean;
  unknown_contributor_count: number;
};

export type RecipeNutritionResponse = {
  totals: AggregatedNutrientTotal[];
  perServing: AggregatedNutrientTotal[] | null;
  per100g: AggregatedNutrientTotal[] | null;
};

export type RecipeNutritionApiResponse = {
  totals: RecipeNutrientTotalResponse[];
  per_serving: RecipeNutrientTotalResponse[] | null;
  per_100g: RecipeNutrientTotalResponse[] | null;
};

export type RecipePublishResponse = {
  recipe: Recipe;
  food: Food;
};

export type RecipeDeleteAffectedRecipe = {
  recipe_id: string;
  recipe_name: string;
  ingredient_occurrence_count: number;
  is_published: boolean;
  needs_republish: boolean;
};

export type RecipeDeleteDependency = {
  code: "recipe_delete_dependencies_exist";
  message: string;
  recipe_id: string;
  projection_food_item_id: string;
  active_dependent_recipe_count: number;
  affected_recipes: RecipeDeleteAffectedRecipe[];
  total_ingredient_rows_affected: number;
};

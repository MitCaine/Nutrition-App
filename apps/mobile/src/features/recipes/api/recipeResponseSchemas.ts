import { z } from "zod";

import { parseDateOnly } from "../../../shared/exact/canonicalValues";
import { NUTRIENT_UNITS } from "../../../shared/nutrition/types";
import type {
  Recipe,
  RecipeNutritionApiResponse,
  RecipePublishResponse,
} from "./types";

const exactDecimal = z
  .string()
  .max(128)
  .regex(/^\d+(?:\.\d+)?$/);

const uuid = z
  .string()
  .regex(
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
  );

const instant = z
  .string()
  .datetime({ offset: true })
  .refine((value) => {
    try {
      parseDateOnly(value.slice(0, 10));
      return true;
    } catch {
      return false;
    }
  });

const nutrientUnit = z.enum(
  NUTRIENT_UNITS,
);

const recipeIngredientSchema = z
  .object({
    id: uuid,
    recipe_id: uuid,
    food_item_id: uuid,
    position:
      z.number().int().nonnegative(),
    amount_quantity: exactDecimal,
    amount_unit: z.enum([
      "serving",
      "g",
    ]),
    serving_definition_id:
      uuid.nullable(),
    resolved_gram_amount:
      exactDecimal.nullable(),
    preparation_note:
      z.string().nullable(),
    amount_display_quantity:
      exactDecimal.nullable(),
    amount_display_unit:
      z.string().nullable(),
  })
  .strict();

const generalRecipeSchema = z
  .object({
    id: uuid,
    user_id: uuid,
    published_food_item_id:
      uuid.nullable(),
    name: z.string(),
    notes: z.string().nullable(),
    serving_count_yield:
      exactDecimal.nullable(),
    final_cooked_weight_grams:
      exactDecimal.nullable(),
    final_cooked_weight_display_quantity:
      exactDecimal.nullable(),
    final_cooked_weight_display_unit:
      z.string().nullable(),
    needs_republish: z.boolean(),
    created_at: instant,
    updated_at: instant,
    ingredients: z.array(
      recipeIngredientSchema,
    ),
  })
  .strict();

const publishedRecipeSchema =
  generalRecipeSchema.extend({
    published_food_item_id: uuid,
    needs_republish:
      z.literal(false),
  });

const recipeListResponseSchema = z
  .object({
    recipes: z.array(
      generalRecipeSchema,
    ),
  })
  .strict();

const recipeNutrientTotalSchema = z
  .object({
    nutrient_id: z.string(),
    amount_known: exactDecimal,
    amount_estimated: exactDecimal,
    unit: nutrientUnit,
    has_unknown_contributors:
      z.boolean(),
    unknown_contributor_count:
      z.number().int().nonnegative(),
  })
  .strict();

const recipeNutritionResponseSchema = z
  .object({
    totals: z.array(
      recipeNutrientTotalSchema,
    ),
    per_serving: z
      .array(
        recipeNutrientTotalSchema,
      )
      .nullable(),
    per_100g: z
      .array(
        recipeNutrientTotalSchema,
      )
      .nullable(),
  })
  .strict();

const servingDefinitionSchema = z
  .object({
    id: uuid,
    label: z.string(),
    quantity: exactDecimal,
    unit: z.string(),
    gram_weight:
      exactDecimal.nullable(),
    reference_quantity:
      exactDecimal.nullable(),
    reference_unit:
      z.string().nullable(),
    reference_gram_weight:
      exactDecimal.nullable(),
    is_default: z.boolean(),
    source: z.string(),
    is_user_confirmed:
      z.boolean(),
  })
  .strict();

const foodNutrientSchema = z
  .object({
    id: uuid,
    nutrient_id: z.string(),
    amount: exactDecimal.nullable(),
    unit: nutrientUnit,
    basis: z.enum([
      "per_serving",
      "per_100g",
      "per_gram",
    ]),
    data_status: z.enum([
      "known",
      "unknown",
      "estimated",
      "zero",
    ]),
    source: z.string(),
    is_user_confirmed:
      z.boolean(),
    original_amount:
      exactDecimal.nullable(),
    original_unit:
      z.string().nullable(),
    original_text:
      z.string().nullable(),
  })
  .strict();

const publishedFoodSchema = z
  .object({
    id: uuid,
    name: z.string(),
    brand: z.string().nullable(),
    notes: z.string().nullable(),
    source_type:
      z.literal("recipe"),
    source_id: uuid,
    is_recipe: z.literal(true),
    source_kind:
      z.literal("recipe"),
    source_label:
      z.literal("Recipe"),
    is_favorite:
      z.literal(false),
    can_favorite:
      z.literal(false),
    created_at: instant,
    updated_at: instant,
    serving_definitions: z.array(
      servingDefinitionSchema,
    ),
    nutrients: z.array(
      foodNutrientSchema,
    ),
  })
  .strict();

const recipePublishResponseSchema = z
  .object({
    recipe: publishedRecipeSchema,
    food: publishedFoodSchema,
  })
  .strict()
  .superRefine(
    (value, context) => {
      if (
        value.recipe
          .published_food_item_id
        !== value.food.id
      ) {
        context.addIssue({
          code:
            z.ZodIssueCode.custom,
          path: [
            "recipe",
            "published_food_item_id",
          ],
          message:
            "Published Recipe must reference the returned managed Food.",
        });
      }

      if (
        value.food.source_id
        !== value.recipe.id
      ) {
        context.addIssue({
          code:
            z.ZodIssueCode.custom,
          path: [
            "food",
            "source_id",
          ],
          message:
            "Managed Food must reference the published Recipe.",
        });
      }
    },
  );

export function parseRecipeResponse(
  raw: unknown,
): Recipe {
  return generalRecipeSchema.parse(
    raw,
  ) as Recipe;
}

export function parseRecipeListResponse(
  raw: unknown,
): Recipe[] {
  return recipeListResponseSchema.parse(
    raw,
  ).recipes as Recipe[];
}

export function parseRecipeNutritionResponse(
  raw: unknown,
): RecipeNutritionApiResponse {
  return recipeNutritionResponseSchema.parse(
    raw,
  ) as RecipeNutritionApiResponse;
}

export function parseRecipePublishResponse(
  raw: unknown,
): RecipePublishResponse {
  return recipePublishResponseSchema.parse(
    raw,
  ) as RecipePublishResponse;
}

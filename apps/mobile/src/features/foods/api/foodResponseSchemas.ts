import { z } from "zod";

import { parseDateOnly } from "../../../shared/exact/canonicalValues";
import { NUTRIENT_UNITS } from "../../../shared/nutrition/types";
import type {
  Food,
  FoodDeleteResult,
  FoodResolvedNutrition,
  FoodSourceKind,
  NutrientDefinition,
  RecentFood,
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

const nutrientUnit = z.enum(NUTRIENT_UNITS);

const nutrientDataStatus = z.enum([
  "known",
  "unknown",
  "estimated",
  "zero",
]);

const nutrientBasis = z.enum([
  "per_serving",
  "per_100g",
  "per_gram",
]);

const sourceKind = z.enum([
  "manual",
  "ocr_confirmed",
  "usda",
  "recipe",
  "duplicate",
  "legacy",
]);

const sourceLabels: Readonly<
  Record<FoodSourceKind, string>
> = {
  manual: "Manual",
  ocr_confirmed: "Scanned label",
  usda: "USDA",
  recipe: "Recipe",
  duplicate: "Duplicated Food",
  legacy: "Other source",
};

const servingDefinitionSchema = z
  .object({
    id: uuid,
    label: z.string(),
    quantity: exactDecimal,
    unit: z.string(),
    gram_weight: exactDecimal.nullable(),
    reference_quantity: exactDecimal.nullable(),
    reference_unit: z.string().nullable(),
    reference_gram_weight: exactDecimal.nullable(),
    is_default: z.boolean(),
    source: z.string(),
    is_user_confirmed: z.boolean(),
  })
  .strict();

const foodNutrientSchema = z
  .object({
    id: uuid,
    nutrient_id: z.string(),
    amount: exactDecimal.nullable(),
    unit: nutrientUnit,
    basis: nutrientBasis,
    data_status: nutrientDataStatus,
    source: z.string(),
    is_user_confirmed: z.boolean(),
    original_amount: exactDecimal.nullable(),
    original_unit: z.string().nullable(),
    original_text: z.string().nullable(),
  })
  .strict();

const foodResponseSchema = z
  .object({
    id: uuid,
    name: z.string(),
    brand: z.string().nullable(),
    notes: z.string().nullable(),
    source_type: z.string(),
    source_id: z.string().nullable(),
    is_recipe: z.boolean(),
    source_kind: sourceKind,
    source_label: z.string(),
    is_favorite: z.boolean(),
    can_favorite: z.boolean(),
    created_at: instant,
    updated_at: instant,
    serving_definitions: z.array(
      servingDefinitionSchema,
    ),
    nutrients: z.array(
      foodNutrientSchema,
    ),
  })
  .strict()
  .superRefine((value, context) => {
    const expectedLabel =
      sourceLabels[value.source_kind];

    if (value.source_label !== expectedLabel) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["source_label"],
        message:
          "Food source label does not match source kind.",
      });
    }
  });

const foodListResponseSchema = z
  .object({
    foods: z.array(foodResponseSchema),
  })
  .strict();

const recentFoodResponseSchema = z
  .object({
    food: foodResponseSchema,
    last_used_at: instant,
  })
  .strict();

const recentFoodListResponseSchema = z
  .object({
    foods: z.array(
      recentFoodResponseSchema,
    ),
  })
  .strict();

const resolvedFoodNutrientSchema = z
  .object({
    nutrient_id: z.string(),
    amount: exactDecimal.nullable(),
    unit: nutrientUnit,
    data_status: nutrientDataStatus,
    source_basis: nutrientBasis,
  })
  .strict();

const resolvedFoodAmountSchema = z
  .object({
    amount_definition_id: uuid,
    display_label: z.string(),
    is_default: z.boolean(),
    entered_quantity: exactDecimal,
    semantic_amount_mode: z.enum([
      "serving",
      "g",
    ]),
    resolved_grams: exactDecimal.nullable(),
    valid_for_logging: z.boolean(),
    nutrients: z.array(
      resolvedFoodNutrientSchema,
    ),
  })
  .strict();

const foodResolvedNutritionSchema = z
  .object({
    nutrition_authority: z.enum([
      "food_item",
      "recipe_publication_revision",
    ]),
    recipe_id: uuid.nullable(),
    recipe_publication_revision_id:
      uuid.nullable(),
    amounts: z.array(
      resolvedFoodAmountSchema,
    ),
  })
  .strict();

const nutrientReferenceValueSchema = z
  .object({
    amount: exactDecimal,
    unit: nutrientUnit,
    source_version: z.string(),
    standard: z.string(),
  })
  .strict();

const nutrientDefinitionSchema = z
  .object({
    id: z.string(),
    display_name: z.string(),
    default_unit: nutrientUnit,
    nutrient_kind: z.string(),
    parent_nutrient_id:
      z.string().nullable(),
    display_order: z.number().int(),
    fda_daily_value:
      nutrientReferenceValueSchema.nullable(),
    dri_reference_kinds:
      z.array(z.string()),
  })
  .strict();

const nutrientDefinitionListSchema = z.array(
  nutrientDefinitionSchema,
);

const foodDeleteAffectedRecipeSchema = z
  .object({
    recipe_id: uuid,
    recipe_name: z.string(),
    removed_ingredient_count:
      z.number().int().nonnegative(),
    needs_republish: z.boolean(),
  })
  .strict();

const foodDeleteResultSchema = z
  .object({
    food_id: uuid,
    deleted: z.boolean(),
    removed_ingredient_count:
      z.number().int().nonnegative(),
    affected_recipes: z.array(
      foodDeleteAffectedRecipeSchema,
    ),
  })
  .strict();

export function parseFoodResponse(
  raw: unknown,
): Food {
  return foodResponseSchema.parse(raw) as Food;
}

export function parseFoodListResponse(
  raw: unknown,
): Food[] {
  return foodListResponseSchema.parse(raw)
    .foods as Food[];
}

export function parseRecentFoodListResponse(
  raw: unknown,
): RecentFood[] {
  return recentFoodListResponseSchema.parse(raw)
    .foods as RecentFood[];
}

export function parseFoodResolvedNutritionResponse(
  raw: unknown,
): FoodResolvedNutrition {
  return foodResolvedNutritionSchema.parse(
    raw,
  ) as FoodResolvedNutrition;
}

export function parseNutrientDefinitionListResponse(
  raw: unknown,
): NutrientDefinition[] {
  return nutrientDefinitionListSchema.parse(
    raw,
  ) as NutrientDefinition[];
}

export function parseFoodDeleteResultResponse(
  raw: unknown,
): FoodDeleteResult {
  return foodDeleteResultSchema.parse(
    raw,
  ) as FoodDeleteResult;
}

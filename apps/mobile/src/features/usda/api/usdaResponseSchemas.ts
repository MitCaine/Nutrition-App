import { z } from "zod";

import { NUTRIENT_UNITS } from "../../../shared/nutrition/types";
import type {
  UsdaFoodPreview,
  UsdaSearchResponse,
} from "./types";

const exactDecimal = z
  .string()
  .max(128)
  .regex(/^\d+(?:\.\d+)?$/);

const nutrientUnit = z.enum(
  NUTRIENT_UNITS,
);

const nutrientBasis = z.enum([
  "per_100g",
  "per_serving",
  "per_gram",
]);

const nutrientDataStatus = z.enum([
  "known",
  "unknown",
  "estimated",
  "zero",
]);

const jsonValue: z.ZodType<unknown> =
  z.lazy(() =>
    z.union([
      z.string(),
      z.number().finite(),
      z.boolean(),
      z.null(),
      z.array(jsonValue),
      z.record(jsonValue),
    ]),
  );

const jsonObject = z.record(jsonValue);

const nutrientCandidateSchema = z
  .object({
    nutrient_id: z.string(),
    amount: exactDecimal.nullable(),
    unit: nutrientUnit,
    basis: nutrientBasis,
    data_status: nutrientDataStatus,
    source: z.literal("usda_fdc"),
    external_nutrient_id:
      z.string().nullable(),
    external_nutrient_number:
      z.string().nullable(),
    original_amount:
      exactDecimal.nullable(),
    original_unit:
      z.string().nullable(),
    display_name:
      z.string().nullable(),
  })
  .strict();

const searchResultSchema = z
  .object({
    fdc_id: z.number().int(),
    description: z.string(),
    data_type: z.string(),
    brand_owner: z.string().nullable(),
    food_category: z.string().nullable(),
    publication_date:
      z.string().nullable(),
    importable: z.boolean(),
    nutrient_preview: z.array(
      nutrientCandidateSchema,
    ),
  })
  .strict();

const searchResponseSchema = z
  .object({
    query: z.string(),
    page_number: z.number().int(),
    page_size: z.number().int(),
    total_hits:
      z.number().int().nonnegative().nullable(),
    foods: z.array(searchResultSchema),
  })
  .strict();

const servingCandidateSchema = z
  .object({
    candidate_id: z.string(),
    label: z.string(),
    quantity: exactDecimal,
    unit: z.string(),
    gram_weight: exactDecimal.nullable(),
    is_default: z.boolean(),
    source: z.literal("usda_fdc"),
  })
  .strict();

const foodPreviewSchema = z
  .object({
    source_type: z.literal("usda"),
    external_id: z.string(),
    fdc_id: z.number().int(),
    name: z.string(),
    brand: z.string().nullable(),
    data_type: z.string(),
    food_category: z.string().nullable(),
    publication_date:
      z.string().nullable(),
    nutrients: z.array(
      nutrientCandidateSchema,
    ),
    serving_definitions: z.array(
      servingCandidateSchema,
    ),
    diagnostics: z.array(z.string()),
    source_metadata: jsonObject,
  })
  .strict();

export function parseUsdaSearchResponse(
  raw: unknown,
): UsdaSearchResponse {
  return searchResponseSchema.parse(
    raw,
  ) as UsdaSearchResponse;
}

export function parseUsdaFoodPreviewResponse(
  raw: unknown,
): UsdaFoodPreview {
  return foodPreviewSchema.parse(
    raw,
  ) as UsdaFoodPreview;
}

import { z } from "zod";

import { apiRequest } from "../../../shared/api/client";
import type { OcrRecognitionResult } from "../../../native/ocr/NutritionOcr";
import type { OcrConfirmationInput, OcrConfirmationResponse, ParsedNutritionLabel } from "./types";
import { validateFoodSourceContract } from "../../foods/api/foodApi";

const decimalValue = z.union([z.string(), z.number()]).transform(String);
const fieldSchema = z.object({
  value: z.union([decimalValue, z.boolean(), z.null()]),
  comparison: z.literal("less_than").nullable(),
  source_text: z.string(), source_observation_ids: z.array(z.string()),
  confidence: z.number().min(0).max(1),
  status: z.enum(["parsed", "ambiguous", "missing", "unsupported"]),
  warning_codes: z.array(z.string()),
}).strict();
const responseSchema = z.object({
  serving: z.object({
    servings_per_container: fieldSchema, serving_size_display: fieldSchema,
    serving_quantity: fieldSchema, serving_unit: fieldSchema,
    gram_weight: fieldSchema, approximate: fieldSchema,
  }).strict().nullable(),
  calories: fieldSchema,
  nutrients: z.array(z.object({
    nutrient_id: z.string().nullable(), original_name: z.string(), amount: fieldSchema,
    unit: fieldSchema, daily_value_percent: fieldSchema.nullable(),
    source_observation_ids: z.array(z.string()), confidence: z.number().min(0).max(1),
    status: z.enum(["parsed", "ambiguous", "missing", "unsupported"]),
    warning_codes: z.array(z.string()),
  }).strict()),
  unparsed_lines: z.array(z.object({ id: z.string(), text: z.string(), source_observation_ids: z.array(z.string()), confidence: z.number(), reason: z.string().nullable() }).strict()),
  warnings: z.array(z.object({ code: z.string(), message: z.string(), source_observation_ids: z.array(z.string()) }).strict()),
  parser_version: z.string(),
}).strict();

export function parserRequestFromRecognition(result: OcrRecognitionResult) {
  return {
    full_text: result.fullText,
    observations: result.observations.map((observation) => ({
      id: observation.id,
      text: observation.text,
      confidence: observation.confidence,
      bounding_box: observation.boundingBox,
    })),
  };
}

export async function parseNutritionLabel(result: OcrRecognitionResult): Promise<ParsedNutritionLabel> {
  const raw = await apiRequest<unknown>("/ocr/nutrition-label/parse", {
    method: "POST", body: JSON.stringify(parserRequestFromRecognition(result)),
  });
  return responseSchema.parse(raw) as ParsedNutritionLabel;
}

export async function confirmNutritionLabel(input: OcrConfirmationInput): Promise<OcrConfirmationResponse> {
  const response = await apiRequest<OcrConfirmationResponse>("/ocr/nutrition-label/confirm", {
    method: "POST", body: JSON.stringify(input),
  });
  return { ...response, food: validateFoodSourceContract(response.food) };
}

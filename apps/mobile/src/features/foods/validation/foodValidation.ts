import { z } from "zod";

import { foodFocusKey, nutrientFocusKey, servingFocusKey, type ServingFocusField } from "../../../shared/forms/focusTargets";
import { validationIssue, type ValidationIssue } from "../../../shared/forms/validation";

export type FoodValidationTarget =
  | "food.name"
  | "food.brand"
  | "food.notes"
  | `serving.${string}.${ServingFocusField}`
  | `nutrient.${string}.amount`;

export const nutrientStatusSchema = z.enum(["known", "unknown", "estimated", "zero"]);

export const servingSchema = z
  .object({
    label: z.string().min(1),
    quantity: z.string().min(1),
    unit: z.string().min(1),
    gram_weight: z.string().optional().nullable(),
    is_default: z.boolean(),
  })
  .superRefine((serving, ctx) => {
    if (Number(serving.quantity) <= 0) {
      ctx.addIssue({ code: "custom", message: "Serving quantity must be greater than zero" });
    }
    if (serving.gram_weight && (!Number.isFinite(Number(serving.gram_weight)) || Number(serving.gram_weight) <= 0)) {
      ctx.addIssue({ code: "custom", message: "Gram weight must be greater than zero" });
    }
  });

export const foodNutrientSchema = z
  .object({
    nutrient_id: z.string(),
    amount: z.string().optional().nullable(),
    unit: z.enum(["kcal", "g", "mg", "mcg", "IU"]),
    basis: z.enum(["per_serving", "per_100g", "per_gram"]),
    data_status: nutrientStatusSchema,
  })
  .superRefine((nutrient, ctx) => {
    if ((nutrient.data_status === "known" || nutrient.data_status === "estimated") && !nutrient.amount) {
      ctx.addIssue({ code: "custom", message: "Known and estimated nutrients need an amount" });
    }
    if (nutrient.data_status === "known" && Number(nutrient.amount) === 0) {
      ctx.addIssue({ code: "custom", message: "Use zero status for explicit zero values" });
    }
    if (nutrient.data_status === "unknown" && nutrient.amount) {
      ctx.addIssue({ code: "custom", message: "Unknown nutrients must not include an amount" });
    }
  });

export const foodMutationSchema = z
  .object({
    name: z.string().trim().min(1, "Food name is required."),
    brand: z.string().optional().nullable(),
    notes: z.string().optional().nullable(),
    serving_definitions: z.array(servingSchema).min(1),
    nutrients: z.array(foodNutrientSchema),
  })
  .superRefine((food, ctx) => {
    const defaultCount = food.serving_definitions.filter((serving) => serving.is_default).length;
    if (defaultCount !== 1) {
      ctx.addIssue({ code: "custom", message: "Choose exactly one default serving" });
    }
    const defaultIndex = food.serving_definitions.findIndex((serving) => serving.is_default);
    const defaultGramWeight = defaultIndex >= 0 ? Number(food.serving_definitions[defaultIndex].gram_weight) : Number.NaN;
    if (defaultIndex >= 0 && (!Number.isFinite(defaultGramWeight) || defaultGramWeight <= 0)) {
      ctx.addIssue({ code: "custom", path: ["serving_definitions", defaultIndex, "gram_weight"], message: "Add an equivalent weight before setting this as the default amount." });
    }
    const baseAmounts = food.serving_definitions.filter(
      (serving) => Number(serving.quantity) === 100 && serving.unit.trim().toLowerCase() === "g" && Number(serving.gram_weight) === 100,
    );
    if (baseAmounts.length !== 1 || baseAmounts[0].label.trim().toLowerCase().replace(/\s+/g, "") !== "100g") {
      ctx.addIssue({ code: "custom", message: "Foods must include one fixed 100 g base amount" });
    }
  });

export function validationMessage(error: unknown): string {
  if (error instanceof z.ZodError) {
    return error.issues[0]?.message ?? "Invalid food";
  }
  return error instanceof Error ? error.message : "Invalid food";
}

export function foodValidationIssue(
  error: z.ZodError,
  context: { servingKeys: string[]; nutrientIds: string[] },
): ValidationIssue<FoodValidationTarget> {
  const first = error.issues[0];
  const path = first?.path ?? [];
  let target: FoodValidationTarget = "food.name";
  if (path[0] === "brand") target = "food.brand";
  if (path[0] === "notes") target = "food.notes";
  if (path[0] === "serving_definitions" && typeof path[1] === "number") {
    const key = context.servingKeys[path[1]] ?? context.servingKeys[0];
    if (key) {
      const field: ServingFocusField = path[2] === "label"
        ? "label"
        : path[2] === "unit"
        ? "unit"
        : path[2] === "gram_weight"
        ? "gramWeight"
        : "quantity";
      target = `serving.${key}.${field}`;
    }
  }
  if (path[0] === "nutrients" && typeof path[1] === "number") {
    const nutrientId = context.nutrientIds[path[1]];
    if (nutrientId) target = `nutrient.${nutrientId}.amount`;
  }
  return validationIssue({
    code: target === "food.name" ? "food_name_required" : "food_validation_failed",
    message: first?.message ?? "Review the highlighted food field.",
    target,
    announce: true,
    moveFocus: true,
    valuesRemainValid: true,
  });
}

export function foodValidationTargetFocusKey(target: FoodValidationTarget): string {
  if (target === "food.name") return foodFocusKey("name");
  if (target === "food.brand") return foodFocusKey("brand");
  if (target === "food.notes") return foodFocusKey("notes");
  if (target.startsWith("serving.")) {
    const [, key, field] = target.split(".");
    return servingFocusKey(key, field as ServingFocusField);
  }
  const [, nutrientId] = target.split(".");
  return nutrientFocusKey(nutrientId);
}

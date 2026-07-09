import { z } from "zod";

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
    if (serving.gram_weight && Number(serving.gram_weight) <= 0) {
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
    name: z.string().min(1),
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
  });

export function validationMessage(error: unknown): string {
  if (error instanceof z.ZodError) {
    return error.issues[0]?.message ?? "Invalid food";
  }
  return error instanceof Error ? error.message : "Invalid food";
}

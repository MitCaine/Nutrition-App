import { z } from "zod";

import {
  MEAL_INVALID_MESSAGE,
  NOTE_TOO_LONG_MESSAGE,
  codePointLength,
  isSupportedMeal,
} from "./logContracts";

const mealSchema = z.string().refine(isSupportedMeal, MEAL_INVALID_MESSAGE).nullable().optional();
const noteSchema = z.preprocess(
  (value) => (typeof value === "string" ? value.trim() || null : value),
  z.string().refine(
    (value) => codePointLength(value) <= 1000,
    NOTE_TOO_LONG_MESSAGE,
  ).nullable().optional(),
);

export const logInputSchema = z.object({
  food_item_id: z.string().min(1),
  logged_date: z.string().min(1),
  amount_quantity: z.string().min(1).refine((value) => Number(value) > 0, "Amount must be greater than zero"),
  amount_unit: z.enum(["serving", "g"]),
  serving_definition_id: z.string().optional().nullable(),
  meal_type: mealSchema,
  notes: noteSchema,
});

import { z } from "zod";

export const logInputSchema = z.object({
  food_item_id: z.string().min(1),
  logged_date: z.string().min(1),
  amount_quantity: z.string().min(1).refine((value) => Number(value) > 0, "Amount must be greater than zero"),
  amount_unit: z.enum(["serving", "g"]),
  serving_definition_id: z.string().optional().nullable(),
  meal_type: z.string().optional().nullable(),
  notes: z.string().optional().nullable(),
});

import {
  createClientServingKey,
  formatNutrientFormNumber,
  formatServingFormNumber,
  nutrientPayloadNumber,
  servingPayloadNumber,
  updateServingValues,
  type ServingFormValue,
} from "../src/features/foods/hooks/useFoodForm";
import { createServingFormValues } from "../src/features/foods/hooks/useFoodForm";
import { normalizeServingQuantityInput } from "../src/features/foods/utils/amountForm";
import {
  foodFormHiddenNutrients,
  foodFormVisibleNutrients,
} from "../src/features/foods/components/NutrientEntryList";
import { foodMutationSchema, servingSchema } from "../src/features/foods/validation/foodValidation";
import type { Food, FoodNutrientInput, NutrientDefinition } from "../src/features/foods/api/types";
import { parseDecimal } from "../src/shared/exact/decimal";
import { NUTRIENT_CATALOG_BY_ID } from "../src/shared/nutrition/catalog";

test("edit nutrient visibility hides unknown rows, preserves zero, and allows explicit reveal", () => {
  const definitions: NutrientDefinition[] = [
    NUTRIENT_CATALOG_BY_ID.get("protein")!,
    NUTRIENT_CATALOG_BY_ID.get("calcium")!,
    NUTRIENT_CATALOG_BY_ID.get("potassium")!,
  ];
  const values: FoodNutrientInput[] = [
    { nutrient_id: "protein", amount: "20", unit: "g", basis: "per_serving" as const, data_status: "known" as const },
    { nutrient_id: "calcium", amount: "0", unit: "mg", basis: "per_serving" as const, data_status: "zero" as const },
    { nutrient_id: "potassium", amount: null, unit: "mg", basis: "per_serving" as const, data_status: "unknown" as const },
  ];

  expect(foodFormVisibleNutrients(definitions, values, new Set(), true).map(({ id }) => id))
    .toEqual(["protein", "calcium"]);
  expect(foodFormHiddenNutrients(definitions, values, new Set()).map(({ id }) => id))
    .toEqual(["potassium"]);
  expect(foodFormVisibleNutrients(definitions, values, new Set(["potassium"]), true).map(({ id }) => id))
    .toEqual(["protein", "calcium", "potassium"]);
  expect(foodFormVisibleNutrients(definitions, values, new Set(), false).map(({ id }) => id))
    .toEqual(["protein", "calcium", "potassium"]);
});

test("serving form trims raw decimals for initial display", () => {
  expect(formatServingFormNumber("100.000000")).toBe("100");
  expect(formatServingFormNumber("85.000000")).toBe("85");
  expect(formatServingFormNumber("1.250000")).toBe("1.25");
  expect(formatServingFormNumber(null)).toBe("");
});

test("serving form preserves original precision for unchanged values", () => {
  expect(servingPayloadNumber("100", "100.000000")).toBe("100.000000");
  expect(servingPayloadNumber("85", "85.000000")).toBe("85.000000");
  expect(servingPayloadNumber("86", "85.000000")).toBe("86");
});

test.each([
  ["312.000000", "312"],
  ["6.250000", "6.25"],
  ["0.000000", "0"],
  ["1.500000", "1.5"],
  ["28.349523", "28.35"],
  ["1200.000000", "1200"],
])("nutrient form adaptively formats %s as %s", (stored, displayed) => {
  expect(formatNutrientFormNumber(stored)).toBe(displayed);
});

test("nutrient form preserves stored precision unless the displayed value changes", () => {
  expect(nutrientPayloadNumber("28.35", "28.349523")).toBe("28.349523");
  expect(nutrientPayloadNumber("28.4", "28.349523")).toBe("28.4");
  expect(nutrientPayloadNumber(null, "28.349523")).toBeNull();
});

const servings: ServingFormValue[] = [
  { key: "persisted-serving", label: "1 cup", quantity: "1", unit: "cup", gram_weight: "170", is_default: true, isBaseAmount: false, labelMode: "automatic" },
  { key: "client-serving", label: "1 scoop", quantity: "1", unit: "scoop", gram_weight: "30", is_default: false, isBaseAmount: false, labelMode: "automatic" },
];

test("editing one serving preserves stable keys and unrelated row identity", () => {
  const next = updateServingValues(servings, "client-serving", { label: "2 scoops" });
  expect(next.map((serving) => serving.key)).toEqual(["persisted-serving", "client-serving"]);
  expect(next[0]).toBe(servings[0]);
  expect(next[1]).not.toBe(servings[1]);
  expect(next[1].label).toBe("2 scoops");
});

test("setting default only replaces rows whose default state changes", () => {
  const third = { ...servings[1], key: "unchanged-third" };
  const next = updateServingValues([...servings, third], "client-serving", { is_default: true });
  expect(next[0]).not.toBe(servings[0]);
  expect(next[1].is_default).toBe(true);
  expect(next[2]).toBe(third);
});

test("new serving client keys are stable-value-independent and unique", () => {
  const first = createClientServingKey();
  const second = createClientServingKey();
  expect(first).not.toBe(second);
  expect(first).toMatch(/^client-serving-\d+$/);
});


test("valid loose quantity input is canonicalized instead of failing the runtime decimal parser", () => {
  // The physical-QA state: quantity typed as ".5" with a known positive total.
  expect(normalizeServingQuantityInput(".5")).toBe("0.5");
  expect(normalizeServingQuantityInput("2/3")).toBe("0.666666667");
  expect(normalizeServingQuantityInput("1 1/2")).toBe("1.5");
  // The runtime parser (source of the false "must be non-negative decimals" error) accepts
  // the canonical form and rejects the loose form; payloads must therefore be canonicalized.
  expect(parseDecimal("0.5")).toBe("0.500000");
  expect(() => parseDecimal(".5")).toThrow();
  // The client schema accepts the canonical form and still rejects genuinely invalid values.
  expect(servingSchema.safeParse({ label: "0.5 tsp", quantity: "0.5", unit: "tsp", gram_weight: "139", is_default: false }).success).toBe(true);
  expect(servingSchema.safeParse({ label: "bad", quantity: "-1", unit: "tsp", gram_weight: "139", is_default: false }).success).toBe(false);
  expect(servingSchema.safeParse({ label: "bad", quantity: "abc", unit: "tsp", gram_weight: "139", is_default: false }).success).toBe(false);
});

test("reference and current representation survive a save/reload model round trip independently", () => {
  const saved = createServingFormValues({
    ...baseFoodFixture(),
    serving_definitions: [
      { id: "base", label: "100 g", quantity: "100", unit: "g", gram_weight: "100", is_default: false, source: "manual", is_user_confirmed: true },
      {
        id: "tbsp", label: "8 Tbsp", quantity: "8", unit: "tbsp", gram_weight: "50", is_default: true,
        reference_quantity: "1", reference_unit: "cup", reference_gram_weight: "100",
        source: "manual", is_user_confirmed: true,
      },
    ],
  });
  const serving = saved.find((item) => item.unit === "tbsp")!;
  expect(serving).toEqual(expect.objectContaining({
    quantity: "8", unit: "tbsp", gram_weight: "50",
    reference_quantity: "1", reference_unit: "cup", reference_gram_weight: "100",
  }));
  const parsed = foodMutationSchema.safeParse({
    name: "Flour",
    brand: null,
    notes: null,
    serving_definitions: saved.map(({ key, originalQuantity, originalGramWeight, isBaseAmount, labelMode, consistencyWarning, ...rest }) => rest),
    nutrients: [],
  });
  expect(parsed.success).toBe(true);
  if (parsed.success) {
    expect(parsed.data.serving_definitions[1]).toEqual(expect.objectContaining({
      quantity: "8", unit: "tbsp", gram_weight: "50",
      reference_quantity: "1", reference_unit: "cup", reference_gram_weight: "100",
    }));
  }
});

test("reference triplet is all-or-none", () => {
  const base = { label: "8 Tbsp", quantity: "8", unit: "tbsp", gram_weight: "50", is_default: true };
  expect(servingSchema.safeParse({ ...base, reference_quantity: null, reference_unit: null, reference_gram_weight: null }).success).toBe(true);
  expect(servingSchema.safeParse({ ...base, reference_quantity: "1", reference_unit: "cup", reference_gram_weight: "100" }).success).toBe(true);
  expect(servingSchema.safeParse({ ...base, reference_quantity: "1", reference_unit: null, reference_gram_weight: "100" }).success).toBe(false);
  expect(servingSchema.safeParse({ ...base, reference_quantity: "1", reference_unit: "cup", reference_gram_weight: null }).success).toBe(false);
  expect(servingSchema.safeParse({ ...base, reference_quantity: "0", reference_unit: "cup", reference_gram_weight: "100" }).success).toBe(false);
  expect(servingSchema.safeParse({ ...base, reference_quantity: "1", reference_unit: "cup", reference_gram_weight: "-1" }).success).toBe(false);
});

function baseFoodFixture(): Food {
  return {
    id: "food-1",
    name: "Flour",
    brand: null,
    notes: null,
    source_type: "manual",
    source_id: null,
    is_recipe: false,
    source_kind: "manual",
    source_label: "Manual",
    is_favorite: false,
    can_favorite: true,
    serving_definitions: [],
    nutrients: [],
  };
}

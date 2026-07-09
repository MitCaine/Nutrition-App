import { foodMutationSchema } from "../src/features/foods/validation/foodValidation";

const validFood = {
  name: "Manual Food",
  brand: null,
  notes: null,
  serving_definitions: [
    { label: "1 serving", quantity: "1", unit: "serving", gram_weight: "100", is_default: true },
  ],
  nutrients: [
    {
      nutrient_id: "protein",
      amount: "10",
      unit: "g",
      basis: "per_serving",
      data_status: "known",
    },
  ],
};

test("manual food validation distinguishes zero from unknown", () => {
  expect(
    foodMutationSchema.safeParse({
      ...validFood,
      nutrients: [{ ...validFood.nutrients[0], amount: "0", data_status: "zero" }],
    }).success,
  ).toBe(true);

  expect(
    foodMutationSchema.safeParse({
      ...validFood,
      nutrients: [{ ...validFood.nutrients[0], amount: "", data_status: "unknown" }],
    }).success,
  ).toBe(true);

  expect(
    foodMutationSchema.safeParse({
      ...validFood,
      nutrients: [{ ...validFood.nutrients[0], amount: "0", data_status: "known" }],
    }).success,
  ).toBe(false);
});

test("manual food validation requires one default serving", () => {
  expect(
    foodMutationSchema.safeParse({
      ...validFood,
      serving_definitions: [{ ...validFood.serving_definitions[0], is_default: false }],
    }).success,
  ).toBe(false);

  expect(
    foodMutationSchema.safeParse({
      ...validFood,
      serving_definitions: [
        validFood.serving_definitions[0],
        { label: "1 bar", quantity: "1", unit: "bar", gram_weight: "50", is_default: false },
      ],
    }).success,
  ).toBe(true);
});

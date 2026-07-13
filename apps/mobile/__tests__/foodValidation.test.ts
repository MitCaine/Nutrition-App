import { foodMutationSchema } from "../src/features/foods/validation/foodValidation";

const validFood = {
  name: "Manual Food",
  brand: null,
  notes: null,
  serving_definitions: [
    { label: "100 g", quantity: "100", unit: "g", gram_weight: "100", is_default: false },
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
      serving_definitions: validFood.serving_definitions.map((serving) => ({ ...serving, is_default: false })),
    }).success,
  ).toBe(false);

  expect(
    foodMutationSchema.safeParse({
      ...validFood,
      serving_definitions: [
        ...validFood.serving_definitions,
        { label: "1 bar", quantity: "1", unit: "bar", gram_weight: "50", is_default: false },
      ],
    }).success,
  ).toBe(true);
});

test("manual food validation requires an immutable canonical 100 g amount", () => {
  expect(foodMutationSchema.safeParse(validFood).success).toBe(true);
  expect(foodMutationSchema.safeParse({ ...validFood, serving_definitions: validFood.serving_definitions.slice(1) }).success).toBe(false);
  expect(foodMutationSchema.safeParse({
    ...validFood,
    serving_definitions: validFood.serving_definitions.map((serving) => serving.label === "100 g" ? { ...serving, gram_weight: "99" } : serving),
  }).success).toBe(false);
});

test("manual food validation rejects an unknown-weight default amount with actionable guidance", () => {
  const result = foodMutationSchema.safeParse({
    ...validFood,
    serving_definitions: validFood.serving_definitions.map((serving) =>
      serving.is_default ? { ...serving, gram_weight: null } : serving,
    ),
  });
  expect(result.success).toBe(false);
  if (!result.success) {
    expect(result.error.issues).toEqual(expect.arrayContaining([
      expect.objectContaining({
        message: "Add an equivalent weight before setting this as the default amount.",
        path: ["serving_definitions", 1, "gram_weight"],
      }),
    ]));
  }
});

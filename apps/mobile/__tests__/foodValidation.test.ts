import {
  foodMutationSchema,
  foodValidationIssue,
  foodValidationTargetFocusKey,
} from "../src/features/foods/validation/foodValidation";

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

test.each([
  ["18.125", true],
  ["1.2345675", true],
  ["99999999.9999989", true],
  ["99999999.999999", true],
  ["1e100", false],
  ["100000000.000000", false],
  ["99999999.9999995", false],
  ["999999999999999999", false],
] as const)("manual nutrient amount %s follows the exact NUMERIC(14,6) contract", (amount, expected) => {
  const result = foodMutationSchema.safeParse({
    ...validFood,
    nutrients: [{ ...validFood.nutrients[0], amount }],
  });

  expect(result.success).toBe(expected);
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

test("food validation returns a stable logical target that maps to the registered field", () => {
  const result = foodMutationSchema.safeParse({ ...validFood, name: "" });
  expect(result.success).toBe(false);
  if (result.success) return;
  const issue = foodValidationIssue(result.error, {
    servingKeys: ["base", "serving"],
    nutrientIds: ["protein"],
  });
  expect(issue).toEqual(expect.objectContaining({
    code: "food_name_required",
    message: "Food name is required.",
    target: "food.name",
    moveFocus: true,
    valuesRemainValid: true,
  }));
  expect(foodValidationTargetFocusKey(issue.target)).toBe("food:name");
});


test("manual food validation rejects duplicate nutrient identities within one basis", () => {
  const result = foodMutationSchema.safeParse({
    ...validFood,
    nutrients: [
      { ...validFood.nutrients[0], basis: "per_100g" },
      {
        ...validFood.nutrients[0],
        basis: "per_100g",
        amount: "20",
      },
    ],
  });

  expect(result.success).toBe(false);
  if (!result.success) {
    expect(result.error.issues).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          message:
            "Foods cannot contain duplicate nutrient identities for the same basis.",
          path: ["nutrients", 1, "nutrient_id"],
        }),
      ]),
    );
  }
});

test("manual food validation allows one nutrient at distinct bases", () => {
  const result = foodMutationSchema.safeParse({
    ...validFood,
    nutrients: [
      { ...validFood.nutrients[0], basis: "per_100g" },
      {
        ...validFood.nutrients[0],
        basis: "per_serving",
        amount: "20",
      },
    ],
  });

  expect(result.success).toBe(true);
});

test("manual food validation rejects negative nutrient amounts", () => {
  const result = foodMutationSchema.safeParse({
    ...validFood,
    nutrients: [
      {
        ...validFood.nutrients[0],
        amount: "-0.000001",
      },
    ],
  });

  expect(result.success).toBe(false);
});

import { z } from "zod";

import {
  createFood,
  createFoodServing,
  deleteFood,
  duplicateFood,
  getFood,
  getFoodResolvedNutrition,
  listFavoriteFoods,
  listFoods,
  listNutrients,
  listRecentFoods,
  setFoodFavorite,
  updateFood,
} from "../src/features/foods/api/foodApi";
import {
  parseFoodDeleteResultResponse,
  parseFoodResolvedNutritionResponse,
  parseFoodResponse,
  parseNutrientDefinitionListResponse,
  parseRecentFoodListResponse,
} from "../src/features/foods/api/foodResponseSchemas";

const foodId =
  "11111111-1111-4111-8111-111111111111";
const servingId =
  "22222222-2222-4222-8222-222222222222";
const nutrientId =
  "33333333-3333-4333-8333-333333333333";
const recipeId =
  "44444444-4444-4444-8444-444444444444";
const revisionId =
  "55555555-5555-4555-8555-555555555555";
const amountId =
  "66666666-6666-4666-8666-666666666666";

const timestamp = "2026-08-22T18:00:00Z";

const canonicalFood = {
  id: foodId,
  name: "Canonical Food",
  brand: null,
  notes: null,
  source_type: "manual",
  source_id: null,
  is_recipe: false,
  source_kind: "manual" as const,
  source_label: "Manual",
  is_favorite: false,
  can_favorite: true,
  created_at: timestamp,
  updated_at: timestamp,
  serving_definitions: [
    {
      id: servingId,
      label: "1 serving",
      quantity: "1.000000",
      unit: "serving",
      gram_weight: "125.000000",
      reference_quantity: null,
      reference_unit: null,
      reference_gram_weight: null,
      is_default: true,
      source: "manual",
      is_user_confirmed: true,
    },
  ],
  nutrients: [
    {
      id: nutrientId,
      nutrient_id: "calories",
      amount: "120.000000",
      unit: "kcal" as const,
      basis: "per_serving" as const,
      data_status: "known" as const,
      source: "manual",
      is_user_confirmed: true,
      original_amount: null,
      original_unit: null,
      original_text: null,
    },
  ],
};

const nutrientCatalog = [
  {
    id: "calories",
    display_name: "Calories",
    default_unit: "kcal" as const,
    nutrient_kind: "energy",
    parent_nutrient_id: null,
    display_order: 1,
    fda_daily_value: {
      amount: "2000",
      unit: "kcal" as const,
      source_version: "2020",
      standard: "adult",
    },
    dri_reference_kinds: ["dv"],
  },
];

const resolvedNutrition = {
  nutrition_authority: "food_item" as const,
  recipe_id: null,
  recipe_publication_revision_id: null,
  amounts: [
    {
      amount_definition_id: amountId,
      display_label: "1 serving",
      is_default: true,
      entered_quantity: "1.000000",
      semantic_amount_mode: "serving" as const,
      resolved_grams: "125.000000",
      valid_for_logging: true,
      nutrients: [
        {
          nutrient_id: "calories",
          amount: "120.000000",
          unit: "kcal" as const,
          data_status: "known" as const,
          source_basis: "per_serving" as const,
        },
      ],
    },
  ],
};

const deleteResult = {
  food_id: foodId,
  deleted: true,
  removed_ingredient_count: 1,
  affected_recipes: [
    {
      recipe_id: recipeId,
      recipe_name: "Recipe",
      removed_ingredient_count: 1,
      needs_republish: true,
    },
  ],
};

function clone<T>(value: T): T {
  return JSON.parse(
    JSON.stringify(value),
  ) as T;
}

function mockJson(
  value: unknown,
  status = 200,
): void {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status,
    json: async () => value,
  });
}

test(
  "canonical Food parser validates complete backend Food responses without changing exact values",
  () => {
    expect(
      parseFoodResponse(canonicalFood),
    ).toEqual(canonicalFood);

    expect(
      parseFoodResponse(canonicalFood)
        .nutrients[0].amount,
    ).toBe("120.000000");

    expect(
      parseFoodResponse(canonicalFood)
        .serving_definitions[0]
        .gram_weight,
    ).toBe("125.000000");
  },
);

test.each([
  [
    "invalid Food UUID",
    {
      ...canonicalFood,
      id: "food-1",
    },
  ],
  [
    "numeric exact decimal",
    {
      ...canonicalFood,
      serving_definitions: [
        {
          ...canonicalFood
            .serving_definitions[0],
          quantity: 1,
        },
      ],
    },
  ],
  [
    "exponent exact decimal",
    {
      ...canonicalFood,
      nutrients: [
        {
          ...canonicalFood.nutrients[0],
          amount: "1e2",
        },
      ],
    },
  ],
  [
    "invalid nutrient unit",
    {
      ...canonicalFood,
      nutrients: [
        {
          ...canonicalFood.nutrients[0],
          unit: "cal",
        },
      ],
    },
  ],
  [
    "source label mismatch",
    {
      ...canonicalFood,
      source_label: "USDA",
    },
  ],
  [
    "missing backend timestamp",
    (() => {
      const value =
        clone(canonicalFood) as
        Record<string, unknown>;

      delete value.created_at;
      return value;
    })(),
  ],
  [
    "unexpected top-level field",
    {
      ...canonicalFood,
      unexpected: true,
    },
  ],
  [
    "unexpected nested field",
    {
      ...canonicalFood,
      serving_definitions: [
        {
          ...canonicalFood
            .serving_definitions[0],
          unexpected: true,
        },
      ],
    },
  ],
])(
  "canonical Food parser rejects %s",
  (_name, value) => {
    expect(() =>
      parseFoodResponse(value),
    ).toThrow(z.ZodError);
  },
);

test(
  "Food list and recent wrappers are strict and preserve timestamps",
  () => {
    expect(
      parseRecentFoodListResponse({
        foods: [
          {
            food: canonicalFood,
            last_used_at: timestamp,
          },
        ],
      }),
    ).toEqual([
      {
        food: canonicalFood,
        last_used_at: timestamp,
      },
    ]);

    expect(() =>
      parseRecentFoodListResponse({
        foods: [
          {
            food: canonicalFood,
            last_used_at: "not-a-time",
          },
        ],
      }),
    ).toThrow(z.ZodError);

    expect(() =>
      parseRecentFoodListResponse({
        foods: [
          {
            food: canonicalFood,
            last_used_at: timestamp,
            unexpected: true,
          },
        ],
      }),
    ).toThrow(z.ZodError);
  },
);

test(
  "nutrient catalog validation preserves exact daily values and rejects malformed units",
  () => {
    expect(
      parseNutrientDefinitionListResponse(
        nutrientCatalog,
      ),
    ).toEqual(nutrientCatalog);

    expect(() =>
      parseNutrientDefinitionListResponse([
        {
          ...nutrientCatalog[0],
          default_unit: "cal",
        },
      ]),
    ).toThrow(z.ZodError);

    expect(() =>
      parseNutrientDefinitionListResponse([
        {
          ...nutrientCatalog[0],
          fda_daily_value: {
            ...nutrientCatalog[0]
              .fda_daily_value,
            amount: 2000,
          },
        },
      ]),
    ).toThrow(z.ZodError);
  },
);

test(
  "resolved nutrition validates UUIDs, exact decimals, status, units, and strict nested objects",
  () => {
    expect(
      parseFoodResolvedNutritionResponse(
        resolvedNutrition,
      ),
    ).toEqual(resolvedNutrition);

    expect(() =>
      parseFoodResolvedNutritionResponse({
        ...resolvedNutrition,
        recipe_id: recipeId,
        recipe_publication_revision_id:
          revisionId,
        amounts: [
          {
            ...resolvedNutrition.amounts[0],
            amount_definition_id:
              "amount-1",
          },
        ],
      }),
    ).toThrow(z.ZodError);

    expect(() =>
      parseFoodResolvedNutritionResponse({
        ...resolvedNutrition,
        amounts: [
          {
            ...resolvedNutrition.amounts[0],
            entered_quantity: "-1",
          },
        ],
      }),
    ).toThrow(z.ZodError);

    expect(() =>
      parseFoodResolvedNutritionResponse({
        ...resolvedNutrition,
        amounts: [
          {
            ...resolvedNutrition.amounts[0],
            nutrients: [
              {
                ...resolvedNutrition
                  .amounts[0]
                  .nutrients[0],
                data_status: "present",
              },
            ],
          },
        ],
      }),
    ).toThrow(z.ZodError);
  },
);

test(
  "Food delete result validates UUID identities and non-negative integer counts",
  () => {
    expect(
      parseFoodDeleteResultResponse(
        deleteResult,
      ),
    ).toEqual(deleteResult);

    expect(() =>
      parseFoodDeleteResultResponse({
        ...deleteResult,
        removed_ingredient_count: -1,
      }),
    ).toThrow(z.ZodError);

    expect(() =>
      parseFoodDeleteResultResponse({
        ...deleteResult,
        affected_recipes: [
          {
            ...deleteResult
              .affected_recipes[0],
            recipe_id: "recipe-1",
          },
        ],
      }),
    ).toThrow(z.ZodError);
  },
);

test(
  "all twelve Food capability operations validate canonical successful responses",
  async () => {
    mockJson(nutrientCatalog);
    await expect(
      listNutrients(),
    ).resolves.toEqual(nutrientCatalog);

    mockJson({
      foods: [canonicalFood],
    });
    await expect(
      listFoods(),
    ).resolves.toEqual([canonicalFood]);

    mockJson(canonicalFood);
    await expect(
      getFood(foodId),
    ).resolves.toEqual(canonicalFood);

    mockJson({
      foods: [canonicalFood],
    });
    await expect(
      listFavoriteFoods(),
    ).resolves.toEqual([canonicalFood]);

    mockJson({
      foods: [
        {
          food: canonicalFood,
          last_used_at: timestamp,
        },
      ],
    });
    await expect(
      listRecentFoods(),
    ).resolves.toEqual([
      {
        food: canonicalFood,
        last_used_at: timestamp,
      },
    ]);

    mockJson(canonicalFood);
    await expect(
      setFoodFavorite(
        foodId,
        true,
      ),
    ).resolves.toEqual(canonicalFood);

    mockJson(resolvedNutrition);
    await expect(
      getFoodResolvedNutrition(
        foodId,
      ),
    ).resolves.toEqual(
      resolvedNutrition,
    );

    mockJson(canonicalFood, 201);
    await expect(
      createFood({
        name: "Canonical Food",
        serving_definitions: [
          {
            label: "1 serving",
            quantity: "1",
            unit: "serving",
            is_default: true,
          },
        ],
        nutrients: [],
      }),
    ).resolves.toEqual(canonicalFood);

    mockJson(canonicalFood);
    await expect(
      updateFood(
        foodId,
        {
          name: "Canonical Food",
          serving_definitions: [
            {
              label: "1 serving",
              quantity: "1",
              unit: "serving",
              is_default: true,
            },
          ],
          nutrients: [],
        },
      ),
    ).resolves.toEqual(canonicalFood);

    mockJson(deleteResult);
    await expect(
      deleteFood({
        foodId,
      }),
    ).resolves.toEqual(deleteResult);

    mockJson(canonicalFood, 201);
    await expect(
      duplicateFood({
        foodId,
        clientRequestId:
          "77777777-7777-4777-8777-777777777777",
      }),
    ).resolves.toEqual(canonicalFood);

    mockJson(canonicalFood, 201);
    await expect(
      createFoodServing(
        foodId,
        {
          label: "1 slice",
          quantity: "1",
          unit: "slice",
          is_default: false,
        },
      ),
    ).resolves.toEqual(canonicalFood);
  },
);

test(
  "Food capability API seams reject malformed successful responses before use",
  async () => {
    mockJson({
      ...canonicalFood,
      id: "food-1",
    });

    await expect(
      getFood(foodId),
    ).rejects.toBeInstanceOf(z.ZodError);

    mockJson({
      foods: [canonicalFood],
      unexpected: true,
    });

    await expect(
      listFoods(),
    ).rejects.toBeInstanceOf(z.ZodError);

    mockJson([
      {
        ...nutrientCatalog[0],
        default_unit: "cal",
      },
    ]);

    await expect(
      listNutrients(),
    ).rejects.toBeInstanceOf(z.ZodError);

    mockJson({
      foods: [
        {
          food: canonicalFood,
          last_used_at: "not-a-time",
        },
      ],
    });

    await expect(
      listRecentFoods(),
    ).rejects.toBeInstanceOf(z.ZodError);

    mockJson({
      ...resolvedNutrition,
      amounts: [
        {
          ...resolvedNutrition.amounts[0],
          entered_quantity: 1,
        },
      ],
    });

    await expect(
      getFoodResolvedNutrition(foodId),
    ).rejects.toBeInstanceOf(z.ZodError);

    mockJson({
      ...canonicalFood,
      source_label: "USDA",
    });

    await expect(
      createFood({
        name: "Canonical Food",
        serving_definitions: [
          {
            label: "1 serving",
            quantity: "1",
            unit: "serving",
            is_default: true,
          },
        ],
        nutrients: [],
      }),
    ).rejects.toBeInstanceOf(z.ZodError);

    mockJson({
      ...deleteResult,
      removed_ingredient_count: -1,
    });

    await expect(
      deleteFood({
        foodId,
      }),
    ).rejects.toBeInstanceOf(z.ZodError);
  },
);

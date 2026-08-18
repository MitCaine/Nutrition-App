import {
  NUTRIENT_CATALOG,
} from "../src/shared/nutrition/catalog";
import {
  canonicalNutrientParentId,
  groupCanonicalNutrientsBySection,
  nutrientVisibleDepth,
} from "../src/shared/nutrition/nutrientSections";

test("nutrition presentation starts with the familiar Nutrition Facts sequence", () => {
  const sections =
    groupCanonicalNutrientsBySection(
      NUTRIENT_CATALOG,
      (nutrient) => nutrient.id,
    );

  expect(
    sections.map(
      ({ id }) => id,
    ),
  ).toEqual([
    "nutrition_facts",
    "vitamins",
    "minerals",
    "fatty_acids",
    "other",
  ]);

  const nutritionFacts =
    sections.find(
      ({ id }) =>
        id === "nutrition_facts",
    );

  expect(
    nutritionFacts?.label,
  ).toBeNull();

  expect(
    nutritionFacts?.items.map(
      ({ id }) => id,
    ),
  ).toEqual([
    "calories",
    "total_fat",
    "saturated_fat",
    "trans_fat",
    "cholesterol",
    "sodium",
    "total_carbohydrate",
    "dietary_fiber",
    "total_sugars",
    "added_sugars",
    "protein",
    "vitamin_d",
    "calcium",
    "iron",
    "potassium",
  ]);
});

test("fatty acids use a real Omega-3 parent without synthesizing hierarchy", () => {
  const sections =
    groupCanonicalNutrientsBySection(
      NUTRIENT_CATALOG,
      (nutrient) => nutrient.id,
    );

  const fattyAcids =
    sections.find(
      ({ id }) =>
        id === "fatty_acids",
    );

  expect(
    fattyAcids?.items.map(
      ({
        id,
        parent_nutrient_id,
      }) => [
        id,
        parent_nutrient_id,
      ],
    ),
  ).toEqual([
    ["total_omega_3", null],
    [
      "alpha_linolenic_acid",
      "total_omega_3",
    ],
    ["epa", "total_omega_3"],
    ["dha", "total_omega_3"],
    ["linoleic_acid", null],
  ]);
});


test("visible hierarchy depth preserves nested Nutrition Facts relationships", () => {
  const carbohydrateTree =
    new Set([
      "total_carbohydrate",
      "total_sugars",
      "added_sugars",
    ]);

  expect(
    nutrientVisibleDepth(
      "total_carbohydrate",
      carbohydrateTree,
      canonicalNutrientParentId,
    ),
  ).toBe(0);

  expect(
    nutrientVisibleDepth(
      "total_sugars",
      carbohydrateTree,
      canonicalNutrientParentId,
    ),
  ).toBe(1);

  expect(
    nutrientVisibleDepth(
      "added_sugars",
      carbohydrateTree,
      canonicalNutrientParentId,
    ),
  ).toBe(2);

  expect(
    nutrientVisibleDepth(
      "epa",
      new Set([
        "total_omega_3",
        "epa",
      ]),
      canonicalNutrientParentId,
    ),
  ).toBe(1);

  expect(
    nutrientVisibleDepth(
      "added_sugars",
      new Set([
        "total_carbohydrate",
        "added_sugars",
      ]),
      canonicalNutrientParentId,
    ),
  ).toBe(0);
});

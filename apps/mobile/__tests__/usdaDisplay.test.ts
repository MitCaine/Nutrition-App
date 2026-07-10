import {
  canStartUsdaImport,
  formatUsdaNutrient,
  formatUsdaNutrientLabel,
  formatUsdaNutrientPreview,
  usdaImportErrorMessage,
  usdaPreviewMessage,
  usdaResultMeta,
  usdaSearchMessage,
} from "../src/features/usda/utils/usdaDisplay";
import type { UsdaSearchResult } from "../src/features/usda/api/types";

const searchResult: UsdaSearchResult = {
  fdc_id: 555000,
  description: "Example Protein Bar",
  data_type: "Branded",
  brand_owner: "Example Foods",
  food_category: "Bars",
  importable: true,
  nutrient_preview: [
    {
      nutrient_id: "calories",
      amount: "300",
      unit: "kcal",
      basis: "per_100g",
      data_status: "known",
      source: "usda_fdc",
      display_name: "Calories",
    },
    {
      nutrient_id: "cholesterol",
      amount: "0",
      unit: "mg",
      basis: "per_100g",
      data_status: "zero",
      source: "usda_fdc",
      display_name: "Cholesterol",
    },
    {
      nutrient_id: "vitamin_d",
      amount: null,
      unit: "mcg",
      basis: "per_100g",
      data_status: "unknown",
      source: "usda_fdc",
      display_name: "Vitamin D",
    },
  ],
};

test("USDA search messages cover empty loading no-result and error states", () => {
  expect(usdaSearchMessage({ query: "", isLoading: false, isError: false })).toBe(
    "Search USDA foods by name, brand, or ingredient.",
  );
  expect(usdaSearchMessage({ query: "banana", isLoading: true, isError: false })).toBe(
    "Searching USDA foods...",
  );
  expect(usdaSearchMessage({ query: "banana", isLoading: false, isError: true })).toBe(
    "USDA search is unavailable right now. Try again later.",
  );
  expect(usdaSearchMessage({ query: "banana", isLoading: false, isError: false, resultCount: 0 })).toBe(
    "No USDA foods found. Try a different search.",
  );
  expect(usdaSearchMessage({ query: "banana", isLoading: false, isError: false, resultCount: 1 })).toBeNull();
});

test("USDA result formatting includes brand and useful nutrient preview", () => {
  expect(usdaResultMeta(searchResult)).toBe("Branded - Example Foods");
  expect(formatUsdaNutrientPreview(searchResult.nutrient_preview)).toBe(
    "Calories: 300kcal - Cholesterol: 0mg",
  );
  expect(formatUsdaNutrient(searchResult.nutrient_preview[2])).toBe("unknown");
});

test("USDA nutrient formatting trims raw decimals and formats raw ids", () => {
  expect(
    formatUsdaNutrient({
      nutrient_id: "saturated_fat",
      amount: "2.350000",
      unit: "g",
      basis: "per_100g",
      data_status: "known",
      source: "usda_fdc",
    }),
  ).toBe("2.35g");
  expect(
    formatUsdaNutrientLabel({
      nutrient_id: "total_carbohydrate",
      amount: "12.000000",
      unit: "g",
      basis: "per_100g",
      data_status: "known",
      source: "usda_fdc",
    }),
  ).toBe("Total Carbohydrate");
});

test("USDA preview and import states use clear user-facing messages", () => {
  expect(usdaPreviewMessage(true, false)).toBe("Loading USDA food...");
  expect(usdaPreviewMessage(false, true)).toBe("USDA food details are unavailable right now. Try again later.");
  expect(usdaPreviewMessage(false, false)).toBeNull();
  expect(usdaImportErrorMessage()).toBe("Import failed. Try again later.");
});

test("USDA import action is blocked while an import is already pending", () => {
  expect(canStartUsdaImport(false)).toBe(true);
  expect(canStartUsdaImport(true)).toBe(false);
});

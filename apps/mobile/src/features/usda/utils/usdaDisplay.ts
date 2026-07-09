import type { UsdaNutrientCandidate, UsdaSearchResult } from "../api/types";

export type UsdaSearchStateInput = {
  query: string;
  isLoading: boolean;
  isError: boolean;
  resultCount?: number;
};

export function usdaSearchMessage(state: UsdaSearchStateInput): string | null {
  if (state.query.trim().length < 2) {
    return "Search USDA foods by name, brand, or ingredient.";
  }
  if (state.isLoading) {
    return "Searching USDA foods...";
  }
  if (state.isError) {
    return "USDA search is unavailable right now. Try again later.";
  }
  if (state.resultCount === 0) {
    return "No USDA foods found. Try a different search.";
  }
  return null;
}

export function usdaPreviewMessage(isLoading: boolean, isError: boolean): string | null {
  if (isError) {
    return "USDA food details are unavailable right now. Try again later.";
  }
  if (isLoading) {
    return "Loading USDA food...";
  }
  return null;
}

export function usdaImportErrorMessage(): string {
  return "Import failed. Try again later.";
}

export function formatUsdaNutrient(nutrient: UsdaNutrientCandidate): string {
  if (nutrient.data_status === "unknown") {
    return "unknown";
  }
  return `${nutrient.amount ?? "0"}${nutrient.unit}`;
}

export function formatUsdaNutrientPreview(nutrients: UsdaNutrientCandidate[]): string | null {
  const preview = nutrients
    .filter((nutrient) => nutrient.data_status !== "unknown")
    .slice(0, 3)
    .map((nutrient) => `${nutrient.display_name ?? nutrient.nutrient_id}: ${formatUsdaNutrient(nutrient)}`);
  return preview.length > 0 ? preview.join(" - ") : null;
}

export function usdaResultMeta(food: UsdaSearchResult): string {
  return [food.data_type, food.brand_owner].filter(Boolean).join(" - ");
}

export function canStartUsdaImport(isPending: boolean): boolean {
  return !isPending;
}

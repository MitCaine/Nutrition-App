import type { Food } from "../../foods/api/types";
import type { NutrientDataStatus, NutrientUnit } from "../../../shared/nutrition/types";

export type UsdaNutrientCandidate = {
  nutrient_id: string;
  amount?: string | null;
  unit: NutrientUnit;
  basis: "per_100g" | "per_serving" | "per_gram";
  data_status: NutrientDataStatus;
  source: "usda_fdc";
  external_nutrient_id?: string | null;
  external_nutrient_number?: string | null;
  original_amount?: string | null;
  original_unit?: string | null;
  display_name?: string | null;
};

export type UsdaServingCandidate = {
  candidate_id: string;
  label: string;
  quantity: string;
  unit: string;
  gram_weight?: string | null;
  is_default: boolean;
  source: "usda_fdc";
};

export type UsdaSearchResult = {
  fdc_id: number;
  description: string;
  data_type: string;
  brand_owner?: string | null;
  food_category?: string | null;
  publication_date?: string | null;
  importable: boolean;
  nutrient_preview: UsdaNutrientCandidate[];
};

export type UsdaSearchResponse = {
  query: string;
  page_number: number;
  page_size: number;
  total_hits?: number | null;
  foods: UsdaSearchResult[];
};

export type UsdaFoodPreview = {
  source_type: "usda";
  external_id: string;
  fdc_id: number;
  name: string;
  brand?: string | null;
  data_type: string;
  food_category?: string | null;
  publication_date?: string | null;
  nutrients: UsdaNutrientCandidate[];
  serving_definitions: UsdaServingCandidate[];
  diagnostics: string[];
};

export type UsdaImportResult = Food;

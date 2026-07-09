import type { NutrientDataStatus, NutrientUnit } from "../../../shared/nutrition/types";

export type NutrientBasis = "per_serving" | "per_100g" | "per_gram";

export type ServingDefinitionInput = {
  label: string;
  quantity: string;
  unit: string;
  gram_weight?: string | null;
  is_default: boolean;
};

export type FoodNutrientInput = {
  nutrient_id: string;
  amount?: string | null;
  unit: NutrientUnit;
  basis: NutrientBasis;
  data_status: NutrientDataStatus;
};

export type FoodMutationInput = {
  name: string;
  brand?: string | null;
  notes?: string | null;
  serving_definitions: ServingDefinitionInput[];
  nutrients: FoodNutrientInput[];
};

export type ServingDefinition = ServingDefinitionInput & {
  id: string;
  source: string;
  is_user_confirmed: boolean;
};

export type FoodNutrient = Required<FoodNutrientInput> & {
  id: string;
  source: string;
  is_user_confirmed: boolean;
  original_amount?: string | null;
  original_unit?: string | null;
  original_text?: string | null;
};

export type Food = {
  id: string;
  name: string;
  brand?: string | null;
  notes?: string | null;
  source_type: string;
  source_id?: string | null;
  is_recipe: boolean;
  serving_definitions: ServingDefinition[];
  nutrients: FoodNutrient[];
};

export type NutrientDefinition = {
  id: string;
  display_name: string;
  default_unit: NutrientUnit;
  nutrient_kind: string;
  parent_nutrient_id?: string | null;
  display_order: number;
};

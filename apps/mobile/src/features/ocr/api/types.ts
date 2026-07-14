import type { Food, FoodMutationInput } from "../../foods/api/types";

export type ParseStatus = "parsed" | "ambiguous" | "missing" | "unsupported";
export type ParsedField = {
  value: string | boolean | null;
  comparison: "less_than" | null;
  source_text: string;
  source_observation_ids: string[];
  confidence: number;
  status: ParseStatus;
  warning_codes: string[];
};
export type ParsedServing = {
  servings_per_container: ParsedField;
  serving_size_display: ParsedField;
  serving_quantity: ParsedField;
  serving_unit: ParsedField;
  gram_weight: ParsedField;
  approximate: ParsedField;
};
export type ParsedNutrient = {
  nutrient_id: string | null;
  original_name: string;
  amount: ParsedField;
  unit: ParsedField;
  daily_value_percent: ParsedField | null;
  source_observation_ids: string[];
  confidence: number;
  status: ParseStatus;
  warning_codes: string[];
};
export type ParsedNutritionLabel = {
  serving: ParsedServing | null;
  calories: ParsedField;
  nutrients: ParsedNutrient[];
  unparsed_lines: Array<{ id: string; text: string; source_observation_ids: string[]; confidence: number; reason: string | null }>;
  warnings: Array<{ code: string; message: string; source_observation_ids: string[] }>;
  parser_version: string;
};

export type ReviewDecision = "accepted" | "edited" | "omitted" | "unresolved";
export type ConfirmationField = {
  fieldKey: string;
  nutrientId: string | null;
  label: string;
  suggestedValue: string | null;
  confirmedValue: string;
  unit: string | null;
  decision: ReviewDecision;
  parseStatus: ParseStatus;
  comparison: "less_than" | null;
  confidence: number;
  sourceText: string;
  sourceObservationIds: string[];
  warningCodes: string[];
  resolution: string | null;
};
export type UnknownNutrientDraft = {
  originalName: string;
  sourceText: string;
  sourceObservationIds: string[];
  warningCodes: string[];
  dismissed: boolean;
};
export type NutritionConfirmationDraft = {
  parserVersion: string;
  imageSourceType: "camera" | "photo_library";
  name: string;
  brand: string;
  notes: string;
  servingDisplay: string;
  servingQuantity: string;
  servingUnit: string;
  gramWeight: string;
  servingProvenance: {
    display: ParsedField | null;
    quantity: ParsedField | null;
    unit: ParsedField | null;
    gramWeight: ParsedField | null;
  };
  calories: ConfirmationField;
  nutrients: ConfirmationField[];
  unknownNutrients: UnknownNutrientDraft[];
  parserWarningCodes: string[];
};

export type TraceFieldDecisionInput = {
  field_key: string;
  nutrient_id: string | null;
  suggested_value: string | null;
  confirmed_value: string | null;
  unit: string | null;
  decision: Exclude<ReviewDecision, "unresolved">;
  parse_status: ParseStatus;
  comparison: "less_than" | null;
  confidence: string;
  source_text: string;
  source_observation_ids: string[];
  warning_codes: string[];
  resolution: string | null;
};
export type OcrConfirmationInput = {
  parser_version: string;
  image_source_type: "camera" | "photo_library";
  client_request_id: string;
  food: FoodMutationInput;
  field_decisions: TraceFieldDecisionInput[];
  unknown_nutrients: Array<{
    original_name: string;
    source_text: string;
    source_observation_ids: string[];
    warning_codes: string[];
    decision: "dismissed";
  }>;
  parser_warning_codes: string[];
};
export type OcrConfirmationResponse = { food: Food; trace_id: string };

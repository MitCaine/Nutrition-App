import type { FoodMutationInput } from "../../foods/api/types";
import type { NutrientUnit } from "../../../shared/nutrition/types";
import type {
  ConfirmationField, NutritionConfirmationDraft, OcrConfirmationInput,
  ParsedField, ParsedNutritionLabel, ReviewDecision,
} from "../api/types";

const NUTRIENT_LABELS: Record<string, string> = {
  calories: "Calories", total_fat: "Total Fat", saturated_fat: "Saturated Fat",
  trans_fat: "Trans Fat", cholesterol: "Cholesterol", sodium: "Sodium",
  total_carbohydrate: "Total Carbohydrate", dietary_fiber: "Dietary Fiber",
  total_sugars: "Total Sugars", added_sugars: "Added Sugars", protein: "Protein",
  vitamin_d: "Vitamin D", calcium: "Calcium", iron: "Iron", potassium: "Potassium", magnesium: "Magnesium",
};

function stringValue(field: ParsedField | null | undefined): string {
  return typeof field?.value === "string" ? field.value : typeof field?.value === "number" ? String(field.value) : "";
}

function initialDecision(field: ParsedField, forceReview = false): ReviewDecision {
  if (field.status === "missing" || field.status === "unsupported") return "omitted";
  if (forceReview || field.status === "ambiguous" || field.comparison || field.confidence < 0.8) return "unresolved";
  return "accepted";
}

function confirmationField(fieldKey: string, nutrientId: string | null, label: string, field: ParsedField, unit: string | null, forceReview = false): ConfirmationField {
  const value = stringValue(field);
  return {
    fieldKey, nutrientId, label, suggestedValue: value || null, confirmedValue: value,
    unit, decision: initialDecision(field, forceReview), parseStatus: field.status,
    comparison: field.comparison, confidence: field.confidence, sourceText: field.source_text,
    sourceObservationIds: field.source_observation_ids, warningCodes: field.warning_codes,
    resolution: null,
  };
}

export function draftFromParsedLabel(parsed: ParsedNutritionLabel, imageSourceType: "camera" | "photo_library"): NutritionConfirmationDraft {
  const calories = confirmationField("nutrient.calories", "calories", "Calories", parsed.calories, "kcal", true);
  const canonical = parsed.nutrients.filter((item) => item.nutrient_id).map((item) =>
    confirmationField(`nutrient.${item.nutrient_id}`, item.nutrient_id, NUTRIENT_LABELS[item.nutrient_id as string] ?? item.original_name, item.amount, stringValue(item.unit) || null),
  );
  return {
    parserVersion: parsed.parser_version, imageSourceType, name: "", brand: "", notes: "",
    servingDisplay: stringValue(parsed.serving?.serving_size_display),
    servingQuantity: stringValue(parsed.serving?.serving_quantity) || "1",
    servingUnit: stringValue(parsed.serving?.serving_unit) || "serving",
    gramWeight: stringValue(parsed.serving?.gram_weight), calories, nutrients: canonical,
    servingProvenance: {
      display: parsed.serving?.serving_size_display ?? null,
      quantity: parsed.serving?.serving_quantity ?? null,
      unit: parsed.serving?.serving_unit ?? null,
      gramWeight: parsed.serving?.gram_weight ?? null,
    },
    unknownNutrients: parsed.nutrients.filter((item) => !item.nutrient_id).map((item) => ({
      originalName: item.original_name, sourceText: item.amount.source_text,
      sourceObservationIds: item.source_observation_ids, warningCodes: item.warning_codes, dismissed: false,
    })),
    parserWarningCodes: parsed.warnings.map((warning) => warning.code),
  };
}

export function updateReview(field: ConfirmationField, value: string, decision?: ReviewDecision): ConfirmationField {
  const changed = value !== (field.suggestedValue ?? "");
  return { ...field, confirmedValue: value, decision: decision ?? (changed ? "edited" : "accepted"), resolution: field.parseStatus === "ambiguous" || field.comparison ? (changed ? "entered exact value" : "selected suggestion") : field.resolution };
}

export function confirmationValidationError(draft: NutritionConfirmationDraft): string | null {
  if (!draft.name.trim()) return "Food name is required.";
  const grams = Number(draft.gramWeight);
  if (!Number.isFinite(grams) || grams <= 0) return "Enter a positive gram weight for the label serving.";
  const fields = [draft.calories, ...draft.nutrients];
  if (fields.some((field) => field.decision === "unresolved")) return "Review every flagged or ambiguous value before creating the Food.";
  if (draft.unknownNutrients.some((item) => !item.dismissed)) return "Dismiss each unknown nutrient after reviewing its source text.";
  for (const field of fields) {
    if (field.decision !== "omitted" && (!field.confirmedValue || !Number.isFinite(Number(field.confirmedValue)) || Number(field.confirmedValue) < 0)) {
      return `${field.label} must be a nonnegative number or omitted.`;
    }
    if (field.comparison === "less_than" && field.decision === "accepted") return `${field.label} is a less-than value; enter an exact replacement or omit it.`;
  }
  return null;
}

function retainedNutrient(field: ConfirmationField) {
  if (field.decision === "omitted" || !field.nutrientId) return null;
  const amount = field.confirmedValue;
  return {
    nutrient_id: field.nutrientId, amount, unit: field.unit as NutrientUnit,
    basis: "per_serving" as const, data_status: Number(amount) === 0 ? "zero" as const : "known" as const,
  };
}

export function confirmationPayload(draft: NutritionConfirmationDraft, clientRequestId: string): OcrConfirmationInput | null {
  if (confirmationValidationError(draft)) return null;
  const fields = [draft.calories, ...draft.nutrients];
  const nutrients = fields.map(retainedNutrient).filter((value): value is NonNullable<typeof value> => Boolean(value));
  const grams = draft.gramWeight;
  const servingLabel = draft.servingDisplay || `${draft.servingQuantity} ${draft.servingUnit}`;
  const food: FoodMutationInput = {
    name: draft.name.trim(), brand: draft.brand.trim() || null, notes: draft.notes.trim() || null,
    serving_definitions: [
      { label: "100 g", quantity: "100", unit: "g", gram_weight: "100", is_default: false },
      { label: servingLabel, quantity: draft.servingQuantity || "1", unit: draft.servingUnit || "serving", gram_weight: grams, is_default: true },
    ],
    nutrients,
  };
  const basicDecision = (fieldKey: string, confirmedValue: string | null, suggested: ParsedField | null, unit: string | null = null) => {
    const suggestedValue = suggested ? stringValue(suggested) || null : null;
    const omitted = confirmedValue === null || confirmedValue === "";
    return {
      field_key: fieldKey, nutrient_id: null, suggested_value: suggestedValue,
      confirmed_value: omitted ? null : confirmedValue, unit,
      decision: omitted ? "omitted" as const : confirmedValue === suggestedValue ? "accepted" as const : "edited" as const,
      parse_status: suggested?.status ?? "missing" as const, comparison: suggested?.comparison ?? null,
      confidence: String(suggested?.confidence ?? 0), source_text: suggested?.source_text ?? "",
      source_observation_ids: suggested?.source_observation_ids ?? [], warning_codes: suggested?.warning_codes ?? [],
      resolution: suggested?.status === "ambiguous" || suggested?.comparison ? "confirmed during review" : null,
    };
  };
  return {
    parser_version: draft.parserVersion, image_source_type: draft.imageSourceType,
    client_request_id: clientRequestId, food,
    field_decisions: [
      basicDecision("food.name", draft.name.trim(), null),
      basicDecision("food.brand", draft.brand.trim() || null, null),
      basicDecision("food.notes", draft.notes.trim() || null, null),
      basicDecision("serving.display", servingLabel, draft.servingProvenance.display),
      basicDecision("serving.quantity", draft.servingQuantity, draft.servingProvenance.quantity),
      basicDecision("serving.unit", draft.servingUnit, draft.servingProvenance.unit),
      basicDecision("serving.gram_weight", grams, draft.servingProvenance.gramWeight, "g"),
      ...fields.map((field) => ({
      field_key: field.fieldKey, nutrient_id: field.nutrientId,
      suggested_value: field.suggestedValue, confirmed_value: field.decision === "omitted" ? null : field.confirmedValue,
      unit: field.unit, decision: field.decision as Exclude<ReviewDecision, "unresolved">,
      parse_status: field.parseStatus, comparison: field.comparison, confidence: String(field.confidence),
      source_text: field.sourceText, source_observation_ids: field.sourceObservationIds,
      warning_codes: field.warningCodes, resolution: field.resolution,
      })),
    ],
    unknown_nutrients: draft.unknownNutrients.map((item) => ({
      original_name: item.originalName, source_text: item.sourceText,
      source_observation_ids: item.sourceObservationIds, warning_codes: item.warningCodes, decision: "dismissed" as const,
    })),
    parser_warning_codes: draft.parserWarningCodes,
  };
}

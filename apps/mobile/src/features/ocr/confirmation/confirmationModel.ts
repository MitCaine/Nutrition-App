import type { FoodMutationInput, NutrientDefinition } from "../../foods/api/types";
import type { NutrientUnit } from "../../../shared/nutrition/types";
import type {
  ConfirmationField, NutritionConfirmationDraft, OcrConfirmationInput,
  ParsedField, ParsedNutritionLabel, ReviewDecision,
} from "../api/types";
import { isPositiveDecimalString, isUnsignedDecimalString, isZeroDecimalString } from "../../../shared/forms/decimalString";
import { nutrientAmountValidationMessage } from "../../../shared/nutrition/nutrientAmount";

const NUTRIENT_LABELS: Record<string, string> = {
  calories: "Calories", total_fat: "Total Fat", saturated_fat: "Saturated Fat",
  trans_fat: "Trans Fat", cholesterol: "Cholesterol", sodium: "Sodium",
  total_carbohydrate: "Total Carbohydrate", dietary_fiber: "Dietary Fiber",
  total_sugars: "Total Sugars", added_sugars: "Added Sugars", protein: "Protein",
  vitamin_d: "Vitamin D", calcium: "Calcium", iron: "Iron", potassium: "Potassium", magnesium: "Magnesium",
};

const MANUAL_ADD_RESOLUTION = "manually added because OCR did not provide it";

function stringValue(field: ParsedField | null | undefined): string {
  return typeof field?.value === "string" ? field.value : typeof field?.value === "number" ? String(field.value) : "";
}

function initialDecision(field: ParsedField): ReviewDecision {
  if (field.status !== "parsed" || field.comparison || field.confidence < 0.8) return "unresolved";
  return "accepted";
}

function confirmationField(fieldKey: string, nutrientId: string | null, label: string, field: ParsedField, unit: string | null): ConfirmationField {
  const value = stringValue(field);
  return {
    fieldKey, nutrientId, label, suggestedValue: value || null, confirmedValue: value,
    unit, decision: initialDecision(field), parseStatus: field.status,
    comparison: field.comparison, confidence: field.confidence, sourceText: field.source_text,
    sourceObservationIds: field.source_observation_ids, warningCodes: field.warning_codes,
    resolution: null,
  };
}

function canonicalReviewFields(parsed: ParsedNutritionLabel): ConfirmationField[] {
  const candidatesById = new Map<string, ParsedNutritionLabel["nutrients"]>();
  for (const candidate of parsed.nutrients) {
    if (!candidate.nutrient_id) continue;
    const candidates = candidatesById.get(candidate.nutrient_id) ?? [];
    candidates.push(candidate);
    candidatesById.set(candidate.nutrient_id, candidates);
  }
  return [...candidatesById].map(([nutrientId, candidates]) => {
    const first = candidates[0]!;
    const label = NUTRIENT_LABELS[nutrientId] ?? first.original_name;
    if (candidates.length === 1) {
      const unit = first.unit.status === "parsed" ? stringValue(first.unit) || null : null;
      const reviewField = confirmationField(`nutrient.${nutrientId}`, nutrientId, label, first.amount, unit);
      return {
        ...reviewField,
        decision: unit && first.status === "parsed" ? reviewField.decision : "unresolved",
        parseStatus: first.status,
        confidence: first.confidence,
        sourceObservationIds: [...new Set([
          ...first.amount.source_observation_ids,
          ...first.unit.source_observation_ids,
          ...first.source_observation_ids,
        ])],
        warningCodes: [...new Set([
          ...first.amount.warning_codes,
          ...first.unit.warning_codes,
          ...first.warning_codes,
        ])],
      };
    }
    const units = [...new Set(candidates
      .filter((candidate) => candidate.unit.status === "parsed")
      .map((candidate) => stringValue(candidate.unit))
      .filter(Boolean))];
    return {
      fieldKey: `nutrient.${nutrientId}`,
      nutrientId,
      label,
      suggestedValue: null,
      confirmedValue: "",
      unit: units.length === 1 ? units[0]! : null,
      decision: "unresolved",
      parseStatus: "ambiguous",
      comparison: null,
      confidence: Math.min(...candidates.map((candidate) => Math.min(candidate.confidence, candidate.amount.confidence, candidate.unit.confidence))),
      sourceText: [...new Set(candidates.map((candidate) => candidate.amount.source_text).filter(Boolean))].join(" | "),
      sourceObservationIds: [...new Set(candidates.flatMap((candidate) => [
        ...candidate.source_observation_ids,
        ...candidate.amount.source_observation_ids,
        ...candidate.unit.source_observation_ids,
      ]))],
      warningCodes: [...new Set(["conflicting_nutrient_values", ...candidates.flatMap((candidate) => [
        ...candidate.warning_codes,
        ...candidate.amount.warning_codes,
        ...candidate.unit.warning_codes,
      ])])],
      resolution: null,
    };
  });
}

export function draftFromParsedLabel(parsed: ParsedNutritionLabel, imageSourceType: "camera" | "photo_library"): NutritionConfirmationDraft {
  const calories = confirmationField("nutrient.calories", "calories", "Calories", parsed.calories, "kcal");
  const canonical = canonicalReviewFields(parsed);
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

export function hydrateCanonicalNutrientUnits(
  draft: NutritionConfirmationDraft,
  nutrients: readonly NutrientDefinition[],
): NutritionConfirmationDraft {
  const definitionsById = new Map(nutrients.map((nutrient) => [nutrient.id, nutrient]));
  const hydrateField = (field: ConfirmationField): ConfirmationField => {
    if (!field.nutrientId) return field;
    const definition = definitionsById.get(field.nutrientId);
    if (!definition || field.unit === definition.default_unit) return field;
    return { ...field, unit: definition.default_unit };
  };
  const calories = hydrateField(draft.calories);
  let nutrientsChanged = false;
  const hydratedNutrients = draft.nutrients.map((field) => {
    const hydrated = hydrateField(field);
    if (hydrated !== field) nutrientsChanged = true;
    return hydrated;
  });
  return calories === draft.calories && !nutrientsChanged
    ? draft
    : { ...draft, calories, nutrients: hydratedNutrients };
}

export function updateReview(field: ConfirmationField, value: string, decision?: ReviewDecision): ConfirmationField {
  const changed = value !== (field.suggestedValue ?? "");
  const nextDecision = decision ?? (changed ? "edited" : "accepted");
  if (field.comparison === "less_than" && !changed && nextDecision === "accepted") {
    return { ...field, confirmedValue: value, decision: "unresolved", resolution: null };
  }
  const manuallyAdded = field.resolution === MANUAL_ADD_RESOLUTION;
  const reviewed = field.decision === "unresolved"
    || field.decision === "omitted"
    || field.parseStatus !== "parsed"
    || field.confidence < 0.8
    || Boolean(field.comparison);
  return {
    ...field,
    confirmedValue: value,
    decision: nextDecision,
    resolution: manuallyAdded
      ? field.resolution
      : reviewed
        ? (changed ? "entered exact value after review" : "accepted OCR suggestion after review")
        : field.resolution,
  };
}

export function omitReview(field: ConfirmationField): ConfirmationField {
  return {
    ...field,
    confirmedValue: "",
    decision: "omitted",
    resolution: field.resolution === MANUAL_ADD_RESOLUTION
      ? MANUAL_ADD_RESOLUTION
      : "explicitly omitted after review",
  };
}

export function addManualNutrient(
  draft: NutritionConfirmationDraft,
  nutrient: NutrientDefinition,
): NutritionConfirmationDraft {
  const existingIds = new Set([draft.calories.nutrientId, ...draft.nutrients.map(({ nutrientId }) => nutrientId)]);
  if (existingIds.has(nutrient.id)) return draft;
  return {
    ...draft,
    nutrients: [...draft.nutrients, {
      fieldKey: `nutrient.${nutrient.id}`,
      nutrientId: nutrient.id,
      label: nutrient.display_name,
      suggestedValue: null,
      confirmedValue: "",
      unit: nutrient.default_unit,
      decision: "unresolved",
      parseStatus: "missing",
      comparison: null,
      confidence: 0,
      sourceText: "",
      sourceObservationIds: [],
      warningCodes: [],
      resolution: MANUAL_ADD_RESOLUTION,
    }],
  };
}

export type ConfirmationValidationIssue = Readonly<{
  message: string;
  fieldKey: string | null;
}>;

export function confirmationValidationIssues(draft: NutritionConfirmationDraft): ConfirmationValidationIssue[] {
  const issues: ConfirmationValidationIssue[] = [];
  if (!draft.name.trim()) issues.push({ message: "Food name is required.", fieldKey: "food.name" });
  if (!isPositiveDecimalString(draft.servingQuantity)) {
    issues.push({ message: "Serving quantity must be a positive number.", fieldKey: "serving.quantity" });
  }
  if (!isPositiveDecimalString(draft.gramWeight)) {
    issues.push({ message: "Serving grams must be a positive number.", fieldKey: "serving.gram_weight" });
  }
  const fields = [draft.calories, ...draft.nutrients];
  for (const field of fields) {
    if (field.decision === "unresolved") {
      issues.push({
        message: `${field.label} requires review: enter a value, accept the OCR suggestion, or explicitly omit it.`,
        fieldKey: field.fieldKey,
      });
      continue;
    }
    if (field.decision === "omitted") continue;
    if (!isUnsignedDecimalString(field.confirmedValue)) {
      issues.push({ message: `${field.label} must be a nonnegative number.`, fieldKey: field.fieldKey });
      continue;
    }
    const exactAmountError = nutrientAmountValidationMessage(field.confirmedValue);
    if (exactAmountError) {
      issues.push({ message: `${field.label}: ${exactAmountError}`, fieldKey: field.fieldKey });
      continue;
    }
    if (!field.unit) {
      issues.push({ message: `${field.label} requires a canonical nutrient unit.`, fieldKey: field.fieldKey });
      continue;
    }
    if (field.comparison === "less_than" && field.decision === "accepted") {
      issues.push({ message: `${field.label} is a less-than value; enter an exact replacement or omit it.`, fieldKey: field.fieldKey });
    }
  }
  if (draft.unknownNutrients.some((item) => !item.dismissed)) {
    issues.push({ message: "Dismiss each unknown nutrient after reviewing its source text.", fieldKey: null });
  }
  return issues;
}

export function confirmationValidationIssue(draft: NutritionConfirmationDraft): ConfirmationValidationIssue | null {
  return confirmationValidationIssues(draft)[0] ?? null;
}

export function confirmationValidationError(draft: NutritionConfirmationDraft): string | null {
  return confirmationValidationIssue(draft)?.message ?? null;
}

function retainedNutrient(field: ConfirmationField) {
  if ((field.decision !== "accepted" && field.decision !== "edited") || !field.nutrientId) return null;
  const amount = field.confirmedValue;
  return {
    nutrient_id: field.nutrientId, amount, unit: field.unit as NutrientUnit,
    basis: "per_serving" as const, data_status: isZeroDecimalString(amount) ? "zero" as const : "known" as const,
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

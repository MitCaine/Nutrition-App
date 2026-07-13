import { useMemo, useState } from "react";

import type {
  Food,
  FoodMutationInput,
  FoodNutrientInput,
  NutrientDefinition,
  ServingDefinitionInput,
} from "../api/types";
import { formatDisplayNumber } from "../../../shared/nutrition/display";
import { foodMutationSchema, validationMessage } from "../validation/foodValidation";
import {
  applyAmountPatch,
  amountHasKnownGramWeight,
  canonicalBaseAmount,
  dedupeCanonicalBaseAmounts,
  generatedAmountLabel,
  isCanonicalBaseAmount,
  repairDuplicateAmountKeys,
  repairLegacyStructuredAmount,
  type AmountFormValue,
  DEFAULT_AMOUNT_WEIGHT_MESSAGE,
} from "../utils/amountForm";

export type ServingFormValue = AmountFormValue;
type InitialServing = ServingDefinitionInput & { id?: string };
let nextClientServingId = 0;

export function createClientServingKey(): string {
  const key = `client-serving-${nextClientServingId}`;
  nextClientServingId += 1;
  return key;
}

export function updateServingValues(
  servings: ServingFormValue[],
  key: string,
  patch: Partial<ServingFormValue>,
): ServingFormValue[] {
  return servings.map((serving) => {
    if (serving.key === key) {
      return applyAmountPatch(serving, {
        ...patch,
        is_default: patch.is_default ? true : patch.is_default ?? serving.is_default,
      });
    }
    if (patch.is_default && serving.is_default) {
      return { ...serving, is_default: false };
    }
    return serving;
  });
}

export function formatServingFormNumber(value: string | number | null | undefined): string {
  return value == null || value === "" ? "" : formatDisplayNumber(value, { useGrouping: false });
}

export function servingPayloadNumber(displayValue: string, originalValue?: string): string {
  return originalValue && displayValue === formatServingFormNumber(originalValue) ? originalValue : displayValue;
}

export function formatNutrientFormNumber(value: string | number | null | undefined): string | null {
  return value == null || value === "" ? null : formatDisplayNumber(value, { useGrouping: false });
}

export function nutrientPayloadNumber(displayValue: string | null | undefined, originalValue?: string | number | null): string | null {
  if (displayValue == null || displayValue === "") return null;
  if (originalValue == null) return displayValue;
  return displayValue === formatNutrientFormNumber(originalValue) ? String(originalValue) : displayValue;
}

export function useFoodForm(food: Food | undefined, nutrients: NutrientDefinition[]) {
  const [name, setName] = useState(food?.name ?? "");
  const [brand, setBrand] = useState(food?.brand ?? "");
  const [notes, setNotes] = useState(food?.notes ?? "");
  const [error, setError] = useState<string | null>(null);
  const [invalidServingKey, setInvalidServingKey] = useState<string | null>(null);
  const [defaultAmountError, setDefaultAmountError] = useState<{ key: string; message: string } | null>(null);
  const [servings, setServings] = useState<ServingFormValue[]>(() => {
    const source: InitialServing[] = food?.serving_definitions.length ? food.serving_definitions : [];
    let mapped: ServingFormValue[] = source.map((serving) => {
      const quantity = String(serving.quantity);
      const gramWeight = serving.gram_weight == null ? "" : String(serving.gram_weight);
      const displayQuantity = formatServingFormNumber(quantity);
      const displayGramWeight = formatServingFormNumber(gramWeight);
      const isBaseAmount = isCanonicalBaseAmount(serving);
      return repairLegacyStructuredAmount({
        key: serving.id ?? createClientServingKey(),
        label: isBaseAmount ? "100 g" : serving.label,
        quantity: isBaseAmount ? "100" : displayQuantity,
        unit: isBaseAmount ? "g" : serving.unit,
        gram_weight: isBaseAmount ? "100" : displayGramWeight,
        is_default: serving.is_default,
        isBaseAmount,
        labelMode: isBaseAmount || serving.label.trim() === generatedAmountLabel(displayQuantity, serving.unit) ? "automatic" as const : "manual" as const,
        originalQuantity: quantity,
        originalGramWeight: gramWeight,
      });
    });
    mapped = dedupeCanonicalBaseAmounts(repairDuplicateAmountKeys(mapped, createClientServingKey));
    if (!mapped.some((serving) => serving.isBaseAmount)) {
      mapped.unshift(canonicalBaseAmount(createClientServingKey(), !mapped.some((serving) => serving.is_default)));
    }
    if (mapped.length === 1) {
      mapped.push({
        key: createClientServingKey(), label: "1 serving", quantity: "1", unit: "serving", gram_weight: "",
        is_default: false, isBaseAmount: false, labelMode: "automatic",
      });
    }
    return mapped;
  });
  const [values, setValues] = useState<FoodNutrientInput[]>(() => {
    if (!food) {
      return [];
    }
    return food.nutrients.map((nutrient) => ({
      nutrient_id: nutrient.nutrient_id,
      amount: formatNutrientFormNumber(nutrient.amount),
      unit: nutrient.unit,
      basis: nutrient.basis,
      data_status: nutrient.data_status,
    }));
  });

  const mergedValues = useMemo<FoodNutrientInput[]>(() => {
    const existing = new Map(values.map((value) => [value.nutrient_id, value]));
    return nutrients.map((nutrient) => {
      const emptyValue: FoodNutrientInput = {
        nutrient_id: nutrient.id,
        amount: null,
        unit: nutrient.default_unit,
        basis: "per_serving",
        data_status: "unknown",
      };
      return existing.get(nutrient.id) ?? emptyValue;
    });
  }, [nutrients, values]);

  function updateServing(key: string, patch: Partial<ServingFormValue>) {
    const target = servings.find((serving) => serving.key === key);
    if (patch.is_default && target && !target.isBaseAmount && !amountHasKnownGramWeight(target)) {
      setDefaultAmountError({ key, message: DEFAULT_AMOUNT_WEIGHT_MESSAGE });
      setInvalidServingKey(key);
      return;
    }
    if (defaultAmountError?.key === key) setDefaultAmountError(null);
    setInvalidServingKey(null);
    setServings((current) => updateServingValues(current, key, patch));
  }

  function addServing(): string {
    const key = createClientServingKey();
    setServings((current) => [
      ...current,
      { key, label: "1 serving", quantity: "1", unit: "serving", gram_weight: "", is_default: false, isBaseAmount: false, labelMode: "automatic" },
    ]);
    return key;
  }

  function removeServing(key: string) {
    if (defaultAmountError?.key === key) setDefaultAmountError(null);
    setServings((current) => {
      if (current.find((serving) => serving.key === key)?.isBaseAmount) {
        return current;
      }
      if (current.length === 1) {
        return current;
      }
      const next = current.filter((serving) => serving.key !== key);
      if (!next.some((serving) => serving.is_default)) {
        next[0] = { ...next[0], is_default: true };
      }
      return next;
    });
  }

  function buildPayload(): FoodMutationInput | null {
    const input: FoodMutationInput = {
      name,
      brand: brand || null,
      notes: notes || null,
      serving_definitions: servings.map((serving) => {
        const { key: _key, originalQuantity, originalGramWeight, isBaseAmount: _isBaseAmount, labelMode: _labelMode, consistencyWarning: _consistencyWarning, ...payloadServing } = serving;
        return {
          ...payloadServing,
          quantity:
            originalQuantity ? servingPayloadNumber(payloadServing.quantity, originalQuantity) : payloadServing.quantity,
          gram_weight:
            originalGramWeight && payloadServing.gram_weight
              ? servingPayloadNumber(payloadServing.gram_weight, originalGramWeight)
              : payloadServing.gram_weight || null,
        };
      }),
      nutrients: mergedValues.map((nutrient) => ({
        ...nutrient,
        amount: nutrientPayloadNumber(
          nutrient.amount,
          food?.nutrients.find((original) => original.nutrient_id === nutrient.nutrient_id)?.amount,
        ),
      })),
    };
    const parsed = foodMutationSchema.safeParse(input);
    if (!parsed.success) {
      const servingIndex = parsed.error.issues.map((issue) => issue.path).find((path) => path[0] === "serving_definitions" && typeof path[1] === "number")?.[1];
      setInvalidServingKey(typeof servingIndex === "number" ? servings[servingIndex]?.key ?? null : null);
      setError(validationMessage(parsed.error));
      return null;
    }
    setError(null);
    setInvalidServingKey(null);
    return parsed.data;
  }

  return {
    fields: { name, brand, notes },
    setters: { setName, setBrand, setNotes },
    servings,
    updateServing,
    addServing,
    removeServing,
    nutrients: mergedValues,
    setNutrients: setValues,
    error,
    invalidServingKey,
    defaultAmountError,
    buildPayload,
  };
}

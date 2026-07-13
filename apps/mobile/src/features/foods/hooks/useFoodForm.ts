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

export type ServingFormValue = ServingDefinitionInput & {
  key: string;
  originalQuantity?: string;
  originalGramWeight?: string;
};
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
      return {
        ...serving,
        ...patch,
        is_default: patch.is_default ? true : patch.is_default ?? serving.is_default,
      };
    }
    if (patch.is_default && serving.is_default) {
      return { ...serving, is_default: false };
    }
    return serving;
  });
}

export function formatServingFormNumber(value: string | number | null | undefined): string {
  return value == null || value === "" ? "" : formatDisplayNumber(value);
}

export function servingPayloadNumber(displayValue: string, originalValue?: string): string {
  return originalValue && displayValue === formatServingFormNumber(originalValue) ? originalValue : displayValue;
}

export function useFoodForm(food: Food | undefined, nutrients: NutrientDefinition[]) {
  const [name, setName] = useState(food?.name ?? "");
  const [brand, setBrand] = useState(food?.brand ?? "");
  const [notes, setNotes] = useState(food?.notes ?? "");
  const [error, setError] = useState<string | null>(null);
  const [servings, setServings] = useState<ServingFormValue[]>(() => {
    const source: InitialServing[] = food?.serving_definitions.length
      ? food.serving_definitions
      : [{ label: "1 serving", quantity: "1", unit: "serving", gram_weight: null, is_default: true }];
    return source.map((serving) => {
      const quantity = String(serving.quantity);
      const gramWeight = serving.gram_weight == null ? "" : String(serving.gram_weight);
      return {
        key: serving.id ?? createClientServingKey(),
        label: serving.label,
        quantity: formatServingFormNumber(quantity),
        unit: serving.unit,
        gram_weight: formatServingFormNumber(gramWeight),
        is_default: serving.is_default,
        originalQuantity: quantity,
        originalGramWeight: gramWeight,
      };
    });
  });
  const [values, setValues] = useState<FoodNutrientInput[]>(() => {
    if (!food) {
      return [];
    }
    return food.nutrients.map((nutrient) => ({
      nutrient_id: nutrient.nutrient_id,
      amount: nutrient.amount == null ? null : String(nutrient.amount),
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
    setServings((current) => updateServingValues(current, key, patch));
  }

  function addServing() {
    setServings((current) => [
      ...current,
      { key: createClientServingKey(), label: "1 serving", quantity: "1", unit: "serving", gram_weight: "", is_default: false },
    ]);
  }

  function removeServing(key: string) {
    setServings((current) => {
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
        const { key: _key, originalQuantity, originalGramWeight, ...payloadServing } = serving;
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
      nutrients: mergedValues,
    };
    const parsed = foodMutationSchema.safeParse(input);
    if (!parsed.success) {
      setError(validationMessage(parsed.error));
      return null;
    }
    setError(null);
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
    buildPayload,
  };
}

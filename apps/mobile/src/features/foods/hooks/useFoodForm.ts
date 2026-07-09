import { useMemo, useRef, useState } from "react";

import type {
  Food,
  FoodMutationInput,
  FoodNutrientInput,
  NutrientDefinition,
  ServingDefinitionInput,
} from "../api/types";
import { foodMutationSchema, validationMessage } from "../validation/foodValidation";

export type ServingFormValue = ServingDefinitionInput & { key: string };
type InitialServing = ServingDefinitionInput & { id?: string };

export function useFoodForm(food: Food | undefined, nutrients: NutrientDefinition[]) {
  const servingKeyCounter = useRef(0);
  function nextServingKey() {
    const key = `serving-${servingKeyCounter.current}`;
    servingKeyCounter.current += 1;
    return key;
  }
  const [name, setName] = useState(food?.name ?? "");
  const [brand, setBrand] = useState(food?.brand ?? "");
  const [notes, setNotes] = useState(food?.notes ?? "");
  const [error, setError] = useState<string | null>(null);
  const [servings, setServings] = useState<ServingFormValue[]>(() => {
    const source: InitialServing[] = food?.serving_definitions.length
      ? food.serving_definitions
      : [{ label: "1 serving", quantity: "1", unit: "serving", gram_weight: null, is_default: true }];
    return source.map((serving, index) => ({
      key: serving.id ?? `serving-new-${index}`,
      label: serving.label,
      quantity: String(serving.quantity),
      unit: serving.unit,
      gram_weight: serving.gram_weight == null ? "" : String(serving.gram_weight),
      is_default: serving.is_default,
    }));
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
    setServings((current) =>
      current.map((serving) =>
        serving.key === key
          ? {
              ...serving,
              ...patch,
              is_default: patch.is_default ? true : patch.is_default ?? serving.is_default,
            }
          : patch.is_default
            ? { ...serving, is_default: false }
            : serving,
      ),
    );
  }

  function addServing() {
    setServings((current) => [
      ...current,
      { key: nextServingKey(), label: "1 serving", quantity: "1", unit: "serving", gram_weight: "", is_default: false },
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
      serving_definitions: servings.map(({ key: _key, ...serving }) => ({
        ...serving,
        gram_weight: serving.gram_weight || null,
      })),
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

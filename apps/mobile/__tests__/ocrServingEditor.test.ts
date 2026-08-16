import React, { useState } from "react";
import { Pressable, Text, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { NutritionConfirmationDraft, ParsedField } from "../src/features/ocr/api/types";
import { OcrServingEditor } from "../src/features/ocr/components/OcrServingEditor";
import { confirmationPayload } from "../src/features/ocr/confirmation/confirmationModel";

const focusProps = () => ({ ref: () => undefined, onFocus: () => undefined });

type ServingValue = Pick<
  NutritionConfirmationDraft,
  "servingDisplay" | "servingQuantity" | "servingUnit" | "gramWeight"
>;

function Harness({ initial, onPatch = jest.fn() }: { initial: ServingValue; onPatch?: jest.Mock }) {
  const [value, setValue] = useState(initial);
  return React.createElement(OcrServingEditor, {
    value,
    focusProps,
    onChange: (patch) => {
      onPatch(patch);
      setValue((current) => ({ ...current, ...patch }));
    },
  });
}

function input(root: TestRenderer.ReactTestInstance, label: string) {
  return root.findAllByType(TextInput).find((node) => node.props.accessibilityLabel === label)!;
}

function action(root: TestRenderer.ReactTestInstance, label: string) {
  return root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === label)!;
}

function textValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(textValue).join("");
  return "";
}

function visibleText(root: TestRenderer.ReactTestInstance): string {
  return root.findAllByType(Text).map((node) => textValue(node.props.children)).join(" ");
}

test("OCR serving editor exposes total serving grams while deriving the per-unit equivalent", async () => {
  const onPatch = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(Harness, {
      initial: { servingDisplay: "2 cups (30g)", servingQuantity: "2", servingUnit: "cup", gramWeight: "30" },
      onPatch,
    }));
  });

  expect(input(renderer.root, "Serving grams").props.value).toBe("30");
  expect(input(renderer.root, "Serving grams").props.editable).toBe(true);
  expect(visibleText(renderer.root)).toContain("2 cups (30g)");
  expect(visibleText(renderer.root)).toContain("15 g per cup · 30 g total");
  expect(visibleText(renderer.root)).not.toContain("2 cups (30g) (30 g)");

  await act(async () => input(renderer.root, "Serving quantity").props.onChangeText("3"));
  expect(input(renderer.root, "Serving grams").props.value).toBe("45");
  expect(onPatch).toHaveBeenLastCalledWith({ servingQuantity: "3", gramWeight: "45" });
  expect(visibleText(renderer.root)).toContain("15 g per cup · 45 g total");
  expect(visibleText(renderer.root)).toContain("2 cups (30g)");
  expect(visibleText(renderer.root)).not.toContain("2 cups (30g) (45 g)");

  await act(async () => action(renderer.root, "Use automatic label for 2 cups (30g)").props.onPress());
  expect(onPatch).toHaveBeenLastCalledWith({ servingDisplay: "" });
  expect(visibleText(renderer.root)).toContain("3 cup (45 g)");
  await act(async () => renderer.unmount());
});

test("OCR serving editor accepts common fractions and normalizes them before persistence", async () => {
  const onPatch = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(Harness, {
      initial: { servingDisplay: "2/3 cup (55g)", servingQuantity: ".667", servingUnit: "cup", gramWeight: "55" },
      onPatch,
    }));
  });

  expect(input(renderer.root, "Serving quantity").props.value).toBe("2/3");
  expect(input(renderer.root, "Serving quantity").props.keyboardType).toBe("numbers-and-punctuation");
  expect(input(renderer.root, "Serving grams").props.value).toBe("55");
  expect(visibleText(renderer.root)).toContain("82.5 g per cup · 55 g total");
  expect(onPatch).toHaveBeenCalledWith({ servingQuantity: "0.666666667" });

  onPatch.mockClear();
  await act(async () => input(renderer.root, "Serving quantity").props.onChangeText("1"));
  expect(onPatch).toHaveBeenLastCalledWith({ servingQuantity: "1", gramWeight: "82.5" });
  expect(input(renderer.root, "Serving grams").props.value).toBe("82.5");

  await act(async () => input(renderer.root, "Serving quantity").props.onChangeText("2/3"));
  expect(onPatch).toHaveBeenLastCalledWith({ servingQuantity: "0.666666667", gramWeight: "55" });
  expect(input(renderer.root, "Serving grams").props.value).toBe("55");
  await act(async () => renderer.unmount());
});

test("OCR serving editor recovers structured values from a clear serving display instead of retaining fallbacks", async () => {
  const onPatch = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(Harness, {
      initial: { servingDisplay: "2/3 cup (55 g)", servingQuantity: "1", servingUnit: "serving", gramWeight: "" },
      onPatch,
    }));
  });

  expect(onPatch).toHaveBeenCalledWith({
    servingQuantity: "0.666666667",
    servingUnit: "cup",
    gramWeight: "55",
  });
  expect(input(renderer.root, "Serving quantity").props.value).toBe("2/3");
  expect(input(renderer.root, "Serving grams").props.value).toBe("55");
  expect(visibleText(renderer.root)).toContain("82.5 g per cup · 55 g total");
  await act(async () => renderer.unmount());
});

test("OCR serving editor uses deterministic weight conversion and supports custom units", async () => {
  const onPatch = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(Harness, {
      initial: { servingDisplay: "", servingQuantity: "2", servingUnit: "cup", gramWeight: "30" },
      onPatch,
    }));
  });

  await act(async () => action(renderer.root, "Serving unit").props.onPress());
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "oz" }).props.onPress());
  expect(onPatch).toHaveBeenLastCalledWith({ servingUnit: "oz", gramWeight: "56.699046" });
  expect(input(renderer.root, "Serving grams").props.value).toBe("56.699046");
  expect(input(renderer.root, "Serving grams").props.editable).toBe(false);
  expect(visibleText(renderer.root)).toContain("56.7 g total");

  await act(async () => action(renderer.root, "Serving unit").props.onPress());
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Custom unit" }).props.onPress());
  await act(async () => input(renderer.root, "Custom unit name").props.onChangeText("scoop"));
  await act(async () => action(renderer.root, "Use custom unit scoop").props.onPress());
  expect(onPatch).toHaveBeenLastCalledWith({ servingUnit: "scoop", gramWeight: "" });
  expect(input(renderer.root, "Serving grams").props.editable).toBe(true);

  await act(async () => input(renderer.root, "Serving grams").props.onChangeText("30"));
  expect(onPatch).toHaveBeenLastCalledWith({ gramWeight: "30" });
  expect(visibleText(renderer.root)).toContain("15 g per scoop · 30 g total");
  expect(visibleText(renderer.root)).toContain("2 scoops (30 g)");
  await act(async () => renderer.unmount());
});

test("recognized weight units derive a missing total gram weight without overwriting an explicit OCR equivalent", async () => {
  const onPatch = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(Harness, {
      initial: { servingDisplay: "28 g", servingQuantity: "28", servingUnit: "g", gramWeight: "" },
      onPatch,
    }));
  });
  expect(onPatch).toHaveBeenCalledWith({ gramWeight: "28" });
  expect(input(renderer.root, "Serving grams").props.value).toBe("28");
  expect(input(renderer.root, "Serving grams").props.editable).toBe(false);
  await act(async () => renderer.unmount());

  onPatch.mockClear();
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(Harness, {
      initial: { servingDisplay: "1 oz (28g)", servingQuantity: "1", servingUnit: "oz", gramWeight: "28" },
      onPatch,
    }));
  });
  expect(onPatch).not.toHaveBeenCalled();
  expect(input(renderer.root, "Serving grams").props.value).toBe("28");
  expect(visibleText(renderer.root)).toContain("28 g per oz");
  await act(async () => renderer.unmount());
});

test("automatic OCR serving labels use shared pluralization and preserve serving provenance", () => {
  const parsedField = (value: string): ParsedField => ({
    value,
    comparison: null,
    source_text: `source ${value}`,
    source_observation_ids: [`obs-${value}`],
    confidence: 0.99,
    status: "parsed",
    warning_codes: [],
  });
  const draft: NutritionConfirmationDraft = {
    parserVersion: "nutrition_label_v1",
    imageSourceType: "photo_library",
    name: "Protein",
    brand: "Brand",
    notes: "",
    servingDisplay: "",
    servingQuantity: "2",
    servingUnit: "scoop",
    gramWeight: "30",
    servingProvenance: {
      display: parsedField("2 scoop"),
      quantity: parsedField("2"),
      unit: parsedField("scoop"),
      gramWeight: parsedField("30"),
    },
    calories: {
      fieldKey: "nutrient.calories",
      nutrientId: "calories",
      label: "Calories",
      suggestedValue: "120",
      confirmedValue: "120",
      unit: "kcal",
      decision: "accepted",
      parseStatus: "parsed",
      comparison: null,
      confidence: 0.99,
      sourceText: "Calories 120",
      sourceObservationIds: ["obs-calories"],
      warningCodes: [],
      resolution: null,
    },
    nutrients: [],
    unknownNutrients: [],
    parserWarningCodes: [],
  };

  const payload = confirmationPayload(draft, "request-1")!;
  expect(payload.food.serving_definitions[1]).toEqual(expect.objectContaining({
    label: "2 scoops",
    quantity: "2",
    unit: "scoop",
    gram_weight: "30",
  }));
  expect(payload.field_decisions).toContainEqual(expect.objectContaining({
    field_key: "serving.display",
    suggested_value: "2 scoop",
    confirmed_value: "2 scoops",
    decision: "edited",
    source_observation_ids: ["obs-2 scoop"],
  }));
  expect(payload.field_decisions).toContainEqual(expect.objectContaining({
    field_key: "serving.gram_weight",
    suggested_value: "30",
    confirmed_value: "30",
    decision: "accepted",
    unit: "g",
    source_observation_ids: ["obs-30"],
  }));
});

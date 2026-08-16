import React, { useState } from "react";
import { Pressable, Text, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { NutritionConfirmationDraft, ParsedField } from "../src/features/ocr/api/types";
import { OcrServingEditor } from "../src/features/ocr/components/OcrServingEditor";
import { confirmationPayload } from "../src/features/ocr/confirmation/confirmationModel";
import { servingConversionReviewMessage, UNCONVERTED_SERVING_UNIT_WARNING } from "../src/features/foods/utils/amountForm";

const focusProps = () => ({ ref: () => undefined, onFocus: () => undefined });

type ServingValue = Pick<
  NutritionConfirmationDraft,
  "servingDisplay" | "servingQuantity" | "servingUnit" | "gramWeight" | "servingReferenceQuantity" | "servingReferenceUnit" | "servingReferenceGramWeight"
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

function input(renderer: TestRenderer.ReactTestRenderer, label: string) {
  return renderer.root.findAllByType(TextInput).find((node) => node.props.accessibilityLabel === label)!;
}

function action(renderer: TestRenderer.ReactTestRenderer, label: string) {
  return renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === label)!;
}

function textValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(textValue).join("");
  return "";
}

function visibleText(renderer: TestRenderer.ReactTestRenderer): string {
  return renderer.root.findAllByType(Text).map((node) => textValue(node.props.children)).join(" ");
}

function chooseUnit(renderer: TestRenderer.ReactTestRenderer, unit: string) {
  renderer.root.findByProps({ accessibilityLabel: unit }).props.onPress();
}

async function mount(initial: ServingValue, onPatch = jest.fn()) {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(Harness, { initial, onPatch }));
  });
  return renderer;
}

test("OCR reference recovered from the label stays fixed while the representation converts", async () => {
  const onPatch = jest.fn();
  const renderer = await mount({ servingDisplay: "2/3 cup (55 g)", servingQuantity: "1", servingUnit: "serving", gramWeight: "" }, onPatch);

  expect(onPatch).toHaveBeenCalledWith(expect.objectContaining({
    servingQuantity: "0.666666667",
    servingUnit: "cup",
    gramWeight: "55",
    servingDisplay: "",
  }));
  expect(visibleText(renderer)).toContain("2/3 cup = 55 g");
  expect(visibleText(renderer)).toContain("82.5 g per cup · 55 g total");

  onPatch.mockClear();
  await act(async () => action(renderer, "Serving unit").props.onPress());
  await act(async () => chooseUnit(renderer, "tbsp"));
  expect(input(renderer, "Serving quantity").props.value).toBe("10 2/3");
  expect(visibleText(renderer)).toContain("10 2/3 Tbsp (55 g)");
  expect(visibleText(renderer)).toContain("5.2 g per Tbsp");
  expect(visibleText(renderer)).toContain("2/3 cup = 55 g");
  expect(onPatch).toHaveBeenLastCalledWith(expect.objectContaining({
    servingQuantity: "10.666666667",
    servingUnit: "tbsp",
    gramWeight: "55",
    servingReferenceQuantity: "0.666666667",
    servingReferenceUnit: "cup",
    servingReferenceGramWeight: "55",
  }));

  await act(async () => action(renderer, "Serving unit").props.onPress());
  await act(async () => chooseUnit(renderer, "cup"));
  expect(input(renderer, "Serving quantity").props.value).toBe("2/3");
  await act(async () => renderer.unmount());
});

test("OCR reference editing corrects the relationship and recalculates the representation", async () => {
  const onPatch = jest.fn();
  const renderer = await mount({ servingDisplay: "", servingQuantity: "2", servingUnit: "cup", gramWeight: "30" }, onPatch);
  expect(visibleText(renderer)).toContain("2 cups = 30 g");

  await act(async () => action(renderer, "Serving unit").props.onPress());
  await act(async () => chooseUnit(renderer, "tbsp"));
  expect(visibleText(renderer)).toContain("32 Tbsp (30 g)");

  await act(async () => action(renderer, "Edit reference measurement").props.onPress());
  await act(async () => input(renderer, "Reference grams").props.onChangeText("45"));
  await act(async () => action(renderer, "Confirm reference measurement").props.onPress());
  expect(onPatch).toHaveBeenLastCalledWith(expect.objectContaining({
    servingQuantity: "32", gramWeight: "45",
    servingReferenceQuantity: "2", servingReferenceUnit: "cup", servingReferenceGramWeight: "45",
  }));
  expect(visibleText(renderer)).toContain("2 cups = 45 g");
  expect(visibleText(renderer)).toContain("32 Tbsp (45 g)");
  await act(async () => renderer.unmount());
});

test("OCR refused conversions keep the reference for review and clear on explicit correction", async () => {
  const onPatch = jest.fn();
  const renderer = await mount({ servingDisplay: "", servingQuantity: "2", servingUnit: "cup", gramWeight: "30" }, onPatch);

  await act(async () => action(renderer, "Serving unit").props.onPress());
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Custom unit" }).props.onPress());
  await act(async () => input(renderer, "Custom unit name").props.onChangeText("scoop"));
  await act(async () => action(renderer, "Use custom unit scoop").props.onPress());

  expect(UNCONVERTED_SERVING_UNIT_WARNING).toBe("We couldn't convert this amount automatically. Check the quantity.");
  expect(visibleText(renderer)).toContain(servingConversionReviewMessage("scoop", "30"));
  expect(visibleText(renderer)).toContain("Enter how many scoops equal 30 g.");
  expect(visibleText(renderer)).toContain("2 cups = 30 g");
  expect(visibleText(renderer)).toContain("30 g total");
  expect(visibleText(renderer)).not.toContain("g per scoop");
  expect(onPatch).toHaveBeenLastCalledWith(expect.objectContaining({
    servingQuantity: "",
    servingUnit: "scoop",
    servingConversionReviewRequired: true,
  }));
  expect(input(renderer, "Serving quantity").props.value).toBe("");

  await act(async () => input(renderer, "Serving quantity").props.onChangeText("2"));
  // Resolving an incompatible unit explicitly establishes a new measured reference.
  expect(onPatch).toHaveBeenLastCalledWith(expect.objectContaining({
    servingQuantity: "2",
    servingReferenceQuantity: "2",
    servingReferenceUnit: "scoop",
    servingReferenceGramWeight: "30",
    servingConversionReviewRequired: false,
  }));
  expect(visibleText(renderer)).not.toContain(servingConversionReviewMessage("scoop", "30"));
  expect(visibleText(renderer)).toContain("2 scoops = 30 g");
  expect(visibleText(renderer)).toContain("15 g per scoop · 30 g total");
  await act(async () => renderer.unmount());
});

test("OCR reference editing removes storage-only trailing zeroes without rounding", async () => {
  const renderer = await mount({
    servingDisplay: "",
    servingQuantity: "8.000000",
    servingUnit: "tbsp",
    gramWeight: "50.000000",
    servingReferenceQuantity: "1.000000",
    servingReferenceUnit: "cup",
    servingReferenceGramWeight: "100.000000",
  });
  await act(async () => action(renderer, "Edit reference measurement").props.onPress());
  expect(input(renderer, "Reference quantity").props.value).toBe("1");
  expect(input(renderer, "Reference grams").props.value).toBe("100");
  await act(async () => renderer.unmount());
});

test("recognized weight-unit references derive their gram total", async () => {
  const onPatch = jest.fn();
  const renderer = await mount({ servingDisplay: "28 g", servingQuantity: "28", servingUnit: "g", gramWeight: "" }, onPatch);
  expect(onPatch).toHaveBeenCalledWith(expect.objectContaining({ gramWeight: "28" }));
  expect(input(renderer, "Reference grams").props.value).toBe("28");
  expect(input(renderer, "Reference grams").props.editable).toBe(false);
  await act(async () => renderer.unmount());
});

test("a deliberate representation quantity edit changes current grams but keeps the OCR reference stable", async () => {
  const onPatch = jest.fn();
  const renderer = await mount({ servingDisplay: "", servingQuantity: "2", servingUnit: "cup", gramWeight: "30" }, onPatch);

  await act(async () => input(renderer, "Serving quantity").props.onChangeText("1"));
  expect(onPatch).toHaveBeenLastCalledWith(expect.objectContaining({
    servingQuantity: "1", gramWeight: "15",
    servingReferenceQuantity: "2", servingReferenceUnit: "cup", servingReferenceGramWeight: "30",
  }));
  expect(visibleText(renderer)).toContain("2 cups = 30 g");
  expect(visibleText(renderer)).toContain("1 cup (15 g)");
  await act(async () => renderer.unmount());
});

test("OCR partial volume amounts convert from the exact current physical anchor instead of the full reference", async () => {
  const onPatch = jest.fn();
  const renderer = await mount({ servingDisplay: "", servingQuantity: "2", servingUnit: "cup", gramWeight: "30" }, onPatch);

  await act(async () => action(renderer, "Serving unit").props.onPress());
  await act(async () => chooseUnit(renderer, "tbsp"));
  await act(async () => input(renderer, "Serving quantity").props.onChangeText("16"));

  expect(visibleText(renderer)).toContain("16 Tbsp (15 g)");
  expect(visibleText(renderer)).toContain("2 cups = 30 g");

  onPatch.mockClear();
  await act(async () => action(renderer, "Serving unit").props.onPress());
  await act(async () => chooseUnit(renderer, "cup"));

  expect(input(renderer, "Serving quantity").props.value).toBe("1");
  expect(onPatch).toHaveBeenLastCalledWith(expect.objectContaining({
    servingQuantity: "1", servingUnit: "cup", gramWeight: "15",
  }));
  expect(visibleText(renderer)).toContain("1 cup (15 g)");
  expect(visibleText(renderer)).toContain("2 cups = 30 g");
  await act(async () => renderer.unmount());
});

test("resolved OCR count/custom representations promote the new reference and scale later quantity edits", async () => {
  const onPatch = jest.fn();
  const renderer = await mount({ servingDisplay: "", servingQuantity: "1", servingUnit: "cup", gramWeight: "100" }, onPatch);
  await act(async () => action(renderer, "Serving unit").props.onPress());
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Custom unit" }).props.onPress());
  await act(async () => input(renderer, "Custom unit name").props.onChangeText("piece"));
  await act(async () => action(renderer, "Use custom unit piece").props.onPress());
  await act(async () => input(renderer, "Serving quantity").props.onChangeText("2"));
  expect(visibleText(renderer)).toContain("2 pieces = 100 g");
  expect(visibleText(renderer)).toContain("2 pieces (100 g)");

  onPatch.mockClear();
  for (const raw of ["", "0", "0.", "0.5"]) {
    await act(async () => input(renderer, "Serving quantity").props.onChangeText(raw));
  }
  expect(onPatch).toHaveBeenLastCalledWith(expect.objectContaining({ servingQuantity: "0.5", gramWeight: "25" }));
  expect(visibleText(renderer)).toContain("1/2 piece (25 g)");
  expect(visibleText(renderer)).toContain("50 g per piece");
  expect(visibleText(renderer)).toContain("2 pieces = 100 g");
  await act(async () => renderer.unmount());
});

test("an explicitly customized OCR label remains authoritative across unit conversion", async () => {
  const onPatch = jest.fn();
  const renderer = await mount({ servingDisplay: "", servingQuantity: "1", servingUnit: "cup", gramWeight: "100" }, onPatch);
  await act(async () => action(renderer, "Customize label for 1 cup").props.onPress());
  await act(async () => input(renderer, "Serving label").props.onChangeText("My bowl"));
  expect(visibleText(renderer)).toContain("My bowl (100 g)");
  await act(async () => action(renderer, "Serving unit").props.onPress());
  await act(async () => chooseUnit(renderer, "tbsp"));
  expect(visibleText(renderer)).toContain("My bowl (100 g)");
  expect(visibleText(renderer)).toContain("1 cup = 100 g");
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

test("OCR explicit reference edit resets an incompatible current representation to the new reference", async () => {
  const onPatch = jest.fn();
  const renderer = await mount({
    servingDisplay: "",
    servingQuantity: "8",
    servingUnit: "tsp",
    gramWeight: "50",
    servingReferenceQuantity: "8",
    servingReferenceUnit: "tsp",
    servingReferenceGramWeight: "50",
  }, onPatch);

  await act(async () => action(renderer, "Edit reference measurement").props.onPress());
  await act(async () => input(renderer, "Reference quantity").props.onChangeText("1"));
  await act(async () => action(renderer, "Reference unit").props.onPress());
  await act(async () => chooseUnit(renderer, "piece"));
  await act(async () => input(renderer, "Reference grams").props.onChangeText("100"));
  await act(async () => action(renderer, "Confirm reference measurement").props.onPress());

  expect(onPatch).toHaveBeenLastCalledWith(expect.objectContaining({
    servingQuantity: "1",
    servingUnit: "piece",
    gramWeight: "100",
    servingReferenceQuantity: "1",
    servingReferenceUnit: "piece",
    servingReferenceGramWeight: "100",
    servingConversionReviewRequired: false,
  }));
  expect(visibleText(renderer)).toContain("1 piece = 100 g");
  expect(visibleText(renderer)).toContain("1 piece (100 g)");
  expect(visibleText(renderer)).not.toContain(UNCONVERTED_SERVING_UNIT_WARNING);

  onPatch.mockClear();
  await act(async () => input(renderer, "Serving quantity").props.onChangeText("2"));
  expect(onPatch).toHaveBeenLastCalledWith(expect.objectContaining({
    servingQuantity: "2",
    gramWeight: "200",
  }));
  expect(visibleText(renderer)).toContain("2 pieces (200 g)");
  expect(visibleText(renderer)).toContain("1 piece = 100 g");
  await act(async () => renderer.unmount());
});

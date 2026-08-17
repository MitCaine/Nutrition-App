import React, { useState } from "react";
import { Pressable, Text, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type {
  NutritionConfirmationDraft,
  ParsedField,
} from "../src/features/ocr/api/types";
import { OcrServingEditor } from "../src/features/ocr/components/OcrServingEditor";
import { confirmationPayload } from "../src/features/ocr/confirmation/confirmationModel";

const focusProps = () => ({
  ref: () => undefined,
  onFocus: () => undefined,
});

type ServingValue = Pick<
  NutritionConfirmationDraft,
  | "servingDisplay"
  | "servingQuantity"
  | "servingUnit"
  | "gramWeight"
  | "servingReferenceQuantity"
  | "servingReferenceUnit"
  | "servingReferenceGramWeight"
  | "servingConversionReviewRequired"
>;

function Harness({
  initial,
  onPatch = jest.fn(),
}: {
  initial: ServingValue;
  onPatch?: jest.Mock;
}) {
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

function input(
  renderer: TestRenderer.ReactTestRenderer,
  label: string,
) {
  return renderer.root
    .findAllByType(TextInput)
    .find((node) => node.props.accessibilityLabel === label)!;
}

function action(
  renderer: TestRenderer.ReactTestRenderer,
  label: string,
) {
  return renderer.root
    .findAllByType(Pressable)
    .find((node) => node.props.accessibilityLabel === label)!;
}

function textValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map(textValue).join("");
  }
  return "";
}

function visibleText(renderer: TestRenderer.ReactTestRenderer): string {
  return renderer.root
    .findAllByType(Text)
    .map((node) => textValue(node.props.children))
    .join(" ");
}

function chooseUnit(
  renderer: TestRenderer.ReactTestRenderer,
  unit: string,
) {
  renderer.root.findByProps({ accessibilityLabel: unit }).props.onPress();
}

async function mount(
  initial: ServingValue,
  onPatch = jest.fn(),
) {
  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      React.createElement(Harness, { initial, onPatch }),
    );
  });

  return renderer;
}

test("OCR structured serving recovery produces one direct gram relationship", async () => {
  const onPatch = jest.fn();

  const renderer = await mount(
    {
      servingDisplay: "2/3 cup (55 g)",
      servingQuantity: "1",
      servingUnit: "serving",
      gramWeight: "",
    },
    onPatch,
  );

  expect(onPatch).toHaveBeenCalledWith({
    servingQuantity: "0.666666667",
    servingUnit: "cup",
    gramWeight: "55",
    servingDisplay: "",
  });

  expect(visibleText(renderer)).toContain("2/3 cup = 55 g");
  expect(visibleText(renderer)).toContain(
    "82.5 g per cup · 55 g total",
  );
  expect(visibleText(renderer)).not.toContain("Reference measurement");

  await act(async () => renderer.unmount());
});

test("OCR unit edits leave quantity and grams unchanged", async () => {
  const onPatch = jest.fn();

  const renderer = await mount(
    {
      servingDisplay: "",
      servingQuantity: "1",
      servingUnit: "slice",
      gramWeight: "28",
    },
    onPatch,
  );

  await act(async () => action(renderer, "Serving unit").props.onPress());
  await act(async () => chooseUnit(renderer, "cup"));

  expect(onPatch).toHaveBeenLastCalledWith({
    servingUnit: "cup",
    servingConversionReviewRequired: false,
  });

  expect(input(renderer, "Serving quantity").props.value).toBe("1");
  expect(input(renderer, "Serving grams").props.value).toBe("28");
  expect(visibleText(renderer)).toContain("1 cup = 28 g");

  await act(async () => renderer.unmount());
});

test("OCR keyboard quantity intermediates never rescale grams", async () => {
  const onPatch = jest.fn();

  const renderer = await mount(
    {
      servingDisplay: "",
      servingQuantity: "1",
      servingUnit: "cup",
      gramWeight: "28",
    },
    onPatch,
  );

  await act(async () =>
    input(renderer, "Serving quantity").props.onChangeText(".2"),
  );

  expect(onPatch).toHaveBeenLastCalledWith({
    servingQuantity: "0.2",
    servingConversionReviewRequired: false,
  });
  expect(input(renderer, "Serving grams").props.value).toBe("28");

  await act(async () =>
    input(renderer, "Serving quantity").props.onChangeText(".25"),
  );

  expect(onPatch).toHaveBeenLastCalledWith({
    servingQuantity: "0.25",
    servingConversionReviewRequired: false,
  });

  expect(input(renderer, "Serving grams").props.value).toBe("28");
  expect(visibleText(renderer)).toContain("1/4 cup = 28 g");
  expect(visibleText(renderer)).toContain(
    "112 g per cup · 28 g total",
  );

  await act(async () => renderer.unmount());
});

test("OCR gram edits leave serving quantity and unit unchanged", async () => {
  const onPatch = jest.fn();

  const renderer = await mount(
    {
      servingDisplay: "",
      servingQuantity: "2",
      servingUnit: "slice",
      gramWeight: "28",
    },
    onPatch,
  );

  await act(async () =>
    input(renderer, "Serving grams").props.onChangeText("56"),
  );

  expect(onPatch).toHaveBeenLastCalledWith({
    gramWeight: "56",
    servingConversionReviewRequired: false,
  });

  expect(input(renderer, "Serving quantity").props.value).toBe("2");
  expect(visibleText(renderer)).toContain("2 slices = 56 g");
  expect(visibleText(renderer)).toContain(
    "28 g per slice · 56 g total",
  );

  await act(async () => renderer.unmount());
});

test("legacy OCR reference state is not exposed as a second authoring authority", async () => {
  const onPatch = jest.fn();

  const renderer = await mount(
    {
      servingDisplay: "",
      servingQuantity: "0.25",
      servingUnit: "cup",
      gramWeight: "28",
      servingReferenceQuantity: "1",
      servingReferenceUnit: "slice",
      servingReferenceGramWeight: "28",
      servingConversionReviewRequired: true,
    },
    onPatch,
  );

  // Only obsolete editor review state is cleared here. Compatibility
  // reference fields are normalized later when the payload is built.
  expect(onPatch).toHaveBeenCalledWith({
    servingConversionReviewRequired: false,
  });

  expect(visibleText(renderer)).toContain("1/4 cup = 28 g");
  expect(visibleText(renderer)).not.toContain("Reference measurement");

  await act(async () => renderer.unmount());
});

test("custom OCR display labels remain independent of gram anchoring", async () => {
  const renderer = await mount({
    servingDisplay: "",
    servingQuantity: "1",
    servingUnit: "cup",
    gramWeight: "100",
  });

  await act(async () =>
    action(renderer, "Customize label for 1 cup").props.onPress(),
  );

  await act(async () =>
    input(renderer, "Serving label").props.onChangeText("My bowl"),
  );

  expect(visibleText(renderer)).toContain("My bowl = 100 g");

  await act(async () => renderer.unmount());
});

test("confirmation payload normalizes compatibility reference to current serving", () => {
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
    servingQuantity: "0.25",
    servingUnit: "cup",
    gramWeight: "28",
    servingReferenceQuantity: "1",
    servingReferenceUnit: "slice",
    servingReferenceGramWeight: "28",
    servingProvenance: {
      display: parsedField("1 slice"),
      quantity: parsedField("1"),
      unit: parsedField("slice"),
      gramWeight: parsedField("28"),
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

  expect(payload.food.serving_definitions[1]).toEqual(
    expect.objectContaining({
      label: "0.25 cup",
      quantity: "0.25",
      unit: "cup",
      gram_weight: "28",
      reference_quantity: "0.25",
      reference_unit: "cup",
      reference_gram_weight: "28",
    }),
  );
});

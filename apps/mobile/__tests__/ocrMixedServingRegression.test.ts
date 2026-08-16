import React, { useState } from "react";
import { TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { NutritionConfirmationDraft } from "../src/features/ocr/api/types";
import { OcrServingEditor } from "../src/features/ocr/components/OcrServingEditor";
import { parseLocalNutritionLabel } from "../src/runtime/local/localOcrParser";

type ServingValue = Pick<
  NutritionConfirmationDraft,
  "servingDisplay" | "servingQuantity" | "servingUnit" | "gramWeight"
>;

const focusProps = () => ({ ref: () => undefined, onFocus: () => undefined });

function parseMixed(...servingObservations: string[]) {
  return parseLocalNutritionLabel({
    full_text: "ignored",
    observations: [
      { id: "header", text: "Nutrition Facts", confidence: 0.99 },
      ...servingObservations.map((text, index) => ({
        id: `serving-${index + 1}`,
        text,
        confidence: 0.98 - index * 0.01,
      })),
      { id: "calories", text: "Calories 100", confidence: 0.99 },
    ],
  });
}

test("local OCR parses an intact mixed-fraction serving without absorbing the fraction into the unit", () => {
  const result = parseMixed("Serving size 1 1/2 cup (208 g)");

  expect(result.serving?.serving_size_display.value).toBe("1 1/2 cup (208 g)");
  expect(result.serving?.serving_quantity.value).toBe("1.500000");
  expect(result.serving?.serving_unit.value).toBe("cup");
  expect(result.serving?.gram_weight.value).toBe("208");
});

test("local OCR rejoins a split mixed-fraction serving and preserves provenance", () => {
  const result = parseMixed("Serving size", "1 1/2 cup (208 g)");

  expect(result.serving?.serving_quantity.value).toBe("1.500000");
  expect(result.serving?.serving_unit.value).toBe("cup");
  expect(result.serving?.gram_weight.value).toBe("208");
  expect(result.serving?.serving_quantity.source_observation_ids).toEqual([
    "serving-1",
    "serving-2",
  ]);
});

test("local OCR rejoins mixed-fraction serving grams separately", () => {
  const result = parseMixed("Serving size 1 1/2 cup", "(208 g)");

  expect(result.serving?.serving_quantity.value).toBe("1.500000");
  expect(result.serving?.serving_unit.value).toBe("cup");
  expect(result.serving?.gram_weight.value).toBe("208");
  expect(result.serving?.gram_weight.source_observation_ids).toEqual([
    "serving-1",
    "serving-2",
  ]);
});

function RecoveryHarness({ onPatch }: { onPatch: jest.Mock }) {
  const [value, setValue] = useState<ServingValue>({
    servingDisplay: "1 1/2 cup (208 g)",
    servingQuantity: "1",
    servingUnit: "serving",
    gramWeight: "",
  });

  return React.createElement(OcrServingEditor, {
    value,
    focusProps,
    onChange: (patch) => {
      onPatch(patch);
      setValue((current) => ({ ...current, ...patch }));
    },
  });
}

test("OCR display recovery keeps a mixed fraction in quantity instead of creating a numeric custom unit", async () => {
  const onPatch = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(React.createElement(RecoveryHarness, { onPatch }));
  });

  expect(onPatch).toHaveBeenCalledWith({
    servingQuantity: "1.5",
    servingUnit: "cup",
    gramWeight: "208",
  });
  expect(onPatch).not.toHaveBeenCalledWith(
    expect.objectContaining({ servingUnit: "1/2 cup" }),
  );

  const quantity = renderer.root
    .findAllByType(TextInput)
    .find((node) => node.props.accessibilityLabel === "Serving quantity");
  expect(quantity?.props.value).toBe("1 1/2");

  await act(async () => renderer.unmount());
});

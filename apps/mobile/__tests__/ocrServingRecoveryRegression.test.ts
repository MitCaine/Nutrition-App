import React, { useState } from "react";
import { Text, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { NutritionConfirmationDraft } from "../src/features/ocr/api/types";
import { OcrServingEditor } from "../src/features/ocr/components/OcrServingEditor";

type ServingValue = Pick<
  NutritionConfirmationDraft,
  "servingDisplay" | "servingQuantity" | "servingUnit" | "gramWeight"
>;

const focusProps = () => ({
  ref: () => undefined,
  onFocus: () => undefined,
});

function Harness({ onPatch }: { onPatch: jest.Mock }) {
  const [value, setValue] = useState<ServingValue>({
    servingDisplay: "2/3 cup (55 g)",
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

function rootText(renderer: TestRenderer.ReactTestRenderer): string {
  return renderer.root
    .findAllByType(Text)
    .map((node) =>
      typeof node.props.children === "string"
        ? node.props.children
        : "",
    )
    .join(" ");
}

function input(
  root: TestRenderer.ReactTestInstance,
  label: string,
) {
  return root
    .findAllByType(TextInput)
    .find((node) => node.props.accessibilityLabel === label)!;
}

test("OCR serving recovery runs once, then user quantity edits leave recovered grams fixed", async () => {
  const onPatch = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      React.createElement(Harness, { onPatch }),
    );
  });

  expect(onPatch).toHaveBeenCalledWith({
    servingQuantity: "0.666666667",
    servingUnit: "cup",
    gramWeight: "55",
    servingDisplay: "",
  });

  expect(
    input(renderer.root, "Serving quantity").props.value,
  ).toBe("2/3");

  expect(
    input(renderer.root, "Serving grams").props.value,
  ).toBe("55");

  onPatch.mockClear();

  await act(async () =>
    input(renderer.root, "Serving quantity").props.onChangeText("1"),
  );

  expect(onPatch).toHaveBeenCalledTimes(1);
  expect(onPatch).toHaveBeenLastCalledWith({
    servingQuantity: "1",
    servingConversionReviewRequired: false,
  });

  expect(
    input(renderer.root, "Serving quantity").props.value,
  ).toBe("1");

  expect(
    input(renderer.root, "Serving grams").props.value,
  ).toBe("55");

  expect(rootText(renderer)).not.toContain("Reference measurement");
  expect(rootText(renderer)).toContain("1 cup = 55 g");
  expect(rootText(renderer)).toContain(
    "55 g per cup · 55 g total",
  );

  await act(async () => renderer.unmount());
});

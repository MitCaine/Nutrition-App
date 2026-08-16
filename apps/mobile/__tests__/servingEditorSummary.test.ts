import React from "react";
import { Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import { ServingDefinitionsEditor } from "../src/features/foods/components/ServingDefinitionsEditor";
import type { ServingFormValue } from "../src/features/foods/hooks/useFoodForm";

const focusProps = () => ({ ref: () => undefined, onFocus: () => undefined });

function textValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(textValue).join("");
  return "";
}

const servings: ServingFormValue[] = [
  { key: "base", label: "100 g", quantity: "100", unit: "g", gram_weight: "100", is_default: true, isBaseAmount: true, labelMode: "automatic" },
  {
    key: "fraction",
    label: "0.666666667 cup",
    quantity: "0.666666667",
    unit: "cup",
    gram_weight: "82.089552",
    is_default: false,
    isBaseAmount: false,
    labelMode: "automatic",
  },
  { key: "manual", label: "Big bowl", quantity: "1.5", unit: "bowl", gram_weight: "45", is_default: false, isBaseAmount: false, labelMode: "manual" },
];

test("collapsed serving summaries humanize fractions and derived grams without mutating servings", async () => {
  const updateServing = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(
      React.createElement(ServingDefinitionsEditor, {
        servings,
        updateServing,
        addServing: jest.fn(() => "unused"),
        removeServing: jest.fn(),
        focusProps,
        invalidServingKey: null,
        defaultAmountError: null,
        validationTarget: null,
        validationError: null,
      }),
    );
  });

  const visibleText = renderer.root.findAllByType(Text).map((node) => textValue(node.props.children)).join(" | ");

  expect(visibleText).toContain("2/3 cup");
  expect(visibleText).toContain("123.1 g per cup · 82.1 g total");
  expect(visibleText).toContain("Big bowl");
  expect(visibleText).toContain("30 g per bowl · 45 g total");
  expect(visibleText).not.toContain("0.666666667");
  expect(visibleText).not.toContain("82.089552");
  expect(visibleText).not.toContain("123.134328");

  expect(servings[1].quantity).toBe("0.666666667");
  expect(servings[1].gram_weight).toBe("82.089552");
  expect(servings[1].label).toBe("0.666666667 cup");
  expect(updateServing).not.toHaveBeenCalled();

  await act(async () => {
    renderer.unmount();
  });
});

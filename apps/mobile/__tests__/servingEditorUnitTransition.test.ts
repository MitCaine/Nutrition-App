import React, { useState } from "react";
import { Pressable, Text, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import { ServingDefinitionsEditor } from "../src/features/foods/components/ServingDefinitionsEditor";
import { updateServingValues, type ServingFormValue } from "../src/features/foods/hooks/useFoodForm";
import { UNCONVERTED_SERVING_UNIT_WARNING } from "../src/features/foods/utils/amountForm";

const focusProps = () => ({ ref: () => undefined, onFocus: () => undefined });

function textValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(textValue).join("");
  return "";
}

function visibleText(renderer: TestRenderer.ReactTestRenderer): string {
  return renderer.root.findAllByType(Text).map((node) => textValue(node.props.children)).join(" | ");
}

function press(renderer: TestRenderer.ReactTestRenderer, label: string) {
  const target = renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === label);
  if (!target) throw new Error(`missing pressable: ${label}`);
  target.props.onPress();
}

function openUnitPicker(renderer: TestRenderer.ReactTestRenderer) {
  const trigger = renderer.root.findAllByType(Pressable).find((node) => typeof node.props.accessibilityLabel === "string" && node.props.accessibilityLabel.startsWith("Choose unit for"));
  if (!trigger) throw new Error("missing unit picker trigger");
  trigger.props.onPress();
}

function chooseUnit(renderer: TestRenderer.ReactTestRenderer, unit: string) {
  renderer.root.findByProps({ accessibilityLabel: unit }).props.onPress();
}

let latestServings: ServingFormValue[] = [];

function Harness({ initial }: { initial: ServingFormValue[] }) {
  const [servings, setServings] = useState(initial);
  const updateServing = (key: string, patch: Partial<ServingFormValue>) => {
    setServings((current) => {
      const next = updateServingValues(current, key, patch);
      latestServings = next;
      return next;
    });
  };
  return React.createElement(ServingDefinitionsEditor, {
    servings,
    updateServing,
    addServing: () => "unused",
    removeServing: () => undefined,
    focusProps,
    invalidServingKey: null,
    defaultAmountError: null,
    validationTarget: null,
    validationError: null,
  });
}

async function renderEditor(servings: ServingFormValue[]) {
  latestServings = servings;
  const renderer = TestRenderer.create(React.createElement(Harness, { initial: servings }));
  await act(async () => undefined);
  return renderer;
}

const cupServing: ServingFormValue = {
  key: "fraction",
  label: "",
  quantity: "1.5",
  unit: "cup",
  gram_weight: "208",
  is_default: false,
  isBaseAmount: false,
  labelMode: "automatic",
};

const baseServing: ServingFormValue = {
  key: "base", label: "100 g", quantity: "100", unit: "g", gram_weight: "100", is_default: true, isBaseAmount: true, labelMode: "automatic",
};

test("Food serving editor preserves the physical serving across cup -> oz -> cup", async () => {
  const renderer = await renderEditor([baseServing, cupServing]);
  await act(async () => press(renderer, "Edit 1 1/2 cup"));

  await act(async () => openUnitPicker(renderer));
  await act(async () => chooseUnit(renderer, "oz"));
  expect(visibleText(renderer)).toContain("7.337 oz");
  expect(visibleText(renderer)).toContain("208 g total");
  const ounceState = latestServings.find((serving) => serving.key === "fraction")!;
  expect(ounceState.quantity).toBe("7.336984");
  expect(ounceState.gram_weight).toBe("208");
  expect(ounceState.unit).toBe("oz");
  expect(ounceState.label).toBe("7.336984 oz");

  await act(async () => openUnitPicker(renderer));
  await act(async () => chooseUnit(renderer, "cup"));
  expect(visibleText(renderer)).toContain("1 1/2 cup");
  expect(visibleText(renderer)).toContain("138.7 g per cup · 208 g total");
  const restored = latestServings.find((serving) => serving.key === "fraction")!;
  expect(restored.quantity).toBe("1.5");
  expect(restored.gram_weight).toBe("208");
  expect(restored.unit).toBe("cup");
  await act(async () => renderer.unmount());
});

test("Food serving editor volume round trip cup -> tbsp -> cup preserves the serving", async () => {
  const renderer = await renderEditor([baseServing, cupServing]);
  await act(async () => press(renderer, "Edit 1 1/2 cup"));

  await act(async () => openUnitPicker(renderer));
  await act(async () => chooseUnit(renderer, "tbsp"));
  expect(visibleText(renderer)).toContain("24 Tbsp");
  expect(visibleText(renderer)).toContain("208 g total");

  await act(async () => openUnitPicker(renderer));
  await act(async () => chooseUnit(renderer, "cup"));
  expect(visibleText(renderer)).toContain("1 1/2 cup");
  const restored = latestServings.find((serving) => serving.key === "fraction")!;
  expect(restored.quantity).toBe("1.5");
  expect(restored.gram_weight).toBe("208");
  await act(async () => renderer.unmount());
});

test("Food serving editor keeps known grams for review when no conversion is defensible", async () => {
  const renderer = await renderEditor([baseServing, cupServing]);
  await act(async () => press(renderer, "Edit 1 1/2 cup"));

  await act(async () => openUnitPicker(renderer));
  await act(async () => chooseUnit(renderer, "piece"));
  expect(visibleText(renderer)).toContain(UNCONVERTED_SERVING_UNIT_WARNING);
  expect(visibleText(renderer)).toContain("208 g total");
  expect(visibleText(renderer)).not.toContain("138.7 g per piece");
  const refused = latestServings.find((serving) => serving.key === "fraction")!;
  expect(refused.gram_weight).toBe("208");
  expect(refused.quantity).toBe("1.5");
  expect(refused.unit).toBe("piece");
  expect(refused.consistencyWarning).toBe(UNCONVERTED_SERVING_UNIT_WARNING);

  // An explicit quantity correction resolves the review state; per-unit derivation resumes.
  await act(async () => {
    renderer.root.findAllByType(TextInput).find((node) => node.props.accessibilityLabel === "Quantity")!.props.onChangeText("2");
  });
  expect(visibleText(renderer)).not.toContain(UNCONVERTED_SERVING_UNIT_WARNING);
  expect(visibleText(renderer)).toContain("104 g per piece · 208 g total");
  const corrected = latestServings.find((serving) => serving.key === "fraction")!;
  expect(corrected.quantity).toBe("2");
  expect(corrected.gram_weight).toBe("208");
  expect(corrected.consistencyWarning).toBeUndefined();

  // The corrected amount replaced the represented serving, so the previous 1.5-cup anchor
  // is stale: returning to cup must refuse rather than restore the outdated volume.
  await act(async () => openUnitPicker(renderer));
  await act(async () => chooseUnit(renderer, "cup"));
  expect(visibleText(renderer)).toContain("2 cup");
  expect(visibleText(renderer)).toContain(UNCONVERTED_SERVING_UNIT_WARNING);
  expect(visibleText(renderer)).toContain("208 g total");
  const returned = latestServings.find((serving) => serving.key === "fraction")!;
  expect(returned.gram_weight).toBe("208");
  expect(returned.quantity).toBe("2");
  await act(async () => renderer.unmount());
});

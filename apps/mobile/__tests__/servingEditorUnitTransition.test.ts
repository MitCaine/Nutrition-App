import React, { useState } from "react";
import { Pressable, Text, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import { ServingDefinitionsEditor } from "../src/features/foods/components/ServingDefinitionsEditor";
import {
  updateServingValues,
  type ServingFormValue,
} from "../src/features/foods/hooks/useFoodForm";

const focusProps = () => ({
  ref: () => undefined,
  onFocus: () => undefined,
});

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
    .join(" | ");
}

function press(renderer: TestRenderer.ReactTestRenderer, label: string) {
  const target = renderer.root
    .findAllByType(Pressable)
    .find((node) => node.props.accessibilityLabel === label);

  if (!target) throw new Error(`missing pressable: ${label}`);
  target.props.onPress();
}

function openPicker(
  renderer: TestRenderer.ReactTestRenderer,
  triggerStart: string,
) {
  const trigger = renderer.root
    .findAllByType(Pressable)
    .find(
      (node) =>
        typeof node.props.accessibilityLabel === "string"
        && node.props.accessibilityLabel.startsWith(triggerStart),
    );

  if (!trigger) {
    throw new Error(`missing picker trigger: ${triggerStart}`);
  }
  trigger.props.onPress();
}

function chooseOption(
  renderer: TestRenderer.ReactTestRenderer,
  label: string,
) {
  renderer.root.findByProps({ accessibilityLabel: label }).props.onPress();
}

function inputByLabel(
  renderer: TestRenderer.ReactTestRenderer,
  label: string,
) {
  const field = renderer.root
    .findAllByType(TextInput)
    .find((node) => node.props.accessibilityLabel === label);

  if (!field) throw new Error(`missing input: ${label}`);
  return field;
}

let latestServings: ServingFormValue[] = [];

function Harness({ initial }: { initial: ServingFormValue[] }) {
  const [servings, setServings] = useState(initial);

  const updateServing = (
    key: string,
    patch: Partial<ServingFormValue>,
  ) => {
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
  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      React.createElement(Harness, { initial: servings }),
    );
  });

  return renderer;
}

function portionServing(
  quantity: string,
  unit: string,
  grams: string,
): ServingFormValue {
  return {
    key: "fraction",
    label: "",
    quantity,
    unit,
    gram_weight: grams,
    is_default: false,
    isBaseAmount: false,
    labelMode: "automatic",
  };
}

const baseServing: ServingFormValue = {
  key: "base",
  label: "100 g",
  quantity: "100",
  unit: "g",
  gram_weight: "100",
  is_default: true,
  isBaseAmount: true,
  labelMode: "automatic",
};

function currentPortion() {
  return latestServings.find((serving) => serving.key === "fraction")!;
}

test("saved serving authoring is one explicit quantity/unit/gram relationship", async () => {
  const renderer = await renderEditor([
    baseServing,
    portionServing("1", "slice", "28"),
  ]);

  expect(visibleText(renderer)).toContain("1 slice");
  expect(visibleText(renderer)).toContain("28 g");

  await act(async () => press(renderer, "Edit 1 slice"));

  expect(inputByLabel(renderer, "Serving quantity").props.value).toBe("1");
  expect(inputByLabel(renderer, "Serving grams").props.value).toBe("28");
  expect(visibleText(renderer)).toContain("1 slice = 28 g");
  expect(visibleText(renderer)).not.toContain("Reference measurement");

  await act(async () => renderer.unmount());
});

test("changing unit never recalculates quantity or grams", async () => {
  const renderer = await renderEditor([
    baseServing,
    portionServing("1", "slice", "28"),
  ]);

  await act(async () => press(renderer, "Edit 1 slice"));
  await act(async () => openPicker(renderer, "Choose unit for 1 slice"));
  await act(async () => chooseOption(renderer, "cup"));

  expect(currentPortion()).toEqual(
    expect.objectContaining({
      quantity: "1",
      unit: "cup",
      gram_weight: "28",
    }),
  );
  expect(visibleText(renderer)).toContain("1 cup = 28 g");

  await act(async () => renderer.unmount());
});

test("keyboard intermediates change only serving quantity and never rescale grams", async () => {
  const renderer = await renderEditor([
    baseServing,
    portionServing("1", "cup", "28"),
  ]);

  await act(async () => press(renderer, "Edit 1 cup"));

  await act(async () =>
    inputByLabel(renderer, "Serving quantity").props.onChangeText(".2"),
  );

  expect(currentPortion()).toEqual(
    expect.objectContaining({
      quantity: ".2",
      unit: "cup",
      gram_weight: "28",
    }),
  );

  await act(async () =>
    inputByLabel(renderer, "Serving quantity").props.onChangeText(".25"),
  );

  expect(currentPortion()).toEqual(
    expect.objectContaining({
      quantity: ".25",
      unit: "cup",
      gram_weight: "28",
    }),
  );
  expect(visibleText(renderer)).toContain("1/4 cup = 28 g");

  await act(async () => renderer.unmount());
});

test("changing serving quantity does not scale grams", async () => {
  const renderer = await renderEditor([
    baseServing,
    portionServing("1", "slice", "28"),
  ]);

  await act(async () => press(renderer, "Edit 1 slice"));

  await act(async () =>
    inputByLabel(renderer, "Serving quantity").props.onChangeText("2"),
  );

  expect(currentPortion()).toEqual(
    expect.objectContaining({
      quantity: "2",
      unit: "slice",
      gram_weight: "28",
    }),
  );
  expect(visibleText(renderer)).toContain("2 slices = 28 g");

  await act(async () => renderer.unmount());
});

test("changing grams does not alter quantity or unit", async () => {
  const renderer = await renderEditor([
    baseServing,
    portionServing("2", "slice", "28"),
  ]);

  await act(async () => press(renderer, "Edit 2 slices"));

  await act(async () =>
    inputByLabel(renderer, "Serving grams").props.onChangeText("56"),
  );

  expect(currentPortion()).toEqual(
    expect.objectContaining({
      quantity: "2",
      unit: "slice",
      gram_weight: "56",
    }),
  );
  expect(visibleText(renderer)).toContain("2 slices = 56 g");

  await act(async () => renderer.unmount());
});

test("legacy reference fields are not exposed as editable serving authority", async () => {
  const serving: ServingFormValue = {
    ...portionServing("0.25", "cup", "28"),
    reference_quantity: "1",
    reference_unit: "slice",
    reference_gram_weight: "28",
  };

  const renderer = await renderEditor([baseServing, serving]);

  await act(async () => press(renderer, "Edit 1/4 cup"));

  expect(visibleText(renderer)).toContain("1/4 cup = 28 g");
  expect(visibleText(renderer)).not.toContain("Reference measurement");
  expect(
    renderer.root
      .findAllByType(TextInput)
      .some((node) => node.props.accessibilityLabel === "Reference quantity"),
  ).toBe(false);

  await act(async () => renderer.unmount());
});

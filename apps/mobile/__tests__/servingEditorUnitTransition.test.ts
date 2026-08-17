import React, { useState } from "react";
import { Pressable, Text, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import { ServingDefinitionsEditor } from "../src/features/foods/components/ServingDefinitionsEditor";
import { updateServingValues, type ServingFormValue } from "../src/features/foods/hooks/useFoodForm";
import { servingConversionReviewMessage, UNCONVERTED_SERVING_UNIT_WARNING } from "../src/features/foods/utils/amountForm";

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

function openPicker(renderer: TestRenderer.ReactTestRenderer, triggerStart: string) {
  const trigger = renderer.root.findAllByType(Pressable).find((node) => typeof node.props.accessibilityLabel === "string" && node.props.accessibilityLabel.startsWith(triggerStart));
  if (!trigger) throw new Error(`missing picker trigger: ${triggerStart}`);
  trigger.props.onPress();
}

function chooseOption(renderer: TestRenderer.ReactTestRenderer, label: string) {
  renderer.root.findByProps({ accessibilityLabel: label }).props.onPress();
}

function inputByLabel(renderer: TestRenderer.ReactTestRenderer, label: string) {
  const field = renderer.root.findAllByType(TextInput).find((node) => node.props.accessibilityLabel === label);
  if (!field) throw new Error(`missing input: ${label}`);
  return field;
}

let latestServings: ServingFormValue[] = [];

function Harness({ initial, preserveStaleReviewWarning = false }: { initial: ServingFormValue[]; preserveStaleReviewWarning?: boolean }) {
  const [servings, setServings] = useState(initial);
  const updateServing = (key: string, patch: Partial<ServingFormValue>) => {
    setServings((current) => {
      let next = updateServingValues(current, key, patch);
      if (preserveStaleReviewWarning && patch.consistencyWarning === undefined) {
        next = next.map((serving) => serving.key === key
          ? { ...serving, consistencyWarning: UNCONVERTED_SERVING_UNIT_WARNING }
          : serving);
      }
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

async function renderEditor(servings: ServingFormValue[], preserveStaleReviewWarning = false) {
  latestServings = servings;
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(Harness, { initial: servings, preserveStaleReviewWarning }));
  });
  return renderer;
}

function portionServing(quantity: string, unit: string, grams: string): ServingFormValue {
  return {
    key: "fraction", label: "", quantity, unit, gram_weight: grams,
    is_default: false, isBaseAmount: false, labelMode: "automatic",
  };
}

const baseServing: ServingFormValue = {
  key: "base", label: "100 g", quantity: "100", unit: "g", gram_weight: "100", is_default: true, isBaseAmount: true, labelMode: "automatic",
};

function currentPortion() {
  return latestServings.find((serving) => serving.key === "fraction")!;
}

test("reference measurement is authored, confirmed, and editable", async () => {
  const renderer = await renderEditor([baseServing, portionServing("1", "", "")]);
  await act(async () => press(renderer, "Edit serving size"));

  await act(async () => inputByLabel(renderer, "Reference quantity").props.onChangeText("1"));
  await act(async () => press(renderer, "Reference unit"));
  await act(async () => chooseOption(renderer, "cup"));
  await act(async () => inputByLabel(renderer, "Reference grams").props.onChangeText("100"));
  await act(async () => press(renderer, "Confirm reference measurement"));

  expect(visibleText(renderer)).toContain("1 cup = 100 g");
  expect(visibleText(renderer)).toContain("1 cup (100 g)");
  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "1", unit: "cup", gram_weight: "100",
    reference_quantity: "1", reference_unit: "cup", reference_gram_weight: "100",
  }));

  await act(async () => press(renderer, "Edit reference measurement"));
  expect(inputByLabel(renderer, "Reference quantity").props.value).toBe("1");
  expect(inputByLabel(renderer, "Reference grams").props.value).toBe("100");
  await act(async () => renderer.unmount());
});

test("persisted reference decimals edit without storage-only trailing zeroes", async () => {
  const serving: ServingFormValue = {
    ...portionServing("8", "tbsp", "50"),
    reference_quantity: "1.000000",
    reference_unit: "cup",
    reference_gram_weight: "100.000000",
  };
  const renderer = await renderEditor([baseServing, serving]);
  await act(async () => press(renderer, "Edit 8 Tbsp"));
  await act(async () => press(renderer, "Edit reference measurement"));

  expect(inputByLabel(renderer, "Reference quantity").props.value).toBe("1");
  expect(inputByLabel(renderer, "Reference grams").props.value).toBe("100");
  await act(async () => renderer.unmount());
});

test("compatible conversions change only the representation; the reference and grams stay fixed", async () => {
  const renderer = await renderEditor([baseServing, portionServing("1", "cup", "100")]);
  await act(async () => press(renderer, "Edit 1 cup"));

  await act(async () => openPicker(renderer, "Choose unit for 1 cup"));
  await act(async () => chooseOption(renderer, "tbsp"));
  expect(visibleText(renderer)).toContain("16 Tbsp (100 g)");
  expect(visibleText(renderer)).toContain("1 cup = 100 g");
  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "16", unit: "tbsp", gram_weight: "100",
    reference_quantity: "1", reference_unit: "cup", reference_gram_weight: "100",
  }));

  await act(async () => openPicker(renderer, "Choose unit for"));
  await act(async () => chooseOption(renderer, "oz"));
  expect(visibleText(renderer)).toContain("3.53 oz (100 g)");
  expect(visibleText(renderer)).toContain("1 cup = 100 g");

  await act(async () => openPicker(renderer, "Choose unit for"));
  await act(async () => chooseOption(renderer, "cup"));
  expect(visibleText(renderer)).toContain("1 cup (100 g)");
  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "1", unit: "cup", gram_weight: "100",
    reference_quantity: "1", reference_unit: "cup", reference_gram_weight: "100",
  }));
  await act(async () => renderer.unmount());
});

test("the #97 anchor reference 1.5 cup = 208 g survives an ounces detour exactly", async () => {
  const renderer = await renderEditor([baseServing, portionServing("1.5", "cup", "208")]);
  await act(async () => press(renderer, "Edit 1 1/2 cups"));

  await act(async () => openPicker(renderer, "Choose unit for 1 1/2 cup"));
  await act(async () => chooseOption(renderer, "oz"));
  expect(visibleText(renderer)).toContain("7.34 oz (208 g)");
  expect(visibleText(renderer)).toContain("1 1/2 cups = 208 g");

  await act(async () => openPicker(renderer, "Choose unit for"));
  await act(async () => chooseOption(renderer, "cup"));
  expect(visibleText(renderer)).toContain("1 1/2 cups (208 g)");
  expect(currentPortion().gram_weight).toBe("208");
  expect(currentPortion().quantity).toBe("1.5");
  await act(async () => renderer.unmount());
});

test("editing the reference recalculates the current representation", async () => {
  const renderer = await renderEditor([baseServing, portionServing("1", "cup", "100")]);
  await act(async () => press(renderer, "Edit 1 cup"));
  await act(async () => openPicker(renderer, "Choose unit for 1 cup"));
  await act(async () => chooseOption(renderer, "tbsp"));
  expect(visibleText(renderer)).toContain("16 Tbsp (100 g)");

  await act(async () => press(renderer, "Edit reference measurement"));
  await act(async () => inputByLabel(renderer, "Reference grams").props.onChangeText("110"));
  await act(async () => press(renderer, "Confirm reference measurement"));

  expect(visibleText(renderer)).toContain("1 cup = 110 g");
  expect(visibleText(renderer)).toContain("16 Tbsp (110 g)");
  expect(visibleText(renderer)).not.toContain("6.3 g per Tbsp");
  expect(currentPortion()).toEqual(expect.objectContaining({ quantity: "16", unit: "tbsp", gram_weight: "110", reference_quantity: "1", reference_unit: "cup", reference_gram_weight: "110" }));
  await act(async () => renderer.unmount());
});

test("unsupported units keep the committed relationship intact while equivalence is drafted", async () => {
  const renderer = await renderEditor([baseServing, portionServing("1", "cup", "100")]);
  await act(async () => press(renderer, "Edit 1 cup"));

  await act(async () => openPicker(renderer, "Choose unit for 1 cup"));
  await act(async () => chooseOption(renderer, "piece"));

  expect(visibleText(renderer)).toContain("Equivalent measurement needed");
  expect(visibleText(renderer)).toContain(servingConversionReviewMessage("piece", "100"));
  expect(visibleText(renderer)).toContain("1 cup = 100 g");
  expect(visibleText(renderer)).not.toContain("g per piece");

  // Selecting an incompatible unit starts a draft. The authoritative/current
  // physical serving is still the original cup relationship.
  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "1",
    unit: "cup",
    gram_weight: "100",
    consistencyWarning: UNCONVERTED_SERVING_UNIT_WARNING,
  }));

  await act(async () => renderer.unmount());
});

test("legacy unestablished review state can still be resolved through explicit reference editing", async () => {
  const unresolved: ServingFormValue = {
    ...portionServing("", "slice", "100"),
    consistencyWarning: UNCONVERTED_SERVING_UNIT_WARNING,
    reference_quantity: "1",
    reference_unit: "cup",
    reference_gram_weight: "100",
  };

  const renderer = await renderEditor([baseServing, unresolved]);

  await act(async () => press(renderer, "Edit reference measurement"));
  await act(async () =>
    inputByLabel(renderer, "Reference quantity").props.onChangeText("1")
  );
  await act(async () => press(renderer, "Reference unit"));
  await act(async () => chooseOption(renderer, "slice"));
  await act(async () =>
    inputByLabel(renderer, "Reference grams").props.onChangeText("100")
  );
  await act(async () => press(renderer, "Confirm reference measurement"));

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "1",
    unit: "slice",
    gram_weight: "100",
    reference_quantity: "1",
    reference_unit: "slice",
    reference_gram_weight: "100",
  }));
  expect(currentPortion().consistencyWarning).toBeUndefined();
  expect(visibleText(renderer)).toContain("1 slice = 100 g");
  expect(visibleText(renderer)).not.toContain(
    UNCONVERTED_SERVING_UNIT_WARNING,
  );

  await act(async () => renderer.unmount());
});

test("a deliberate representation quantity edit scales exact grams and keeps the reference", async () => {
  const renderer = await renderEditor([baseServing, portionServing("1", "cup", "100")]);
  await act(async () => press(renderer, "Edit 1 cup"));
  await act(async () => openPicker(renderer, "Choose unit for 1 cup"));
  await act(async () => chooseOption(renderer, "tbsp"));

  await act(async () => inputByLabel(renderer, "Quantity").props.onChangeText("8"));
  expect(visibleText(renderer)).toContain("8 Tbsp (50 g)");
  expect(visibleText(renderer)).toContain("Based on: 1 cup = 100 g");
  const portion = currentPortion();
  expect(portion).toEqual(expect.objectContaining({ quantity: "8", unit: "tbsp", gram_weight: "50" }));
  expect(portion.reference_quantity).toBe("1");
  expect(portion.reference_unit).toBe("cup");
  expect(portion.reference_gram_weight).toBe("100");
  await act(async () => renderer.unmount());
});


test("a partial volume amount converts from its exact current physical anchor without snapping back to the full reference", async () => {
  const renderer = await renderEditor([baseServing, portionServing("1", "cup", "100")]);
  await act(async () => press(renderer, "Edit 1 cup"));
  await act(async () => openPicker(renderer, "Choose unit for 1 cup"));
  await act(async () => chooseOption(renderer, "tbsp"));
  await act(async () => inputByLabel(renderer, "Quantity").props.onChangeText("8"));

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "8", unit: "tbsp", gram_weight: "50",
    reference_quantity: "1", reference_unit: "cup", reference_gram_weight: "100",
  }));

  await act(async () => openPicker(renderer, "Choose unit for"));
  await act(async () => chooseOption(renderer, "cup"));

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "0.5", unit: "cup", gram_weight: "50",
    reference_quantity: "1", reference_unit: "cup", reference_gram_weight: "100",
  }));
  expect(visibleText(renderer)).toContain("1/2 cup (50 g)");
  expect(visibleText(renderer)).toContain("Based on: 1 cup = 100 g");
  await act(async () => renderer.unmount());
});

test("cross-dimension keyboard intermediates remain draft-only until explicit confirmation", async () => {
  const renderer = await renderEditor([
    baseServing,
    portionServing("1", "slice", "28"),
  ]);

  await act(async () => press(renderer, "Edit 1 slice"));
  await act(async () => openPicker(renderer, "Choose unit for 1 slice"));
  await act(async () => chooseOption(renderer, "cup"));

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "1",
    unit: "slice",
    gram_weight: "28",
    consistencyWarning: UNCONVERTED_SERVING_UNIT_WARNING,
  }));

  // This is the exact iOS reproduction: ".2" is only an intermediate
  // keyboard value on the way to ".25". It must not become authority.
  await act(async () =>
    inputByLabel(renderer, "Equivalent quantity").props.onChangeText(".2")
  );

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "1",
    unit: "slice",
    gram_weight: "28",
  }));
  expect(visibleText(renderer)).toContain("1/5 cup (28 g)");
  expect(visibleText(renderer)).toContain("140 g per cup");

  await act(async () =>
    inputByLabel(renderer, "Equivalent quantity").props.onChangeText(".25")
  );

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "1",
    unit: "slice",
    gram_weight: "28",
  }));
  expect(visibleText(renderer)).toContain("1/4 cup (28 g)");
  expect(visibleText(renderer)).toContain("112 g per cup");

  await act(async () => press(renderer, "Confirm equivalent measurement"));

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "0.25",
    unit: "cup",
    gram_weight: "28",
    reference_quantity: "0.25",
    reference_unit: "cup",
    reference_gram_weight: "28",
  }));
  expect(currentPortion().consistencyWarning).toBeUndefined();
  expect(visibleText(renderer)).toContain("1/4 cup = 28 g");

  // Once explicitly confirmed, ordinary edits scale from the confirmed
  // food-specific relationship.
  await act(async () =>
    inputByLabel(renderer, "Quantity").props.onChangeText("0.5")
  );

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "0.5",
    unit: "cup",
    gram_weight: "56",
    reference_quantity: "0.25",
    reference_unit: "cup",
    reference_gram_weight: "28",
  }));

  await act(async () => renderer.unmount());
});

test("canceling a pending equivalence restores the pre-change serving exactly", async () => {
  const renderer = await renderEditor([
    baseServing,
    portionServing("1", "cup", "100"),
  ]);

  await act(async () => press(renderer, "Edit 1 cup"));
  await act(async () => openPicker(renderer, "Choose unit for 1 cup"));
  await act(async () => chooseOption(renderer, "piece"));

  await act(async () =>
    inputByLabel(renderer, "Equivalent quantity").props.onChangeText("2")
  );

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "1",
    unit: "cup",
    gram_weight: "100",
    consistencyWarning: UNCONVERTED_SERVING_UNIT_WARNING,
  }));

  await act(async () => press(renderer, "Cancel equivalent measurement"));

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "1",
    unit: "cup",
    gram_weight: "100",
  }));
  expect(currentPortion().consistencyWarning).toBeUndefined();
  expect(visibleText(renderer)).toContain("1 cup = 100 g");
  expect(visibleText(renderer)).not.toContain("Equivalent measurement needed");

  await act(async () => renderer.unmount());
});

test("real keyboard replacement intermediates never mutate committed authority before confirmation", async () => {
  const serving: ServingFormValue = {
    ...portionServing("8", "tbsp", "50"),
    reference_quantity: "1",
    reference_unit: "cup",
    reference_gram_weight: "100",
  };

  const renderer = await renderEditor([baseServing, serving]);
  await act(async () => press(renderer, "Edit 8 Tbsp"));
  await act(async () => openPicker(renderer, "Choose unit for 8 Tbsp"));
  await act(async () => chooseOption(renderer, "piece"));

  for (const raw of ["", "0", "0.", "0.5"]) {
    await act(async () =>
      inputByLabel(renderer, "Equivalent quantity").props.onChangeText(raw)
    );

    expect(currentPortion()).toEqual(expect.objectContaining({
      quantity: "8",
      unit: "tbsp",
      gram_weight: "50",
      reference_quantity: "1",
      reference_unit: "cup",
      reference_gram_weight: "100",
    }));
  }

  expect(visibleText(renderer)).toContain("1/2 piece (50 g)");
  expect(visibleText(renderer)).toContain("100 g per piece");

  await act(async () => press(renderer, "Confirm equivalent measurement"));

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "0.5",
    unit: "piece",
    gram_weight: "50",
    reference_quantity: "0.5",
    reference_unit: "piece",
    reference_gram_weight: "50",
  }));

  await act(async () =>
    inputByLabel(renderer, "Quantity").props.onChangeText("1")
  );

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "1",
    unit: "piece",
    gram_weight: "100",
    reference_quantity: "0.5",
    reference_unit: "piece",
    reference_gram_weight: "50",
  }));

  await act(async () => renderer.unmount());
});

test("confirmed weight-to-volume equivalence becomes the stable volume reference", async () => {
  const renderer = await renderEditor([
    baseServing,
    portionServing("100", "g", "100"),
  ]);

  await act(async () => press(renderer, "Edit 100 g"));
  await act(async () => openPicker(renderer, "Choose unit for 100 g"));
  await act(async () => chooseOption(renderer, "cup"));

  await act(async () =>
    inputByLabel(renderer, "Equivalent quantity").props.onChangeText("2")
  );

  // Still the original committed serving until confirmation.
  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "100",
    unit: "g",
    gram_weight: "100",
  }));

  await act(async () => press(renderer, "Confirm equivalent measurement"));

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "2",
    unit: "cup",
    gram_weight: "100",
    reference_quantity: "2",
    reference_unit: "cup",
    reference_gram_weight: "100",
  }));

  await act(async () =>
    inputByLabel(renderer, "Quantity").props.onChangeText("1")
  );

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "1",
    unit: "cup",
    gram_weight: "50",
    reference_quantity: "2",
    reference_unit: "cup",
    reference_gram_weight: "100",
  }));
  expect(visibleText(renderer)).toContain("1 cup (50 g)");
  expect(visibleText(renderer)).toContain("Based on: 2 cups = 100 g");

  await act(async () => renderer.unmount());
});

test("a confirmed equivalence remains authoritative even if the parent warning render is stale", async () => {
  const renderer = await renderEditor(
    [baseServing, portionServing("16", "tbsp", "100")],
    true,
  );

  await act(async () => press(renderer, "Edit 16 Tbsp"));
  await act(async () => openPicker(renderer, "Choose unit for"));
  await act(async () => chooseOption(renderer, "piece"));

  await act(async () =>
    inputByLabel(renderer, "Equivalent quantity").props.onChangeText("1")
  );

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "16",
    unit: "tbsp",
    gram_weight: "100",
  }));

  await act(async () => press(renderer, "Confirm equivalent measurement"));

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "1",
    unit: "piece",
    gram_weight: "100",
    reference_quantity: "1",
    reference_unit: "piece",
    reference_gram_weight: "100",
  }));

  // The harness deliberately re-injects the stale parent sentinel.
  // Local resolution authority must still prevent a second promotion.
  await act(async () =>
    inputByLabel(renderer, "Quantity").props.onChangeText("2")
  );

  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "2",
    unit: "piece",
    gram_weight: "200",
    reference_quantity: "1",
    reference_unit: "piece",
    reference_gram_weight: "100",
  }));
  expect(visibleText(renderer)).toContain("2 pieces (200 g)");
  expect(visibleText(renderer)).toContain("Based on: 1 piece = 100 g");

  await act(async () => renderer.unmount());
});

test("editing the reference to an incompatible unit resets current to the explicit new reference", async () => {
  const renderer = await renderEditor([baseServing, portionServing("8", "tsp", "50")]);
  await act(async () => press(renderer, "Edit 8 tsp"));
  await act(async () => press(renderer, "Edit reference measurement"));
  await act(async () => inputByLabel(renderer, "Reference quantity").props.onChangeText("1"));
  await act(async () => press(renderer, "Reference unit"));
  await act(async () => chooseOption(renderer, "piece"));
  await act(async () => inputByLabel(renderer, "Reference grams").props.onChangeText("100"));
  await act(async () => press(renderer, "Confirm reference measurement"));

  // tsp and piece have no defensible conversion. Explicit reference editing is authoritative,
  // so the old 8 tsp = 50 g current amount is discarded rather than left in review state.
  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "1", unit: "piece", gram_weight: "100",
    reference_quantity: "1", reference_unit: "piece", reference_gram_weight: "100",
  }));
  expect(currentPortion().consistencyWarning).toBeUndefined();
  expect(visibleText(renderer)).toContain("1 piece = 100 g");
  expect(visibleText(renderer)).toContain("1 piece (100 g)");
  expect(visibleText(renderer)).not.toContain(UNCONVERTED_SERVING_UNIT_WARNING);

  // The next ordinary current-quantity edit scales from the explicit 1 piece = 100 g reference;
  // it must never re-promote stale 50 g from the old teaspoon representation.
  await act(async () => inputByLabel(renderer, "Quantity").props.onChangeText("2"));
  expect(currentPortion()).toEqual(expect.objectContaining({
    quantity: "2", unit: "piece", gram_weight: "200",
    reference_quantity: "1", reference_unit: "piece", reference_gram_weight: "100",
  }));
  expect(visibleText(renderer)).toContain("2 pieces (200 g)");
  expect(visibleText(renderer)).toContain("Based on: 1 piece = 100 g");
  await act(async () => renderer.unmount());
});

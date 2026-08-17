import React from "react";
import { AccessibilityInfo, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import TestRenderer, { act } from "react-test-renderer";
import type { Food } from "../src/features/foods/api/types";

let mockNutrients: Array<Record<string, unknown>> = [];
const mockCreateFood = jest.fn();
const mockUpdateFood = jest.fn();
const activeRenderers = new Set<TestRenderer.ReactTestRenderer>();

afterEach(async () => {
  await act(async () => {
    activeRenderers.forEach((renderer) => {
      try {
        void renderer.root;
        renderer.unmount();
      } catch {
        // The test already unmounted this renderer.
      }
    });
  });
  activeRenderers.clear();
  jest.useRealTimers();
});

jest.mock("../src/features/foods/hooks/useFoods", () => ({
  useNutrients: () => ({ data: mockNutrients, isLoading: false, isError: false, refetch: jest.fn() }),
  useFoodMutations: () => ({
    createFood: { mutateAsync: mockCreateFood },
    updateFood: { mutateAsync: mockUpdateFood },
  }),
}));

import { FoodFormScreen } from "../src/features/foods/screens/FoodFormScreen";

beforeEach(() => {
  mockNutrients = [];
  mockCreateFood.mockReset().mockResolvedValue({ id: "food-1" });
  mockUpdateFood.mockReset().mockResolvedValue({ id: "food-1" });
});

const editableFood: Food = {
  id: "food-edit",
  name: "Oats",
  brand: "Pantry Co",
  notes: null,
  source_type: "manual",
  source_id: null,
  is_recipe: false,
  source_kind: "manual",
  source_label: "Manual",
  is_favorite: false,
  can_favorite: true,
  serving_definitions: [
    { id: "base", label: "100 g", quantity: "100", unit: "g", gram_weight: "100", is_default: true, source: "manual", is_user_confirmed: true },
    { id: "scoop", label: "1 scoop", quantity: "1", unit: "scoop", gram_weight: "30", is_default: false, source: "manual", is_user_confirmed: true },
  ],
  nutrients: [],
};

function textContent(node: TestRenderer.ReactTestInstance | string): string {
  return typeof node === "string" ? node : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join("");
}

function managementSurface(node: TestRenderer.ReactTestInstance): TestRenderer.ReactTestInstance {
  return node.findAllByType(View).find((child) => StyleSheet.flatten(child.props.style)?.minHeight === 36)!;
}

test("custom food validation keeps values, associates the error, and announces the targeted failure", async () => {
  jest.useFakeTimers();
  const announce = jest.spyOn(AccessibilityInfo, "announceForAccessibility").mockImplementation(() => undefined);
  const infoWithOptions = AccessibilityInfo as typeof AccessibilityInfo & {
    announceForAccessibilityWithOptions: (message: string, options: { queue?: boolean }) => void;
  };
  const announceWithOptions = jest.spyOn(infoWithOptions, "announceForAccessibilityWithOptions").mockImplementation(() => undefined);
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(FoodFormScreen, {
      onCancel: jest.fn(),
      onSaved: jest.fn(),
    }));
  });
  activeRenderers.add(renderer);
  const inputBefore = renderer.root.findAllByType(TextInput).find((node) => node.props.accessibilityLabel === "Food name");
  expect(inputBefore?.props.value).toBe("");
  const save = renderer.root.findAllByType(Pressable).find((node) => textContent(node) === "Save");
  await act(async () => save?.props.onPress());
  await act(async () => jest.advanceTimersByTime(100));

  const inputAfter = renderer.root.findAllByType(TextInput).find((node) => node.props.accessibilityLabel === "Food name");
  expect(inputAfter?.props.value).toBe("");
  expect(inputAfter?.props["aria-invalid"]).toBe(true);
  expect(inputAfter?.props["aria-required"]).toBe(true);
  const error = renderer.root.findAllByType(Text).find((node) => node.props.accessibilityRole === "alert");
  expect(textContent(error!)).toBe("Food name is required.");
  const announcedMessages = [
    ...announce.mock.calls.map(([message]) => message),
    ...announceWithOptions.mock.calls.map(([message]) => message),
  ];
  expect(announcedMessages).toEqual(["Food name is required."]);
  await act(async () => renderer.unmount());
  announce.mockRestore();
  announceWithOptions.mockRestore();
});

test("custom food foundations expose headings, persistent field labels, and contextual actions", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(FoodFormScreen, {
      onCancel: jest.fn(),
      onSaved: jest.fn(),
    }));
  });
  activeRenderers.add(renderer);
  expect(renderer.root.findByProps({ accessibilityRole: "header", children: "New Food" })).toBeDefined();
  for (const label of ["Food name", "Brand", "Notes"]) {
    const input = renderer.root.findAllByType(TextInput).find((node) => node.props.accessibilityLabel === label);
    expect(input).toBeDefined();
    const visibleLabel = renderer.root.findAllByType(Text).find((node) => node.props.nativeID === input?.props["aria-labelledby"]);
    expect(visibleLabel).toBeDefined();
    expect(textContent(visibleLabel!)).toContain(label);
  }
  expect(renderer.root.findByProps({ accessibilityLabel: "Cancel creating food" })).toBeDefined();
  expect(renderer.root.findByProps({ accessibilityLabel: "Add serving size" }).props.accessibilityHint).toContain("expands");
  expect(renderer.root.findByProps({ accessibilityLabel: "Save food" }).props.accessibilityHint).toContain("logging confirmation");
  await act(async () => renderer.unmount());
});

test("Edit Food keeps Cancel actionable and uses a larger title than its primary section headings", async () => {
  const onCancel = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(FoodFormScreen, {
      food: editableFood,
      onCancel,
      onSaved: jest.fn(),
    }));
  });
  activeRenderers.add(renderer);

  const cancel = renderer.root.findByProps({ accessibilityLabel: "Cancel editing food" });
  await act(async () => cancel.props.onPress());
  expect(onCancel).toHaveBeenCalledTimes(1);

  const heading = (label: string) => renderer.root.findAllByType(Text).find(
    (node) => textContent(node) === label && node.props.accessibilityRole === "header",
  )!;
  const titleStyle = StyleSheet.flatten(heading("Edit Food").props.style);
  const sectionStyles = ["Food", "Serving sizes", "Nutrients"].map((label) =>
    StyleSheet.flatten(heading(label).props.style),
  );
  expect(sectionStyles.every((style) => style.fontSize === sectionStyles[0].fontSize)).toBe(true);
  expect(sectionStyles.every((style) => style.fontWeight === sectionStyles[0].fontWeight)).toBe(true);
  expect(titleStyle.fontSize).toBeGreaterThan(sectionStyles[0].fontSize);
  const customServingHeadingStyle = StyleSheet.flatten(heading("Custom serving sizes").props.style);
  expect(customServingHeadingStyle.fontSize).toBeLessThanOrEqual(sectionStyles[0].fontSize);
  const brandLabel = renderer.root.findAllByType(Text).find((node) => textContent(node) === "Brand")!;
  const brandInput = renderer.root.findByProps({ accessibilityLabel: "Brand" });
  expect(StyleSheet.flatten(brandLabel.props.style)).toMatchObject({ fontSize: 14 });
  expect(StyleSheet.flatten(brandInput.props.style)).toMatchObject({ fontSize: 16 });
  await act(async () => renderer.unmount());
});

test("canonical and custom default controls share a trailing slot and retain lower Edit and Remove actions", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(FoodFormScreen, {
      food: editableFood,
      onCancel: jest.fn(),
      onSaved: jest.fn(),
    }));
  });
  activeRenderers.add(renderer);

  const baseControl = renderer.root.findAllByType(View).find((node) =>
    node.props.accessibilityLabel === "Default amount" && node.props.accessibilityRole === "text",
  )!;
  const customControl = renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Set 1 scoop as default")!;
  const baseStyle = StyleSheet.flatten(baseControl.props.style);
  const customStyle = StyleSheet.flatten(customControl.props.style);
  expect(baseStyle).toMatchObject({ minHeight: 44, minWidth: 96 });
  expect(customStyle).toMatchObject({ minHeight: 44, minWidth: 96 });
  expect(StyleSheet.flatten(managementSurface(baseControl).props.style)).toMatchObject({ minHeight: 36, minWidth: 96, paddingHorizontal: 12, paddingVertical: 8 });
  expect(StyleSheet.flatten(managementSurface(customControl).props.style)).toMatchObject({ minHeight: 36, minWidth: 96, paddingHorizontal: 12, paddingVertical: 8 });
  expect(textContent(baseControl)).toBe("✓ Default");
  expect(textContent(customControl)).toBe("Set default");
  const edit = renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Edit 1 scoop")!;
  expect(StyleSheet.flatten(edit.props.style)).toMatchObject({ minHeight: 44 });
  expect(StyleSheet.flatten(managementSurface(edit).props.style)).toMatchObject({ minHeight: 36, paddingHorizontal: 12, paddingVertical: 8 });
  expect(renderer.root.findByProps({ accessibilityLabel: "Edit 1 scoop" })).toBeDefined();
  expect(renderer.root.findByProps({ accessibilityLabel: "Remove 1 scoop" })).toBeDefined();
  expect(renderer.root.findAllByType(Text).map(textContent).join(" ")).not.toContain("Canonical nutrient basis");

  await act(async () => customControl.props.onPress());
  expect(renderer.root.findAllByProps({ accessibilityLabel: "Set 1 scoop as default" })).toHaveLength(0);
  const customDefaultControl = renderer.root.findAllByType(View).find((node) =>
    node.props.accessibilityLabel === "Default amount" && node.props.accessibilityRole === "text",
  )!;
  const baseSetDefaultControl = renderer.root.findAllByType(Pressable).find(
    (node) => node.props.accessibilityLabel === "Set 100 grams as default amount",
  )!;
  expect(textContent(customDefaultControl)).toBe("✓ Default");
  expect(textContent(baseSetDefaultControl)).toBe("Set default");
  expect(StyleSheet.flatten(customDefaultControl.props.style)).toMatchObject({ minHeight: 44, minWidth: 96 });
  expect(StyleSheet.flatten(baseSetDefaultControl.props.style)).toMatchObject({ minHeight: 44, minWidth: 96 });
  expect(StyleSheet.flatten(managementSurface(customDefaultControl).props.style)).toMatchObject({ minHeight: 36, minWidth: 96, paddingHorizontal: 12, paddingVertical: 8 });
  expect(StyleSheet.flatten(managementSurface(baseSetDefaultControl).props.style)).toMatchObject({ minHeight: 36, minWidth: 96, paddingHorizontal: 12, paddingVertical: 8 });
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Edit 1 scoop" }).props.onPress());
  const servingQuantityInput = renderer.root.findAllByType(TextInput).find(
    (node) => node.props.accessibilityLabel === "Serving quantity",
  )!;
  expect(StyleSheet.flatten(servingQuantityInput.props.style))
    .toMatchObject({ minHeight: 44, paddingHorizontal: 10, paddingVertical: 10 });
  expect(renderer.root.findByProps({ accessibilityLabel: "Serving grams" }).props.value).toBe("30");
  expect(renderer.root.findAllByType(Text).some((node) => textContent(node) === "Reference measurement")).toBe(false);
  expect(renderer.root.findAllByProps({ accessibilityLabel: "Edit reference measurement" })).toHaveLength(0);
  await act(async () => renderer.unmount());
});

test("Food serving creation uses the direct quantity, unit, and gram-anchor flow", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(FoodFormScreen, {
      onCancel: jest.fn(),
      onSaved: jest.fn(),
    }));
  });
  activeRenderers.add(renderer);

  expect(
    renderer.root.findAllByProps({
      accessibilityLabel: "Edit 1 serving",
    }),
  ).toHaveLength(0);

  const add = renderer.root.findByProps({
    accessibilityLabel: "Add serving size",
  });
  expect(add.props.accessibilityHint).toContain("expands");

  await act(async () => add.props.onPress());

  const quantity = renderer.root.findByProps({
    accessibilityLabel: "Serving quantity",
  });
  const grams = renderer.root.findByProps({
    accessibilityLabel: "Serving grams",
  });

  expect(quantity.props.value).toBe("1");
  expect(grams.props.value).toBe("");

  const unitTrigger = renderer.root
    .findAllByType(Pressable)
    .find(
      (node) =>
        typeof node.props.accessibilityLabel === "string"
        && node.props.accessibilityLabel.startsWith("Choose unit for"),
    )!;

  await act(async () => unitTrigger.props.onPress());
  await act(async () =>
    renderer.root.findByProps({ accessibilityLabel: "slice" }).props.onPress()
  );
  await act(async () =>
    renderer.root
      .findByProps({ accessibilityLabel: "Serving quantity" })
      .props.onChangeText("2")
  );
  await act(async () =>
    renderer.root
      .findByProps({ accessibilityLabel: "Serving grams" })
      .props.onChangeText("56")
  );

  expect(
    renderer.root
      .findAllByType(Text)
      .some((node) => textContent(node) === "2 slices = 56 g"),
  ).toBe(true);

  expect(
    renderer.root
      .findAllByType(Text)
      .some((node) => textContent(node) === "Reference measurement"),
  ).toBe(false);

  await act(async () => renderer.unmount());
});

test("manual nutrient rows keep amount text raw and derive known status without a visible selector", async () => {
  mockNutrients = [{ id: "calories", display_name: "Calories", default_unit: "kcal", nutrient_kind: "energy", parent_nutrient_id: null, display_order: 1 }];
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(FoodFormScreen, {
      onCancel: jest.fn(),
      onSaved: jest.fn(),
    }));
  });
  activeRenderers.add(renderer);
  const amount = renderer.root.findByProps({ accessibilityLabel: "Calories amount" });
  expect(amount.props.accessibilityHint).toBe("Value in kcal");
  expect(amount.props.value).toBe("");
  expect(amount.props.placeholder).not.toBe("0");
  expect(amount.props["aria-labelledby"]).toBeDefined();
  expect(renderer.root.findAllByType(Text).some((node) => textContent(node) === "kcal")).toBe(true);
  expect(StyleSheet.flatten(amount.props.style)).toMatchObject({ height: 40, minHeight: 40, minWidth: 96, paddingHorizontal: 8, width: 112 });
  expect(amount.props.accessibilityState).toMatchObject({ disabled: false });
  for (const status of ["known", "zero", "estimated", "unknown"]) {
    expect(renderer.root.findAllByProps({ accessibilityLabel: `Calories status ${status}` })).toHaveLength(0);
  }
  expect(renderer.root.findByProps({ accessibilityLabel: "Omit Calories" })).toBeDefined();
  await act(async () => amount.props.onChangeText("99999999.9999989"));
  expect(renderer.root.findByProps({ accessibilityLabel: "Calories amount" }).props.value).toBe("99999999.9999989");
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Food name" }).props.onChangeText("Cereal"));
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Save food" }).props.onPress());
  expect(mockCreateFood).toHaveBeenCalledWith(expect.objectContaining({
    nutrients: [expect.objectContaining({ amount: "99999999.9999989", data_status: "known" })],
  }));
  await act(async () => renderer.unmount());
});

test("manual explicit zero derives zero status without a zero-status validation error", async () => {
  mockNutrients = [{ id: "calories", display_name: "Calories", default_unit: "kcal", nutrient_kind: "energy", parent_nutrient_id: null, display_order: 1 }];
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(FoodFormScreen, {
      onCancel: jest.fn(),
      onSaved: jest.fn(),
    }));
  });
  activeRenderers.add(renderer);
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Calories amount" }).props.onChangeText("0.0"));
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Food name" }).props.onChangeText("Cereal"));
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Save food" }).props.onPress());
  expect(mockCreateFood).toHaveBeenCalledWith(expect.objectContaining({
    nutrients: [expect.objectContaining({ amount: "0.0", data_status: "zero" })],
  }));
  expect(renderer.root.findAllByType(Text).some((node) => textContent(node).includes("Use zero status for explicit zero values"))).toBe(false);
  await act(async () => renderer.unmount());
});

test("omitting a manual nutrient preserves the established unknown omission mapping", async () => {
  mockNutrients = [{ id: "calories", display_name: "Calories", default_unit: "kcal", nutrient_kind: "energy", parent_nutrient_id: null, display_order: 1 }];
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(FoodFormScreen, {
      onCancel: jest.fn(),
      onSaved: jest.fn(),
    }));
  });
  activeRenderers.add(renderer);
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Calories amount" }).props.onChangeText("12"));
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Omit Calories" }).props.onPress());
  expect(renderer.root.findByProps({ accessibilityLabel: "Calories amount" }).props.value).toBe("");
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Food name" }).props.onChangeText("Cereal"));
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Save food" }).props.onPress());
  expect(mockCreateFood).toHaveBeenCalledWith(expect.objectContaining({
    nutrients: [expect.objectContaining({ amount: null, data_status: "unknown" })],
  }));
  await act(async () => renderer.unmount());
});

test("invalid manual nutrient text keeps the focused validation association", async () => {
  mockNutrients = [{ id: "calories", display_name: "Calories", default_unit: "kcal", nutrient_kind: "energy", parent_nutrient_id: null, display_order: 1 }];
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(FoodFormScreen, {
      onCancel: jest.fn(),
      onSaved: jest.fn(),
    }));
  });
  activeRenderers.add(renderer);
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Calories amount" }).props.onChangeText("not-a-number"));
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Food name" }).props.onChangeText("Cereal"));
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Save food" }).props.onPress());
  const invalidAmount = renderer.root.findByProps({ accessibilityLabel: "Calories amount" });
  expect(invalidAmount.props["aria-invalid"]).toBe(true);
  expect(invalidAmount.props["aria-describedby"]).toBeDefined();
  const nutrientError = renderer.root.findAllByType(Text).find((node) => node.props.nativeID === invalidAmount.props["aria-describedby"]);
  expect(nutrientError?.props.accessibilityRole).toBe("alert");
  const nutrientContainer = [invalidAmount.parent, invalidAmount.parent?.parent, invalidAmount.parent?.parent?.parent]
    .find((ancestor) => ancestor?.findAllByType(Text).some((node) => node.props.nativeID === invalidAmount.props["aria-describedby"] && node.props.accessibilityRole === "alert"));
  expect(nutrientContainer).toBeDefined();
  await act(async () => renderer.unmount());
});

test("manual nutrient hierarchy uses one shared child indent and a normal terminal content gap", async () => {
  mockNutrients = [
    { id: "total-fat", display_name: "Total Fat", default_unit: "g", nutrient_kind: "macro", parent_nutrient_id: null, display_order: 1 },
    { id: "saturated-fat", display_name: "Saturated Fat", default_unit: "g", nutrient_kind: "macro", parent_nutrient_id: "total-fat", display_order: 2 },
    { id: "trans-fat", display_name: "Trans Fat", default_unit: "g", nutrient_kind: "macro", parent_nutrient_id: "total-fat", display_order: 3 },
    { id: "total-carbohydrate", display_name: "Total Carbohydrate", default_unit: "g", nutrient_kind: "macro", parent_nutrient_id: null, display_order: 4 },
    { id: "dietary-fiber", display_name: "Dietary Fiber", default_unit: "g", nutrient_kind: "macro", parent_nutrient_id: "total-carbohydrate", display_order: 5 },
    { id: "total-sugars", display_name: "Total Sugars", default_unit: "g", nutrient_kind: "macro", parent_nutrient_id: "total-carbohydrate", display_order: 6 },
    { id: "added-sugars", display_name: "Added Sugars", default_unit: "g", nutrient_kind: "macro", parent_nutrient_id: "total-sugars", display_order: 7 },
  ];
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(FoodFormScreen, {
      onCancel: jest.fn(),
      onSaved: jest.fn(),
    }));
  });
  activeRenderers.add(renderer);

  function nutrientTitle(label: string) {
    return renderer.root.findAllByType(Text).find(
      (node) => node.props.nativeID?.startsWith("nutrient-label-") && textContent(node) === label,
    );
  }

  function nutrientRow(node: TestRenderer.ReactTestInstance | undefined) {
    let current = node;
    while (current) {
      const style = StyleSheet.flatten(current.props.style);
      if (style?.borderBottomWidth === 1 && style.paddingBottom === 8) {
        return current;
      }
      current = current.parent ?? undefined;
    }
    return undefined;
  }

  const parentRowStyle = StyleSheet.flatten(nutrientRow(nutrientTitle("Total Fat"))?.props.style);
  const childRowStyles = ["Saturated Fat", "Trans Fat", "Dietary Fiber", "Total Sugars", "Added Sugars"]
    .map((label) => StyleSheet.flatten(nutrientRow(nutrientTitle(label))?.props.style));
  expect(parentRowStyle.paddingLeft ?? 0).toBe(0);
  expect(childRowStyles).toHaveLength(5);
  expect(childRowStyles.every((style) => style.paddingLeft === 16)).toBe(true);
  expect(childRowStyles.map((style) => style.paddingLeft)).toEqual([16, 16, 16, 16, 16]);

  for (const label of ["Saturated Fat", "Trans Fat", "Dietary Fiber", "Total Sugars", "Added Sugars"]) {
    const amount = renderer.root.findByProps({ accessibilityLabel: `${label} amount` });
    const titleRow = nutrientRow(nutrientTitle(label));
    const amountRow = nutrientRow(amount);
    expect(titleRow?.findAllByType(TextInput).filter(
      (node) => node.props.accessibilityLabel === `${label} amount`,
    )).toHaveLength(1);
    const titleRowStyle = StyleSheet.flatten(titleRow?.props.style);
    const amountRowStyle = StyleSheet.flatten(amountRow?.props.style);
    expect(titleRowStyle).toEqual(amountRowStyle);
  }
  expect(renderer.root.findByProps({ accessibilityLabel: "Omit Added Sugars" })).toBeDefined();
  expect(StyleSheet.flatten(renderer.root.findByProps({ accessibilityLabel: "Saturated Fat amount" }).props.style))
    .toMatchObject({ height: 40, minHeight: 40, minWidth: 96, paddingHorizontal: 8, width: 112 });

  const scrollViews = renderer.root.findAllByType(ScrollView);
  expect(scrollViews).toHaveLength(1);
  expect(StyleSheet.flatten(scrollViews[0].props.contentContainerStyle)).toMatchObject({ paddingBottom: 16 });
  await act(async () => renderer.unmount());
});

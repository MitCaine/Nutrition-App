import React from "react";
import { AccessibilityInfo, Pressable, Text, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

let mockNutrients: Array<Record<string, unknown>> = [];
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
    createFood: { mutateAsync: jest.fn() },
    updateFood: { mutateAsync: jest.fn() },
  }),
}));

import { FoodFormScreen } from "../src/features/foods/screens/FoodFormScreen";

beforeEach(() => { mockNutrients = []; });

function textContent(node: TestRenderer.ReactTestInstance | string): string {
  return typeof node === "string" ? node : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join("");
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
  expect(renderer.root.findByProps({ accessibilityLabel: "Add another amount" }).props.accessibilityHint).toContain("expands");
  expect(renderer.root.findByProps({ accessibilityLabel: "Save food" }).props.accessibilityHint).toContain("logging confirmation");
  await act(async () => renderer.unmount());
});

test("serving controls expose contextual expansion and modal radio state", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(FoodFormScreen, {
      onCancel: jest.fn(),
      onSaved: jest.fn(),
    }));
  });
  activeRenderers.add(renderer);
  const edit = renderer.root.findByProps({ accessibilityLabel: "Edit 1 serving" });
  expect(edit.props.accessibilityState).toMatchObject({ expanded: false });
  await act(async () => edit.props.onPress());
  const unit = renderer.root.findByProps({ accessibilityLabel: "Choose unit for 1 serving, current unit serving" });
  expect(unit.props.accessibilityState).toMatchObject({ expanded: false });
  await act(async () => unit.props.onPress());
  expect(renderer.root.findByProps({ accessibilityRole: "header", children: "Choose unit for 1 serving" })).toBeDefined();
  expect(renderer.root.findByProps({ accessibilityLabel: "serving", accessibilityRole: "radio" }).props.accessibilityState).toMatchObject({ checked: true, selected: true });
  expect(renderer.root.findByProps({ accessibilityLabel: "Cancel choosing unit" })).toBeDefined();
  await act(async () => renderer.unmount());
});

test("nutrient values and status choices identify the nutrient and selected state", async () => {
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
  expect(amount.props.accessibilityState).toMatchObject({ disabled: true });
  const unknown = renderer.root.findByProps({ accessibilityLabel: "Calories status unknown" });
  expect(unknown.props.accessibilityState).toMatchObject({ checked: true, selected: true });
  const known = renderer.root.findByProps({ accessibilityLabel: "Calories status known" });
  expect(known.props.accessibilityRole).toBe("radio");
  await act(async () => known.props.onPress());
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Food name" }).props.onChangeText("Cereal"));
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Save food" }).props.onPress());
  const invalidAmount = renderer.root.findByProps({ accessibilityLabel: "Calories amount" });
  expect(invalidAmount.props["aria-invalid"]).toBe(true);
  expect(invalidAmount.props["aria-describedby"]).toBeDefined();
  await act(async () => renderer.unmount());
});

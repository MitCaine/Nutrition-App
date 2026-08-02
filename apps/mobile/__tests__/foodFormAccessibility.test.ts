import React from "react";
import { AccessibilityInfo, Pressable, Text, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import { FoodFormScreen } from "../src/features/foods/screens/FoodFormScreen";

afterEach(() => jest.useRealTimers());

jest.mock("../src/features/foods/hooks/useFoods", () => ({
  useNutrients: () => ({ data: [] }),
  useFoodMutations: () => ({
    createFood: { mutateAsync: jest.fn() },
    updateFood: { mutateAsync: jest.fn() },
  }),
}));

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
  const inputBefore = renderer.root.findAllByType(TextInput).find((node) => node.props.accessibilityLabel === "Food name");
  expect(inputBefore?.props.value).toBe("");
  const save = renderer.root.findAllByType(Pressable).find((node) => textContent(node) === "Save");
  await act(async () => save?.props.onPress());
  await act(async () => jest.advanceTimersByTime(100));

  const inputAfter = renderer.root.findAllByType(TextInput).find((node) => node.props.accessibilityLabel === "Food name");
  expect(inputAfter?.props.value).toBe("");
  expect(inputAfter?.props["aria-invalid"]).toBe(true);
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

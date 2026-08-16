import React from "react";
import { Pressable, Text, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import { ServingUnitPicker } from "../src/features/foods/components/ServingUnitPicker";

function textContent(node: TestRenderer.ReactTestInstance | string): string {
  return typeof node === "string" ? node : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join("");
}

test("shared serving unit picker exposes grouped built-ins and returns canonical units", async () => {
  const onChange = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(ServingUnitPicker, {
      value: "slice",
      onChange,
      contextLabel: "1 slice",
    }));
  });

  const trigger = renderer.root.findByProps({ accessibilityLabel: "Choose unit for 1 slice, current unit slice" });
  expect(trigger.props.accessibilityState).toMatchObject({ expanded: false, disabled: false });
  expect(renderer.root.findByProps({ accessibilityLabel: "Unit" }).props.value).toBe("slice");

  await act(async () => trigger.props.onPress());
  for (const heading of ["Weight", "Volume", "Count or portion", "Custom"]) {
    expect(renderer.root.findAllByType(Text).some((node) => textContent(node) === heading)).toBe(true);
  }
  expect(renderer.root.findByProps({ accessibilityLabel: "slice" }).props.accessibilityState)
    .toMatchObject({ checked: true, selected: true });

  await act(async () => renderer.root.findByProps({ accessibilityLabel: "cup" }).props.onPress());
  expect(onChange).toHaveBeenCalledWith("cup");
  await act(async () => renderer.unmount());
});

test("shared serving unit picker supports explicit custom units", async () => {
  const onChange = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(ServingUnitPicker, {
      value: "",
      onChange,
    }));
  });

  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Choose unit, current unit not selected" }).props.onPress());
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Custom unit" }).props.onPress());

  const customInput = renderer.root.findAllByType(TextInput).find((node) => node.props.accessibilityLabel === "Custom unit name");
  expect(customInput).toBeDefined();
  await act(async () => customInput?.props.onChangeText("scoop"));

  const useCustom = renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Use custom unit scoop");
  expect(useCustom).toBeDefined();
  await act(async () => useCustom?.props.onPress());
  expect(onChange).toHaveBeenCalledWith("scoop");
  await act(async () => renderer.unmount());
});

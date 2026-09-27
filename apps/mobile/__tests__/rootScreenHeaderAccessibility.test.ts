import React from "react";
import { Pressable, StyleSheet } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import { RootScreenHeader } from "../src/shared/components/RootScreenHeader";
import { OPEN_SETTINGS_ACCESSIBILITY_LABEL } from "../src/shared/components/rootScreenHeaderModel";

jest.mock("@expo/vector-icons", () => ({ Ionicons: "Ionicons" }));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...actual.LIGHT_THEME, preference: "system", effectiveScheme: "light", setPreference: jest.fn() }) };
});

test("root header actions keep semantics, minimum targets, and enabled activation", async () => {
  const onAction = jest.fn();
  const onSettings = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(RootScreenHeader, {
      title: "Saved Foods",
      onOpenSettings: onSettings,
      action: { label: "Select", accessibilityLabel: "Select saved foods", accessibilityHint: "Choose entries", checked: true, onPress: onAction },
    }));
  });
  const controls = renderer.root.findAllByType(Pressable);
  expect(controls).toHaveLength(2);
  const [action, settings] = controls;
  expect(action.props.accessibilityRole).toBe("checkbox");
  expect(action.props.accessibilityLabel).toBe("Select saved foods");
  expect(action.props.accessibilityHint).toBe("Choose entries");
  expect(action.props.accessibilityState).toMatchObject({ checked: true, disabled: false });
  expect(settings.props.accessibilityRole).toBe("button");
  expect(settings.props.accessibilityLabel).toBe(OPEN_SETTINGS_ACCESSIBILITY_LABEL);
  for (const control of controls) {
    const style = StyleSheet.flatten(typeof control.props.style === "function"
      ? control.props.style({ pressed: false }) : control.props.style);
    expect(style).toMatchObject({ minHeight: 44, minWidth: 44 });
  }
  await act(async () => { action.props.onPress(); settings.props.onPress(); });
  expect(onAction).toHaveBeenCalledTimes(1);
  expect(onSettings).toHaveBeenCalledTimes(1);
  await act(async () => renderer.unmount());
});

test("disabled root action cannot activate and retains its presentation", async () => {
  const onAction = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(RootScreenHeader, {
      title: "Saved Foods",
      onOpenSettings: jest.fn(),
      action: { label: "Select", disabled: true, onPress: onAction },
    }));
  });
  const action = renderer.root.findAllByType(Pressable)[0];
  expect(action.props.accessibilityLabel).toBe("Select");
  expect(action.props.accessibilityState).toMatchObject({ disabled: true });
  expect(action.props.disabled).toBe(true);
  expect(action.props.onPress).toBeUndefined();
  expect(StyleSheet.flatten(typeof action.props.style === "function"
    ? action.props.style({ pressed: false }) : action.props.style)).toMatchObject({ opacity: 0.45 });
  expect(onAction).not.toHaveBeenCalled();
  await act(async () => renderer.unmount());
});

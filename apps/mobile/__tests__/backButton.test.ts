import React from "react";
import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import { BackButton } from "../src/shared/components/BackButton";

jest.mock("@expo/vector-icons", () => ({
  Ionicons: function MockIonicons() {
    return null;
  },
}));

jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...actual.LIGHT_THEME, preference: "system", effectiveScheme: "light", setPreference: jest.fn() }) };
});

function textContent(node: TestRenderer.ReactTestInstance | string): string {
  return typeof node === "string" ? node : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join("");
}

test("shared Back uses the icon treatment and keeps the shared target", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(BackButton, {
      accessibilityLabel: "Back from settings",
      onPress: jest.fn(),
    }));
  });
  const back = renderer.root.findByType(Pressable);
  const textNodes = back.findAllByType(Text);
  const icon = back.findByType(Ionicons);
  expect(textContent(back)).toBe("Back");
  expect(textContent(back)).not.toContain("‹");
  expect(textNodes).toHaveLength(1);
  expect(icon.props.name).toBe("chevron-back");
  expect(icon.props.size).toBe(24);
  expect(icon.props.color).toBeDefined();
  const resolvedStyle = (back.props.style as (state: { pressed: boolean }) => unknown)({ pressed: false });
  expect(StyleSheet.flatten(resolvedStyle as never)).toMatchObject({ alignItems: "center", flexDirection: "row", gap: 4, minHeight: 44, minWidth: 44 });
  expect(back.props.accessibilityRole).toBe("button");
  await act(async () => renderer.unmount());
});

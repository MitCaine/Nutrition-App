import React from "react";
import { Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import { BottomNavigation } from "../src/app/navigation/BottomNavigation";
import { RootScreenHeader } from "../src/shared/components/RootScreenHeader";

jest.mock("@expo/vector-icons", () => ({ Ionicons: "Ionicons" }));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...actual.LIGHT_THEME, preference: "system", effectiveScheme: "light", setPreference: jest.fn() }) };
});

function textContent(node: TestRenderer.ReactTestInstance | string): string {
  return typeof node === "string" ? node : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join("");
}

test("fixed root chrome caps visual text growth while preserving accessible controls", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(React.Fragment, null,
      React.createElement(RootScreenHeader, { title: "Saved Foods", onOpenSettings: jest.fn() }),
      React.createElement(BottomNavigation, { activeTab: "foods", onSelect: jest.fn() }),
    ));
  });
  const cappedLabels = renderer.root.findAllByType(Text)
    .filter((node) => node.props.maxFontSizeMultiplier === 1.5)
    .map(textContent);
  expect(cappedLabels).toEqual(expect.arrayContaining(["Saved Foods", "Foods", "Daily Log", "Recipes"]));
  await act(async () => renderer.unmount());
});
